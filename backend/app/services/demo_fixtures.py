"""Versioned, entirely synthetic DEMO inputs; no database or filesystem writes."""
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

DEMO_EMAIL = "demo@healthtracker.test"
DEMO_NAME = "Health Tracker Demo"
DEMO_SOURCE = "demo_history_v1"
DEMO_NOTE = "DEMO_HISTORY_V1: datos sintéticos de demostración; no son mediciones."
DEMO_PLAN_NAME = "DEMO · Full Body A/B/C"


def identity(key):
    return str(uuid5(NAMESPACE_URL, "health-tracker/demo-history/v1/" + key))


DEMO_PUBLIC_ID = identity("account")


def variation(day, key, size):
    return uuid5(NAMESPACE_URL, f"demo-history-v1/{day.isoformat()}/{key}").int % size


# Exact existing USDA identities; fallback values are synthetic approximations
# per 100 g. Never add micronutrients absent from a valid catalog vector.
# catalog ID, name, protein, total carbohydrate, fat, fiber
FOODS = {
    "oats": ("169705", "Avena seca", 13, 68, 7, 10),
    "milk": ("171267", "Leche 2%", 3.3, 4.8, 2, 0),
    "banana": ("173944", "Plátano", 1.1, 23, .3, 2.6),
    "egg": ("173424", "Huevo cocido", 13, 1.1, 10.6, 0),
    "chicken": ("171477", "Pechuga de pollo asada", 31, 0, 3.6, 0),
    "rice": ("168878", "Arroz blanco cocido", 2.7, 28, .3, .4),
    "broccoli": ("169967", "Brócoli cocido", 2.4, 7.2, .4, 3.3),
    "oil": ("171413", "Aceite de oliva", 0, 0, 100, 0),
    "beans": ("173735", "Frijol negro cocido", 8.9, 23.7, .5, 8.7),
    "tortilla": ("175036", "Tortilla de maíz", 5.7, 44.6, 2.9, 6.3),
    "avocado": ("171705", "Aguacate", 2, 8.5, 14.7, 6.7),
    "fish": ("175177", "Tilapia cocida", 26, 0, 2.7, 0),
    "yogurt": ("170894", "Yogur griego natural", 10, 4, .4, 0),
    "apple": ("171688", "Manzana con piel", .3, 13.8, .2, 2.4),
    "beef": ("171794", "Res molida cocida 90/10", 28, 0, 12, 0),
    "pasta": ("168928", "Pasta cocida", 5.8, 30.9, .9, 1.8),
}

MENUS = (
    (("breakfast", "Avena, leche, plátano y huevo", (("oats", 55), ("milk", 250), ("banana", 100), ("egg", 100))),
     ("lunch", "Pollo, arroz y brócoli", (("chicken", 150), ("rice", 330), ("broccoli", 100), ("oil", 16))),
     ("dinner", "Pescado con frijoles y tortillas", (("fish", 120), ("beans", 80), ("tortilla", 90), ("avocado", 50), ("oil", 12))),
     ("snack", "Yogur con manzana", (("yogurt", 150), ("apple", 150)))),
    (("breakfast", "Huevos, tortillas y frijoles", (("egg", 120), ("tortilla", 80), ("beans", 50), ("oil", 6))),
     ("lunch", "Res con pasta y brócoli", (("beef", 150), ("pasta", 260), ("broccoli", 100), ("oil", 12))),
     ("dinner", "Pollo con arroz y aguacate", (("chicken", 130), ("rice", 240), ("avocado", 60), ("broccoli", 70), ("oil", 8))),
     ("snack", "Yogur, avena y plátano", (("yogurt", 180), ("oats", 25), ("banana", 120)))),
    (("breakfast", "Yogur con avena y manzana", (("yogurt", 250), ("oats", 55), ("apple", 150))),
     ("lunch", "Pescado, arroz y verduras", (("fish", 180), ("rice", 280), ("broccoli", 100), ("oil", 22))),
     ("dinner", "Tacos de res y frijoles", (("beef", 130), ("beans", 60), ("tortilla", 100), ("avocado", 50), ("oil", 8))),
     ("snack", "Leche con plátano", (("milk", 250), ("banana", 150)))),
)

# Names shipped in the real Gym presets; official resolution reuses identities,
# aliases and available exact external catalog references.
MOVEMENTS = (("Prensa", 100, 5), ("Press banca", 40, 2.5), ("Remo", 40, 2.5),
             ("Curl femoral", 30, 2.5), ("Press militar", 25, 2.5),
             ("Jalón al pecho", 40, 2.5), ("Sentadilla", 50, 2.5), ("Peso muerto rumano", 50, 2.5))
DAY_MOVEMENTS = ((0, 1, 2, 3, 4, 5), (6, 1, 5, 7, 3, 2), (0, 4, 2, 7, 1, 5))
EXTERNAL_MOVEMENTS = ("Leg_Press", "Machine_Bench_Press", "Bent_Over_Barbell_Row",
                      "Seated_Leg_Curl", "Barbell_Shoulder_Press", "Wide-Grip_Lat_Pulldown",
                      "Barbell_Full_Squat", "Romanian_Deadlift")


def performance(day, anchor, movement, number):
    _, base, step = MOVEMENTS[movement]
    week = max(0, (day - anchor).days // 7)
    progress = week - week // 5  # Occasional maintenance week.
    cycle = 3 + movement % 2
    weight = Decimal(str(base)) + Decimal(str(step)) * (progress // cycle)
    lower = variation(day, f"performance/{movement}", 11) == 0
    reps = max(6, 11 - number + progress % cycle - int(lower) * 2)
    rir = 1 + variation(day, f"rir/{movement}/{number}", 3)
    return {"load": str(weight), "unit": "kg", "reps": reps, "rir": str(rir), "rpe": str(10 - rir)}
