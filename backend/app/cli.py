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


def register_commands(app) -> None:
    app.cli.add_command(seed_admin_command)
    app.cli.add_command(seed_group)
