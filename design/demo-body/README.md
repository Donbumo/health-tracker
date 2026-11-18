# QA visual de peso y composición DEMO

Todas las imágenes muestran **datos completamente ficticios** persistidos por el
generador real de la rama `codex/demo-history`. No provienen del NAS, de una
báscula o de un usuario real. Flask, los servicios, las consultas y los gráficos
son los existentes; no se usan mocks de interfaz.

- Periodo: 2026-10-01 a 2026-11-18.
- 49 pesajes y 21 registros de composición integrados en esos pesajes.
- Peso, grasa, músculo, agua, grasa visceral e IMC; media móvil de siete días.
- Cinco páginas, seis anchos por página, cinco métricas de composición.
- `qa/report.json`: cero errores JavaScript/HTTP y cero overflow en 30 layouts.

Capturas de peso: [escritorio](qa/weight-1366.png), [móvil](qa/weight-390.png).
Composición: [grasa](qa/body_fat-390.png), [músculo](qa/muscle_mass-1366.png),
[agua](qa/water-390.png), [grasa visceral](qa/visceral_fat-390.png), [IMC](qa/bmi-390.png).
[Noviembre frente a los mismos días de octubre](qa/november-vs-october.png).

Reproducción local: ejecutar `scripts/demo/qa_app.py`; pasar la URL temporal
loopback que imprime como `DEMO_QA_URL` a `node scripts/demo/body_ui_qa.cjs`.
El navegador usa una base SQLite temporal exclusivamente ficticia. La prueba
independiente `scripts/demo/mariadb_qa.py` verifica persistencia, backfill,
conservación, login y dashboards sobre MariaDB 11.4 aislada, 0046 y RC/RR.
