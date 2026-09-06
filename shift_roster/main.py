#!/usr/bin/env python3
"""
Entry point — CLI and scheduler.

Usage:
  python main.py run               # Send today's roster notifications now
  python main.py run --dry-run     # Preview messages without sending
  python main.py run --date 2024-06-15  # Run for a specific date
  python main.py schedule          # Start the daily scheduler daemon
"""
import datetime
import sys

import click
import schedule
import time

from src.config import config
from src.logger import get_logger
from src.runner import run as _run

log = get_logger("main")


@click.group()
def cli():
    """Shift Roster WhatsApp Notification System."""
    pass


@cli.command()
@click.option("--date", default=None, help="Target date YYYY-MM-DD (default: today + offset)")
@click.option("--dry-run", is_flag=True, help="Print messages without sending")
def run(date, dry_run):
    """Fetch roster and send WhatsApp notifications."""
    target = None
    if date:
        try:
            target = datetime.date.fromisoformat(date)
        except ValueError:
            click.echo(f"Invalid date format: {date}. Use YYYY-MM-DD.", err=True)
            sys.exit(1)

    result = _run(target_date=target, dry_run=dry_run)
    click.echo(f"\nResult: {result}")


@cli.command()
def schedule_daemon():
    """Start the scheduler daemon — sends notifications daily at SEND_TIME."""
    send_time = config.SEND_TIME
    log.info("Scheduler started. Will run daily at %s", send_time)
    click.echo(f"Scheduler running. Daily job at {send_time}. Press Ctrl+C to stop.")

    schedule.every().day.at(send_time).do(_run)

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    cli()
