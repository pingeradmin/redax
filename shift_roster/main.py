#!/usr/bin/env python3
"""
Shift Roster — Pingerbot WhatsApp Integration

Commands:
  python main.py web               Start the web dashboard + Pingerbot webhook
  python main.py run               Send today's roster notifications now
  python main.py run --dry-run     Preview messages without sending
  python main.py run --date 2024-06-15
  python main.py schedule          Start daily scheduler daemon (no web UI)
"""
import datetime
import sys
import threading
import time

import click
import schedule

from src.config import config
from src.db.models import init_db
from src.logger import get_logger
from src.runner import run as _run

log = get_logger("main")


@click.group()
def cli():
    """Shift Roster WhatsApp Notification System (Pingerbot)."""
    pass


@cli.command()
@click.option("--host", default="0.0.0.0", help="Listen host")
@click.option("--port", default=None, type=int, help="Listen port (default from .env)")
@click.option("--debug", is_flag=True)
def web(host, port, debug):
    """Start the web dashboard + Pingerbot inbound webhook server."""
    from src.webapp import app
    port = port or config.WEB_PORT
    log.info("Starting web server on %s:%s", host, port)
    click.echo(f"\n  ShiftRoster running at  http://{host}:{port}")
    click.echo(f"  Webhook endpoint        http://{host}:{port}/webhook/pingerbot\n")
    app.run(host=host, port=port, debug=debug)


@cli.command()
@click.option("--date", default=None, help="Target date YYYY-MM-DD")
@click.option("--dry-run", is_flag=True, help="Preview without sending")
def run(date, dry_run):
    """Fetch roster and send WhatsApp notifications."""
    target = None
    if date:
        try:
            target = datetime.date.fromisoformat(date)
        except ValueError:
            click.echo(f"Invalid date: {date}. Use YYYY-MM-DD.", err=True)
            sys.exit(1)
    result = _run(target_date=target, dry_run=dry_run)
    click.echo(f"\nResult: {result}")


@cli.command("schedule")
def schedule_daemon():
    """Start the daily scheduler daemon (no web UI)."""
    send_time = config.SEND_TIME
    log.info("Scheduler started — daily job at %s", send_time)
    click.echo(f"Scheduler running. Daily notifications at {send_time}. Ctrl+C to stop.")
    schedule.every().day.at(send_time).do(_run)
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    init_db()
    cli()
