"""
Flask web application:
  /            → dashboard (today's roster)
  /login       → login
  /roster/input   → manual roster entry form
  /roster/paste   → paste bulk text / WhatsApp message
  /roster/view    → view roster by date
  /reports        → generate & download reports
  /attendance     → attendance report (roster vs actual punches from ESSL DB)
  /api/attendance-notify → send attendance report via WhatsApp
  /webhook/pingerbot → inbound WhatsApp via Pingerbot
  /api/notify     → trigger employee notifications
"""
from __future__ import annotations

import datetime
import io
import os

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, jsonify, Response,
)
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user,
)
from werkzeug.security import generate_password_hash, check_password_hash

from src.config import config
from src.db.models import init_db
from src.db import settings_store
from src.db.roster_store import (
    fetch_roster_from_db, save_roster, log_receipt_error,
)
from src.logger import get_logger
from src.roster.parser import parse_roster_message
from src.roster.processor import (
    build_employee_message, build_full_summary, group_by_department,
)
from src.roster.report import text_report, whatsapp_report
from src.roster.attendance import (
    analyse as analyse_attendance,
    attendance_whatsapp_report,
    attendance_employee_message,
)
from src.whatsapp.pingerbot import send_message, send_bulk

log = get_logger(__name__)

# ── App setup ────────────────────────────────────────────────────────────────

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

# ── Auth ─────────────────────────────────────────────────────────────────────

_PWD_HASH = generate_password_hash(config.ADMIN_PASSWORD)


class AdminUser(UserMixin):
    id = "admin"


@login_manager.user_loader
def load_user(user_id):
    return AdminUser() if user_id == "admin" else None


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if (
            username == config.ADMIN_USERNAME
            and check_password_hash(_PWD_HASH, password)
        ):
            login_user(AdminUser())
            return redirect(url_for("dashboard"))
        flash("Invalid credentials.", "danger")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


# ── Dashboard ────────────────────────────────────────────────────────────────

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

        # Collect rows from the dynamic table form
        records = []
        names  = request.form.getlist("emp_name")
        phones = request.form.getlist("phone")
        depts  = request.form.getlist("department")
        codes  = request.form.getlist("shift_code")
        snames = request.form.getlist("shift_name")
        starts = request.form.getlist("shift_start")
        ends   = request.form.getlist("shift_end")
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
    return render_template("roster_input.html", today=today_str)


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
    try:
        target = datetime.date.fromisoformat(date_str)
    except ValueError:
        target = datetime.date.today()

    records = fetch_roster_from_db(target)
    by_dept = group_by_department(records)
    text_rpt = text_report(records, target) if records else ""
    wa_rpt = whatsapp_report(records, target) if records else ""

    return render_template(
        "reports.html",
        records=records,
        by_dept=by_dept,
        target_date=target,
        date_str=date_str,
        text_report=text_rpt,
        wa_report=wa_rpt,
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


# ── Notify employees ──────────────────────────────────────────────────────────

@app.route("/api/notify", methods=["POST"])
@login_required
def api_notify():
    data = request.get_json(silent=True) or {}
    date_str = data.get("date", datetime.date.today().isoformat())
    dry_run = data.get("dry_run", False)

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

    # Manager summary
    summary = whatsapp_report(records, target)
    for ph in config.MANAGER_PHONES:
        if ph:
            messages.append((ph, summary))

    if dry_run:
        preview = [{"phone": p, "message": m} for p, m in messages]
        return jsonify({"dry_run": True, "messages": preview})

    result = send_bulk(messages)
    result["date"] = date_str
    return jsonify(result)


# ── Pingerbot inbound webhook ─────────────────────────────────────────────────

@app.route("/webhook/pingerbot", methods=["POST"])
def pingerbot_webhook():
    """
    Receive inbound WhatsApp messages from Pingerbot.

    Expected JSON body (adjust field names to match your Pingerbot version):
    {
        "from":    "+919876543210",
        "message": "Roster 2024-06-15\nAlice ...",
        ...
    }
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "ignored", "reason": "no JSON body"}), 200

    # Normalise field names (Pingerbot may use different keys)
    sender  = (
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

    # Check authorised senders (skip check if list is empty = allow all)
    normalised_sender = "+" + sender.lstrip("+")
    if config.AUTHORIZED_SENDERS:
        if normalised_sender not in config.AUTHORIZED_SENDERS:
            log.warning("Rejected message from unauthorised sender: %s", sender)
            return jsonify({"status": "unauthorised"}), 200

    # Parse roster
    roster_date, records = parse_roster_message(message)

    if not roster_date:
        log_receipt_error(sender, message, "no date found")
        send_message(
            normalised_sender,
            "❌ Could not read the roster. Please include a date line, e.g.:\n"
            "*Roster 2024-06-15*\nThen list employees one per line.",
        )
        return jsonify({"status": "parse_error", "reason": "no date"}), 200

    if not records:
        log_receipt_error(sender, message, "no rows parsed")
        send_message(
            normalised_sender,
            f"⚠️ Date *{roster_date}* found but no employee rows could be parsed.\n"
            "Format example:\n"
            "Alice +919876543210 Morning 06:00 14:00",
        )
        return jsonify({"status": "parse_error", "reason": "no rows"}), 200

    # Save
    count = save_roster(records, message, sender)

    # Auto-notify employees
    messages = []
    for rec in records:
        phone = rec.get("phone", "").strip()
        if phone:
            messages.append((phone, build_employee_message(rec)))
    for ph in config.MANAGER_PHONES:
        if ph:
            messages.append((ph, whatsapp_report(records, roster_date)))

    result = send_bulk(messages)

    # Confirm back to roster sender
    send_message(
        normalised_sender,
        f"✅ Roster for *{roster_date}* received and saved.\n"
        f"  Employees: {count}\n"
        f"  Notifications sent: {result['sent']}\n"
        f"  Failed: {result['failed']}",
    )

    return jsonify({
        "status":       "ok",
        "roster_date":  str(roster_date),
        "saved":        count,
        "sent":         result["sent"],
        "failed":       result["failed"],
    })


# ── Settings ──────────────────────────────────────────────────────────────────

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        settings_store.set("pingerbot_instance_id", request.form.get("instance_id", ""))
        settings_store.set("pingerbot_access_token", request.form.get("access_token", ""))
        settings_store.set("manager_phones", request.form.get("manager_phones", ""))
        settings_store.set("authorized_senders", request.form.get("authorized_senders", ""))
        settings_store.set("send_time", request.form.get("send_time", "07:00"))

        # Apply to live config so next send uses new values
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
        "instance_id":       settings_store.get("pingerbot_instance_id",
                                                  config.PINGERBOT_INSTANCE_ID),
        "access_token":      settings_store.get("pingerbot_access_token",
                                                  config.PINGERBOT_API_TOKEN),
        "manager_phones":    settings_store.get("manager_phones",
                                                  ",".join(config.MANAGER_PHONES)),
        "authorized_senders": settings_store.get("authorized_senders",
                                                   ",".join(config.AUTHORIZED_SENDERS)),
        "send_time":         settings_store.get("send_time", config.SEND_TIME),
    }
    return render_template("settings.html", current=current)


# ── Attendance Report (roster vs ESSL punches) ────────────────────────────────

@app.route("/attendance")
@login_required
def attendance():
    date_str = request.args.get("date", datetime.date.today().isoformat())
    try:
        target = datetime.date.fromisoformat(date_str)
    except ValueError:
        target = datetime.date.today()

    roster  = []
    records = []
    error   = None

    try:
        from src.db.roster_store import fetch_roster_from_db
        roster = fetch_roster_from_db(target)

        if roster:
            from src.etimetracklite.punch_connector import first_last_punches
            punch_summary = first_last_punches(target)
            records = analyse_attendance(roster, punch_summary)
    except Exception as exc:
        error = str(exc)
        log.error("Attendance fetch error: %s", exc)

    status_counts = {
        "PRESENT":    sum(1 for r in records if r["status"] == "PRESENT"),
        "LATE":       sum(1 for r in records if r["status"] == "LATE"),
        "ABSENT":     sum(1 for r in records if r["status"] == "ABSENT"),
        "EARLY_EXIT": sum(1 for r in records if r["status"] == "EARLY_EXIT"),
        "HALF_DAY":   sum(1 for r in records if r["status"] == "HALF_DAY"),
    }

    return render_template(
        "attendance.html",
        records=records,
        status_counts=status_counts,
        target_date=target,
        date_str=date_str,
        error=error,
        db_configured=(config.ETL_DB_HOST != "localhost" or config.ETL_DB_PASSWORD != ""),
    )


@app.route("/api/attendance-notify", methods=["POST"])
@login_required
def api_attendance_notify():
    data = request.get_json(silent=True) or {}
    date_str = data.get("date", datetime.date.today().isoformat())
    notify_employees = data.get("notify_employees", True)
    notify_managers  = data.get("notify_managers", True)

    try:
        target = datetime.date.fromisoformat(date_str)
    except ValueError:
        return jsonify({"error": "invalid date"}), 400

    from src.db.roster_store import fetch_roster_from_db
    roster = fetch_roster_from_db(target)
    if not roster:
        return jsonify({"error": "no roster for date"}), 404

    from src.etimetracklite.punch_connector import first_last_punches
    punch_summary = first_last_punches(target)
    records = analyse_attendance(roster, punch_summary)

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
