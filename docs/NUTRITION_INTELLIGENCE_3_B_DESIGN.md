# Nutrition Intelligence 3.0 — propuesta B, sin implementación

Objetivo: ayudar a revisar nutrientes ausentes mediante candidatos equivalentes
del catálogo local. Una sugerencia no prueba identidad, preparación, composición
o concentración. Ningún resultado de IA se convierte automáticamente en conocido.

## Estados y autoridad

| Concepto | Qué significa | Qué puede afectar |
| --- | --- | --- |
| Propuesta | Candidato y explicación generados, todavía sin revisión | Sólo la comparación; no aporta al summary |
| Estimación | Valor orientativo de otra composición, con incertidumbre visible | Lectura separada; target continúa unknown |
| Fuente publicada | Dato de una identidad/revisión concreta, unidad y base verificadas | Vector de ese alimento del catálogo, sin trasladarlo automáticamente al personal |
| Declaración del usuario | Afirmación explícita sobre su alimento, cantidad, fuente y unidades | Nueva definición personal revisada mediante servicio oficial; su procedencia no se presenta como publicación del catálogo |
| Consumo confirmado | Elección explícita de identidad, cantidad y revisión | Nuevo snapshot inmutable de MealLog; no modifica consumos anteriores |

`known/unknown/trace/below_limit` son estados de un valor nutricional; por sí solos
no representan este ciclo de revisión. Una estimación no debe introducirse como
`known` con una nota que intente corregir su autoridad después. La IA no crea
declaraciones del usuario ni confirma un consumo.

## Arquitectura propuesta

1. Fachada de lectura detecta ausencias en una definición personal o borrador,
   conservando owner y revisión base. No muta alimento, receta o día histórico.
2. FoodCatalog busca identidades candidatas en revisiones activas. Nombre,
   preparación, marca, porción, estado crudo/cocido, base y densidad se comparan
   explícitamente. Los aliases ayudan a buscar; no demuestran equivalencia.
3. Una capa de propuestas puede ordenar/explicar candidatos con IA. Usa sólo
   evidencias seleccionadas y un contrato separado del vector canónico. Debe
   seguir consentimiento/configuración del proveedor del proyecto antes de
   transmitir información personal. Sin acceso a escritores de dominio.
4. La comparación muestra original, candidato, nutrientes faltantes, cantidades,
   unidades, fuente/revisión y campos incompatibles. La normalización Decimal
   sólo opera cuando bases/unidades son compatibles. No convierte ml a g sin
   densidad ni equipara formas químicas.
5. El usuario descarta, conserva como estimación separada, selecciona realmente
   la identidad publicada para un nuevo borrador, o declara explícitamente una
   nueva definición personal. Seleccionar un candidato no confirma consumo.
6. Una acción confirmable owner-bound valida la revisión base y su hash, genera
   JSON estándar y llama al servicio oficial que corresponda. El último paso
   muestra el cambio concreto y pide confirmación. Ediciones concurrentes
   invalidan la propuesta; repetir una confirmación usa idempotencia existente.

No se propone DDL en A. Los componentes de búsqueda, snapshots, firmas,
revisión optimista e importación confirmada son reutilizables. Antes de B hay que
revisar cómo representar propuestas/estimaciones fuera del vector canónico y
su portabilidad: no se deben añadir silenciosamente campos a los schemas públicos
ni sobrecargar `accepted_json` para conceder autoridad a una estimación.

## Preservación de definiciones e historial

Actualmente `FoodProduct.revision` aumenta, pero `nutrition_json` conserva sólo
la definición actual; `detail` rechaza solicitar una revisión personal anterior.
Los consumos sí conservan las revisiones en snapshots. Por tanto, esos modelos
bastan para A y no demuestran un archivo completo de definiciones personales
anteriores que nunca se consumieron.

La primera opción B sin DDL es crear una definición personal derivada con nueva
identidad mediante el servicio oficial, dejando intacta la original y guardando
su procedencia/revisión base en el contrato que se revise. La UI debe explicar
que se crea otra definición; no simular que es la revisión siguiente de la misma
identidad. También conserva la estimación separada sin promocionarla a dato conocido.

Si B exige editar bajo la misma identidad y recuperar **todas** sus definiciones
anteriores, incluso sin consumo, esta limitación es evidencia concreta de una
necesidad adicional. Se deberá revisar primero contrato y almacenamiento de
revisiones inmutables y su export/restore, antes de proponer una migración. No se
implementa ni decide esa estructura en este PR. No se borrará una definición
previa para hacer sitio a una sugerencia.

## Propuesta UX

Desde una definición personal: acción “Revisar nutrientes ausentes”. Desde un
consumo histórico: lectura de evidencia y opción “Preparar otra comida”; no ofrece
rellenar retroactivamente el snapshot. Un desconocido no se presenta como déficit.

La revisión tiene cuatro pasos:

1. **Identidad**: original y candidatos con preparación/fuente; explicación de
   coincidencias y diferencias. Ninguno se selecciona por defecto.
2. **Base y cantidad**: g/ml/porción, equivalencias explícitas, unidades y formas.
   Incompatibilidades impiden calcular; no se rellenan placeholders.
3. **Evidencia**: tabla original/candidato/estimación. Cada nutriente muestra
   origen y estado. Desconocidos siguen visibles. Acciones separadas “Conservar
   estimación”, “Elegir este alimento publicado” y “Declarar una nueva definición”.
4. **Confirmación**: diff de la nueva definición o del borrador, alcance y revisión.
   “Guardar definición” y “Confirmar consumo” son decisiones diferentes. Rechazo
   o cancelación preservan el original; un cambio de revisión exige volver a revisar.

La estimación tendría un panel independiente y nunca sumaría en las gráficas de
aportación registrada, elevaría cobertura conocida o alimentaría recomendaciones
de Coach como certeza. Las tablas y el texto comunican el estado además del color.

## Gates antes de implementar B

- Contrato revisado de propuesta/estimación y trazabilidad por nutriente, fuera
  del vector de datos conocidos; esquema sólo si se demuestra necesario.
- Conservación comprobada de definiciones anteriores, snapshots, export y restore.
- Pruebas de rechazo, revisión obsoleta, base incompatible, dos owners,
  idempotencia y doble conteo; confirmación explícita antes de cada escritura.
- Revisión UX de una equivalencia plausible pero incorrecta, para demostrar
  que el usuario puede detectar diferencias y rechazarla.

Fuera de B propuesto: reconocimiento fotográfico, inferencia automática de
porciones, recomendaciones personalizadas y diagnóstico de deficiencias.
