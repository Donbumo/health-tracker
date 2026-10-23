"""Delivery B read model. Bounded audit pages, never a writer or public contract."""
from datetime import date, timezone
from pathlib import Path, PurePosixPath
import hashlib
import hmac
import json
import re

from flask import current_app
from itsdangerous import BadSignature, URLSafeTimedSerializer
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import DailyEnergy, EnergyDay, EnergyEvidenceEvent, UploadedFile
from app.services import energy_days
from app.services.energy_history import METRICS, supported_day
from app.services.backups import BackupError, resolve_uploaded_download

PAGE_SIZE = 25
OPERATIONS = {'import': 'Importación', 'conflict': 'Contradicción conservada',
              'edit_day': 'Decisión del día', 'delete_day': 'Retirada del día',
              'delete_source': 'Retirada de fuente', 'create_steps': 'Registro de pasos',
              'patch_steps': 'Revisión de pasos', 'delete_steps': 'Retirada de pasos'}


def _mapping(value):
    return value if isinstance(value, dict) else {}


def parsed_date(value):
    if not value:
        return None
    target = date.fromisoformat(value)
    if not 1900 <= target.year <= 9998:
        raise ValueError('Fecha fuera del intervalo de consulta.')
    return target


def filters(arguments):
    start, end = parsed_date(arguments.get('from')), parsed_date(arguments.get('to'))
    source = arguments.get('source', '').strip()
    operation = arguments.get('operation', '').strip()
    page = int(arguments.get('page', '1'))
    if (start and end and start > end) or len(source) > 32 or page < 1:
        raise ValueError('Filtros inválidos.')
    if operation and not re.fullmatch('[a-z_]{1,24}', operation):
        raise ValueError('Operación inválida.')
    return {'start': start, 'end': end, 'source': source, 'operation': operation, 'page': page}


def metrics(values):
    """Only canonical metric names, never notes, incoming payloads or raw JSON."""
    values = _mapping(values)
    result = []
    for key, label, unit in METRICS:
        try:
            value = energy_days.decoded(key, values.get(key))
        except (ValueError, TypeError):
            value = None
        result.append({'key': key, 'label': label, 'unit': unit, 'value': value})
    return result


def decisions(resolutions):
    resolutions = _mapping(resolutions)
    result = []
    for key, label, unit in METRICS:
        resolution = resolutions.get(key)
        if not isinstance(resolution, dict):
            continue
        value = metrics({key: resolution.get('value')})[[m[0] for m in METRICS].index(key)]['value']
        sources = [{'source': source, 'value': metrics({key: original})[[m[0] for m in METRICS].index(key)]['value']}
                   for source, original in _mapping(resolution.get('source_values')).items()]
        result.append({'label': label, 'unit': unit, 'value': value,
                       'cleared': resolution.get('value') is None, 'sources': sources})
    return result


def _signer():
    return URLSafeTimedSerializer(current_app.secret_key, salt='energy-private-original-v1')


def _reference(record, file):
    key = current_app.secret_key
    key = key.encode() if isinstance(key, str) else key
    return hmac.new(key, json.dumps([record.id, file.id, file.sha256]).encode(), 'sha256').hexdigest()


def _files(user_id, ids):
    return {row.id: row for row in db.session.scalars(db.select(UploadedFile).where(
        UploadedFile.user_id == user_id, UploadedFile.id.in_(ids)))} if ids else {}


def original(user_id, kind, record, files):
    file = files.get(record.source_file_id)
    if file is None or (record.source_file_sha256 is not None and record.source_file_sha256 != file.sha256):
        return None
    return {'name': Path(file.original_filename.replace('\\', '/')).name,
            'historical_hash': record.source_file_sha256 is not None,
            'token': _signer().dumps([user_id, kind, record.id, file.id, _reference(record, file)])}


def sources(user_id, target):
    registry = db.session.scalar(db.select(EnergyDay).where(EnergyDay.user_id == user_id, EnergyDay.date == target))
    rows = db.session.scalars(db.select(DailyEnergy).where(DailyEnergy.user_id == user_id,
        DailyEnergy.date == target).order_by(DailyEnergy.source, DailyEnergy.id)).all()
    files = _files(user_id, {row.source_file_id for row in rows if row.source_file_id})
    canonical = energy_days.view(user_id, target)
    conflicts = [{'label': label, 'unit': unit, 'values': [energy_days.decoded(key, v) for v in canonical.conflicts[key]]}
                 for key, label, unit in METRICS if canonical and key in canonical.conflicts]
    return {'target': target, 'canonical': canonical, 'conflicts': conflicts,
            'day_deleted': bool(registry and registry.deleted_at),
            'decisions': decisions((registry.resolutions_json or {}) if registry else {}),
            'sources': [{'source': row.source, 'revision': row.revision,
                         'retired': row.deleted_at is not None,
                         'metrics': metrics({key: getattr(row, key) for key, _, _ in METRICS}),
                         'original': original(user_id, 'source', row, files)} for row in rows]}


def audit(user_id, selected):
    # A recorded origin is historical: never substitute today's source label.
    # No UUID join across old/new 0046 tables (their collations can differ).
    source = EnergyEvidenceEvent.payload_json['record']['source'].as_string()
    criteria = [EnergyEvidenceEvent.user_id == user_id]
    if selected['start']:
        criteria.append(EnergyEvidenceEvent.date >= selected['start'])
    if selected['end']:
        criteria.append(EnergyEvidenceEvent.date <= selected['end'])
    if selected['source']:
        criteria.append(source == selected['source'])
    if selected['operation']:
        criteria.append(EnergyEvidenceEvent.kind == selected['operation'])
    total = db.session.scalar(db.select(db.func.count()).select_from(EnergyEvidenceEvent).where(*criteria))
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(selected['page'], pages)
    records = db.session.execute(db.select(EnergyEvidenceEvent, source).where(
        *criteria).order_by(EnergyEvidenceEvent.created_at.desc(), EnergyEvidenceEvent.id.desc()).limit(
            PAGE_SIZE).offset((page - 1) * PAGE_SIZE)).all()
    files = _files(user_id, {record.source_file_id for record, _ in records if record.source_file_id})
    items = []
    for record, label in records:
        payload = _mapping(record.payload_json)
        snapshot = _mapping(payload.get('record'))
        incoming = _mapping(payload.get('incoming'))
        try:
            previous_date = parsed_date(_mapping(payload.get('before')).get('date'))
        except (ValueError, TypeError):
            previous_date = None
        stamp = record.created_at
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        items.append({'date': record.date, 'created_at': stamp,
                      'date_supported': supported_day(record.date),
                      'previous_date': previous_date if previous_date != record.date else None,
                      'source': label or 'Origen no disponible',
                      'operation': OPERATIONS.get(record.kind, record.kind.replace('_', ' ')),
                      'revision': snapshot.get('revision'), 'retired': bool(snapshot.get('deleted')),
                      'metrics': metrics(snapshot.get('values') or {}),
                      'proposals': [m for m in metrics(payload.get('conflicts')) if m['key'] in _mapping(payload.get('conflicts'))],
                      'before': metrics(_mapping(payload.get('before')).get('values')) if payload.get('before') else None,
                      'decisions': decisions(incoming.get('resolutions') or incoming.get('review') or {}),
                      'original': original(user_id, 'event', record, files)})
    source_choices = db.session.scalars(db.select(source).where(
        EnergyEvidenceEvent.user_id == user_id).distinct().order_by(source)).all()
    operations = db.session.scalars(db.select(EnergyEvidenceEvent.kind).where(
        EnergyEvidenceEvent.user_id == user_id).distinct().order_by(EnergyEvidenceEvent.kind)).all()
    return {'items': items, 'total': total, 'page': page, 'pages': pages, 'page_size': PAGE_SIZE,
            'filters': selected, 'source_choices': [s for s in source_choices if s],
            'operation_choices': [(kind, OPERATIONS.get(kind, kind.replace('_', ' '))) for kind in operations]}


def download(user_id, token):
    """Resolve the original again at click time; never trust the page or client."""
    try:
        payload = _signer().loads(token, max_age=15 * 60)
        if not isinstance(payload, list) or len(payload) != 5 or type(payload[0]) is not int or payload[0] != user_id:
            raise ValueError()
        _, kind, record_id, file_id, proof = payload
        model = {'source': DailyEnergy, 'event': EnergyEvidenceEvent}.get(kind)
        if model is None or type(record_id) is not int:
            raise ValueError()
        record = db.session.scalar(db.select(model).where(model.user_id == user_id, model.id == record_id))
        if record is None:
            raise ValueError()
        file = db.session.scalar(db.select(UploadedFile).where(UploadedFile.user_id == user_id,
            UploadedFile.id == record.source_file_id))
        if (file is None or type(file_id) is not int or file.id != file_id or not isinstance(proof, str)
                or not hmac.compare_digest(proof, _reference(record, file))
                or (record.source_file_sha256 is not None and record.source_file_sha256 != file.sha256)):
            raise ValueError()
        relative = PurePosixPath(file.storage_path)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError()
        # Refuse every symlink component, including links within managed storage.
        root = Path(current_app.config['DATA_ROOT'])
        candidate = root
        if root.is_symlink():
            raise ValueError()
        for component in relative.parts:
            candidate = candidate / component
            if candidate.is_symlink():
                raise ValueError()
        # A valid file record must still point into this owner's storage area.
        allowed = [Path(current_app.config[key]) / f'user_{user_id}' for key in ('UPLOAD_ROOT', 'GENERATED_UPLOAD_ROOT')]
        if not any(candidate.resolve().is_relative_to(area.resolve()) for area in allowed):
            raise ValueError()
        path = resolve_uploaded_download(file, user_id=user_id)
        stream = path.open('rb')
        try:
            # Verify the actual descriptor served, so a swap after path checking
            # cannot cause bytes from a different file to be sent.
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            if digest != file.sha256 or stream.tell() != file.size_bytes:
                raise ValueError()
            stream.seek(0)
        except Exception:
            stream.close()
            raise
        return stream, secure_filename(file.original_filename) or 'original.bin'
    except (BadSignature, ValueError, TypeError, OSError, BackupError) as error:
        raise LookupError('Original no disponible o no verificable. Actualiza la consulta.') from error
