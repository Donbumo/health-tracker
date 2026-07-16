# Import Hub

La ruta canónica visible es `/imports`. El flujo es: elegir archivo, detectar o indicar dominio, previsualizar, validar, revisar insert/update/skip/conflict y confirmar.

## Formatos reales soportados

- JSON de los dominios estándar actuales y JSON asistido por el generador existente.
- FIT, GPX y TCX para actividad o ruta.
- CSV/TSV de pesajes o energía diaria con los perfiles existentes.
- Backup ZIP solo en `/account/backups/restore`; no se mezcla con una importación normal.

El preview es read-only. La confirmación está ligada al usuario, contenido, destino y plan; es de un solo uso. Los lotes son atómicos y una repetición segura resulta en `skip` en vez de duplicar.

El Hub muestra un inventario generado por `ImportAdapterRegistry` y las cinco ejecuciones recientes. Las rutas avanzadas anteriores permanecen por compatibilidad, pero no se duplican en la navegación.

No se soportan APIs privadas de fabricantes, archivos ejecutables, mapping reusable persistido ni restore completo desde este flujo.
