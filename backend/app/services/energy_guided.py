"""Read-only guided previews. Domain writes stay in the existing official services."""
import base64
import binascii
import json
import hashlib
from pathlib import PurePosixPath

from flask import current_app
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.extensions import db
from app.models import DailyEnergy, EnergyDay
from app.services import energy_days as energy
from app.services.energy_history import METRICS
from app.services.energy_provenance import parsed_date
from app.services.importers.standard_import_executor import StandardImportExecutor

MAX_BYTES = 256 * 1024
FIELDS = [*METRICS, ('notes', 'Notas', '')]


class GuidedInputError(ValueError):
    """Presentation context only; official validation/ranges remain authoritative."""
    def __init__(self, field, message):
        super().__init__(message)
        self.field = field


def serializer():
    return URLSafeTimedSerializer(current_app.secret_key, salt='energy-guided-review-v1')


def sign(user_id, mode, material, state):
    digest = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return serializer().dumps({'owner': user_id, 'mode': mode, 'material': digest, 'state': state})


def verify(token, user_id, mode, material, state):
    try:
        saved = serializer().loads(token, max_age=15 * 60)
    except BadSignature as exc:
        raise energy.EnergyConflict('La revisión caducó o no es válida. Prepara una nueva.') from exc
    digest = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if saved != {'owner': user_id, 'mode': mode, 'material': digest, 'state': state}:
        raise energy.EnergyConflict('El día o la propuesta cambió. Revisa de nuevo antes de confirmar.')


def upload_envelope(file):
    raw = file.stream.read(MAX_BYTES + 1)
    name = PurePosixPath((file.filename or '').replace('\\', '/')).name
    if not raw or len(raw) > MAX_BYTES or not name.lower().endswith('.json') or len(name) > 255:
        raise ValueError('Selecciona un JSON de hasta 256 KiB. Para otros tamaños usa la importación existente.')
    return {'raw': base64.b64encode(raw).decode(), 'name': name}


def unpack(envelope):
    try:
        if not isinstance(envelope, dict) or not all(isinstance(envelope.get(k), str) for k in ('raw', 'name')):
            raise ValueError()
        if set(envelope) != {'raw', 'name'} or len(envelope['raw']) > (MAX_BYTES * 4 // 3 + 4):
            raise ValueError()
        raw = base64.b64decode(envelope['raw'], validate=True)
        if not raw or len(raw) > MAX_BYTES or not envelope['name'].lower().endswith('.json') or len(envelope['name']) > 255:
            raise ValueError()
        document = json.loads(raw.decode('utf-8-sig'))
    except (ValueError, UnicodeError, TypeError, binascii.Error, KeyError) as exc:
        raise ValueError('El archivo no contiene un JSON UTF-8 válido o excede el límite.') from exc
    return raw, document


def import_preview(envelope, user_id):
    _, document = unpack(envelope)
    if not isinstance(document, dict):
        raise ValueError('Selecciona un documento estándar de energía diaria.')
    executor = StandardImportExecutor()
    plan = executor.plan_documents([document], user_id=user_id, target_type='daily_energy')
    if any(op['operation'] in ('invalid', 'conflict') for op in plan['operations']):
        raise ValueError('El JSON no cumple el contrato de energía o no pertenece a esta cuenta. Revisa fecha, unidades, tipos y propietario con la importación estándar.')
    if document.get('evidence') is not None:
        raise ValueError('Este archivo contiene un historial completo. Usa el restore oficial para revisar identidades, revisiones y retiradas; esta guía importa una observación.')
    target = parsed_date(document['data']['date'])
    source = document['data'].get('source', document['source_type']).strip()
    if not source:
        raise ValueError('La fuente está vacía. Corrige el original antes de revisar.')
    registry = db.session.scalar(db.select(EnergyDay).where(EnergyDay.user_id==user_id, EnergyDay.date==target))
    source_row = db.session.scalar(db.select(DailyEnergy).where(DailyEnergy.user_id==user_id, DailyEnergy.date==target, DailyEnergy.source==source))
    if (registry and registry.deleted_at is not None) or (source_row and source_row.deleted_at is not None):
        raise ValueError('El día o la fuente está retirado. Esta importación no restaura eliminaciones explícitas.')
    if not any(document['data'].get(key) is not None for _, key in list(energy.FIELDS.items())[:5]):
        raise ValueError('No hay métricas conocidas. No se registrará un día vacío ni se convertirán ausencias en cero.')
    canonical = energy.view(user_id, target)
    same_source = source_row
    fields = []
    for field, label, unit in FIELDS:
        incoming = energy.decoded(field, document['data'].get(energy.FIELDS[field]))
        old = getattr(canonical, field) if canonical else None
        source_old = getattr(same_source, field) if same_source else None
        if incoming is None:
            operation = 'Conservar · sin dato nuevo'
        elif source_old is not None and source_old != incoming:
            operation = 'Conservar propuesta contradictoria · no sobrescribir'
        elif old is not None and old != incoming:
            operation = 'Añadir evidencia discrepante · revisión pendiente'
        elif canonical and field in canonical.conflicts:
            operation = 'Conservar evidencia · el campo sigue pendiente'
        elif incoming == source_old:
            operation = 'Sin cambio de valor'
        else:
            operation = 'Añadir dato conocido'
        fields.append({'key': field, 'label': label, 'unit': unit, 'current': old, 'source_current': source_old,
                       'conflicts': canonical.conflicts.get(field, []) if canonical else [],
                       'incoming': incoming, 'operation': operation})
    material = {'envelope': envelope}
    return {'document': document, 'plan': plan, 'executor': executor, 'target': target,
            'source': source, 'fields': fields,
            'partial': document['data'].get('total_expenditure_kcal') is None,
            'replay': all(op['operation'] == 'skip' for op in plan['operations']),
            'material': material, 'state': plan['energy_state']}


def review_preview(user_id, target, operations=None):
    canonical = energy.view(user_id, target)
    if canonical is None:
        raise LookupError('Día no disponible.')
    operations = {} if operations is None else operations
    if (not isinstance(operations, dict) or set(operations) - set(energy.FIELDS)
            or any(not isinstance(v, dict) or not isinstance(v.get('choice', 'keep'), str)
                   or not isinstance(v.get('value', ''), str) or len(v.get('value', '')) > 2000 for v in operations.values())):
        raise ValueError('Campo no admitido.')
    fields, values, clear, normalized = [], {}, [], {}
    for field, label, unit in FIELDS:
        choice = operations.get(field, {}).get('choice', 'keep')
        incoming = operations.get(field, {}).get('value', '')
        options = [(str(i), row.source, getattr(row, field)) for i, row in enumerate(canonical.evidence)
                   if row.deleted_at is None and getattr(row, field) is not None]
        if choice == 'keep':
            result = getattr(canonical, field)
            description = 'Conservar estado actual'
        elif choice == 'clear':
            result = None; clear.append(field); description = 'Vaciar explícitamente · no significa cero'
        elif choice == 'manual':
            if incoming == '' and field != 'notes':
                raise GuidedInputError(field, 'Ingresa un valor conocido o elige conservar/vaciar.')
            try:
                result = energy.decoded(field, incoming)
            except energy.EnergyConflict as exc:
                raise GuidedInputError(field, 'Revisa el tipo, la unidad y el rango. Usa punto decimal; pasos requiere un entero.') from exc
            values[field] = result; description = 'Confirmar valor manual'
        elif choice.startswith('source:'):
            selected = next((item for item in options if item[0] == choice[7:]), None)
            if selected is None:
                raise GuidedInputError(field, 'La fuente elegida no está disponible para este campo.')
            result = selected[2]; values[field] = result; description = 'Confirmar fuente: '+selected[1]
        else:
            raise GuidedInputError(field, 'Elige una operación disponible para este campo.')
        normalized[field] = {'choice': choice, 'value': str(incoming) if choice == 'manual' else ''}
        fields.append({'key': field, 'label': label, 'unit': unit, 'current': getattr(canonical, field),
                       'result': result, 'operation': description, 'options': options,
                       'conflicts': canonical.conflicts.get(field, []), **normalized[field]})
    return {'canonical': canonical, 'target': target, 'fields': fields, 'values': values, 'clear': clear,
            'material': normalized, 'state': energy.state_fingerprint(user_id, [target]), 'revision': canonical.revision}
