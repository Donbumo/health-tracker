"""Synthetic analogue of a short imported day, never a copy of personal data."""
import tempfile
import json
from collections import Counter
from pathlib import Path

from qa_app import build_app
from app.extensions import db
from app.models import User
from app.services.exercise_identity import get_or_create_exercise, add_exercise_alias
from app.services.gym_programs import catalog, confirm_program, preview_token, resolve_draft
from app.services.gym_media import media_catalog, media_projection
from app.services.importers.routine_draft import DeterministicParser

storage = tempfile.mkdtemp(prefix='gym-media-qa-')
app = build_app(storage)
with app.app_context():
    user = db.session.execute(db.select(User).where(User.username == 'gym-qa')).scalar_one()
    bench, _ = get_or_create_exercise(user.id, 'QA empuje personalizado')
    add_exercise_alias(user.id, bench.id, 'Press banca')
    add_exercise_alias(user.id, bench.id, 'QA banco alternativo')
    source = 'Dia,Ejercicio,Series,Reps\nD1,QA banco alternativo,2,8\nD1,Sentadilla,2,8\nD1,Remo con barra supino,2,8\nD1,prensa,2,8\nD1,QA movimiento desconocido,2,8\nD2,prensa,2,8'
    draft = DeterministicParser().parse(source.encode(), 'synthetic.csv', 'QA · Identidades y medios')
    for day in draft.days:
        for exercise in day['exercises']:
            exercise['create_new'] = True
    resolve_draft(draft, user.id)
    confirm_program(draft, user.id, preview_token(draft, user.id))
    db.session.commit()
    identities = catalog(user.id)
    binding = media_projection(identities, media_catalog())
    print(json.dumps({'synthetic_catalog_total': len(identities), 'coverage': dict(Counter(binding({'exercise_id': item.public_id})['status'] for item in identities)), 'unresolved_imports': len(draft.unresolved)}), flush=True)
print('Synthetic QA on http://127.0.0.1:8012', flush=True)
app.run(host='127.0.0.1', port=8012, use_reloader=False)
