# Recuperación de sesiones de entrenamiento

Alpha 1.0 conserva este contrato y presenta cada ejercicio en un bloque plegable con accesos rápidos. No cambia el payload del borrador, `client_submission_id`, el momento de borrado ni la recuperación CSRF.

Alpha 0.8.1 corrige la pérdida o bloqueo de formularios largos cuando vence CSRF. La captura web queda protegida por capas:

1. El formulario mantiene un `client_submission_id` UUID estable.
2. Un borrador local se actualiza con debounce de 500 ms.
3. Un borrador owner-only en MariaDB se actualiza con un debounce mayor.
4. Un error CSRF reconstruye el mismo formulario con un token nuevo y no guarda datos de dominio.
5. El reintento con el mismo ID y contenido devuelve la sesión existente; contenido distinto produce `submission_conflict`.
6. Sesión, ejercicios, series, planned workout, cambio de sync y eliminación del borrador servidor se confirman juntos.

El mensaje de recuperación es: “El token de seguridad venció. Recuperamos todos tus datos; vuelve a presionar Guardar.” El borrador no se elimina ante errores HTTP o de red. El navegador lo elimina únicamente al cargar el detalle exitoso de la misma submission.

## Configuración

- CSRF: 8 horas. Flask-WTF recibe el equivalente en segundos por compatibilidad con su versión instalada.
- Sesión web permanente: 12 horas y renovación con actividad.
- Borradores: máximo 256 KiB y expiración de 7 días por defecto.
- `SECRET_KEY` debe llegar por entorno o secret externo, ser estable y superar la validación de arranque. Nunca se genera al iniciar ni se imprime.
- `API_TOKEN_SIGNING_KEY` sigue siendo un concepto independiente para Bearer API.

## QA mínimo

Abrir una sesión planificada, completar métricas y series, confirmar que aparece “Borrador guardado”, recargar y verificar recuperación. Simular un CSRF vencido, confirmar el mensaje y el token nuevo, reenviar y comprobar que existe una sola sesión. Repetir con error de red y verificar que el borrador permanece.

La captura avanzada de cargas no forma parte del hotfix Alpha 0.8.1; se implementa de forma aditiva en el bloque posterior `feature/workout-load-entry`.

