"""One canonical day, retained source identities, conservative confirmed writes.

DailyEnergy is evidence, not an additional daily expenditure. No source totals
are added together. Disagreement is unknown until an explicit reviewed edit.
The user row is the transaction mutex (including the first write of a day).
Callers own commit/rollback; this service never commits a partial batch.
"""
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from types import SimpleNamespace
import uuid

from app.extensions import db
from app.models import DailyEnergy, EnergyDay, EnergyEvidenceEvent, User, UploadedFile

FIELDS = {
    "total_calories": "total_expenditure_kcal",
    "active_calories": "active_expenditure_kcal",
    "resting_calories": "resting_expenditure_kcal",
    "steps": "steps",
    "distance_meters": "distance_meters",
    "notes": "notes",
}


class EnergyConflict(ValueError):
    pass


def encoded(value):
    return str(value) if isinstance(value, Decimal) else value


def decoded(field, value):
    if value is None:
        return value
    if field == "notes":
        if not isinstance(value, str) or len(value) > 2000:
            raise EnergyConflict("Notas inválidas.")
        return value
    try:
        number = Decimal(str(value))
        maximum = 10_000_000 if field == 'steps' else 100_000_000 if field == 'distance_meters' else 100_000
        if not number.is_finite() or not 0 <= number <= maximum or (field == 'steps' and number != number.to_integral_value()):
            raise ValueError()
        return int(number) if field == 'steps' else number.quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError, TypeError) as error:
        raise EnergyConflict("Métrica de energía inválida.") from error


def lock_owner(user_id):
    # A locking read is current under both RC and RR; do not reuse a stale
    # identity-map value read during preview. All producers acquire this first.
    owner = db.session.execute(db.select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    if owner is None:
        raise EnergyConflict("La cuenta no existe.")


def registered_day(user_id, target, *, create=False):
    row = db.session.execute(db.select(EnergyDay).where(EnergyDay.user_id == user_id, EnergyDay.date == target).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    if row is None and create:
        row = EnergyDay(user_id=user_id, date=target, revision=1)
        db.session.add(row)
        db.session.flush()
    return row


def snapshot(record):
    return {"public_id": record.public_id, "date": record.date.isoformat(), "source": record.source,
            "revision": record.revision, "client_event_id": record.client_event_id,
            "values": {field: encoded(getattr(record, field)) for field in FIELDS},
            "raw_payload": record.raw_payload_json,
            "deleted": record.deleted_at is not None}


def append_event(record, kind, *, incoming=None, conflicts=None, source_file_id=None, before=None):
    payload = {"record": snapshot(record), "incoming": incoming, "conflicts": conflicts or {}}
    if before is not None:
        payload["before"] = before
    identity = [record.public_id, kind, incoming, source_file_id] if incoming is not None and kind in {'import','conflict'} else [record.public_id, kind, payload, source_file_id]
    key = hashlib.sha256(json.dumps(identity, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()
    event = db.session.execute(db.select(EnergyEvidenceEvent).where(EnergyEvidenceEvent.user_id == record.user_id, EnergyEvidenceEvent.event_key == key).with_for_update()).scalar_one_or_none()
    if event is None:
        file = db.session.scalar(db.select(UploadedFile).where(UploadedFile.id == source_file_id, UploadedFile.user_id == record.user_id)) if source_file_id is not None else None
        event = EnergyEvidenceEvent(user_id=record.user_id, date=record.date, evidence_public_id=record.public_id,
                                    event_key=key, kind=kind, source_file_id=source_file_id, source_file_sha256=file.sha256 if file is not None else None, payload_json=payload)
        db.session.add(event)
        db.session.flush()
        event._energy_new = True
    else:
        event._energy_new = False
    return event


def changed_source(record, kind, *, before=None):
    """Shared hook for explicit mobile mutations; identities remain untouched."""
    day = registered_day(record.user_id, record.date, create=True)
    day.revision += 1
    day.resolutions_json = {**(day.resolutions_json or {}), '_updated_at':datetime.now(timezone.utc).isoformat()}
    day.deleted_at = None
    return append_event(record, kind, before=before, source_file_id=record.source_file_id)


def step_event(user_id, client_event_id):
    key = hashlib.sha256(('steps-client-event:' + client_event_id).encode()).hexdigest()
    return db.session.scalar(db.select(EnergyEvidenceEvent).where(EnergyEvidenceEvent.user_id == user_id, EnergyEvidenceEvent.event_key == key).with_for_update())


def remember_step_event(record, client_event_id, incoming):
    """Retain additional create-event aliases without replacing legacy IDs."""
    if client_event_id is None or step_event(record.user_id, client_event_id) is not None:
        return
    key = hashlib.sha256(('steps-client-event:' + client_event_id).encode()).hexdigest()
    db.session.add(EnergyEvidenceEvent(user_id=record.user_id, date=record.date,
        evidence_public_id=record.public_id, event_key=key, kind='create_steps',
        payload_json={'incoming': incoming, 'record': snapshot(record)}))
    db.session.flush()


def upsert_document(document, user_id, *, source_file=None, public_id=None, client_event_id=None):
    from app.services.validation import validate_json_document
    validate_json_document(document, 'daily_energy')
    if document.get('evidence') is not None:
        return restore_evidence(document, user_id)
    return _upsert_document(document, user_id, source_file=source_file, public_id=public_id, client_event_id=client_event_id)


def _upsert_document(document, user_id, *, source_file=None, public_id=None, client_event_id=None):
    if document.get("user_id") != user_id:
        raise EnergyConflict("El documento no pertenece a esta cuenta.")
    data = document["data"]
    target = date.fromisoformat(data["date"])
    source = data.get("source", document["source_type"]).strip()
    if not source or len(source) > 32:
        raise EnergyConflict("La fuente de energía no es válida.")
    if source_file is not None and source_file.user_id != user_id:
        raise EnergyConflict("El archivo no pertenece a esta cuenta.")
    lock_owner(user_id)
    day = registered_day(user_id, target, create=True)
    if day.deleted_at is not None:
        raise EnergyConflict("El día fue eliminado. Un import no lo restaura automáticamente.")
    record = db.session.execute(db.select(DailyEnergy).where(DailyEnergy.user_id == user_id, DailyEnergy.date == target, DailyEnergy.source == source).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    created = record is None
    if created:
        record = DailyEnergy(user_id=user_id, date=target, source=source, public_id=public_id or str(uuid.uuid4()),
                             revision=1, client_event_id=client_event_id)
        db.session.add(record)
        db.session.flush()
    before = snapshot(record)
    changed = created
    conflicts = {}
    if record.deleted_at is not None:
        raise EnergyConflict("El registro fue eliminado explícitamente. Revisa el día antes de restaurarlo.")
    for field, key in FIELDS.items():
        value = data.get(key)
        if value is None:  # absent/null never clears; zero remains a value
            continue
        incoming = decoded(field, value)
        current = getattr(record, field)
        if current is None:
            setattr(record, field, incoming)
            changed = True
        elif current != incoming:
            conflicts[field] = encoded(incoming)
    if changed:
        if not created:
            record.revision += 1
        record.raw_payload_json = document
        if record.source_file_id is None and source_file is not None:
            # Keep the legacy single-record pointer; batch file references live
            # in the event bridge (one file may contain many dates).
            used = db.session.scalar(db.select(DailyEnergy.id).where(DailyEnergy.source_file_id == source_file.id).with_for_update())
            if used is None:
                record.source_file_id = source_file.id
            record.source_file_sha256 = source_file.sha256
        record.updated_at = datetime.now(timezone.utc)
    # Every file's origin survives, including renamed/value-identical imports.
    db.session.flush()
    event = append_event(record, "conflict" if conflicts else "import", incoming=document, conflicts=conflicts,
                         source_file_id=source_file.id if source_file is not None else None, before=before if changed else None)
    state = dict(day.resolutions_json or {})
    # Logical disagreement is independent of file bytes/filename. Preserve each
    # file event without reopening a decision for the same source values.
    pending_key = hashlib.sha256(json.dumps([target.isoformat(), source, conflicts], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    new_conflict = bool(conflicts) and pending_key not in {item['key'] for item in state.get('_pending', [])}
    if new_conflict:
        state['_pending'] = [*state.get('_pending', []), {'key': pending_key, 'source': record.source, 'conflicts': conflicts}]
        day.resolutions_json = state
    if changed or new_conflict:
        day.revision += 1
        day.resolutions_json = {**(day.resolutions_json or {}), '_updated_at':datetime.now(timezone.utc).isoformat()}
    record._energy_replay = not changed and not new_conflict
    record._energy_conflicts = conflicts
    db.session.flush()
    return record


def project(rows, day=None, events=()):
    """Pure read model, also usable for legacy fixtures without a registry row."""
    active = [row for row in rows if row.deleted_at is None]
    if not active or (day is not None and day.deleted_at is not None):
        return None
    anchor = min(active, key=lambda row: row.id)
    resolutions = (day.resolutions_json or {}) if day is not None else {}
    if day is not None:
        events = [SimpleNamespace(event_key=item['key'], kind='conflict', source=item['source'], payload_json={'conflicts': item['conflicts']}) for item in resolutions.get('_pending', [])]
    values, conflicts, chosen = {}, {}, {}
    for field in FIELDS:
        resolution = resolutions.get(field)
        candidates = []
        if resolution:
            candidates.append((decoded(field, resolution["value"]), None))
        for row in active:
            value = getattr(row, field)
            if value is None:
                continue
            if resolution and row.source in resolution.get('source_values', {}) and value == decoded(field, resolution['source_values'][row.source]):
                continue
            candidates.append((value, row))
        active_sources = {row.source for row in active}
        for event in events:
            if event.kind != "conflict" or event.source not in active_sources:
                continue
            if resolution and event.event_key in resolution.get("reviewed_keys", []):
                continue
            raw = event.payload_json.get("conflicts", {}).get(field)
            if raw is not None:
                candidates.append((decoded(field, raw), None))
        distinct = {value for value, _ in candidates}
        if len(distinct) > 1:
            values[field] = None
            conflicts[field] = sorted((encoded(value) for value in distinct), key=str)
        else:
            values[field] = candidates[0][0] if candidates else None
            chosen[field] = next((row for value, row in candidates if row is not None), None)
    step_source = chosen.get("steps")
    def aware(value):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    reviewed_at = datetime.fromisoformat(resolutions['_updated_at']) if resolutions.get('_updated_at') else None
    return SimpleNamespace(**values, id=anchor.id, user_id=anchor.user_id, date=anchor.date,
        revision=day.revision if day is not None else max(row.revision for row in active),
        source=anchor.source if len(active) == 1 else "reconciled", source_file=anchor.source_file,
        source_file_id=anchor.source_file_id, public_id=step_source.public_id if step_source else None,
        created_at=min(aware(row.created_at) for row in active), updated_at=max([aware(row.updated_at) for row in active] + ([aware(reviewed_at)] if reviewed_at is not None else [])),
        conflicts=conflicts, field_sources=chosen, evidence=active, registry=day)


def views(user_id, *, start=None, end=None, lock=False):
    query = db.select(DailyEnergy, EnergyDay).outerjoin(EnergyDay, db.and_(EnergyDay.user_id == DailyEnergy.user_id, EnergyDay.date == DailyEnergy.date)).where(DailyEnergy.user_id == user_id)
    if start is not None:
        query = query.where(DailyEnergy.date >= start)
    if end is not None:
        query = query.where(DailyEnergy.date <= end)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    days, groups = {}, defaultdict(list)
    for row, day in db.session.execute(query):
        groups[row.date].append(row)
        days[row.date] = day
    return [view for target, rows in sorted(groups.items(), reverse=True) if (view := project(rows, days.get(target))) is not None]


def view(user_id, target, *, lock=False):
    return next(iter(views(user_id, start=target, end=target, lock=lock)), None)


def state_fingerprint(user_id, targets, *, lock=False):
    """Bind confirmed previews to the entire day, including other sources."""
    output = {}
    for target in sorted(set(targets)):
        rows_query = db.select(DailyEnergy).where(DailyEnergy.user_id == user_id, DailyEnergy.date == target).order_by(DailyEnergy.id)
        day_query = db.select(EnergyDay).where(EnergyDay.user_id == user_id, EnergyDay.date == target)
        if lock:
            rows_query = rows_query.with_for_update().execution_options(populate_existing=True)
            day_query = day_query.with_for_update().execution_options(populate_existing=True)
        rows = db.session.scalars(rows_query).all()
        day = db.session.scalar(day_query)
        payload = [snapshot(row) for row in rows], [day.revision, day.resolutions_json, bool(day.deleted_at)] if day else None
        output[target.isoformat()] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return output


def edit_day(user_id, target, base_revision, values, *, new_date=None, clear=()):
    lock_owner(user_id)
    day = registered_day(user_id, target, create=True)
    current = view(user_id, target, lock=True)
    if current is None or day.revision != base_revision:
        raise EnergyConflict("El día cambió. Recarga y revisa la nueva revisión.")
    new_date = new_date or target
    if new_date != target:
        if registered_day(user_id, new_date) is not None or view(user_id, new_date) is not None:
            raise EnergyConflict("Ya existe un registro en la fecha destino; no se fusionó ni reemplazó.")
    rows = list(current.evidence)
    resolutions = dict(day.resolutions_json or {})
    for field in FIELDS:
        if field not in values and field not in clear:
            continue
        value = None if field in clear else decoded(field, values[field])
        # A preloaded unchanged field is not a fresh resolution of a conflict.
        if value == getattr(current, field) and field not in clear:
            continue
        resolutions[field] = {"value": encoded(value), "reviewed_keys": [item['key'] for item in resolutions.get('_pending', [])],
                              "source_values": {row.source: encoded(getattr(row, field)) for row in rows}}
    if resolutions == (day.resolutions_json or {}) and new_date == target:
        return current
    resolutions['_updated_at'] = datetime.now(timezone.utc).isoformat()
    day.resolutions_json = resolutions
    day.revision += 1
    for record in rows:
        before = snapshot(record)
        if new_date != target:
            record.date = new_date
            record.revision += 1
        append_event(record, "edit_day", incoming={"resolutions": resolutions, "date": new_date.isoformat()}, before=before)
    # Keep the old date's registry as a tombstone; move resolves atomically.
    if new_date != target:
        day.deleted_at = datetime.now(timezone.utc)
        destination = registered_day(user_id, new_date, create=True)
        destination.resolutions_json = resolutions
        destination.revision = day.revision
    db.session.flush()
    return view(user_id, new_date)


def delete_day(user_id, target, base_revision):
    lock_owner(user_id)
    day = registered_day(user_id, target, create=True)
    current = view(user_id, target, lock=True)
    if current is None or day.revision != base_revision:
        raise EnergyConflict("El día cambió. Recarga antes de eliminar.")
    now = datetime.now(timezone.utc)
    for record in current.evidence:
        before = snapshot(record)
        record.deleted_at = now
        record.revision += 1
        append_event(record, "delete_day", before=before, incoming={'review':day.resolutions_json or {}, 'day_revision':day.revision})
    day.deleted_at = now
    day.revision += 1
    db.session.flush()


def delete_evidence(user_id, target, public_id, base_revision):
    lock_owner(user_id)
    day = registered_day(user_id, target, create=True)
    current = view(user_id, target, lock=True)
    if current is None or day.revision != base_revision:
        raise EnergyConflict("El día cambió. Recarga antes de eliminar la fuente.")
    record = next((row for row in current.evidence if row.public_id == public_id), None)
    if record is None:
        raise EnergyConflict("La fuente no pertenece a este día.")
    before = snapshot(record)
    record.deleted_at = datetime.now(timezone.utc)
    record.revision += 1
    append_event(record, "delete_source", before=before)
    day.revision += 1
    if len(current.evidence) == 1:
        day.deleted_at = record.deleted_at
    db.session.flush()


def export_evidence(resource, user_id):
    """Private round-trip metadata, with hashes instead of storage paths/IDs."""
    if resource.user_id != user_id:
        raise EnergyConflict("El día no pertenece a esta cuenta.")
    sources = resource.evidence if hasattr(resource, 'evidence') else [resource]
    day = resource.registry if hasattr(resource, 'evidence') else db.session.scalar(db.select(EnergyDay).where(EnergyDay.user_id == user_id, EnergyDay.date == resource.date))
    output = []
    for row in sources:
        item = snapshot(row)
        item['source_file_sha256'] = row.source_file.sha256 if row.source_file is not None and row.source_file.user_id == user_id else row.source_file_sha256
        item['events'] = []
        events = db.session.scalars(db.select(EnergyEvidenceEvent).where(EnergyEvidenceEvent.user_id == user_id, EnergyEvidenceEvent.evidence_public_id == row.public_id).order_by(EnergyEvidenceEvent.id))
        for event in events:
            file = db.session.scalar(db.select(UploadedFile).where(UploadedFile.id == event.source_file_id, UploadedFile.user_id == user_id)) if event.source_file_id is not None else None
            item['events'].append({'key': event.event_key, 'kind': event.kind, 'payload': event.payload_json, 'source_file_sha256': file.sha256 if file is not None else event.source_file_sha256})
        output.append(item)
    state = dict(day.resolutions_json or {}) if day is not None else {}
    state.pop('_restored_review', None)
    return {'version': 1, 'sources': output, 'review': {'revision': day.revision if day is not None else 1, 'resolutions': state, 'deleted': bool(day and day.deleted_at is not None)}}


def restore_evidence(document, user_id):
    """Confirmed restore preserves source UUIDs on this owner; collisions remap.

    Restoring onto a different explicit review is blocked, never last-write-wins.
    Old source IDs remain in the immutable event payload; they confer no access.
    """
    from app.services.validation import validate_json_document
    validate_json_document(document, 'daily_energy')
    if document.get('user_id') != user_id:
        raise EnergyConflict("El documento no pertenece a esta cuenta.")
    bundle = document['evidence']
    target = date.fromisoformat(document['data']['date'])
    review = bundle['review']
    state = review['resolutions']
    if set(state) - set(FIELDS) - {'_pending', '_updated_at'}:
        raise EnergyConflict("La revisión contiene campos desconocidos.")
    seen = set()
    for source in bundle['sources']:
        if source['date'] != target.isoformat() or source['source'] in seen:
            raise EnergyConflict("La evidencia no corresponde a un único día/fuente.")
        seen.add(source['source'])
        if review['deleted'] and not source['deleted']:
            raise EnergyConflict("Un día eliminado no puede contener una fuente activa.")
        try:
            uuid.UUID(source['public_id'])
            if source.get('client_event_id') is not None:
                uuid.UUID(source['client_event_id'])
        except (ValueError, TypeError, AttributeError) as error:
            raise EnergyConflict("Identidad de evidencia inválida.") from error
        values = {FIELDS[field]: decoded(field, value) for field, value in source['values'].items() if value is not None}
        validate_json_document({'schema_version':'1.0','record_type':'daily_energy','user_id':user_id,'source_type':'uploaded','data':{'date':target.isoformat(),'source':source['source'], **{key: float(value) if isinstance(value, Decimal) else value for key,value in values.items()}}}, 'daily_energy')
    for field, resolution in state.items():
        if field == '_updated_at':
            try:
                datetime.fromisoformat(resolution)
            except (ValueError, TypeError) as error:
                raise EnergyConflict("Fecha de revisión inválida.") from error
            continue
        if field == '_pending':
            if not isinstance(resolution, list):
                raise EnergyConflict("Evidencias pendientes inválidas.")
            for pending in resolution:
                if not isinstance(pending, dict) or set(pending) != {'key','source','conflicts'} or not isinstance(pending['conflicts'], dict) or set(pending['conflicts']) - set(FIELDS) or not isinstance(pending['source'], str) or len(pending['source']) > 32 or not isinstance(pending['key'], str) or len(pending['key']) != 64:
                    raise EnergyConflict("Evidencias pendientes inválidas.")
                for name, value in pending['conflicts'].items():
                    decoded(name, value)
            continue
        if not isinstance(resolution, dict) or set(resolution) != {'value','reviewed_keys','source_values'}:
            raise EnergyConflict("Resolución inválida.")
        decoded(field, resolution['value'])
        if not isinstance(resolution['reviewed_keys'], list) or not isinstance(resolution['source_values'], dict):
            raise EnergyConflict("Resolución inválida.")
        if any(not isinstance(key, str) or len(key) != 64 for key in resolution['reviewed_keys']):
            raise EnergyConflict("Referencias de revisión inválidas.")
        for source, value in resolution['source_values'].items():
            if not isinstance(source, str) or not 1 <= len(source) <= 32:
                raise EnergyConflict("Fuente de revisión inválida.")
            decoded(field, value)
    lock_owner(user_id)
    existing = db.session.scalars(db.select(DailyEnergy).where(DailyEnergy.user_id == user_id, DailyEnergy.date == target).with_for_update()).all()
    day = registered_day(user_id, target, create=True)
    previous = dict(day.resolutions_json or {})
    # Any actual decision differing from this backup requires a new review.
    substantive = {key:value for key,value in previous.items() if key != '_restored_review'}
    if existing and substantive and substantive != state:
        raise EnergyConflict("El día ya tiene decisiones distintas. Revisa antes de restaurar.")
    if existing and bool(day.deleted_at) != review['deleted']:
        raise EnergyConflict("El estado de eliminación del día difiere del backup.")
    if existing and any(row.deleted_at is None for row in existing) and review['deleted']:
        raise EnergyConflict("Un restore no elimina un día activo existente.")
    results = []
    for source in bundle['sources']:
        owned = next((row for row in existing if row.source == source['source']), None)
        if owned is not None and bool(owned.deleted_at) != source['deleted']:
            raise EnergyConflict("El estado de eliminación de la fuente difiere del backup.")
        if owned is not None and snapshot(owned)['values'] != source['values']:
            # Numeric representation differences are harmless; value changes aren't.
            if any(decoded(field, source['values'].get(field)) != getattr(owned, field) for field in FIELDS):
                raise EnergyConflict("La fuente existente difiere del backup; no se reemplaza.")
        if owned is None:
            public_id = source['public_id']
            if db.session.scalar(db.select(DailyEnergy.id).where(DailyEnergy.public_id == public_id)) is not None:
                public_id = str(uuid.uuid4())
            event_id = source.get('client_event_id')
            if event_id is not None and db.session.scalar(db.select(DailyEnergy.id).where(DailyEnergy.user_id == user_id, DailyEnergy.client_event_id == event_id)) is not None:
                raise EnergyConflict("El evento móvil ya pertenece a otra fuente.")
            owned = DailyEnergy(user_id=user_id, date=target, source=source['source'], public_id=public_id,
                                revision=source['revision'], client_event_id=event_id,
                                raw_payload_json=source.get('raw_payload'),
                                deleted_at=datetime.now(timezone.utc) if source['deleted'] else None,
                                **{field: decoded(field, source['values'].get(field)) for field in FIELDS})
            sha = source.get('source_file_sha256')
            file = db.session.scalar(db.select(UploadedFile).where(UploadedFile.user_id == user_id, UploadedFile.sha256 == sha)) if sha else None
            used = db.session.scalar(db.select(DailyEnergy.id).where(DailyEnergy.source_file_id == file.id)) if file else None
            owned.source_file_id = file.id if file and used is None else None
            owned.source_file_sha256 = sha
            db.session.add(owned)
            db.session.flush()
        for event in source['events']:
            duplicate = db.session.scalar(db.select(EnergyEvidenceEvent).where(EnergyEvidenceEvent.user_id == user_id, EnergyEvidenceEvent.event_key == event['key']))
            if duplicate is not None:
                if duplicate.payload_json != event['payload']:
                    raise EnergyConflict("La evidencia del evento difiere del backup.")
                continue
            sha = event.get('source_file_sha256')
            file = db.session.scalar(db.select(UploadedFile).where(UploadedFile.user_id == user_id, UploadedFile.sha256 == sha)) if sha else None
            db.session.add(EnergyEvidenceEvent(user_id=user_id, date=target, evidence_public_id=owned.public_id,
                event_key=event['key'], kind=event['kind'], payload_json=event['payload'], source_file_id=file.id if file else None, source_file_sha256=sha))
        results.append(owned)
    day.resolutions_json = state
    day.revision = max(day.revision, review['revision'])
    if review['deleted']:
        day.deleted_at = datetime.now(timezone.utc)
    db.session.flush()
    result = results[0]
    result._energy_replay = bool(existing)
    return result
