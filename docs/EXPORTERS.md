# Exportadores avanzados

La Fase 6 / Alpha 0.4 usa un flujo uniforme:

```text
recurso owner-only -> capability/preview read-only -> confirmación POST -> render
-> escritura atómica -> SHA256 -> ExportRecord -> descarga owner-only
```

## Matriz

| Dominio | Formatos |
| --- | --- |
| Activity | JSON, CSV resumen, CSV track, CSV laps, GPX 1.1, TCX Activity |
| Route | JSON, CSV puntos, GPX 1.1, TCX Course |
| TrainingPlan/Version | JSON, CSV, HTML, PDF, ZWO, ERG, MRC |
| TrainingSession | completed_workout JSON, CSV, HTML, PDF |

FIT de salida es una capacidad experimental no disponible. No hay encoder mantenido configurado y el sistema no fabrica archivos `.fit` falsos.

## Rutas

- `/exports`: historial del usuario.
- `/exports/new/<domain>/<source_id>`: preview y confirmación.
- `/exports/<id>`: metadata saneada.
- `/exports/<id>/download`: descarga con verificación de tamaño y SHA256.
- `POST /exports/<id>/delete`: elimina el binario gestionado y conserva el registro como `deleted`.

Las acciones se enlazan desde actividades, rutas, rutinas y sesiones. Un ID de otro usuario responde 404.

## Capability y pérdidas

Cada combinación dominio/formato declara disponibilidad, motivo si no es compatible, warnings y `lossy_fields`. ZWO/MRC requieren potencia relativa a FTP explícita; ERG requiere watts explícitos. Los planes de fuerza no se convierten silenciosamente.

El preview no crea archivos ni `ExportRecord`. La generación solo ocurre después de POST con CSRF.

Referencias: [actividad/rutas](ACTIVITY_ROUTE_EXPORTS.md), [entrenamiento](TRAINING_EXPORTS.md) y [storage](EXPORT_STORAGE.md).
