# Handoff activo

## Estado actual

- Trabajo realizado exclusivamente en `feature/web-dashboard-trends`, desde `a7dfb20baca52ff17d5422137823ee5ecc138adb`.
- `/dashboard` es el resumen analítico por periodos y `/today` conserva el flujo operativo diario.
- El resumen incluye energía, proteína, peso y entrenamiento, con intervalos por zona horaria, comparación opcional, cobertura y gráficos SVG locales.
- No hay migraciones, cambios de schema público ni dependencias frontend nuevas. El head Alembic continúa en `20260731_0036`.
- La guía funcional y las fórmulas están en `DASHBOARD_TRENDS.md`; el índice de entrada sigue siendo `DOCUMENTATION_INDEX.md`.

## Trabajo en curso

- La implementación y la QA funcional/visual del dashboard están cerradas y listas para revisión del diff.
- La validación usa únicamente datos ficticios: tema oscuro real y tema claro mediante un override QA aislado ya retirado.
- El gate MariaDB usa una base efímera desde cero, valida Alembic, aislamiento por propietario, agregados e índice con `EXPLAIN`, y elimina después sus recursos exclusivos.
- No quedan servidores, bases, logs, capturas, overrides, contenedores, redes ni volúmenes efímeros del dashboard.

## Bloqueadores y riesgos

- El checkout base no contiene las fixtures generadas FIT/GPX/TCX bajo `examples/qa/real-file-imports`; las pruebas que dependen de esos archivos fallan antes de entrar en el código del dashboard.
- El volumen de entrenamiento se oculta si el periodo mezcla modalidades que no admiten una comparación honesta; esta es una limitación deliberada, no imputación de datos.
- Los días sin registros permanecen como huecos y reducen la cobertura; no se rellenan con cero.

## Siguiente paso

Revisar el diff y, solo con autorización explícita posterior, decidir el commit. No hay commit, push, merge ni tag en este handoff.

## Pruebas relevantes

- Suite focal del dashboard: rangos, DST, serialización, aislamiento por propietario, unidades, valores faltantes, comparación y número constante de consultas.
- Regresiones de autenticación, navegación, `/`, `/dashboard` y `/today`.
- Suite backend completa y pasada adicional sin los dos módulos que requieren fixtures ausentes.
- `compileall`, `docker compose config --quiet`, Alembic `upgrade`, `heads`, `current`, `check`, `git diff --check` y QA visual real.
