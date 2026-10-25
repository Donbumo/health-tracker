# Resumen de salud — propuesta local

[Abrir index.html](index.html). Todos los recursos son locales: `styles.css`, `fixtures.js` y `app.js`. Se puede abrir desde archivos sin servidor ni instalación. No usa `fetch`, cuentas, DB, cookies, almacenamiento local ni servicios externos.

Rama: `codex/unified-health-summary`. Base: `38c6085565f49f560c9c4a1fefc18356bd1e3000`. [Arquitectura y decisiones](../../docs/UNIFIED_HEALTH_SUMMARY_DESIGN.md). [Energy Experience cerrada en producción](../../docs/ENERGY_EXPERIENCE_2_0_D_PRODUCTION.md).

Interacciones: 7/30/90 días, tema claro/oscuro, cinco escenarios del día y detalles locales. Fecha fija ficticia 05-02-2040; los valores están precalculados. La autoría de fixtures reutilizó la función pura `mean` existente; el JavaScript no contiene otro motor de balance o medias. No es una implementación Flask ni una validación productiva de la nueva funcionalidad.

Capturas de la propuesta:

- [Escritorio oscuro](screenshots/desktop-dark.png)
- [Escritorio claro](screenshots/desktop-light.png)
- [Móvil oscuro](screenshots/mobile-dark.png)
- [Móvil claro](screenshots/mobile-light.png)

La verificación de archivos/interacciones de esta propuesta se registra en [preview-checks.json](preview-checks.json). No representa otra campaña de Narrador/axe/zoom de D.

## Implementación Flask para revisión — 25-10-2026

[Informe y comparación](../../docs/UNIFIED_HEALTH_SUMMARY_IMPLEMENTATION.md), [resultados](flask-qa/checks.json) y [capturas reales](flask-qa/). Estos archivos son evidencia distinta de las capturas originales del prototipo. La implementación utiliza el dashboard Flask, fecha real y autoridades canónicas; móvil dispone ingesta/gasto en dos tarjetas y balance a ancho completo.

Reproducir con `scripts/dashboard/unified_health_qa.py` y `scripts/dashboard/unified_health_visual.cjs` desde la raíz. Servidor loopback y SQLite/storage temporales, cuentas ficticias. Ningún recurso del prototipo alimenta los cálculos productivos. No merge ni despliegue autorizado por esta entrega.
