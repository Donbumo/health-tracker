# Energy Experience 2.0 B — evidencia Flask

Implementación en `feature/energy-experience-2-0-b`, basada en A/master `9624142901c191ebc5dd47f333a42f5096e9065e`. B no está fusionada ni desplegada.

[Arquitectura, permisos, pruebas y veinte capturas](../../docs/ENERGY_EXPERIENCE_2_0_B.md).

- `qa/report.json`: 48 combinaciones visuales reales Flask (seis anchos × dos temas × cuatro vistas), teclado, filtros, navegación y descarga owner-only. Veinte PNG mobile/desktop dark/light.
- `qa/linux-focal.xml`: 29 pruebas B en Linux, incluido symlink.
- `qa/mariadb.json`: MariaDB LOCAL aislada, RC/RR, 117 eventos y cinco páginas por fixture, db check sin nuevas operaciones.
- `qa/backend.json`: resumen de regresión focal final.

Datos, usuarios y archivos ficticios. El servidor visual es SQLite temporal; MariaDB se valida por separado. Las capturas no acreditan B en producción ni usan datos personales. Para A operativa consultar [el cierre separado](../../docs/ENERGY_EXPERIENCE_2_0_A_PRODUCTION.md).
