# Web UI Accessibility

## Contrato mínimo

- `lang="es"` y viewport están presentes en el documento base.
- Existe enlace para saltar al contenido principal.
- El contenido principal usa `main` y la navegación tiene nombres accesibles.
- La ruta activa expone `aria-current="page"`.
- Formularios conservan `label` asociado, mensajes próximos al campo y CSRF.
- Foco por teclado es visible con `:focus-visible`.
- Los estados no dependen únicamente del color.
- El menú móvil usa `details/summary`, está cerrado por defecto y mantiene scroll interno.

## Revisión manual

1. Recorrer header, menú, contenido y acciones con Tab y Shift+Tab.
2. Abrir/cerrar el menú móvil con teclado.
3. Comprobar zoom al 200 % sin pérdida de acciones.
4. Verificar tema claro y oscuro del sistema.
5. Confirmar que errores, alertas y estados vacíos mantienen texto comprensible.

Esta fase mejora la base, pero no sustituye una auditoría formal con lector de pantalla y herramientas de contraste.

