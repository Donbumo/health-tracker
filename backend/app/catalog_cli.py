import json
import click
from flask.cli import with_appcontext
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.services.exercise_catalog import catalog_status, cleanup_catalog, sync_catalog
from app.services.exercise_catalog_source import CatalogError


@click.group("exercise-catalog")
def catalog_group():
    """Manage local exercise reference snapshots (administrator CLI only)."""


@catalog_group.command("sync")
@click.option("--source", type=click.Choice(["free-exercise-db"]), default="free-exercise-db")
@click.option("--ref", default="main", help="Resolve once to an immutable source commit.")
@click.option("--dry-run", is_flag=True)
@click.option("--metadata-only", is_flag=True)
@with_appcontext
def sync_command(source, ref, dry_run, metadata_only):
    try:
        result = sync_catalog(ref=ref, dry_run=dry_run, metadata_only=metadata_only)
    except (ValueError, OSError, SQLAlchemyError) as error:
        db.session.rollback()
        raise click.ClickException(str(error) if isinstance(error, CatalogError) else "Sync failed; previous catalog remains active.") from None
    click.echo(json.dumps(result, indent=2))


@catalog_group.command("status")
@with_appcontext
def status_command():
    click.echo(json.dumps(catalog_status(), indent=2))


@catalog_group.command("cleanup")
@with_appcontext
def cleanup_command():
    """Keep the current and previous snapshots; remove orphan staging."""
    try:
        click.echo(json.dumps({"removed_snapshots": cleanup_catalog()}))
    except (CatalogError, OSError):
        raise click.ClickException("Cleanup failed; inspect catalog storage.") from None
