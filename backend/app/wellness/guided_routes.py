"""C: explicit steps, existing writers, no schema or reconciliation policy changes."""
import hashlib
import io
import json

from flask import abort, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.services import energy_days as energy
from app.services import energy_guided as guided
from app.services.energy_provenance import parsed_date
from app.services.files import store_uploaded_file, mark_import_status, UploadError
from app.services.importers.standard_import_executor import StandardImportError, StandardImportTokenError
from app.wellness import wellness_bp


def page(mode, step=1, status=200, **values):
    response = current_app.make_response((render_template('wellness/energy_guided.html', mode=mode, step=step, **values), status))
    response.headers['Cache-Control'] = 'private, no-store'
    return response


def used(token):
    return hashlib.sha256(token.encode()).hexdigest() in session.get('energy_guided_used', [])


def remember(token):
    session['energy_guided_used'] = [*session.get('energy_guided_used', []), hashlib.sha256(token.encode()).hexdigest()][-20:]


@wellness_bp.route('/energy/import', methods=['GET', 'POST'])
@login_required
def energy_guided_import():
    if request.method == 'GET':
        return page('import', preview=None, envelope=None, error=None)
    preview = envelope = None
    try:
        action = request.form.get('action')
        if action == 'confirm' and used(request.form.get('review_token', '')):
            flash('Esta confirmación ya se procesó. No se creó otro consumo ni gasto.', 'info')
            return redirect(url_for('wellness.energy_history'))
        if action == 'upload':
            file = request.files.get('file')
            if file is None:
                raise ValueError('Selecciona un archivo JSON.')
            envelope = guided.upload_envelope(file)
        else:
            envelope = json.loads(request.form.get('envelope', ''))
        preview = guided.import_preview(envelope, current_user.id)
        token = request.form.get('review_token', '')
        stage = request.form.get('stage', '')
        if action != 'upload':
            if (action, stage) not in (('review','2'), ('approve','3'), ('confirm','4'), ('back','3'), ('back','4')):
                raise ValueError('Paso inválido.')
            guided.verify(token, current_user.id, 'import:'+stage, preview['material'], preview['state'])
        if action == 'confirm':
            if request.form.get('confirm') != 'yes':
                raise ValueError('Marca la confirmación explícita para registrar la evidencia revisada.')
            if used(token):
                flash('Esta confirmación ya se procesó. No se creó otro consumo ni gasto.', 'info')
                return redirect(url_for('wellness.energy_sources', date=preview['target']))
            # Lock and verify before storing the original, then verify again after
            # the official upload service commits its separate file metadata.
            energy.lock_owner(current_user.id)
            guided.verify(token, current_user.id, 'import:4', preview['material'], energy.state_fingerprint(current_user.id, [preview['target']], lock=True))
            raw, _ = guided.unpack(envelope)
            file, _ = store_uploaded_file(FileStorage(stream=io.BytesIO(raw), filename=envelope['name'], content_type='application/json'), current_user.id)
            executor = preview['executor']
            fresh = guided.import_preview(envelope, current_user.id)
            energy.lock_owner(current_user.id)
            guided.verify(token, current_user.id, 'import:4', fresh['material'], energy.state_fingerprint(current_user.id, [preview['target']], lock=True))
            result = executor.commit_documents([fresh['document']], user_id=current_user.id, target_type='daily_energy', confirmed=True,
                source_file=file, audit_payload=fresh['document'], audit_metadata={'route': '/energy/import', 'mode': 'guided_confirm'})
            if not result['committed']:
                db.session.rollback()
                raise energy.EnergyConflict('No se aplicó el lote. El original queda conservado para auditoría; revisa de nuevo.')
            mark_import_status(file, current_user.id, status='duplicate' if result['skips'] else 'imported', detected_type='daily_energy')
            remember(token)
            flash('Evidencia revisada registrada. Las contradicciones permanecen pendientes hasta una decisión explícita.', 'success')
            return redirect(url_for('wellness.energy_sources', date=preview['target']))
        if action not in ('upload', 'review', 'approve', 'back'):
            raise ValueError('Paso inválido.')
        step = 4 if action == 'approve' else 3 if action == 'review' else 2
        token = guided.sign(current_user.id, 'import:'+str(step), preview['material'], preview['state'])
        return page('import', step, preview=preview, envelope=envelope, token=token, error=None)
    except (energy.EnergyConflict, StandardImportTokenError):
        db.session.rollback()
        return page('import', status=409, preview=None, envelope=None, error='La revisión cambió, caducó o no se pudo confirmar. No se aplicaron cambios energéticos. Selecciona el archivo y revisa de nuevo; un original ya guardado se conserva para auditoría.')
    except (ValueError, TypeError, KeyError, StandardImportError, UploadError) as exc:
        db.session.rollback()
        return page('import', status=400, preview=None, envelope=None, error=str(exc) if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError) else 'Propuesta inválida. Prepara una nueva revisión.')


@wellness_bp.route('/energy/review', methods=['GET', 'POST'])
@login_required
def energy_guided_review():
    try:
        target = parsed_date(request.values.get('date'))
        if target is None:
            raise ValueError('Selecciona una fecha.')
        if request.method == 'GET':
            preview = guided.review_preview(current_user.id, target)
            return page('review', 2, preview=preview, operations=None, error=None)
        action = request.form.get('action')
        operations = json.loads(request.form['operations']) if action in ('confirm', 'approve') else {
            field: {'choice': request.form.get('choice_'+field, 'keep'), 'value': request.form.get('value_'+field, '')} for field in energy.FIELDS}
        preview = guided.review_preview(current_user.id, target, operations)
        mode = 'review:'+target.isoformat()
        if action == 'confirm':
            token = request.form.get('review_token', '')
            if used(token):
                return redirect(url_for('wellness.energy_sources', date=target))
            if request.form.get('confirm') != 'yes':
                raise ValueError('Confirma explícitamente las operaciones revisadas.')
            energy.lock_owner(current_user.id)
            guided.verify(token, current_user.id, mode+':4', preview['material'], energy.state_fingerprint(current_user.id, [target], lock=True))
            energy.edit_day(current_user.id, target, preview['revision'], preview['values'], clear=preview['clear'])
            db.session.commit(); remember(token)
            flash('Decisiones confirmadas; las evidencias originales permanecen intactas.', 'success')
            return redirect(url_for('wellness.energy_sources', date=target))
        if action not in ('review', 'approve'):
            raise ValueError('Paso inválido.')
        if action == 'approve':
            guided.verify(request.form.get('review_token',''), current_user.id, mode+':3', preview['material'], preview['state'])
        step = 4 if action == 'approve' else 3
        token = guided.sign(current_user.id, mode+':'+str(step), preview['material'], preview['state'])
        return page('review', step, preview=preview, operations=preview['material'], token=token, error=None)
    except LookupError:
        abort(404)
    except energy.EnergyConflict:
        db.session.rollback()
        return page('review', status=409, preview=None, operations=None, error='El día o la revisión cambió. Vuelve a abrir sus fuentes antes de confirmar.')
    except (ValueError, TypeError, KeyError):
        db.session.rollback()
        return page('review', status=400, preview=None, operations=None, error='Revisa las operaciones, unidades y límites. No se guardaron cambios.')
