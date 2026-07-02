import click
from flask import current_app
from flask.cli import with_appcontext

from app.extensions import db
from app.models import User


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


def register_commands(app) -> None:
    app.cli.add_command(seed_admin_command)
