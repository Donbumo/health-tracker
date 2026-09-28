# Exercise Mapping Assistant

## Uso

Mi entrenamiento → Ejercicios por revisar → Revisar/Elegir. Cada candidato del catálogo instalado muestra imagen local (o ausencia explícita), nombre, músculos, equipo, instrucción resumida y licencia. Se puede buscar otra variante, abrir el detalle, vincular o elegir «Ninguno corresponde».

El resumen incluye identidades personales existentes y nombres de las versiones activas de rutinas no eliminadas. Las identidades conservadas por el historial también pueden revisarse aunque ya no exista una rutina activa. La lista separa pendientes y vinculados, con «Cambiar vínculo» para estos últimos.

«Ninguno corresponde» no guarda ni elimina nada: conserva el vínculo previo, si existe, o deja el ejercicio pendiente. No se crea un estado de descarte permanente.

## Identidad y seguridad

- Se reutilizan `Exercise.external_catalog_id` y `ExerciseAlias`. No cambia el modelo ni se añade una migración; head `20260927_0042`.
- La identidad canónica personal conserva UUID, nombre y ownership. La referencia externa aporta la identidad canónica de la fuente y su presentación; nunca fusiona dos identidades personales.
- El nombre revisado se conserva como alias del propietario. Las importaciones posteriores siguen resolviendo ese nombre a la misma identidad mediante el resolver existente.
- No se reescriben documentos/versiones, nombres visibles, sesiones ni series históricas. Para un nombre importado sin identidad previa, esta se crea solamente después de la selección explícita.
- GET y sugerencias son read-only. POST exige sesión y CSRF. El usuario efectivo viene de la sesión; nombres ajenos o no presentes en el inventario del propietario devuelven 404.
- Cada botón contiene una decisión firmada por usuario, nombre, identidad, vínculo anterior, referencia y snapshot. Expira a los 30 minutos. La confirmación bloquea al propietario, relee estado y rechaza revisiones obsoletas. Repetir la misma decisión no duplica identidades ni aliases.
- Las sugerencias usan vocabulario determinístico de búsqueda, separado del resolver y de los aliases persistidos. Incluso un único candidato requiere selección. La búsqueda manual puede explorar todo el catálogo; los resultados se limitan a 24 con indicación para afinar.

## Rutas

- `GET /gym/exercise-links`: resumen propio.
- `GET /gym/exercise-links/review?name=...&q=...`: candidatos locales.
- `POST /gym/exercise-links/review`: confirmar una decisión o volver sin cambios.

El importador de borradores sin guardar conserva su preview y confirmación oficial existentes. Este asistente revisa ejercicios ya importados/persistidos; no importa un archivo ni guarda un borrador por sí mismo.

No cambia External Exercise Catalog, sus fuentes, sync, storage ni endpoints. No hay descargas adicionales, AI ni cambios de contrato público. Los límites de portabilidad del vínculo visual son los mismos documentados en EXERCISE_CATALOG.md.

## QA reproducible

`backend/tests/test_exercise_mapping.py`: fixtures ficticias, aislamiento entre usuarios, CSRF, tokens alterados/obsoletos, referencias retiradas, confirmación, cambio/reintento, alias/import futuro, historial preservado, nombres legacy sin identidad, catálogo vacío y ausencia de autoasignación.

Se puede usar el gate MariaDB del catálogo existente: `CATALOG_TEST_MARIADB=exercise_catalog_unit_qa`, restringido al schema efímero de loopback:33379. No usar bases persistentes.

`scripts/gym/mapping_qa_app.py` exige `MAPPING_QA_ROOT` bajo temp con prefijo `ht-mapping-qa-`. Crea exclusivamente un usuario/rutina/sesión ficticios y medios locales de prueba, sin descargas. Sirve en loopback:8014 y bloquea HTTP saliente. Credenciales de fixture: `mapping-qa` / `fictional-qa-password`.

## Gate de entrega

Commit + PR para revisión. Sin NAS, deploy, migración ni mappings reales en esta entrega. El reporte privado de candidatos reales permanece en la conversación, fuera de Git. La selección de producción queda exclusivamente en manos del usuario después de revisar y desplegar el cambio.

Validación de la interfaz: 24 combinaciones de resumen/candidatos × 6 anchos (360, 390, 430, 768, 1024, 1366) × claro/oscuro. Las paletas se seleccionan exclusivamente en el servidor QA mediante `qa_theme`, sin modificar preferencias del sistema ni CSS productivo. Sin overflow, imágenes rotas ni errores de consola. Confirmación y cambio ficticios comprobados en rutina, sesión en curso y galería.
