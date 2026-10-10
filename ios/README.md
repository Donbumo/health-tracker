# Health Tracker iOS Companion

Cliente iOS nativo (SwiftUI, iOS 17+) equivalente al companion Android de `android/`. Reutiliza `/api/v1`; no contiene un backend alternativo. Se entrega por etapas: **Etapa 1** fundación (auth, API, Keychain), **Etapa 2** sync offline (SwiftData, bootstrap/pull, cola FIFO, sync en segundo plano) **Etapa 3** historial, rutinas en lectura y progreso (caché offline, Swift Charts) **Etapa 4** sesión de entrenamiento en vivo (package verificado, borrador offline con autosave, cola companion) y **Etapa 5** editor de rutinas, catálogo y agenda offline con resolución de conflictos.

## Stack

- Xcode 16.4+, Swift 6 (concurrencia estricta), iOS 17 mínimo.
- Proyecto generado con [XcodeGen](https://github.com/yonaskolb/XcodeGen) desde `project.yml` (el `.xcodeproj` no se versiona).
- `HealthTrackerKit/`: paquete Swift con toda la lógica sin UI (red, sesión, validación, seguridad). Testeable en macOS y simulador.
- `HealthTracker/`: app SwiftUI. `HealthTrackerUITests/`: smoke test end-to-end opcional.

| Android | iOS |
| --- | --- |
| DataStore | `PreferenceStore` (UserDefaults) |
| SecureTokenStore (Keystore) | `TokenStore` (Keychain, `AfterFirstUnlockThisDeviceOnly`) |
| OkHttp | `APIClient` (actor) + `URLSessionTransport` |
| ConnectivityObserver | `ConnectivityMonitor` (NWPathMonitor) |
| Room | `LocalStore` (SwiftData, `@ModelActor`) |
| WorkManager / SyncWorker | `SyncCoordinator` (BGAppRefreshTask + disparadores en primer plano) |
| `processPending` / `synchronize` | `SyncEngine` (cola FIFO estricta, backoff, conflictos, pull paginado) |
| `refreshHistory` / `refreshProgress` / `refreshPlans` | `TrainingRepository` + `LocalStore+Training` |
| `UiFormatters.kt` | `DisplayText` |
| `LoadCalculator` | `LoadCalculator` (aritmética idéntica al `Decimal` de Python del backend) |
| `downloadWorkout` / `startWorkout` / `completeWorkout` | `WorkoutRepository` + `LocalStore+Workout` |
| `processPending` `companion_*` | `CompanionHandlers` |
| `DebouncedAutosave` | `DebouncedAutosave` (actor) |
| `PlanningRules.kt` | `PlanningRules` |
| `createPlanOffline` … `rescheduleWorkoutOffline` | `PlanningRepository` + `LocalStore+Planning` |
| `processPending` `planning_*` | `PlanningHandlers` |

## Construcción

```sh
brew install xcodegen
cd ios
xcodegen generate
open HealthTracker.xcodeproj
```

Tests del paquete (macOS o simulador):

```sh
cd ios/HealthTrackerKit && swift test
xcodebuild -scheme HealthTrackerKit -destination 'platform=iOS Simulator,name=iPhone 16 Pro' test
```

Smoke test UI contra un backend local con usuario QA ficticio (se omite si no hay variables; `QA_EXPECTED_SESSION` y `QA_EXPECTED_EXERCISE` activan la prueba de Plan, Historial y Progreso, `QA_EXPECTED_TODAY_WORKOUT` la captura completa de un entrenamiento programado para hoy y `QA_EXPECTED_CATALOG_EXERCISE` el editor de rutinas con un ejercicio del catálogo):

```sh
TEST_RUNNER_QA_SERVER_URL=http://127.0.0.1:5000 TEST_RUNNER_QA_USERNAME=<usuario-qa> TEST_RUNNER_QA_PASSWORD=<password-qa> \
  xcodebuild -project HealthTracker.xcodeproj -scheme HealthTracker -destination 'platform=iOS Simulator,name=iPhone 16 Pro' test
```

## Seguridad

- HTTPS por defecto. HTTP solo en builds Debug, con confirmación explícita y hosts locales (loopback, RFC1918, `.local`); ATS usa `NSAllowsLocalNetworking`.
- El access token vive solo en memoria; el refresh token en el Keychain ligado a la URL del servidor. Una instalación nueva borra tokens heredados del Keychain.
- Sin redirecciones, respuestas limitadas a 4 MiB, errores saneados (sin hosts ni detalles TLS).
- Firma: define `DEVELOPMENT_TEAM` en `project.yml` (o en Xcode) para instalar en un iPhone físico. El simulador no la requiere.
