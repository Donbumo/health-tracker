# Investigación del protocolo Xiaomi S400

Este documento separa evidencia de hipótesis. No es una especificación de protocolo ni declara soporte funcional.

## Confirmado oficialmente

- El producto objetivo se identifica en la UI únicamente por el modelo elegido por el usuario: **Xiaomi Body Composition Scale S400**.
- Android ofrece APIs estándar para scan BLE, conexión GATT, descubrimiento, `notify`/`indicate` y asociación de companion devices.

No se ha incorporado documentación oficial de Xiaomi sobre UUIDs, frames, unidades, checksums, cifrado, comandos o composición.

## Observado mediante Health Connect

Alpha 1.6 puede observar, con permiso, que existen `WeightRecord` y `BodyFatRecord`, cuántos orígenes intervienen y si el ledger ya los importó. El diagnóstico no muestra valores o identificadores y no demuestra qué dispositivo físico creó un origen.

Sin QA físico todavía no existe observación registrada que vincule un origen concreto con S400.

## Confirmado por usuario

El usuario puede declarar localmente que un fingerprint de origen Health Connect o una asociación BLE corresponde a su S400. Esa elección sirve para procedencia y reconciliación; no demuestra protocolo, autenticidad de hardware ni equivalencia global. Se puede cambiar o revocar.

## Observado mediante captura

Todavía no hay capturas reales en el repositorio. Las fixtures son completamente ficticias y solo prueban parser, límites, replay, estados, repeticiones y variación de bytes.

Cuando exista QA físico, una observación admisible debe registrar localmente:

- captura cifrada y checksum;
- servicio/característica seleccionados desde el snapshot;
- instante relativo;
- valor y unidad vistos en el display como ground truth separado;
- condiciones del ensayo sin identidad personal.

Nunca se debe registrar en Git MAC, nombre completo, manufacturer bytes, paquete completo, timestamp absoluto o valores reales de salud.

## Inferido

- Frames idénticos repetidos pueden indicar estabilidad técnica, pero no necesariamente una medición estable.
- Posiciones variables entre capturas pueden ser offsets candidatos, pero no tienen semántica hasta contrastarlas con varias observaciones controladas.
- Un origen Health Connect confirmado por el usuario puede corresponder a la misma báscula que una futura captura BLE, pero la deduplicación necesita evidencia adicional.

Estas inferencias no habilitan parsing ni escritura de mediciones.

## Desconocido

- UUIDs y características usados por S400.
- Necesidad de emparejamiento, bonding, autenticación o comandos de inicio.
- Delimitación, orden de bytes, unidad, escala, checksum, cifrado y estados de estabilidad.
- Representación de peso, impedancia o cualquier métrica corporal.
- Relación entre la báscula, una aplicación intermedia y `DataOrigin` en Health Connect.
- Cambios por firmware, región, unidad o revisión de hardware.

## Descartado en Alpha 1.6

- Inventar UUIDs, offsets, checksums, comandos o fórmulas.
- Interpretar peso/unidad/impedancia/composición a partir de las fixtures ficticias.
- Derivar una fórmula con una sola observación.
- Guardar una medición BLE real o mostrar **Guardar medición**.
- Declarar composición corporal soportada.
- Escribir hacia Health Connect o enviar capturas al backend.

## Estados del adaptador

`protocol_unknown`, `awaiting_evidence`, `candidate_frame`, `unknown_frame`, `invalid_frame`, `unstable_measurement`, `stable_measurement_unverified`, `verified_weight` y `unsupported_composition` son estados de investigación. El mapper de dominio permanece deshabilitado incluso ante `stable_measurement_unverified`.

## Criterio para habilitar peso

Se requiere una revisión manual con, como mínimo:

1. cinco o más capturas íntegراس;
2. al menos tres pesos distintos;
3. unidades distintas si el dispositivo las admite;
4. repetibilidad entre sesiones;
5. estabilidad técnica consistente;
6. checksum/integridad verificable;
7. coincidencia exacta con cada display registrado;
8. cero colisiones con otros valores/estados;
9. comportamiento comprobado en más de una sesión/dispositivo cuando sea viable;
10. pruebas nuevas que fallen antes del parser y un review humano explícito.

La composición requiere un contrato y evidencia independientes incluso después de habilitar peso.
