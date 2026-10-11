"""Reproduce the reviewed 37-food comparison from bounded official archives.

Run with a Python environment containing openpyxl. No API keys; no health data.
Downloaded archives stay in the OS temp directory. Matching candidates are not
automatically declared equivalent. The reviewed IDs in selection.json are final.
"""
import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2] / "examples/qa/nutrition-intelligence"
SR_URL = "https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_sr_legacy_food_csv_2018-04.zip"
CIQUAL_URL = "https://entrepot.recherche.data.gouv.fr/api/access/datafile/666260"
USDA_NUTRIENTS = {1008: "energy", 1003: "protein", 1004: "fat", 1005: "carbohydrate_total",
    1079: "fiber", 2000: "sugar", 1093: "sodium", 1092: "potassium", 1087: "calcium",
    1089: "iron", 1090: "magnesium", 1091: "phosphorus", 1095: "zinc",
    1106: "vitamin_a_rae", 1105: "retinol", 1162: "vitamin_c", 1114: "vitamin_d",
    1109: "vitamin_e_alpha", 1185: "vitamin_k1", 1165: "thiamin", 1166: "riboflavin",
    1167: "niacin", 1175: "vitamin_b6", 1178: "vitamin_b12", 1190: "folate_dfe",
    1187: "folate_food", 1180: "choline"}
TARGETS = [
    ("Tortilla de maíz", "Tortillas, ready-to-bake or -fry, corn", "Tortilla"),
    ("Arroz blanco cocido", "Rice, white, long-grain, regular, enriched, cooked", "Riz blanc, cuit"),
    ("Frijol negro cocido", "Beans, black, mature seeds, cooked", "Haricot noir"),
    ("Frijol pinto cocido", "Beans, pinto, mature seeds, cooked", "Haricot rouge"),
    ("Pechuga pollo asada", "Chicken, broilers or fryers, breast, meat only, cooked, roasted", "Poulet, filet"),
    ("Huevo cocido", "Egg, whole, cooked, hard-boiled", "Oeuf de poule entier, cuit dur"),
    ("Aguacate crudo", "Avocados, raw, all commercial", "Avocat, pulpe, cru"),
    ("Jitomate crudo", "Tomatoes, red, ripe, raw, year round", "Tomate, pulpe et peau, crue"),
    ("Leche entera", "Milk, whole, 3.25% milkfat", "Lait entier, pasteuris"),
    ("Yogur natural entero", "Yogurt, plain, whole milk", "Yaourt au lait entier, nature"),
    ("Queso fresco", "Cheese, queso fresco", "Fromage frais"),
    ("Avena seca", "Oats", "Flocon d'avoine"),
    ("Plátano crudo", "Bananas, raw", "Banane, pulpe, crue"),
    ("Manzana con piel", "Apples, raw, with skin", "Pomme, pulpe et peau, crue"),
    ("Naranja cruda", "Oranges, raw, all commercial", "Orange, pulpe, crue"),
    ("Papaya cruda", "Papayas, raw", "Papaye, pulpe, crue"),
    ("Mango crudo", "Mangos, raw", "Mangue, pulpe, crue"),
    ("Piña cruda", "Pineapple, raw, all varieties", "Ananas, pulpe, cru"),
    ("Fresa cruda", "Strawberries, raw", "Fraise, crue"),
    ("Limón verde crudo", "Limes, raw", "Citron vert ou Lime"),
    ("Zanahoria cruda", "Carrots, raw", "Carotte, crue"),
    ("Brócoli cocido", "Broccoli, cooked, boiled, drained, without salt", "Brocoli, cuit"),
    ("Espinaca cruda", "Spinach, raw", "Epinard, cru"),
    ("Cebolla cruda", "Onions, raw", "Oignon, cru"),
    ("Calabacita cocida", "Squash, summer, zucchini, includes skin, cooked, boiled", "Courgette, pulpe et peau, cuite"),
    ("Pepino con piel", "Cucumber, with peel, raw", "Concombre, pulpe et peau, cru"),
    ("Papa cocida", "Potatoes, boiled, cooked without skin, flesh, without salt", "Pomme de terre, sans peau"),
    ("Elote cocido", "Corn, sweet, yellow, cooked, boiled, drained, without salt", "Maïs doux"),
    ("Res molida cocida 90/10", "Beef, ground, 90% lean meat / 10% fat, cooked", "Boeuf, steak hach"),
    ("Lenteja cocida", "Lentils, mature seeds, cooked, boiled, without salt", "Lentille, cuite"),
    ("Garbanzo cocido", "Chickpeas (garbanzo beans, bengal gram), mature seeds, cooked", "Pois chiche, cuit"),
    ("Cacahuate crudo", "Peanuts, all types, raw", "Cacahuète ou Arachide"),
    ("Semilla calabaza seca", "Seeds, pumpkin and squash seed kernels, dried", "Graine de courge"),
    ("Nopal cocido", "Nopales, cooked, without salt", "Nopal"),
    ("Chile jalapeño crudo", "Peppers, jalapeno, raw", "Piment"),
    ("Atún en agua escurrido", "Fish, tuna, light, canned in water, drained", "Thon au naturel"),
    ("Pan integral", "Bread, whole-wheat, commercially prepared", "Pain complet")]


def bounded_download(url, name, limit):
    path = Path(tempfile.gettempdir()) / name
    if not path.exists():
        with urllib.request.urlopen(url, timeout=60) as response:
            raw = response.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("Archive exceeds reviewed size")
        path.write_bytes(raw)
    if path.stat().st_size > limit:
        raise ValueError("Cached archive exceeds reviewed size")
    return path


def load():
    import openpyxl
    sr = bounded_download(SR_URL, "ht-nutrition-sr-legacy-2018.zip", 8_000_000)
    ciqual = bounded_download(CIQUAL_URL, "ht-ciqual-2025.xlsx", 2_000_000)
    archive = zipfile.ZipFile(sr)
    if sum(x.file_size for x in archive.infolist()) > 60_000_000:
        raise ValueError("Expanded SR archive exceeds reviewed budget")
    def rows(name):
        member = next(n for n in archive.namelist() if n.endswith("/" + name))
        return list(csv.DictReader(io.StringIO(archive.read(member).decode("utf-8-sig"))))
    foods = rows("food.csv")
    worksheet = openpyxl.load_workbook(ciqual, read_only=True, data_only=True).active
    cirows = list(worksheet.iter_rows(values_only=True))
    manifest = {"usda": {"url": SR_URL, "bytes": sr.stat().st_size,
        "sha256": hashlib.sha256(sr.read_bytes()).hexdigest(), "license": "CC0-1.0", "edition": "SR Legacy April 2018"},
        "ciqual": {"url": CIQUAL_URL, "bytes": ciqual.stat().st_size,
        "sha256": hashlib.sha256(ciqual.read_bytes()).hexdigest(), "license": "Licence Ouverte", "edition": "Ciqual 2025"}}
    return rows, foods, cirows, manifest


def candidates():
    rows, foods, cirows, manifest = load()
    output = []
    for name, en, fr in TARGETS:
        output.append({"target": name, "usda": [f for f in foods if en.casefold() in f["description"].casefold()],
            "ciqual": [{"id": r[6], "name": r[7]} for r in cirows[1:] if fr.casefold() in str(r[7]).casefold()]})
    (ROOT / "candidates.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "source-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def extract_reviewed():
    """Explicit human-reviewed IDs; name search never chooses a runtime identity."""
    rows, foods, cirows, manifest = load()
    selection = json.loads((ROOT / "selection.json").read_text(encoding="utf-8"))
    by_id = {f["fdc_id"]: f for f in foods}
    ci_id = {str(r[6]): r for r in cirows[1:]}
    nutrients = {r["id"]: r for r in rows("nutrient.csv")}
    derivations = {r['id']:r for r in rows('food_nutrient_derivation.csv')}
    all_values = rows("food_nutrient.csv")
    portions = rows("food_portion.csv")
    comparison, snapshot = [], []
    for target, selected in zip(TARGETS, selection, strict=True):
        food = by_id[selected["usda_id"]]
        vector = {}
        for n in all_values:
            key = USDA_NUTRIENTS.get(int(n["nutrient_id"]))
            if n["fdc_id"] != food["fdc_id"] or not key:
                continue
            definition = nutrients[n["nutrient_id"]]
            raw_unit = definition["unit_name"].lower()
            unit = "ug" if raw_unit in {"µg", "mcg"} else raw_unit
            vector[key] = {"state": "known" if n["amount"] else "unknown",
                "value": n["amount"] or None, "unit": unit,
                "provenance": {"source_nutrient_id": n["nutrient_id"],
                    "source_value": n["amount"], "source_unit": definition["unit_name"],
                    "derivation_id": n["derivation_id"], "method":derivations.get(n['derivation_id'],{}).get('description'),
                    "method_code":derivations.get(n['derivation_id'],{}).get('code'), "data_points": n["data_points"],
                    "min": n["min"], "max": n["max"], "footnote": n["footnote"]}}
        servings = [{"id": p["id"], "label": ((p["portion_description"] or p["modifier"]) + " (" + p["amount"] + ")")[:200],
                     "amount": p["gram_weight"], "unit": "g",
                     "provenance": {"usda_portion_id": p["id"], "original_amount": p["amount"], "gram_weight": p["gram_weight"]}}
                    for p in portions if p["fdc_id"] == food["fdc_id"] and p["gram_weight"] and p["amount"] and __import__('decimal').Decimal(p['amount']) > 0]
        snapshot.append({"source": "usda_sr_legacy", "source_food_id": food["fdc_id"], "revision": "2018-04",
            "name": target[0], "source_name": food["description"], "preparation": food["description"],
            "basis_amount": "100", "basis_unit": "g", "density_g_ml": None,
            "nutrients": vector, "servings": servings, "license": "CC0-1.0",
            "provenance": {"url": SR_URL, "edition": "SR Legacy April 2018", "verified_at": None}})
        ci = ci_id.get(selected.get("ciqual_id"))
        comparison.append({"target": target[0], "usda_id": food['fdc_id'], "usda_name": food['description'],
            "usda_nutrient_count": len(vector), "usda_servings": len(servings),
            "ciqual_id": selected.get('ciqual_id'), "ciqual_name": ci[7] if ci else None,
            "ciqual_raw_values": dict(zip(map(str,cirows[0][9:]),ci[9:])) if ci else {},
            "match_note": selected['note'], "comparable_preparation": selected['comparable']})
    doc = {"schema_version": "2.0", "source": "usda_sr_legacy", "revision": "2018-04-mx37",
        "license": "CC0-1.0", "foods": snapshot, "upstream": manifest['usda']}
    (ROOT / 'catalog-sample.json').write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding='utf-8')
    (ROOT / 'comparison.json').write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == "__main__":
    ROOT.mkdir(parents=True, exist_ok=True)
    candidates()
    if (ROOT / 'selection.json').exists():
        extract_reviewed()
