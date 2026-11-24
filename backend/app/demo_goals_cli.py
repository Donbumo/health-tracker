import json

import click
from flask.cli import with_appcontext

from app.extensions import db
from app.services.demo_goals import seed_demo_goals


@click.command("seed-demo-goals")
@click.option("--confirm", is_flag=True, help="Confirmar escritura aditiva de metas ficticias DEMO.")
@click.option("--confirm-production", is_flag=True, help="Confirmación adicional para producción.")
@with_appcontext
def seed_demo_goals_command(confirm, confirm_production):
    try:
        result = seed_demo_goals(confirmed=confirm, confirm_production=confirm_production)
        db.session.commit()
    except Exception as error:
        db.session.rollback()
        # Never echo database exceptions, connection strings or sensitive payloads.
        if isinstance(error, ValueError):
            raise click.ClickException(str(error)) from None
        raise click.ClickException("No se guardaron metas; operación revertida.") from None
    click.echo(json.dumps(result, ensure_ascii=False))
    if result["conflicts"]:
        raise click.ClickException("Se conservaron las metas en conflicto; revisa el informe.")
