"""Bounded source-quality interpretation; never parses or changes amounts."""
import re
import unicodedata

from app.services.nutrition_math import NUTRIENTS


def folded(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value.casefold())
                   if not unicodedata.combining(c)).replace('_', ' ')


SIGNAL = re.compile(r'\b(?:estimad\w*|estimaci\w*|estimat\w*|estimo|aproximad\w*|aproximacion\w*|'
    r'approximate\w*|approximation\w*|proxy|proxies|sustitut\w*|substitut\w*|'
    r'provisional\w*|inciert\w*|incertidumbre|uncertain\w*)\b')
NEGATION = re.compile(r'\b(?:no|sin|not|without|neither)\s+(?:\w+\s+){0,3}$')
UNRELATED = re.compile(r'\b(?:fecha|date|precio|price|marca|brand|caducidad|expiration|lote|batch|packaging)\b')
TEXT_FIELDS = ('method', 'limitations', 'notes', 'uncertainty')
VERIFIED = {'verified', 'label verified', 'verified label', 'measured', 'laboratory measured'}


def explicit_quality(metadata):
    quality = metadata.get('quality')
    if not isinstance(quality, str):return None
    quality = folded(quality).strip()
    if quality in {'estimated', 'estimado', 'estimada'}:return 'estimated'
    if quality in VERIFIED:return 'verified'
    return None  # Unverified/file-declared is not proof against limitations.


def clauses(metadata):
    for field in TEXT_FIELDS:
        values = metadata.get(field, '')
        if not isinstance(values, list):values = [values]
        for value in values:
            if isinstance(value, str):
                yield from re.split(r'[.;!\n]|\b(?:pero|but|however)\b', folded(value))


def uncertain(text):
    return any(not NEGATION.search(text[max(0, match.start()-60):match.start()])
               for match in SIGNAL.finditer(text))


def nutrient_targets(text, keys):
    targets = set()
    for key in keys:
        aliases = {folded(key), folded(NUTRIENTS[key][0])}
        if key == 'fiber':aliases.update({'fibre', 'fibra'})
        if key == 'fat':aliases.add('grasa')
        if any(re.search(r'(?<!\w)'+re.escape(alias)+r'(?!\w)', text) for alias in aliases):
            targets.add(key)
    return targets


def classification(provenance, vector):
    """Explicit per-nutrient quality wins, then scoped limits, then food quality.

    Only source provenance fields participate. Names, amounts and unrelated
    metadata cannot confer nutritional quality. Explicit verification is kept
    as a source assertion, never promoted from a label-like method name.
    """
    provenance = provenance if isinstance(provenance, dict) else {}
    explicit = explicit_quality(provenance)
    baseline = explicit or 'file_declared_unverified'
    scoped = {}
    for text in clauses(provenance):
        if not uncertain(text):continue
        targets = nutrient_targets(text, vector)
        if targets:
            scoped.update({key: 'estimated' for key in targets})
        elif not explicit and not UNRELATED.search(text):baseline = 'estimated'
    qualities = {key: scoped.get(key, baseline) for key in vector}
    for key, value in vector.items():
        # External aliases stay here in source detection, outside the schema.
        metadata = {}
        for field in ('nutrients', 'nutrient_provenance', 'per_nutrient'):
            mapping = provenance.get(field)
            if isinstance(mapping, dict) and isinstance(mapping.get(key), dict):metadata.update(mapping[key])
        if isinstance(value,dict) and isinstance(value.get('provenance'), dict):metadata.update(value['provenance'])
        direct = explicit_quality(metadata)
        if direct:qualities[key] = direct
        elif any(uncertain(text) for text in clauses(metadata)):qualities[key] = 'estimated'
    estimated = sum(value == 'estimated' for value in qualities.values())
    quality = ('mixed' if estimated and estimated < len(qualities) else 'estimated' if estimated
               else 'verified' if qualities and all(q == 'verified' for q in qualities.values())
               else 'file_declared_unverified')
    return quality, qualities
