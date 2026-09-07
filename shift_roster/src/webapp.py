"""
Flask web application:
  /            → dashboard (today's roster)
  /login       → login
  /users       → user management (admin only)
  /shifts      → custom shift management
  /roster/input   → manual roster entry form
  /roster/paste   → paste bulk text / WhatsApp message
  /roster/view    → view roster by date
  /reports        → generate & download reports (daily/monthly/employee PDF)
  /attendance     → attendance report (roster vs actual punches from ESSL DB)
  /api/attendance-notify → send attendance report via WhatsApp
  /webhook/pingerbot → inbound WhatsApp via Pingerbot
  /api/notify     → trigger employee notifications
  /settings       → system settings
"""
from __future__ import annotations

import calendar
import datetime
import io
import os
import threading
import time

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, jsonify, Response,
)
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user,
)

from src.config import config
from src.db.models import init_db, AppUser, get_session as _db_session
from src.db import settings_store
from src.db.roster_store import (
    fetch_roster_from_db, save_roster, log_receipt_error,
)
from src.db import user_store, shift_store
from src.logger import get_logger
from src.roster.parser import parse_roster_message
from src.roster.processor import (
    build_employee_message, build_full_summary, group_by_department,
)
from src.roster.report import text_report, whatsapp_report
from src.roster.attendance import (
    analyse as analyse_attendance,
    analyse_office_employees,
    attendance_whatsapp_report,
    attendance_employee_message,
)
from src.whatsapp.pingerbot import send_message, send_bulk

log = get_logger(__name__)

# ── App setup ─────────────────────────────────────────────────────────────────

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "..", "templates"),
    static_folder=os.path.join(os.path.dirname(__file__), "..", "static"),
)
app.secret_key = config.WEB_SECRET_KEY

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message_category = "warning"

init_db()

# ── Auth ──────────────────────────────────────────────────────────────────────

class DBUser(UserMixin):
    def __init__(self, user: AppUser):
        self._id       = str(user.id)
        self.username  = user.username
        self.full_name = user.full_name or user.username
        self.role      = user.role

    def get_id(self):
        return self._id

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def is_manager(self):
        return self.role in ("admin", "manager")


@login_manager.user_loader
def load_user(user_id):
    try:
        uid = int(user_id)
    except (ValueError, TypeError):
        return None
    sess = _db_session()
    try:
        u = sess.query(AppUser).filter_by(id=uid, active=True).first()
        return DBUser(u) if u else None
    finally:
        sess.close()


def _require_admin():
    """Return a redirect if current user is not admin, else None."""
    if not current_user.is_authenticated or not current_user.is_admin:
        flash("Admin access required.", "danger")
        return redirect(url_for("dashboard"))
    return None


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        user = user_store.authenticate(username, password)
        if user:
            login_user(DBUser(user))
            return redirect(url_for("dashboard"))
        flash("Invalid credentials.", "danger")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def dashboard():
    today = datetime.date.today()
    records = fetch_roster_from_db(today)
    by_dept = group_by_department(records)
    return render_template(
        "dashboard.html",
        records=records,
        by_dept=by_dept,
        today=today,
    )


# ── User Management (admin only) ──────────────────────────────────────────────

@app.route("/users")
@login_required
def users_list():
    err = _require_admin()
    if err:
        return err
    users = user_store.get_all_users()
    return render_template("users_list.html", users=users, roles=user_store.ROLES)


@app.route("/users/create", methods=["GET", "POST"])
@login_required
def user_create():
    err = _require_admin()
    if err:
        return err
    if request.method == "POST":
        username  = request.form.get("username", "").strip()
        password  = request.form.get("password", "").strip()
        full_name = request.form.get("full_name", "").strip()
        role      = request.form.get("role", "viewer")
        if not username or not password:
            flash("Username and password are required.", "danger")
        elif user_store.get_user_by_username(username):
            flash(f"Username '{username}' already exists.", "danger")
        else:
            user_store.create_user(username, password, full_name, role)
            flash(f"User '{username}' created.", "success")
            return redirect(url_for("users_list"))
    return render_template("user_form.html", user=None, roles=user_store.ROLES, action="Create")


@app.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
def user_edit(user_id):
    err = _require_admin()
    if err:
        return err
    u = user_store.get_user_by_id(user_id)
    if not u:
        flash("User not found.", "danger")
        return redirect(url_for("users_list"))
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        role      = request.form.get("role", u.role)
        active    = request.form.get("active") == "1"
        password  = request.form.get("password", "").strip()
        user_store.update_user(
            user_id, full_name=full_name, role=role, active=active,
            password=password or None,
        )
        flash("User updated.", "success")
        return redirect(url_for("users_list"))
    return render_template("user_form.html", user=u, roles=user_store.ROLES, action="Edit")


@app.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
def user_delete(user_id):
    err = _require_admin()
    if err:
        return err
    if int(current_user.get_id()) == user_id:
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for("users_list"))
    user_store.delete_user(user_id)
    flash("User deleted.", "success")
    return redirect(url_for("users_list"))


# ── Custom Shift Management ───────────────────────────────────────────────────

@app.route("/shifts")
@login_required
def shifts_list():
    shifts = shift_store.get_all_shifts()
    return render_template("shifts_list.html", shifts=shifts)


@app.route("/shifts/create", methods=["GET", "POST"])
@login_required
def shift_create():
    if not current_user.is_manager:
        flash("Manager or admin access required.", "danger")
        return redirect(url_for("shifts_list"))
    if request.method == "POST":
        name       = request.form.get("name", "").strip()
        code       = request.form.get("code", "").strip()
        start_time = request.form.get("start_time", "").strip()
        end_time   = request.form.get("end_time", "").strip()
        department = request.form.get("department", "").strip()
        if not name or not start_time or not end_time:
            flash("Name, start time, and end time are required.", "danger")
        else:
            shift_store.create_shift(name, start_time, end_time, code, department)
            flash(f"Shift '{name}' created.", "success")
            return redirect(url_for("shifts_list"))
    return render_template("shift_form.html", shift=None, action="Create")


@app.route("/shifts/<int:shift_id>/edit", methods=["GET", "POST"])
@login_required
def shift_edit(shift_id):
    if not current_user.is_manager:
        flash("Manager or admin access required.", "danger")
        return redirect(url_for("shifts_list"))
    s = shift_store.get_shift_by_id(shift_id)
    if not s:
        flash("Shift not found.", "danger")
        return redirect(url_for("shifts_list"))
    if request.method == "POST":
        shift_store.update_shift(
            shift_id,
            name       = request.form.get("name", s.name).strip(),
            code       = request.form.get("code", s.code or "").strip(),
            start_time = request.form.get("start_time", s.start_time).strip(),
            end_time   = request.form.get("end_time", s.end_time).strip(),
            department = request.form.get("department", s.department or "").strip(),
            active     = request.form.get("active") == "1",
        )
        flash("Shift updated.", "success")
        return redirect(url_for("shifts_list"))
    return render_template("shift_form.html", shift=s, action="Edit")


@app.route("/shifts/<int:shift_id>/delete", methods=["POST"])
@login_required
def shift_delete(shift_id):
    if not current_user.is_manager:
        flash("Manager or admin access required.", "danger")
        return redirect(url_for("shifts_list"))
    shift_store.delete_shift(shift_id)
    flash("Shift deleted.", "success")
    return redirect(url_for("shifts_list"))


# ── Roster Input (manual form) ────────────────────────────────────────────────

@app.route("/roster/input", methods=["GET", "POST"])
@login_required
def roster_input():
    if request.method == "POST":
        roster_date_str = request.form.get("roster_date", "")
        try:
            roster_date = datetime.date.fromisoformat(roster_date_str)
        except ValueError:
            flash("Invalid date.", "danger")
            return redirect(url_for("roster_input"))

        records = []
        names   = request.form.getlist("emp_name")
        phones  = request.form.getlist("phone")
        depts   = request.form.getlist("department")
        codes   = request.form.getlist("shift_code")
        snames  = request.form.getlist("shift_name")
        starts  = request.form.getlist("shift_start")
        ends    = request.form.getlist("shift_end")
        emp_ids = request.form.getlist("emp_id")

        for i, name in enumerate(names):
            if not name.strip():
                continue
            records.append({
                "date":        roster_date,
                "emp_id":      emp_ids[i] if i < len(emp_ids) else "",
                "emp_name":    name.strip(),
                "phone":       phones[i].strip() if i < len(phones) else "",
                "department":  depts[i].strip() if i < len(depts) else "",
                "shift_code":  codes[i].strip() if i < len(codes) else "",
                "shift_name":  snames[i].strip() if i < len(snames) else "",
                "shift_start": starts[i].strip() if i < len(starts) else "",
                "shift_end":   ends[i].strip() if i < len(ends) else "",
            })

        if not records:
            flash("No employee rows entered.", "warning")
            return redirect(url_for("roster_input"))

        count = save_roster(records, "manual-web-entry", "web-admin")
        flash(f"Roster saved — {count} employee(s) for {roster_date}.", "success")
        return redirect(url_for("roster_view", date=roster_date_str))

    today_str = datetime.date.today().isoformat()
    custom_shifts = shift_store.get_all_shifts(active_only=True)
    return render_template("roster_input.html", today=today_str, custom_shifts=custom_shifts)


# ── Roster Paste (bulk text / WhatsApp message) ───────────────────────────────

@app.route("/roster/paste", methods=["GET", "POST"])
@login_required
def roster_paste():
    parsed = []
    roster_date = None
    raw = ""

    if request.method == "POST":
        raw = request.form.get("raw_message", "").strip()
        roster_date, parsed = parse_roster_message(raw)

        if not roster_date:
            flash(
                "Could not find a date in the pasted text. "
                "Add a line like: Roster 2024-06-15",
                "danger",
            )
        elif not parsed:
            flash("Date found but no employee rows could be parsed.", "warning")
        else:
            action = request.form.get("action", "preview")
            if action == "save":
                count = save_roster(parsed, raw, "web-paste")
                flash(f"Roster saved — {count} employee(s) for {roster_date}.", "success")
                return redirect(url_for("roster_view", date=roster_date.isoformat()))

    return render_template(
        "roster_paste.html",
        parsed=parsed,
        roster_date=roster_date,
        raw=raw,
    )


# ── Roster View ───────────────────────────────────────────────────────────────

@app.route("/roster/view")
@login_required
def roster_view():
    date_str = request.args.get("date", datetime.date.today().isoformat())
    try:
        target = datetime.date.fromisoformat(date_str)
    except ValueError:
        target = datetime.date.today()

    records = fetch_roster_from_db(target)
    by_dept = group_by_department(records)
    return render_template(
        "roster_view.html",
        records=records,
        by_dept=by_dept,
        target_date=target,
        date_str=date_str,
    )


# ── Reports ───────────────────────────────────────────────────────────────────

@app.route("/reports")
@login_required
def reports():
    date_str = request.args.get("date", datetime.date.today().isoformat())
    rtype    = request.args.get("type", "daily")   # daily | monthly | employee
    emp_name = request.args.get("emp", "")

    try:
        target = datetime.date.fromisoformat(date_str)
    except ValueError:
        target = datetime.date.today()

    year  = int(request.args.get("year",  target.year))
    month = int(request.args.get("month", target.month))

    records  = fetch_roster_from_db(target)
    by_dept  = group_by_department(records)
    text_rpt = text_report(records, target) if records else ""
    wa_rpt   = whatsapp_report(records, target) if records else ""

    # Employee list for employee-wise selector
    from src.db.models import Employee
    sess = _db_session()
    try:
        emp_list = [e.emp_name for e in sess.query(Employee).order_by(Employee.emp_name).all()]
    finally:
        sess.close()

    return render_template(
        "reports.html",
        records=records,
        by_dept=by_dept,
        target_date=target,
        date_str=date_str,
        text_report=text_rpt,
        wa_report=wa_rpt,
        rtype=rtype,
        year=year,
        month=month,
        emp_name=emp_name,
        emp_list=emp_list,
        months=list(calendar.month_name)[1:],
    )


@app.route("/reports/download")
@login_required
def report_download():
    date_str = request.args.get("date", datetime.date.today().isoformat())
    try:
        target = datetime.date.fromisoformat(date_str)
    except ValueError:
        target = datetime.date.today()

    records = fetch_roster_from_db(target)
    content = text_report(records, target)
    filename = f"roster_{target.isoformat()}.txt"
    return Response(
        content,
        mimetype="text/plain",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.route("/reports/pdf/daily")
@login_required
def report_pdf_daily():
    date_str = request.args.get("date", datetime.date.today().isoformat())
    try:
        target = datetime.date.fromisoformat(date_str)
    except ValueError:
        target = datetime.date.today()

    records = fetch_roster_from_db(target)
    from src.reports.pdf_generator import daily_pdf
    company = settings_store.get("company_name", config.COMPANY_NAME)
    pdf_bytes = daily_pdf(records, target, company)
    filename = f"roster_{target.isoformat()}.pdf"
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.route("/reports/pdf/attendance")
@login_required
def report_pdf_attendance():
    date_str = request.args.get("date", datetime.date.today().isoformat())
    include_office = request.args.get("office", "1") == "1"
    try:
        target = datetime.date.fromisoformat(date_str)
    except ValueError:
        target = datetime.date.today()

    records, error = _build_attendance_records(target, include_office)
    from src.reports.pdf_generator import attendance_pdf
    company = settings_store.get("company_name", config.COMPANY_NAME)
    pdf_bytes = attendance_pdf(records, target, company)
    filename = f"attendance_{target.isoformat()}.pdf"
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.route("/reports/pdf/monthly")
@login_required
def report_pdf_monthly():
    year  = int(request.args.get("year",  datetime.date.today().year))
    month = int(request.args.get("month", datetime.date.today().month))
    include_office = request.args.get("office", "1") == "1"

    all_records = []
    _, num_days = calendar.monthrange(year, month)
    for day in range(1, num_days + 1):
        d = datetime.date(year, month, day)
        if d > datetime.date.today():
            break
        recs, _ = _build_attendance_records(d, include_office)
        for r in recs:
            r = dict(r)
            r["date"] = d
            all_records.append(r)

    from src.reports.pdf_generator import monthly_pdf
    company = settings_store.get("company_name", config.COMPANY_NAME)
    pdf_bytes = monthly_pdf(all_records, year, month, company)
    filename = f"monthly_attendance_{year}_{month:02d}.pdf"
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.route("/reports/pdf/employee")
@login_required
def report_pdf_employee():
    emp_name = request.args.get("emp", "")
    year     = int(request.args.get("year",  datetime.date.today().year))
    month    = int(request.args.get("month", datetime.date.today().month))
    if not emp_name:
        flash("Select an employee.", "warning")
        return redirect(url_for("reports"))

    all_records = []
    _, num_days = calendar.monthrange(year, month)
    for day in range(1, num_days + 1):
        d = datetime.date(year, month, day)
        if d > datetime.date.today():
            break
        recs, _ = _build_attendance_records(d, include_office=True)
        for r in recs:
            if r.get("emp_name", "").lower() == emp_name.lower():
                r = dict(r)
                r["date"] = d
                all_records.append(r)

    from src.reports.pdf_generator import employee_pdf
    company = settings_store.get("company_name", config.COMPANY_NAME)
    pdf_bytes = employee_pdf(all_records, emp_name, company)
    safe = emp_name.replace(" ", "_")
    filename = f"attendance_{safe}_{year}_{month:02d}.pdf"
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ── Notify employees ──────────────────────────────────────────────────────────

@app.route("/api/notify", methods=["POST"])
@login_required
def api_notify():
    data = request.get_json(silent=True) or {}
    date_str = data.get("date", datetime.date.today().isoformat())
    dry_run  = data.get("dry_run", False)

    try:
        target = datetime.date.fromisoformat(date_str)
    except ValueError:
        return jsonify({"error": "invalid date"}), 400

    records = fetch_roster_from_db(target)
    if not records:
        return jsonify({"error": "no roster found for date", "date": date_str}), 404

    messages = []
    for rec in records:
        phone = rec.get("phone", "").strip()
        if not phone:
            continue
        messages.append((phone, build_employee_message(rec)))

    summary = whatsapp_report(records, target)
    for ph in config.MANAGER_PHONES:
        if ph:
            messages.append((ph, summary))

    if dry_run:
        return jsonify({"dry_run": True, "messages": [{"phone": p, "message": m} for p, m in messages]})

    result = send_bulk(messages)
    result["date"] = date_str
    return jsonify(result)


# ── Pingerbot inbound webhook ─────────────────────────────────────────────────

@app.route("/webhook/pingerbot", methods=["POST"])
def pingerbot_webhook():
    data = request.get_json(silent=True, force=True)
    log.info("Pingerbot raw payload: %s", request.get_data(as_text=True)[:500])
    if not data:
        return jsonify({"status": "ignored", "reason": "no JSON body"}), 200

    sender = ""
    message = ""

    event = data.get("event", "")
    if event and event != "messages.upsert":
        return jsonify({"status": "ignored", "reason": f"event={event}"}), 200

    if event == "messages.upsert":
        try:
            msg_obj = (data.get("data") or {}).get("messages", [{}])[0]
            if msg_obj.get("key", {}).get("fromMe"):
                return jsonify({"status": "ignored", "reason": "outgoing"}), 200
            sender_raw = msg_obj.get("key", {}).get("senderPn", "")
            sender = sender_raw.split("@")[0]
            msg_inner = msg_obj.get("message", {})
            message = (
                msg_inner.get("conversation") or
                (msg_inner.get("extendedTextMessage") or {}).get("text", "")
            )
        except (KeyError, IndexError, TypeError):
            return jsonify({"status": "ignored", "reason": "unreadable structure"}), 200
    else:
        sender = (
            data.get("from") or data.get("sender") or
            data.get("phone") or data.get("waId") or ""
        )
        message = (
            data.get("message") or data.get("text") or
            data.get("body") or data.get("content") or ""
        )

    if not sender or not message:
        return jsonify({"status": "ignored", "reason": "missing sender or message"}), 200

    log.info("Webhook: message from %s", sender)

    normalised_sender = "+" + sender.lstrip("+")
    if config.AUTHORIZED_SENDERS:
        if normalised_sender not in config.AUTHORIZED_SENDERS:
            log.warning("Rejected message from unauthorised sender: %s", sender)
            return jsonify({"status": "unauthorised"}), 200

    roster_date, records = parse_roster_message(message)

    if not roster_date:
        log_receipt_error(sender, message, "no date found")
        send_message(
            normalised_sender,
            "Could not read the roster. Please include a date line, e.g.:\n"
            "Roster 2024-06-15\nThen list employees one per line.",
        )
        return jsonify({"status": "parse_error", "reason": "no date"}), 200

    if not records:
        log_receipt_error(sender, message, "no rows parsed")
        send_message(
            normalised_sender,
            f"Date {roster_date} found but no employee rows could be parsed.\n"
            "Format example:\nAlice +919876543210 Morning 06:00 14:00",
        )
        return jsonify({"status": "parse_error", "reason": "no rows"}), 200

    count = save_roster(records, message, sender)

    from src.db.models import Employee
    messages = []
    for rec in records:
        phone = rec.get("phone", "").strip()
        if not phone:
            try:
                sess = _db_session()
                try:
                    emp = sess.query(Employee).filter(
                        Employee.emp_name.ilike(rec.get("emp_name", ""))
                    ).first()
                    if emp and emp.phone:
                        phone = emp.phone
                finally:
                    sess.close()
            except Exception:
                pass
        if phone:
            messages.append((phone, build_employee_message(rec)))
    for ph in config.MANAGER_PHONES:
        if ph:
            messages.append((ph, whatsapp_report(records, roster_date)))

    result = send_bulk(messages)

    send_message(
        normalised_sender,
        f"Roster for {roster_date} received and saved.\n"
        f"Employees: {count}\n"
        f"Notifications sent: {result['sent']}\n"
        f"Failed: {result['failed']}",
    )

    return jsonify({
        "status":      "ok",
        "roster_date": str(roster_date),
        "saved":       count,
        "sent":        result["sent"],
        "failed":      result["failed"],
    })


# ── Employee sync ─────────────────────────────────────────────────────────────

def _do_employee_sync() -> int:
    from src.etimetracklite.punch_connector import sync_employees
    from src.db.models import Employee
    rows = sync_employees()
    if not rows:
        return 0
    sess = _db_session()
    try:
        for r in rows:
            code = r["emp_code"]
            if not code:
                continue
            emp = sess.query(Employee).filter_by(emp_code=code).first()
            if emp:
                emp.emp_name   = r["emp_name"]
                emp.department = r["department"]
                emp.phone      = r["phone"]
                emp.synced_at  = datetime.datetime.utcnow()
            else:
                sess.add(Employee(
                    emp_code=code, emp_name=r["emp_name"],
                    department=r["department"], phone=r["phone"],
                ))
        sess.commit()
    finally:
        sess.close()
    return len(rows)


def _employee_sync_loop(interval_hours: int = 4) -> None:
    while True:
        try:
            count = _do_employee_sync()
            log.info("Auto employee sync: %d employees", count)
        except Exception as exc:
            log.warning("Auto employee sync failed: %s", exc)
        time.sleep(interval_hours * 3600)


_sync_thread = threading.Thread(
    target=_employee_sync_loop, kwargs={"interval_hours": 4}, daemon=True
)
_sync_thread.start()


@app.route("/api/sync-employees", methods=["POST"])
@login_required
def api_sync_employees():
    try:
        count = _do_employee_sync()
        if not count:
            return jsonify({"error": "No employees returned from ESSL"}), 500
        return jsonify({"synced": count})
    except Exception as exc:
        log.error("Employee sync error: %s", exc)
        return jsonify({"error": str(exc)}), 500


@app.route("/api/employees")
@login_required
def api_employees():
    from src.db.models import Employee
    sess = _db_session()
    try:
        emps = sess.query(Employee).order_by(Employee.emp_code).all()
        return jsonify([
            {"emp_code": e.emp_code, "emp_name": e.emp_name,
             "department": e.department or "", "phone": e.phone or ""}
            for e in emps
        ])
    finally:
        sess.close()


# ── Settings ──────────────────────────────────────────────────────────────────

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if not current_user.is_admin:
        flash("Admin access required.", "danger")
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        settings_store.set("company_name",          request.form.get("company_name", ""))
        settings_store.set("pingerbot_instance_id", request.form.get("instance_id", ""))
        settings_store.set("pingerbot_access_token",request.form.get("access_token", ""))
        settings_store.set("manager_phones",        request.form.get("manager_phones", ""))
        settings_store.set("authorized_senders",    request.form.get("authorized_senders", ""))
        settings_store.set("send_time",             request.form.get("send_time", "07:00"))

        config.PINGERBOT_INSTANCE_ID = settings_store.get("pingerbot_instance_id")
        config.PINGERBOT_API_TOKEN   = settings_store.get("pingerbot_access_token")
        config.MANAGER_PHONES = [
            p.strip()
            for p in settings_store.get("manager_phones", "").split(",")
            if p.strip()
        ]
        flash("Settings saved.", "success")
        return redirect(url_for("settings"))

    current = {
        "company_name":      settings_store.get("company_name", config.COMPANY_NAME),
        "instance_id":       settings_store.get("pingerbot_instance_id", config.PINGERBOT_INSTANCE_ID),
        "access_token":      settings_store.get("pingerbot_access_token", config.PINGERBOT_API_TOKEN),
        "manager_phones":    settings_store.get("manager_phones", ",".join(config.MANAGER_PHONES)),
        "authorized_senders":settings_store.get("authorized_senders", ",".join(config.AUTHORIZED_SENDERS)),
        "send_time":         settings_store.get("send_time", config.SEND_TIME),
    }
    return render_template("settings.html", current=current)


# ── Attendance Report ─────────────────────────────────────────────────────────

def _build_attendance_records(target: datetime.date, include_office: bool = True):
    """Build combined roster + office attendance for a date. Returns (records, error)."""
    error = None
    records = []
    try:
        roster = fetch_roster_from_db(target)
        from src.etimetracklite.punch_connector import first_last_punches
        punch_summary = first_last_punches(target)

        roster_records = analyse_attendance(roster, punch_summary)
        records.extend(roster_records)

        if include_office:
            from src.db.models import Employee
            sess = _db_session()
            try:
                emp_cache = [
                    {"emp_code": e.emp_code, "emp_name": e.emp_name,
                     "department": e.department or "", "phone": e.phone or ""}
                    for e in sess.query(Employee).all()
                ]
            finally:
                sess.close()

            roster_ids = {r.get("emp_id", "") for r in roster}
            office = analyse_office_employees(roster_ids, punch_summary, target, emp_cache)
            records.extend(office)
    except Exception as exc:
        error = str(exc)
        log.error("Attendance build error for %s: %s", target, exc)
    return records, error


@app.route("/attendance")
@login_required
def attendance():
    date_str = request.args.get("date", datetime.date.today().isoformat())
    include_office = request.args.get("office", "1") == "1"
    try:
        target = datetime.date.fromisoformat(date_str)
    except ValueError:
        target = datetime.date.today()

    records, error = _build_attendance_records(target, include_office)

    status_counts = {
        "PRESENT":    sum(1 for r in records if r["status"] == "PRESENT"),
        "LATE":       sum(1 for r in records if r["status"] == "LATE"),
        "ABSENT":     sum(1 for r in records if r["status"] == "ABSENT"),
        "EARLY_EXIT": sum(1 for r in records if r["status"] == "EARLY_EXIT"),
        "HALF_DAY":   sum(1 for r in records if r["status"] == "HALF_DAY"),
        "OFFICE":     sum(1 for r in records if r["status"] == "OFFICE"),
    }

    return render_template(
        "attendance.html",
        records=records,
        status_counts=status_counts,
        target_date=target,
        date_str=date_str,
        include_office=include_office,
        error=error,
        db_configured=(config.ETL_DB_HOST != "localhost" or config.ETL_DB_PASSWORD != ""),
    )


@app.route("/api/attendance-notify", methods=["POST"])
@login_required
def api_attendance_notify():
    data = request.get_json(silent=True) or {}
    date_str         = data.get("date", datetime.date.today().isoformat())
    notify_employees = data.get("notify_employees", True)
    notify_managers  = data.get("notify_managers", True)
    include_office   = data.get("include_office", True)

    try:
        target = datetime.date.fromisoformat(date_str)
    except ValueError:
        return jsonify({"error": "invalid date"}), 400

    records, error = _build_attendance_records(target, include_office)
    if error and not records:
        return jsonify({"error": error}), 500

    messages = []
    if notify_employees:
        for rec in records:
            phone = rec.get("phone", "").strip()
            if phone:
                messages.append((phone, attendance_employee_message(rec, target)))

    if notify_managers:
        summary = attendance_whatsapp_report(records, target)
        for ph in config.MANAGER_PHONES:
            if ph:
                messages.append((ph, summary))

    result = send_bulk(messages)
    result["date"] = date_str
    result["records"] = len(records)
    return jsonify(result)
