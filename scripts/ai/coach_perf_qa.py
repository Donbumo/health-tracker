"""Bounded Coach benchmark on the dedicated disposable Gym QA MariaDB only."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
from time import perf_counter
from uuid import uuid4

from sqlalchemy import event

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts" / "gym"))

from strength_qa_app import build_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import User  # noqa: E402
from app.services.coach import CoachBriefService  # noqa: E402
from tests.gym_strength_fixtures import strength_fixture  # noqa: E402


def run():
    with tempfile.TemporaryDirectory(prefix="ht-strength-qa-coach-perf-") as storage:
        app = build_app(storage)
        results = []
        with app.app_context():
            assert db.engine.url.host == "127.0.0.1"
            assert db.engine.url.port == 33381
            assert db.engine.url.database == "gym_progression_qa"
            for exercises, sessions in ((5, 4), (40, 4), (40, 200)):
                account = User(username="qa-coach-perf-" + uuid4().hex, role="user", timezone="UTC")
                account.set_password("fictional-password")
                db.session.add(account)
                db.session.commit()
                owner = account.id
                try:
                    strength_fixture(owner, count=sessions, exercise_count=exercises)
                    db.session.remove()
                    account = db.session.get(User, owner)
                    queries = []

                    def count(*_args):
                        queries.append(1)

                    event.listen(db.engine, "before_cursor_execute", count)
                    started = perf_counter()
                    try:
                        briefs = CoachBriefService().build(account)
                    finally:
                        event.remove(db.engine, "before_cursor_execute", count)
                    elapsed = round((perf_counter() - started) * 1000, 1)
                    results.append({"exercises": exercises, "sessions": sessions,
                                    "daily_signals": len(briefs["today"]["top_priorities"]),
                                    "weekly_signals": len(briefs["week"]["top_priorities"]),
                                    "queries": len(queries), "duration_ms": elapsed})
                finally:
                    db.session.execute(db.delete(User).where(User.id == owner))
                    db.session.commit()
        return results


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
