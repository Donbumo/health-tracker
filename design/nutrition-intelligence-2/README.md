# Nutrition Intelligence 2.0 — sandbox de diseño QA

Abrir `index.html` directamente en un navegador moderno. No requiere Flask,
MariaDB, instalación npm, NAS ni Internet. Los botones sólo alteran memoria;
recargar restablece la demo. No introducir datos personales reales.

Rutas hash: today, add, candidates, review, search, detail, saved, micros, user-food.
Texto/foto usan escenarios fijos QA: no hay parsing, LLM, lectura ni subida de imagen.
Las fixtures nutricionales y referencias son ficticias, sin uso médico.

Recorrido sugerido:

1. Hoy → Guardadas → Usar comida → Registrar.
2. Añadir → Reconocimiento demo → Revisar → confirmar cada candidato → Registrar.
3. Buscar pollo → comparar cruda/cocida → Detalle → 180 g → 297 kcal / 55.8 g proteína → Añadir.
4. Review → cambiar cantidad/unidad → guardar comida reutilizable; historia conservada.
5. Micronutrientes → distinguir coverage, subtotal conocido y referencias demo.
6. Hoy → Escenarios QA → Día vacío; luego restaurar demo.
7. Crear mi alimento → dejar micros vacíos, conservar un cero explícito.
8. Cambiar tema y navegar por teclado.

Dirección visual/arquitectónica aprobada por el usuario. Cierre UI/UX: revisión móvil
compacta con número de pendientes; subtotales parciales sin comparación con objetivos;
y límite del coverage por masa explicado en cada tarjeta de micronutrientes.
Los contratos, snapshots y confirmación permanecen intactos. La implementación
productiva se deja para una tarea posterior.
Contratos: [arquitectura](../../docs/NUTRITION_INTELLIGENCE_2.md).
Fuentes: [comparación](../../docs/NUTRITION_CATALOG_SOURCES.md).

QA reproducible en Windows con Node y Playwright disponibles:

```powershell
# Ajustar NODE_PATH al runtime local si playwright no está en el resolver de Node.
node design/nutrition-intelligence-2/qa.cjs
```

El script usa Edge headless, sólo `file://`, y genera `qa-results.json` y capturas
en `screenshots/`. Verifica seis anchuras y ambos temas, estados vacíos, candidatos,
inputs/targets/foco, cálculo, servings, unknown, snapshots, repetición y navegación.
No ejecuta servidores ni tests de backend. Las capturas son full-page a 390 y 1366;
el viewport móvil es 390×844 (la página puede desplazarse verticalmente).

Vista local opcional: `node design/nutrition-intelligence-2/preview.cjs` y abrir
`http://127.0.0.1:8024`. Sólo sirve una allowlist de archivos del prototipo.
`gallery.html` ofrece una selección visual de capturas, sin servidor obligatorio.
