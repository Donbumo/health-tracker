# AGENTS.md

## Instrucciones principales para agentes de código

Antes de modificar el proyecto, lee primero:

* `docs/PROJECT_CONTEXT.md`

Ese archivo contiene la visión completa del producto, arquitectura, módulos, fases, schemas, importadores, exportadores, reglas de privacidad y estado actual del desarrollo.

## Reglas de trabajo

* No inventes datos reales de salud, nutrición, entrenamiento, médicos o personales.
* No agregues datos reales al repositorio.
* No subas ni generes archivos reales dentro de Git que pertenezcan a usuarios.
* Todo dato real debe vivir en `/data` o en volúmenes Docker ignorados por Git.
* Mantén aislamiento por `user_id`.
* Antes de cambiar modelos o migraciones, revisa si realmente se necesita una migración.
* Si agregas tablas o columnas, crea migración Alembic/Flask-Migrate.
* Si no agregas tablas ni columnas, no generes migraciones innecesarias.
* Conserva compatibilidad con Docker Compose y MariaDB.
* Evita romper pruebas existentes.
* Cuando agregues funcionalidades, agrega o actualiza pruebas.

## Comandos esperados de verificación

Cuando sea posible, ejecutar:

```bash
python -m compileall .
pytest
flask db check
docker compose config
```

Si el entorno Docker está disponible:

```bash
docker compose up -d --build
docker compose ps
docker compose exec app pytest
docker compose exec app flask db check
```

## Estado actual importante

El proyecto ya completó una Fase 6 inicial enfocada en exportadores e importadores de rutinas/sesiones:

* Interfaz común de exportadores.
* Exportación de rutinas en JSON y CSV.
* Exportación de sesiones en JSON, CSV y HTML imprimible.
* Importadores separados para `training_plan` y `completed_workout`.
* Conservación de originales, SHA256 y deduplicación.
* Aislamiento por usuario.
* Stubs documentados para FIT, GPX y Magene.
* Advertencias visibles sobre pérdida de información en CSV.
* TODO documentado para futuro modelo `ExportRecord`.

No se añadieron tablas ni migraciones en esa fase.

Últimas verificaciones conocidas:

* Pruebas locales: 29 passed.
* Docker: 29 passed.
* `compileall`: correcto.
* `flask db check` local: sin cambios pendientes.
* `flask db check` con MariaDB: sin cambios pendientes.
* Compose: válido.
* MariaDB: saludable.
* Login real en `localhost:8000`: correcto.
* Exportaciones HTTP JSON/CSV/HTML y aislamiento: cubiertos por la suite en Docker.

Archivos modificados en esa fase:

* `README.md`
* `training_plans.py`
* `workout_sessions.py`
* `sessions`

## Prioridad

Si hay conflicto entre README, comentarios antiguos o código viejo, tomar como referencia:

1. `docs/PROJECT_CONTEXT.md`
2. Pruebas existentes
3. Estado real del código
4. README
5. Comentarios antiguos
