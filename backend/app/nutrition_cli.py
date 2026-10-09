"""Explicit admin commands; never invoked by daily food search."""
import json
from pathlib import Path
import click
from flask.cli import with_appcontext
from app.extensions import db
from app.services import food_catalog as catalog
from app.services.nutrition_math import NutritionError


@click.group('nutrition-catalog')
def nutrition_catalog_group():
    """Validate/stage/activate bounded local catalog snapshots."""


@nutrition_catalog_group.command('sync')
@click.argument('snapshot',type=click.Path(exists=True,dir_okay=False,path_type=Path))
@click.option('--dry-run',is_flag=True)
@with_appcontext
def sync(snapshot,dry_run):
    if snapshot.stat().st_size>50_000_000:
        raise click.ClickException('Snapshot exceeds reviewed 50 MB budget.')
    try:
        document=json.loads(snapshot.read_text(encoding='utf-8'))
        catalog.LocalSnapshotSource().validate(document)
        if dry_run:
            click.echo(json.dumps({'valid':True,'food_count':len(document['foods']),'bytes':snapshot.stat().st_size}))
            return
        revision=catalog.stage(document)
        db.session.commit()
        click.echo(json.dumps({'source':revision.source_id,'revision':revision.revision,'state':revision.state}))
    except (NutritionError,ValueError) as error:
        db.session.rollback()
        raise click.ClickException(str(error)) from error


@nutrition_catalog_group.command('activate')
@click.argument('source')
@click.argument('revision')
@click.option('--base-revision',type=int,required=True)
@with_appcontext
def activate(source,revision,base_revision):
    catalog.activate(source,revision,base_revision)
    db.session.commit()
    click.echo('Catalog revision activated atomically.')


@nutrition_catalog_group.command('rollback')
@click.argument('source')
@click.option('--base-revision',type=int,required=True)
@with_appcontext
def rollback(source,base_revision):
    catalog.rollback(source,base_revision)
    db.session.commit()
    click.echo('Previous snapshot restored; historical events preserved.')


@nutrition_catalog_group.command('status')
@with_appcontext
def status():
    click.echo(json.dumps(catalog.status()))
