# Capacidades companion

`POST /api/v1/companion/negotiate` acepta listas explícitas de versiones, features, métricas y límites. El servidor devuelve aceptadas/rechazadas, límites efectivos, perfil UUID y revisión.

Features 1.0: `offline`, `rest_timer`, `haptics`, `rpe`, `rir`, `weight`, `heart_rate_summary`, `calories_summary`.

Métricas 1.0: `reps`, `weight_kg`, `duration_seconds`, `distance_m`, `rest_seconds`, `rpe`, `rir`, `average_heart_rate_bpm`, `calories_burned`.

El perfil no guarda MAC, IMEI, serial físico, advertising ID, tokens ni secretos. Una actualización exige `base_revision`. Dispositivos revocados no negocian.

Capacidades que permanecen falsas: `watch_bridge`, `bluetooth_bridge`, `continuous_telemetry`, `fit_output`, `vendor_huawei`, `vendor_garmin` y `vendor_magene`.
