# Nutrition Experience 2.1 — evidencia local

Implementación Flask/Jinja real, no prototipo estático. Datos de usuario
exclusivamente QA ficticios; catálogo público real con atribución separada.

- [Galería](gallery.html).
- [Seis correcciones finales](../../docs/NUTRITION_EXPERIENCE_2_1_FINAL_REVIEW.md).
- [Implementación](../../docs/NUTRITION_EXPERIENCE_2_1_IMPLEMENTATION.md).
- [Catálogo](../../docs/NUTRITION_EXPERIENCE_2_1_CATALOG.md).
- [Importación](../../docs/NUTRITION_EXPERIENCE_2_1_IMPORT.md).
- [QA y compatibilidad](../../docs/NUTRITION_EXPERIENCE_2_1_QA.md).
- [Comparación con diseño aprobado](../../docs/NUTRITION_EXPERIENCE_2_1_VISUAL.md).

Reproducción local: `python scripts/nutrition/qa_app_21.py` utiliza SQLite
efímero en TEMP y el puerto QA existente 8025. No abre la base personal.
`node scripts/nutrition/ui_qa_21.cjs` ejecuta capturas y flujos con Playwright/Edge.
`python scripts/nutrition/mariadb_qa_21.py` utiliza únicamente la instancia y
schema QA local ya reservados; no crea ni resetea schemas, stacks o contenedores.

La suite backend se ejecuta desde el repositorio con `PYTHONPATH=backend`:
`python -m pytest backend/tests -q`.
No se ejecuta downgrade 0044. No se accede al NAS. Nada de esta carpeta contiene
una base de datos, secretos reales o datos personales de producción.

Paquete para adjuntar: `nutrition-experience-2-1-final-review.zip` en la raíz del
repositorio. Incluye archivos modificados/nuevos de esta rama, catálogo público,
fixtures ficticias, informes y capturas; no es un backup de cuenta. La entrega
es la evidencia previa revisada. El usuario autorizó después commit, push y PR;
las diez capturas `qa/final-first-*-390.png` y `qa/final-focal-report.json`
documentan los dos ajustes posteriores. No hay autorización de deploy o merge.

Repetición focal: `node scripts/nutrition/final_focal_qa_21.cjs`, con el mismo
servidor QA. No repite importaciones, migraciones ni suites completas.

La validación final incluye 252 combinaciones responsive, respuesta OFF ficticia
(no petición externa), biblioteca con 125 productos y 125 recetas, y retención/
eliminación antes de confirmar. `mariadb_product_qa_21.py` prueba sólo consultas
y eliminación de originales QA no confirmados, sin DDL.
