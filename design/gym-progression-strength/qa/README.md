# Validación de diseño Gym

Capturas y validación inicial: 2026-10-03. Aprobación visual y revalidación de
cierre: 2026-10-04. Solo fixtures ficticios y media pública local.

## Resultado

- Home, Exercise Progress y Post-Workout: **aprobación visual PASS**.
- 18 combinaciones responsive: 3 pantallas × 360/390/430/768/1024/1366.
- Sin overflow horizontal, imágenes rotas ni controles principales menores de 44 px.
- Claro: las 3 pantallas en 390 y 1366, sin overflow.
- 9 escenarios alternativos capturados, además del progreso positivo base.
- 14 gates de interacción: PASS. Navegación, periodos, datos accesibles,
  propuesta/preview/confirmar/descartar, Escape, Tab/Shift+Tab, skip link,
  galería por identidad, recorrido móvil y D2 sin inicio automático.
- Select de escenarios: 16 px. Foco: outline 3 px. Texto + iconos para estados.
- 12 pares de color comprobados: contraste mínimo 5.26:1.
- Consola: 0 warnings / 0 errors durante QA.
- No se realizó una auditoría integral WCAG ni una prueba con lector de pantalla.

### Revalidación de cierre — 2026-10-04

- 12 tests JS y 2 checks existentes de accesibilidad: PASS; 4 tests no relacionados
  del archivo de accesibilidad quedan deselected. Sin suite backend completa.
- 18 combinaciones responsive y 6 en claro: PASS, sin overflow, imágenes rotas
  ni controles principales menores de 44 px.
- 9 comprobaciones de accesibilidad en navegador: PASS (skip link, Tab/Shift+Tab,
  Escape/retorno de foco, datos de gráfica, label/tamaño de select y estados textuales).
- 12 pares de contraste: mínimo 5.26:1. Consola sin warnings ni errores.
- Zoom 200% no verificado: el atajo del navegador integrado disponible no cambió
  el zoom de la página; no se registra como PASS. Los checks responsive conservan
  las dimensiones reales comprobadas.
- Compose config: PASS con entorno ficticio explícito; sin leer `.env`.
- Se conserva la UI y las capturas aprobadas; solo se finaliza documentación,
  estado de aprobación en la galería y evidencia del cierre.

## Comandos ejecutados

```powershell
node --check design/gym-progression-strength/app.js
node --check design/gym-progression-strength/fixtures.js
node --test scripts/gym/presentation.test.cjs scripts/gym/media.test.cjs scripts/gym/test_draft_autosave.cjs
```

Resultado: **12 PASS** en las pruebas frontend existentes.

Desde `backend/`:

```powershell
..\.venv\Scripts\python.exe -m pytest -q tests/test_web_ui_homelab.py -k 'app_shell_has_skip_link or design_system_has_responsive'
```

Resultado: **2 PASS**, 4 deselected. Fixtures SQLite en memoria y filesystem
temporal; no stack persistente. No se ejecutó la suite backend completa.

`docker compose --env-file <archivo temporal QA explícito> config --quiet`:
**PASS**, sin leer `.env`, levantar servicios ni montar volúmenes.

`git diff --check` y `git diff --cached --check`: PASS antes del commit.
El alcance del commit es únicamente `design/gym-progression-strength/` y
`docs/GYM_PROGRESSION_STRENGTH_UX.md`.

## Capturas completas

| Pantalla | Móvil 390×844 oscuro | Escritorio 1366×900 oscuro |
| --- | --- | --- |
| Home | [Abrir](mobile-390-home-dark.png) | [Abrir](desktop-1366-home-dark.png) |
| Progreso | [Abrir](mobile-390-progress-dark.png) | [Abrir](desktop-1366-progress-dark.png) |
| Cierre | [Abrir](mobile-390-summary-dark.png) | [Abrir](desktop-1366-summary-dark.png) |

Son capturas full-page, por lo que su altura incluye todo el scroll. El navegador
puede excluir su gutter vertical de 15 px de la imagen (375/1351 px de contenido);
los viewports solicitados y comprobados son 390/1366.

Hay equivalentes `*-light.png` y `state-*.png` para mantener, debajo del rango,
tope, revisión, una sesión, sin historial, sin imagen, programa nuevo y sin
propuestas. `interaction-confirmed-desktop-dark.png` muestra una confirmación
simulada. `validation.json` contiene medidas y resultados de interacción de la
validación inicial. `closure-validation.json` registra la revalidación del cierre
aprobado, sin sustituir las capturas ni ampliar el diseño.

## Límites y parada

Backend changes = **0**. No migrations, rules, cálculos de fuerza, writes, AI,
tags, merge ni acceso al NAS. No se usaron datos personales. El usuario autorizó
el commit de diseño y el push de la rama el 2026-10-04.
Base del prototipo:
`50053882f7fbb05b90fbce8dcac5c390566232d3`.

Los mocks todavía no son adaptadores de runtime. La dirección visual está
aprobada y lista para guiar la implementación; conectar datos o el motor necesita
una fase posterior autorizada.
