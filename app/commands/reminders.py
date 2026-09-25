"""Flask CLI commands for reminders."""

import click
from flask import current_app
from flask.cli import with_appcontext

from app.services.reminders import check_and_send_reminders


@click.command('check-reminders')
@click.option('--hospital-id', type=int, help='Filter by hospital ID')
@with_appcontext
def check_reminders_command(hospital_id):
    """Check and send appointment reminders."""
    click.echo('Checking for appointments needing reminders...')
    result = check_and_send_reminders(hospital_id=hospital_id)
    click.echo(f'Reminders sent: {result}')