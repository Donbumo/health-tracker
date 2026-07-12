# Checklist de release alpha privada

Usa esta lista antes de invitar a un compañero real a una alpha por LAN/VPN.

## Instalación y migraciones

- [ ] `git status --short --branch` muestra la rama esperada.
- [ ] `.env` existe localmente, no se comparte y no contiene placeholders.
- [ ] `docker compose config --quiet` pasa.
- [ ] `docker compose up --build -d` levanta `web` y `db`.
- [ ] `docker compose exec web flask db upgrade` termina sin error.
- [ ] `docker compose exec web flask db check` dice `No new upgrade operations detected`.
- [ ] `/healthz` responde `status: ok`.

## Admin y cuenta de compañero

- [ ] Admin puede iniciar sesión.
- [ ] Admin abre `/admin/users`.
- [ ] Admin crea un segundo usuario con rol `user`.
- [ ] Email duplicado se rechaza con mensaje claro.
- [ ] El nuevo usuario inicia sesión desde navegador normal.
- [ ] Usuario normal no puede abrir `/admin/users` ni `/admin/system`.

## Primer acceso

- [ ] Dashboard vacío responde 200.
- [ ] Se ve aviso de `Alpha 0.1`.
- [ ] Se ve aviso de que no sustituye atención médica.
- [ ] Se ve checklist de primeros pasos.
- [ ] La navegación funciona en ancho móvil.
- [ ] `/privacy` explica almacenamiento, export y alcance LAN/VPN.

## Capturas mínimas

- [ ] Usuario registra peso manual.
- [ ] Usuario registra energía manual.
- [ ] Usuario registra nutrición manual.
- [ ] Usuario registra una sesión de entrenamiento basada en rutina propia.
- [ ] Cada guardado muestra éxito o error comprensible.
- [ ] Después de capturar, el dashboard muestra datos actualizados.

## Importación y auditoría

- [ ] `/imports/standard` abre para usuario autenticado.
- [ ] `/imports/files` abre para usuario autenticado.
- [ ] Preview de JSON válido no escribe datos.
- [ ] Preview de FIT/GPX/TCX/CSV válido no escribe datos de dominio.
- [ ] Confirmación explícita guarda datos.
- [ ] Reimportar el mismo FIT/GPX/TCX/CSV devuelve `skip` o duplicado esperado, no inserta copias.
- [ ] `/imports/history` muestra el run agregado.
- [ ] `/imports/history/<id>` muestra hashes truncados y no payload crudo.
- [ ] Token inválido o plan conflictivo no crea datos de dominio.

## Export y aislamiento

- [ ] Usuario descarga `/account/export.json`.
- [ ] Export no incluye `password_hash`, tokens ni archivos binarios.
- [ ] Segundo usuario no ve peso, energía, nutrición, sesiones, imports ni exports del primero.
- [ ] IDs ajenos responden 404 o 403 según ruta.

## Logout y persistencia

- [ ] Logout se hace por POST con CSRF desde navegación.
- [ ] Después de logout, dashboard redirige a login.
- [ ] Reiniciar `web` conserva login/data en DB.
- [ ] Reiniciar `db` sin borrar volúmenes conserva datos.
- [ ] `docker compose down` y `docker compose up -d` conservan datos.
- [ ] No se usa `docker compose down -v`.

## Validación técnica

- [ ] `.\.venv\Scripts\python.exe -m compileall -q backend`
- [ ] `.\.venv\Scripts\python.exe -m pytest backend/tests/ -q`
- [ ] `docker compose exec -T web flask db check`
- [ ] Si se instala pytest temporalmente en Docker, queda documentado.
- [ ] `git diff --check` limpio.
- [ ] No hay archivos temporales ni cambios en `/data`, `.env`, schemas públicos o migraciones innecesarias.

## Decisión

La alpha privada está lista si:

- [ ] No hay bloqueantes de login, captura, dashboard, export o logout.
- [ ] El aislamiento por usuario está probado.
- [ ] Hay un procedimiento claro de acceso LAN/VPN.
- [ ] Admin sabe crear y entregar cuentas.
- [ ] La suite local y Docker están verdes.
