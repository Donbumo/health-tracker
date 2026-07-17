# Despliegue alpha privada

Guía para levantar Health Tracker como alpha privada en Windows usando Docker, LAN o VPN. No expongas esta app directamente a Internet.

## Alcance

- Uso recomendado: mismo equipo, red local o VPN privada.
- No es SaaS público.
- Incluye restore de cuenta y backup ZIP; valida el flujo con datos ficticios antes de usarlo operativamente.
- No uses datos reales en pruebas de Git; los datos reales viven en MariaDB, `/data` o volúmenes Docker ignorados.

## Requisitos

- Windows 10/11.
- Docker Desktop iniciado con contenedores Linux.
- Repositorio actualizado.
- Archivo `.env` creado desde `.env.example` con secretos reales de la instalación.

No leas ni compartas `.env` en tickets, chats o prompts.

## Actualizar código

Desde PowerShell, en la raíz del repo:

```powershell
git status --short --branch
git checkout master
git pull
```

Si vas a probar una rama distinta, confirma primero su base y alcance; este runbook no fija una rama histórica.

## Levantar la app

```powershell
docker compose config --quiet
docker compose up --build -d
docker compose exec web flask db upgrade
docker compose exec web flask db check
```

Verifica salud:

```powershell
curl http://localhost:8000/healthz
```

Abre:

```text
http://localhost:8000
```

## Acceso desde otro dispositivo

Obtén la IP local del equipo Windows:

```powershell
ipconfig
```

Busca la IPv4 de la red Wi-Fi/Ethernet, por ejemplo:

```text
192.168.1.50
```

Desde un teléfono o computadora en la misma LAN:

```text
http://192.168.1.50:8000
```

Para VPN, usa la IP o nombre interno que entregue la VPN.

No abras el puerto 8000 a Internet. Si en el futuro se publica fuera de LAN/VPN, requiere HTTPS, reverse proxy, endurecimiento de cookies, backups probados y revisión de seguridad.

## Crear usuario para un compañero

1. Inicia sesión como admin.
2. Abre `/admin/users`.
3. Crea usuario con email, contraseña temporal y rol `user`.
4. Entrega por un canal seguro:
   - URL privada.
   - Email de acceso.
   - Contraseña temporal.
   - Aviso de que es alpha privada y no sustituye atención médica.

La app no envía correos. Nunca se muestran contraseñas almacenadas.

## Prueba desde teléfono

1. Abre la URL LAN/VPN.
2. Inicia sesión con la cuenta creada.
3. Revisa el dashboard.
4. Captura peso, energía y nutrición ficticia o de QA.
5. Exporta `/account/export.json`.
6. Cierra sesión.

## Logs

Ver logs en vivo:

```powershell
docker compose logs -f web
```

Ver últimos eventos:

```powershell
docker compose logs web --tail=120
```

## Reiniciar sin borrar datos

```powershell
docker compose restart web
docker compose restart db
```

O detener sin borrar volúmenes:

```powershell
docker compose down
docker compose up -d
```

No uses `docker compose down -v` si quieres conservar MariaDB.

## Backup

Export individual de usuario:

```text
/account/export.json
```

Dump de MariaDB desde Docker:

```powershell
docker compose exec db mariadb-dump -u root -p health_tracker > health_tracker_backup.sql
```

Guarda backups fuera del repo. No subas dumps a Git.

El restore soportado de la aplicación está documentado en [ACCOUNT_RESTORE.md](ACCOUNT_RESTORE.md) y [FULL_BACKUP.md](FULL_BACKUP.md). Un dump SQL es una operación distinta y debe ensayarse en infraestructura aislada antes de depender de él.
