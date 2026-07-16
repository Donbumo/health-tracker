# Flujo diario

1. Abre `/dashboard` y revisa **Entrenamiento de hoy**.
2. Si existe un borrador, continúa desde el aviso; no crees una segunda captura.
3. Inicia el entrenamiento planeado o elige un día de la rutina activa.
4. Registra solo series realizadas. Cada ejercicio es plegable y la barra de accesos permite saltar entre ejercicios.
5. Usa carga total o componentes; el servidor conserva la entrada original y normaliza el total a kg.
6. Revisa RIR, RPE, descanso, duración, frecuencia cardiaca y calorías cuando existan.
7. Guarda una sola vez. El botón se protege durante el envío y `client_submission_id` evita duplicados.
8. Comprueba detalle, historial y progreso.

El borrador local y el owner-only del servidor ayudan ante reload o red. Un CSRF vencido reconstruye el formulario; el borrador solo se elimina después de confirmar una sesión guardada.
