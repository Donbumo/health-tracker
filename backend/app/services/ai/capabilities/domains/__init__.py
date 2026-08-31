from app.services.ai.capabilities.domains.activity import MANIFEST as ACTIVITY
from app.services.ai.capabilities.domains.body import MANIFEST as BODY
from app.services.ai.capabilities.domains.data import MANIFEST as DATA
from app.services.ai.capabilities.domains.energy import MANIFEST as ENERGY
from app.services.ai.capabilities.domains.goals import MANIFEST as GOALS
from app.services.ai.capabilities.domains.nutrition import MANIFEST as NUTRITION
from app.services.ai.capabilities.domains.summary import MANIFEST as SUMMARY
from app.services.ai.capabilities.domains.training import MANIFEST as TRAINING


MANIFESTS = (SUMMARY, ENERGY, NUTRITION, BODY, ACTIVITY, TRAINING, GOALS, DATA)


def load_manifests():
    return MANIFESTS


__all__ = ["MANIFESTS", "load_manifests"]
