import click
from flask import current_app
from flask.cli import with_appcontext

from app.extensions import db
from app.models import User
from app.services.demo_seed import (
    DEMO_EMAIL,
    DEMO_PASSWORD,
    DemoSeedError,
    seed_demo_data,
)
from app.services.backup_reconcile import BackupReconciliationService


@click.command("seed-admin")
@with_appcontext
def seed_admin_command() -> None:
    """Create the initial administrator if it does not exist."""
    username = (current_app.config.get("ADMIN_USERNAME") or "").strip()
    password = current_app.config.get("ADMIN_PASSWORD") or ""

    if not username:
        raise click.ClickException("ADMIN_USERNAME is required")
    if len(username) > 80:
        raise click.ClickException("ADMIN_USERNAME must be at most 80 characters")
    if len(password) < 12 or password == "replace-with-a-long-random-password":
        raise click.ClickException("ADMIN_PASSWORD must contain at least 12 characters")

    existing = db.session.execute(
        db.select(User).where(User.username == username)
    ).scalar_one_or_none()
    if existing:
        if not existing.is_admin:
            raise click.ClickException(
                "ADMIN_USERNAME already belongs to a non-admin user"
            )
        click.echo(f"Admin user '{username}' already exists; no changes made.")
        return

    admin = User(username=username, role="admin")
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()
    click.echo(f"Admin user '{username}' created.")


@click.group("seed")
def seed_group() -> None:
    """Populate explicit development and QA fixtures."""


@seed_group.command("demo")
@with_appcontext
def seed_demo_command() -> None:
    """Create idempotent fictional data for manual browser QA."""
    try:
        _user, created = seed_demo_data()
    except DemoSeedError as error:
        raise click.ClickException(str(error)) from error

    total_created = sum(created.values())
    click.echo("Demo QA listo; todos los registros son ficticios.")
    click.echo(f"Email: {DEMO_EMAIL}")
    click.echo(f"Password: {DEMO_PASSWORD}")
    click.echo(f"Registros creados en esta ejecución: {total_created}")


@click.group("backup")
def backup_group() -> None:
    """Operate and reconcile full account backups."""


@backup_group.command("reconcile")
@click.option(
    "--apply",
    "apply_changes",
    is_flag=True,
    help="Apply safe status/staging repairs. Default is dry-run.",
)
@click.option(
    "--stale-after-hours",
    type=click.IntRange(min=1, max=24 * 365),
    default=24,
    show_default=True,
)
@with_appcontext
def backup_reconcile_command(apply_changes: bool, stale_after_hours: int) -> None:
    """Report storage drift without exposing filenames or health data."""
    report = BackupReconciliationService().reconcile(
        apply=apply_changes,
        stale_after_hours=stale_after_hours,
    )
    click.echo(f"mode={report['mode']}")
    for key in (
        "missing_uploads",
        "corrupt_uploads",
        "missing_exports",
        "corrupt_exports",
        "orphan_files",
        "stale_staging",
        "abandoned_runs",
        "records_updated",
        "staging_removed",
        "suspicious_symlinks",
    ):
        click.echo(f"{key}={report[key]}")

    # In dry-run, print per-orphan metadata block (allowlisted, no content/paths).
    orphan_details = report.get("orphan_details", [])
    for index, detail in enumerate(orphan_details):
        click.echo(f"orphan[{index}]:")
        click.echo(f"  storage_kind={detail['storage_kind']}")
        if "relative_path" in detail:
            click.echo(f"  relative_path={detail['relative_path']}")
        else:
            click.echo(f"  path_fingerprint={detail['path_fingerprint']}")
        click.echo(f"  size_bytes={detail['size_bytes']}")
        click.echo(f"  sha256={detail['sha256']}")
        click.echo(f"  modified_at={detail['modified_at']}")
        click.echo(f"  probable_category={detail['probable_category']}")
        click.echo(f"  matching_database_record={str(detail['matching_database_record']).lower()}")

    suspicious_symlinks = report.get("suspicious_symlink_details", [])
    for index, detail in enumerate(suspicious_symlinks):
        click.echo(f"symlink[{index}]:")
        click.echo(f"  storage_kind={detail['storage_kind']}")
        click.echo(f"  path_fingerprint={detail['path_fingerprint']}")
        click.echo(f"  reason={detail['reason']}")


def register_commands(app) -> None:
    app.cli.add_command(seed_admin_command)
    app.cli.add_command(seed_group)
    app.cli.add_command(backup_group)
