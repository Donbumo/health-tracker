package io.healthtracker.companion.ui

import android.os.Build
import android.content.Intent
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import io.healthtracker.companion.BuildConfig
import io.healthtracker.companion.core.config.ThemePreference
import io.healthtracker.companion.core.config.UnitPreference
import io.healthtracker.companion.core.database.DraftSetEntity
import io.healthtracker.companion.core.database.PackageExerciseEntity
import io.healthtracker.companion.core.database.MobilePlanSetEntity
import io.healthtracker.companion.core.load.ComponentInput
import io.healthtracker.companion.core.load.LoadCalculator
import io.healthtracker.companion.core.load.LoadMode
import io.healthtracker.companion.core.healthconnect.HealthConnectRecordType
import io.healthtracker.companion.core.healthconnect.HealthConnectDiagnosticContext
import io.healthtracker.companion.core.healthconnect.sanitizedHealthConnectDiagnostic
import io.healthtracker.companion.core.healthconnect.HealthConnectUiStatus
import io.healthtracker.companion.core.model.AuthState
import io.healthtracker.companion.core.model.LoadDetailsDto
import io.healthtracker.companion.core.planning.planningDateRange
import io.healthtracker.companion.core.planning.planningMonthGrid
import io.healthtracker.companion.core.planning.shiftedPlanningAnchor
import io.healthtracker.companion.core.planning.validPrescription
import java.math.BigDecimal
import java.time.DayOfWeek
import java.time.LocalDate
import java.time.YearMonth
import java.time.format.DateTimeFormatter
import kotlinx.coroutines.delay
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.json.Json

private enum class Destination(val route: String, val label: String, val symbol: String) {
    TODAY("today", "Hoy", "●"), PLAN("plan", "Plan", "+"), HISTORY("history", "Historial", "◷"), PROGRESS("progress", "Progreso", "↗"),
    SETTINGS("settings", "Ajustes", "⚙"), WORKOUT("workout", "Entrenamiento", "▶"),
    PLAN_DETAIL("plan_detail", "Rutina", ""), PLAN_WORKOUT("plan_workout", "Editor", ""),
    HISTORY_DETAIL("history_detail", "Sesión", ""), EXERCISE_DETAIL("exercise_detail", "Ejercicio", ""),
    HEALTH_DAY("health_day", "Salud", ""), BODY_HISTORY("body_history", "Cuerpo", ""),
    NUTRITION_DAY("nutrition_day", "Nutrición", ""), FOOD_CATALOG("food_catalog", "Alimentos", ""),
    STEPS_HISTORY("steps_history", "Pasos", ""), EXTERNAL_SOURCES("external_sources", "Fuentes externas", ""),
    DATA_PRIVACY("data_privacy", "Datos y privacidad", ""), ENGAGEMENT("engagement", "Objetivos y recordatorios", ""),
    MEDICAL_RECORDS("medical_records", "Estudios médicos", ""), MEDICAL_DETAIL("medical_detail", "Estudio médico", ""),
    MEDICAL_HISTORY("medical_history", "Historial de laboratorio", "")
}

@Composable
fun CompanionApp(viewModel: CompanionViewModel) {
    val auth by viewModel.auth.collectAsState()
    val message by viewModel.message.collectAsState()
    val busy by viewModel.busy.collectAsState()
    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(message) {
        message?.let {
            snackbar.showSnackbar(it)
            viewModel.clearMessage()
        }
    }
    Box(Modifier.fillMaxSize()) {
        when (auth) {
            AuthState.AUTHENTICATED -> Home(viewModel, snackbar)
            AuthState.AUTHENTICATING -> LoadingScreen("Restaurando sesión segura…")
            else -> LoginScreen(viewModel, snackbar, auth)
        }
        if (busy) {
            Surface(color = MaterialTheme.colorScheme.scrim.copy(alpha = 0.25f), modifier = Modifier.fillMaxSize()) {
                Box(contentAlignment = Alignment.Center) { CircularProgressIndicator() }
            }
        }
    }
}

@Composable
private fun LoadingScreen(text: String) {
    Box(
        Modifier.fillMaxSize().semantics { liveRegion = LiveRegionMode.Polite; contentDescription = text },
        contentAlignment = Alignment.Center,
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(16.dp)) {
            CircularProgressIndicator(modifier = Modifier.testTag("loading_indicator"))
            Text(text)
        }
    }
}

@Composable
private fun LoginScreen(viewModel: CompanionViewModel, snackbar: SnackbarHostState, auth: AuthState) {
    val preferences by viewModel.preferences.collectAsState()
    var server by remember { mutableStateOf("") }
    var localHttp by remember { mutableStateOf(false) }
    var email by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var deviceName by remember { mutableStateOf(Build.MODEL.take(120)) }
    LaunchedEffect(preferences.serverUrl) {
        if (server.isBlank()) server = preferences.serverUrl.orEmpty()
        if (BuildConfig.ALLOW_LOCAL_HTTP && preferences.allowLocalHttp) localHttp = true
    }
    Scaffold(snackbarHost = { SnackbarHost(snackbar) }) { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(padding).padding(horizontal = 24.dp).imePadding().testTag("login_screen"),
            verticalArrangement = Arrangement.spacedBy(14.dp),
            contentPadding = PaddingValues(vertical = 32.dp),
        ) {
            item {
                Text("Health Tracker", style = MaterialTheme.typography.headlineMedium, modifier = Modifier.semantics { heading() })
                Text("Android Companion ${BuildConfig.VERSION_NAME}", style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(8.dp))
                Text(
                    when (auth) {
                        AuthState.DEVICE_REVOKED -> "Este dispositivo fue revocado. Inicia sesión para registrarlo nuevamente."
                        AuthState.SERVER_INCOMPATIBLE -> "El servidor no ofrece un contrato Android compatible. Revisa su versión."
                        AuthState.TOKEN_EXPIRED -> "La sesión venció. Inicia sesión nuevamente."
                        AuthState.OFFLINE -> "No se pudo alcanzar el servidor. Revisa la red y vuelve a intentar."
                        else -> "Configura tu servidor privado y entra con tu cuenta."
                    },
                )
            }
            item {
                OutlinedTextField(
                    value = server, onValueChange = { server = it }, label = { Text("URL del servidor") },
                    placeholder = { Text("https://tracker.example.local") }, singleLine = true,
                    modifier = Modifier.fillMaxWidth().semantics { contentDescription = "URL base del servidor" },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                )
            }
            if (BuildConfig.ALLOW_LOCAL_HTTP) item {
                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                    Switch(checked = localHttp, onCheckedChange = { localHttp = it })
                    Spacer(Modifier.width(12.dp))
                    Column {
                        Text("Permitir HTTP local en debug")
                        Text("Solo loopback, emulador, RFC1918 o .local", style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
            item {
                OutlinedButton(
                    onClick = { viewModel.testServer(server, localHttp) },
                    modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
                ) { Text("Probar conexión") }
            }
            item {
                OutlinedTextField(
                    value = email, onValueChange = { email = it }, label = { Text("Usuario o email") },
                    singleLine = true, modifier = Modifier.fillMaxWidth(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
                )
            }
            item {
                OutlinedTextField(
                    value = password, onValueChange = { password = it }, label = { Text("Contraseña") },
                    singleLine = true, visualTransformation = PasswordVisualTransformation(),
                    modifier = Modifier.fillMaxWidth(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                )
            }
            item {
                OutlinedTextField(
                    value = deviceName, onValueChange = { deviceName = it.take(120) }, label = { Text("Nombre del dispositivo") },
                    singleLine = true, modifier = Modifier.fillMaxWidth(),
                )
            }
            item {
                Button(
                    onClick = { viewModel.login(server, localHttp, email, password, deviceName) },
                    enabled = server.isNotBlank() && email.isNotBlank() && password.isNotBlank() && deviceName.isNotBlank(),
                    modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp),
                ) { Text("Iniciar sesión", Modifier.testTag("login_button")) }
            }
            item {
                Text(
                    "La contraseña solo se usa para el login. El refresh token se cifra con Android Keystore; no se guarda en Room ni DataStore.",
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }
    }
}

@Composable
private fun Home(viewModel: CompanionViewModel, snackbar: SnackbarHostState) {
    val nav = rememberNavController()
    val entry by nav.currentBackStackEntryAsState()
    val route = entry?.destination?.route ?: Destination.TODAY.route
    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        bottomBar = {
            if (route !in setOf(Destination.WORKOUT.route, Destination.PLAN_DETAIL.route, Destination.PLAN_WORKOUT.route, Destination.HISTORY_DETAIL.route, Destination.EXERCISE_DETAIL.route, Destination.HEALTH_DAY.route, Destination.BODY_HISTORY.route, Destination.NUTRITION_DAY.route, Destination.FOOD_CATALOG.route, Destination.STEPS_HISTORY.route, Destination.EXTERNAL_SOURCES.route, Destination.DATA_PRIVACY.route, Destination.ENGAGEMENT.route, Destination.MEDICAL_RECORDS.route, Destination.MEDICAL_DETAIL.route, Destination.MEDICAL_HISTORY.route)) NavigationBar {
                listOf(Destination.TODAY, Destination.PLAN, Destination.HISTORY, Destination.PROGRESS, Destination.SETTINGS).forEach { destination ->
                    NavigationBarItem(
                        selected = route == destination.route,
                        onClick = { nav.navigate(destination.route) { launchSingleTop = true; popUpTo(Destination.TODAY.route) { saveState = true }; restoreState = true } },
                        icon = { Text(destination.symbol) }, label = { Text(destination.label) },
                    )
                }
            }
        },
    ) { padding ->
        NavHost(navController = nav, startDestination = Destination.TODAY.route, modifier = Modifier.padding(padding)) {
            composable(Destination.TODAY.route) { TodayScreen(
                viewModel,
                openWorkout = { nav.navigate(Destination.WORKOUT.route) },
                openProgress = { nav.navigate(Destination.PROGRESS.route) },
                openHealth = { nav.navigate(Destination.HEALTH_DAY.route) },
                openBody = { nav.navigate(Destination.BODY_HISTORY.route) },
                openNutrition = { nav.navigate(Destination.NUTRITION_DAY.route) },
                openSteps = { nav.navigate(Destination.STEPS_HISTORY.route) },
                openEngagement = { nav.navigate(Destination.ENGAGEMENT.route) },
            ) }
            composable(Destination.PLAN.route) { PlanScreen(viewModel) { id ->
                viewModel.selectPlan(id); nav.navigate(Destination.PLAN_DETAIL.route)
            } }
            composable(Destination.PLAN_DETAIL.route) { PlanDetailScreen(
                viewModel,
                close = { viewModel.selectPlan(null); nav.popBackStack() },
                openWorkout = { id -> viewModel.selectPlanWorkout(id); nav.navigate(Destination.PLAN_WORKOUT.route) },
            ) }
            composable(Destination.PLAN_WORKOUT.route) { PlanWorkoutEditor(
                viewModel,
                close = { viewModel.selectPlanWorkout(null); nav.popBackStack() },
            ) }
            composable(Destination.HISTORY.route) { HistoryScreen(viewModel) { id ->
                viewModel.openHistory(id); nav.navigate(Destination.HISTORY_DETAIL.route)
            } }
            composable(Destination.HISTORY_DETAIL.route) { HistoryDetailScreen(viewModel) {
                viewModel.closeHistory(); nav.popBackStack()
            } }
            composable(Destination.PROGRESS.route) { ProgressScreen(viewModel) { id ->
                viewModel.openProgressExercise(id); nav.navigate(Destination.EXERCISE_DETAIL.route)
            } }
            composable(Destination.EXERCISE_DETAIL.route) { ExerciseDetailScreen(viewModel) {
                viewModel.closeProgressExercise(); nav.popBackStack()
            } }
            composable(Destination.SETTINGS.route) { SettingsScreen(
                viewModel,
                { nav.navigate(Destination.EXTERNAL_SOURCES.route) },
                { nav.navigate(Destination.DATA_PRIVACY.route) },
                { nav.navigate(Destination.ENGAGEMENT.route) },
            ) }
            composable(Destination.WORKOUT.route) { WorkoutScreen(viewModel) { nav.popBackStack() } }
            composable(Destination.HEALTH_DAY.route) { DailyHealthScreen(viewModel, { nav.popBackStack() }, { nav.navigate(Destination.BODY_HISTORY.route) }, { nav.navigate(Destination.NUTRITION_DAY.route) }, { nav.navigate(Destination.STEPS_HISTORY.route) }, { nav.navigate(Destination.MEDICAL_RECORDS.route) }) }
            composable(Destination.BODY_HISTORY.route) { BodyHistoryScreen(viewModel) { nav.popBackStack() } }
            composable(Destination.NUTRITION_DAY.route) { NutritionDayScreen(viewModel, { nav.popBackStack() }, { nav.navigate(Destination.FOOD_CATALOG.route) }) }
            composable(Destination.FOOD_CATALOG.route) { FoodCatalogScreen(viewModel) { nav.popBackStack() } }
            composable(Destination.STEPS_HISTORY.route) { StepsHistoryScreen(viewModel) { nav.popBackStack() } }
            composable(Destination.EXTERNAL_SOURCES.route) { ExternalSourcesScreen(viewModel) { nav.popBackStack() } }
            composable(Destination.DATA_PRIVACY.route) { DataPrivacyScreen(viewModel) { nav.popBackStack() } }
            composable(Destination.ENGAGEMENT.route) { GoalsAndRemindersScreen(viewModel) { nav.popBackStack() } }
            composable(Destination.MEDICAL_RECORDS.route) { MedicalRecordsScreen(viewModel, { nav.popBackStack() }) { id ->
                viewModel.openMedicalStudy(id); nav.navigate(Destination.MEDICAL_DETAIL.route)
            } }
            composable(Destination.MEDICAL_DETAIL.route) { MedicalStudyDetailScreen(viewModel, {
                viewModel.openMedicalStudy(null); nav.popBackStack()
            }) { key ->
                viewModel.selectMedicalHistory(key); nav.navigate(Destination.MEDICAL_HISTORY.route)
            } }
            composable(Destination.MEDICAL_HISTORY.route) { MedicalHistoryScreen(viewModel) { nav.popBackStack() } }
        }
    }
}

@Composable
private fun TodayScreen(
    viewModel: CompanionViewModel,
    openWorkout: () -> Unit,
    openProgress: () -> Unit,
    openHealth: () -> Unit,
    openBody: () -> Unit,
    openNutrition: () -> Unit,
    openSteps: () -> Unit,
    openEngagement: () -> Unit,
) {
    val preferences by viewModel.preferences.collectAsState()
    val profile by viewModel.profile.collectAsState()
    val connected by viewModel.connected.collectAsState()
    val pending by viewModel.pendingCount.collectAsState()
    val conflicts by viewModel.conflictCount.collectAsState()
    val startInProgress by viewModel.startInProgress.collectAsState()
    val downloadInProgress by viewModel.downloadInProgress.collectAsState()
    val syncInProgress by viewModel.syncInProgress.collectAsState()
    val today by viewModel.today.collectAsState()
    val next by viewModel.nextWorkout.collectAsState()
    val draft by viewModel.activeDraft.collectAsState()
    val downloaded by viewModel.downloadedDelivery.collectAsState()
    val todayWorkouts by viewModel.todayWorkouts.collectAsState()
    val downloadedPackages by viewModel.downloadedPackages.collectAsState()
    val history by viewModel.history.collectAsState()
    val weekly by viewModel.weeklyProgress.collectAsState()
    val recentRecord by viewModel.latestPersonalRecord.collectAsState()
    val health by viewModel.dailyHealth.collectAsState()
    val confirmedScaleBodyStatIds by viewModel.confirmedScaleBodyStatIds.collectAsState()
    val healthDate by viewModel.healthDate.collectAsState()
    val operationalToday by viewModel.planningToday.collectAsState()
    val goals by viewModel.goals.collectAsState()
    LaunchedEffect(operationalToday) { viewModel.setHealthDate(operationalToday) }
    LaunchedEffect(healthDate, connected) { if (connected) viewModel.refreshHealth() }
    var showDiscardCorrupt by remember { mutableStateOf(false) }
    LazyColumn(
        modifier = Modifier.fillMaxSize().padding(horizontal = 20.dp).testTag("today_screen"),
        contentPadding = PaddingValues(vertical = 20.dp), verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item {
            Text("Hoy", style = MaterialTheme.typography.headlineMedium, modifier = Modifier.semantics { heading() })
            Text(profile?.email ?: "Cuenta", style = MaterialTheme.typography.bodyMedium)
            Text(preferences.serverUrl ?: "Servidor sin configurar", style = MaterialTheme.typography.bodySmall)
        }
        item {
            Card(Modifier.fillMaxWidth().semantics { liveRegion = LiveRegionMode.Polite }) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(if (connected) "Con conexión" else "Sin red: modo offline", style = MaterialTheme.typography.titleMedium)
                    Text(
                        when {
                            !connected -> "Tus cambios se guardan en este dispositivo"
                            syncInProgress -> "Sincronizando…"
                            conflicts > 0 -> "Requiere atención"
                            pending > 0 -> "Sincronización pendiente"
                            else -> "Sincronizado · ${readableInstant(preferences.lastSyncAt)}"
                        },
                    )
                    Text(if (pending == 1) "1 operación pendiente" else "$pending operaciones pendientes")
                    if (!connected && pending > 0) Text("Tus cambios están guardados y se enviarán al volver la red.")
                    if (conflicts > 0) Text("Conflictos: $conflicts. Conservamos tu copia local; sincroniza y revisa antes de reintentar.", color = MaterialTheme.colorScheme.error)
                }
            }
        }
        item {
            Card(onClick = openEngagement, modifier = Modifier.fillMaxWidth()) {
                Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                    Text("Objetivos activos", style = MaterialTheme.typography.titleMedium)
                    val active = goals.filter { it.state == "active" }.take(3)
                    if (active.isEmpty()) Text("No hay objetivos configurados.")
                    active.forEach { goal -> Text("${goalLabel(goal.goalType)}: ${goal.targetValue} ${goal.unit}") }
                    Text(if (goals.count { it.state == "active" } > 3) "Ver todos" else "Configurar", color = MaterialTheme.colorScheme.primary)
                }
            }
        }
        item {
            Text("Salud de hoy", style = MaterialTheme.typography.titleLarge, modifier = Modifier.semantics { heading() })
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                AssistChip(onClick = openBody, label = { Text("Registrar peso") })
                AssistChip(onClick = openNutrition, label = { Text("Añadir comida") })
                AssistChip(onClick = openSteps, label = { Text("Registrar pasos") })
            }
        }
        item {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Card(onClick = openBody, modifier = Modifier.weight(1f)) {
                    Column(Modifier.padding(12.dp)) {
                        Text("Peso")
                        Text(health?.weightKg?.let { "$it kg" } ?: "—")
                        if (health?.weightSource == "health_connect") Text(
                            if (health?.weightId?.let { it in confirmedScaleBodyStatIds } == true) "Báscula confirmada" else "Health Connect",
                            style = MaterialTheme.typography.labelSmall,
                        )
                        Text(humanHealthStatus(health?.syncStatus), style = MaterialTheme.typography.bodySmall)
                    }
                }
                Card(onClick = openSteps, modifier = Modifier.weight(1f)) {
                    Column(Modifier.padding(12.dp)) {
                        Text("Pasos")
                        Text(health?.steps?.toString() ?: "—")
                        if (health?.stepsSource == "health_connect_aggregate") Text("Health Connect", style = MaterialTheme.typography.labelSmall)
                        Text(humanHealthStatus(health?.syncStatus), style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        }
        item {
            Card(onClick = openNutrition, modifier = Modifier.fillMaxWidth()) {
                Column(Modifier.padding(14.dp)) {
                    Text("Nutrición")
                    Text(health?.caloriesKcal?.let { "$it kcal · P ${health?.proteinG ?: "—"} g · C ${health?.carbohydrateG ?: "—"} g · G ${health?.fatG ?: "—"} g" } ?: "Sin entradas")
                    Text(humanHealthStatus(health?.syncStatus), style = MaterialTheme.typography.bodySmall)
                    TextButton(onClick = openHealth) { Text("Ver salud del día") }
                }
            }
        }
        if (draft != null) item {
            ElevatedCard(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text("Entrenamiento en progreso", style = MaterialTheme.typography.titleLarge)
                    Text("Estado: ${humanDraftStatus(draft?.status.orEmpty())}")
                    if (draft?.status == "corrupt") {
                        Text("El borrador no superó una validación local de integridad. No se enviará.", color = MaterialTheme.colorScheme.error)
                        Text(humanDraftIsolationReason(draft?.corruptReasonCode), style = MaterialTheme.typography.bodySmall)
                        OutlinedButton(
                            onClick = { showDiscardCorrupt = true },
                            modifier = Modifier.fillMaxWidth().heightIn(min = 50.dp),
                        ) { Text("Descartar borrador corrupto") }
                    } else if (draft?.status == "completion_pending" || draft?.status == "aborted_pending") {
                        Text(
                            if (draft?.status == "completion_pending") "Entrenamiento completado"
                            else "Cancelación guardada",
                            style = MaterialTheme.typography.titleMedium,
                        )
                        Text("Pendiente de sincronización")
                        Text("La operación final ya está guardada y no puede editarse mientras espera confirmación.")
                        Button(
                            onClick = viewModel::syncNow,
                            enabled = connected && !syncInProgress,
                            modifier = Modifier.fillMaxWidth().heightIn(min = 50.dp),
                        ) {
                            Text(if (syncInProgress) "Sincronizando…" else "Sincronizar ahora")
                        }
                    } else {
                        Button(onClick = openWorkout, modifier = Modifier.fillMaxWidth().heightIn(min = 50.dp)) { Text("Continuar") }
                    }
                }
            }
        }
        if (draft == null || draft?.deliveryId != downloaded) item {
            ElevatedCard(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text("Entrenamiento de hoy", style = MaterialTheme.typography.titleLarge)
                    if (today == null) {
                        Text("No hay entrenamiento programado para hoy.")
                        Text(if (connected) "Sincroniza para comprobar si hay cambios." else "Puedes seguir usando los datos guardados y sincronizar al recuperar la red.")
                        Button(
                            onClick = viewModel::syncNow,
                            enabled = connected && !syncInProgress,
                            modifier = Modifier.heightIn(min = 48.dp),
                        ) { Text(if (syncInProgress) "Sincronizando…" else "Sincronizar") }
                    } else {
                        Text(today?.title.orEmpty(), style = MaterialTheme.typography.titleMedium)
                        Text("Estado: ${humanWorkoutStatus(today?.status.orEmpty())}")
                        when {
                            downloaded == null -> Button(
                                onClick = viewModel::downloadToday,
                                enabled = connected && !downloadInProgress,
                                modifier = Modifier.fillMaxWidth().heightIn(min = 50.dp).testTag("download_workout"),
                            ) { Text(if (downloadInProgress) "Descargando…" else if (connected) "Descargar para usar offline" else "Descarga requiere conexión") }
                            draft == null -> {
                                Text("Descargado · disponible sin conexión", modifier = Modifier.testTag("offline_available"))
                                Button(
                                    onClick = { viewModel.startToday(openWorkout) },
                                    enabled = !startInProgress,
                                    modifier = Modifier.fillMaxWidth().heightIn(min = 50.dp).testTag("start_workout"),
                                ) { Text(if (startInProgress) "Iniciando…" else "Empezar") }
                            }
                        }
                    }
                }
            }
        }
        items(todayWorkouts.drop(1), key = { it.id }) { scheduled ->
            val packageEntity = downloadedPackages.firstOrNull { it.plannedWorkoutId == scheduled.id }
            val active = packageEntity?.deliveryId == draft?.deliveryId
            ElevatedCard(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(scheduled.title, style = MaterialTheme.typography.titleMedium)
                    Text(
                        humanWorkoutStatus(
                            when {
                                active -> "active"
                                packageEntity != null && scheduled.status == "planned" -> "downloaded"
                                else -> scheduled.status
                            },
                        ),
                    )
                    when {
                        scheduled.status == "completed" -> Unit
                        active -> Button(onClick = openWorkout, modifier = Modifier.fillMaxWidth()) { Text("Continuar") }
                        packageEntity != null -> Button(
                            onClick = { viewModel.startScheduled(scheduled.id, openWorkout) },
                            enabled = !startInProgress,
                            modifier = Modifier.fillMaxWidth(),
                        ) { Text(if (startInProgress) "Iniciando…" else "Empezar") }
                        else -> Button(
                            onClick = { viewModel.downloadScheduled(scheduled.id) },
                            enabled = connected && !downloadInProgress && scheduled.status != "syncing",
                            modifier = Modifier.fillMaxWidth(),
                        ) { Text(if (downloadInProgress) "Descargando…" else "Descargar para usar offline") }
                    }
                }
            }
        }
        next?.let { workout -> item {
            Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(16.dp)) {
                Text("Siguiente", style = MaterialTheme.typography.titleMedium)
                Text(workout.title)
                Text(readableDate(workout.scheduledForDate))
            } }
        } }
        item {
            Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("Progreso reciente", style = MaterialTheme.typography.titleMedium)
                Text("${weekly?.sessions ?: history.count { runCatching { java.time.Instant.parse(it.completedAt).isAfter(java.time.Instant.now().minusSeconds(7 * 86400L)) }.getOrDefault(false) }} sesiones en los últimos 7 días")
                recentRecord?.let { Text("Mejor marca reciente: ${humanRecordType(it.type)} · ${it.value} ${it.unit}") }
                TextButton(onClick = openProgress) { Text("Ver progreso") }
            } }
        }
        history.firstOrNull()?.let { session -> item {
            Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(16.dp)) {
                Text("Última sesión", style = MaterialTheme.typography.titleMedium)
                Text(readableInstant(session.completedAt))
                Text("${session.exerciseCount} ejercicios · ${session.setCount} series")
            } }
        } }
        item { Spacer(Modifier.height(72.dp)) }
    }
    if (showDiscardCorrupt) ConfirmationDialog(
        title = "¿Descartar borrador aislado?",
        text = "Se eliminará únicamente este borrador local y sus operaciones pendientes. No se puede deshacer.",
        confirm = "Descartar",
        onDismiss = { showDiscardCorrupt = false },
        onConfirm = { showDiscardCorrupt = false; viewModel.discardCorruptDraft() },
        requireAcknowledgement = true,
        destructive = true,
    )
}

@Composable
private fun PlanScreen(viewModel: CompanionViewModel, openPlan: (String) -> Unit) {
    val plans by viewModel.plans.collectAsState()
    val planned by viewModel.planned.collectAsState()
    val conflicts by viewModel.planningConflicts.collectAsState()
    val connected by viewModel.connected.collectAsState()
    val refreshing by viewModel.planningRefreshing.collectAsState()
    val activeDraft by viewModel.activeDraft.collectAsState()
    val downloadedPackages by viewModel.downloadedPackages.collectAsState()
    val showArchived by viewModel.showArchivedPlans.collectAsState()
    val planningToday by viewModel.planningToday.collectAsState()
    var tab by rememberSaveable { mutableIntStateOf(0) }
    var newName by rememberSaveable { mutableStateOf("") }
    var showCreate by remember { mutableStateOf(false) }
    val nextScheduled = planned.firstOrNull {
        it.scheduledForDate >= planningToday.toString() &&
            it.status in setOf("planned", "locally_pending", "syncing")
    }
    LaunchedEffect(Unit) { viewModel.refreshPlanning() }
    Column(Modifier.fillMaxSize().testTag("plan_screen")) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 12.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column {
                Text("Plan", style = MaterialTheme.typography.headlineMedium, modifier = Modifier.semantics { heading() })
                Text(if (connected) "Sincronizado con tu servidor" else "Disponible sin conexión", style = MaterialTheme.typography.bodySmall)
            }
            TextButton(onClick = viewModel::refreshPlanning, enabled = connected && !refreshing) {
                Text(if (refreshing) "Actualizando…" else "Actualizar")
            }
        }
        PrimaryTabRow(selectedTabIndex = tab) {
            Tab(selected = tab == 0, onClick = { tab = 0 }, text = { Text("Rutinas") })
            Tab(selected = tab == 1, onClick = { tab = 1 }, text = { Text("Agenda") })
        }
        if (tab == 0) {
            LazyColumn(
                Modifier.fillMaxSize().padding(horizontal = 20.dp),
                contentPadding = PaddingValues(vertical = 16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                if (conflicts.isNotEmpty()) item {
                    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer)) {
                        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text("Cambios que requieren atención", style = MaterialTheme.typography.titleMedium)
                            conflicts.forEach { conflict ->
                                Text("Local: ${conflict.localName ?: conflict.entityType} · revisión ${conflict.localRevision}")
                                Text("Servidor: ${conflict.remoteName ?: "no disponible"}${conflict.serverRevision?.let { " · revisión $it" }.orEmpty()}", style = MaterialTheme.typography.bodySmall)
                                Text(humanPlanningConflict(conflict.changedFields), style = MaterialTheme.typography.bodySmall)
                                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    TextButton(onClick = { viewModel.keepRemoteConflict(conflict.entityId) }) { Text("Usar servidor") }
                                    TextButton(onClick = { viewModel.retryPlanningConflict(conflict.entityId) }) { Text("Reintentar copia local") }
                                    if (conflict.entityType in setOf("plan", "workout")) {
                                        TextButton(onClick = { viewModel.duplicatePlanningConflict(conflict.entityId) }) { Text("Duplicar copia local") }
                                    }
                                    TextButton(onClick = { viewModel.keepRemoteConflict(conflict.entityId) }) { Text("Cancelar cambio local") }
                                }
                            }
                        }
                    }
                }
                item {
                    Button(onClick = { showCreate = true }, modifier = Modifier.fillMaxWidth().heightIn(min = 50.dp)) {
                        Text("Crear rutina")
                    }
                }
                item {
                    FilterChip(
                        selected = showArchived,
                        onClick = { viewModel.showArchivedPlans(!showArchived) },
                        label = { Text(if (showArchived) "Mostrando archivadas" else "Mostrar archivadas") },
                    )
                }
                item {
                    Card(Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(14.dp)) {
                            Text("Próxima programación", style = MaterialTheme.typography.titleMedium)
                            Text(nextScheduled?.let { "${it.scheduledForDate} · ${it.title}" } ?: "Sin entrenamientos próximos")
                        }
                    }
                }
                if (plans.isEmpty()) item {
                    Text("Aún no hay rutinas. Crea una incluso sin conexión; se sincronizará después.")
                }
                items(plans, key = { it.publicId }) { plan ->
                    ElevatedCard(onClick = { openPlan(plan.publicId) }, modifier = Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            Text(plan.name, style = MaterialTheme.typography.titleLarge)
                            plan.description?.let { Text(it, maxLines = 2) }
                            Text("Revisión ${plan.revision} · ${humanPlanningSync(plan.syncStatus)}", style = MaterialTheme.typography.bodySmall)
                        }
                    }
                }
            }
        } else {
            PlanningCalendarAgenda(
                planned,
                activePlannedId = activeDraft?.deliveryId?.let { deliveryId ->
                    downloadedPackages.firstOrNull { it.deliveryId == deliveryId }?.plannedWorkoutId
                },
                downloadedIds = downloadedPackages.mapTo(mutableSetOf()) { it.plannedWorkoutId },
                today = planningToday,
                onCancel = viewModel::cancelScheduledWorkout,
                onReschedule = viewModel::rescheduleWorkout,
            )
        }
    }
    if (showCreate) AlertDialog(
        onDismissRequest = { showCreate = false },
        title = { Text("Nueva rutina") },
        text = {
            OutlinedTextField(
                value = newName,
                onValueChange = { newName = it.take(120) },
                label = { Text("Nombre") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
        },
        confirmButton = {
            Button(onClick = {
                val value = newName.trim()
                showCreate = false
                newName = ""
                viewModel.createPlan(value, onCreated = openPlan)
            }, enabled = newName.isNotBlank()) { Text("Crear") }
        },
        dismissButton = { TextButton(onClick = { showCreate = false }) { Text("Cancelar") } },
    )
}

@Composable
private fun PlanningAgenda(
    planned: List<io.healthtracker.companion.core.database.PlannedWorkoutEntity>,
    activeToday: Boolean,
    downloadedToday: Boolean,
    onCancel: (String) -> Unit,
    onReschedule: (String, LocalDate) -> Unit,
) {
    var monthMode by rememberSaveable { mutableStateOf(false) }
    var anchor by rememberSaveable { mutableStateOf(LocalDate.now().toString()) }
    var rescheduleId by rememberSaveable { mutableStateOf<String?>(null) }
    var rescheduleDate by rememberSaveable { mutableStateOf(LocalDate.now().toString()) }
    val anchorDate = runCatching { LocalDate.parse(anchor) }.getOrDefault(LocalDate.now())
    val range = planningDateRange(anchorDate, monthMode)
    val first = range.start
    val last = range.endInclusive
    val visible = planned.filter { it.scheduledForDate >= first.toString() && it.scheduledForDate <= last.toString() }
        .groupBy { it.scheduledForDate }
    LazyColumn(
        Modifier.fillMaxSize().padding(horizontal = 20.dp).testTag("planning_agenda"),
        contentPadding = PaddingValues(vertical = 16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                OutlinedButton(onClick = { anchor = (if (monthMode) anchorDate.minusMonths(1) else anchorDate.minusWeeks(1)).toString() }) { Text("Anterior") }
                Text(if (monthMode) YearMonth.from(anchorDate).toString() else "${first.format(shortDate)} – ${last.format(shortDate)}")
                OutlinedButton(onClick = { anchor = (if (monthMode) anchorDate.plusMonths(1) else anchorDate.plusWeeks(1)).toString() }) { Text("Siguiente") }
            }
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(selected = !monthMode, onClick = { monthMode = false }, label = { Text("Semana") })
                FilterChip(selected = monthMode, onClick = { monthMode = true }, label = { Text("Mes") })
                TextButton(onClick = { anchor = LocalDate.now().toString() }) { Text("Hoy") }
            }
        }
        items((0L..java.time.temporal.ChronoUnit.DAYS.between(first, last)).map(first::plusDays)) { date ->
            val entries = visible[date.toString()].orEmpty()
            if (!monthMode || entries.isNotEmpty() || date == LocalDate.now()) {
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text(date.format(longDate), style = MaterialTheme.typography.titleMedium)
                        if (entries.isEmpty()) Text("Sin entrenamiento", style = MaterialTheme.typography.bodySmall)
                        entries.forEach { item ->
                            Text(item.title)
                            val today = item.scheduledForDate == LocalDate.now().toString()
                            Text(
                                when {
                                    item.status == "completed" -> "Completado"
                                    today && activeToday -> "Activo"
                                    today && downloadedToday -> "Descargado"
                                    else -> humanWorkoutStatus(item.status)
                                },
                                style = MaterialTheme.typography.bodySmall,
                            )
                            if (item.status in setOf("planned", "pending")) {
                                Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                                    if (item.sourceWorkoutId != null) TextButton(onClick = {
                                        rescheduleId = item.id
                                        rescheduleDate = item.scheduledForDate
                                    }) { Text("Cambiar fecha") }
                                    TextButton(onClick = { onCancel(item.id) }) { Text("Cancelar") }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    if (rescheduleId != null) AlertDialog(
        onDismissRequest = { rescheduleId = null },
        title = { Text("Cambiar fecha") },
        text = { OutlinedTextField(value = rescheduleDate, onValueChange = { rescheduleDate = it.take(10) }, label = { Text("Fecha (AAAA-MM-DD)") }) },
        confirmButton = {
            Button(
                onClick = {
                    val id = rescheduleId ?: return@Button
                    val date = runCatching { LocalDate.parse(rescheduleDate) }.getOrNull() ?: return@Button
                    rescheduleId = null
                    onReschedule(id, date)
                },
                enabled = runCatching { LocalDate.parse(rescheduleDate) }.isSuccess,
            ) { Text("Confirmar") }
        },
        dismissButton = { TextButton(onClick = { rescheduleId = null }) { Text("Volver") } },
    )
}

@Composable
private fun PlanningCalendarAgenda(
    planned: List<io.healthtracker.companion.core.database.PlannedWorkoutEntity>,
    activePlannedId: String?,
    downloadedIds: Set<String>,
    today: LocalDate,
    onCancel: (String) -> Unit,
    onReschedule: (String, LocalDate) -> Unit,
) {
    var monthMode by rememberSaveable { mutableStateOf(false) }
    var anchor by rememberSaveable { mutableStateOf(today.toString()) }
    var selected by rememberSaveable { mutableStateOf(today.toString()) }
    var rescheduleId by rememberSaveable { mutableStateOf<String?>(null) }
    var rescheduleDate by rememberSaveable { mutableStateOf(today.toString()) }
    var cancelId by rememberSaveable { mutableStateOf<String?>(null) }
    val anchorDate = runCatching { LocalDate.parse(anchor) }.getOrDefault(today)
    val selectedDate = runCatching { LocalDate.parse(selected) }.getOrDefault(today)
    val range = planningDateRange(anchorDate, monthMode)
    val displayDates = if (monthMode) planningMonthGrid(anchorDate) else
        (0L..6L).map(range.start::plusDays)
    val byDate = planned.groupBy { it.scheduledForDate }
    val selectedEntries = byDate[selectedDate.toString()].orEmpty()
    val weekday = DateTimeFormatter.ofPattern("EEE")

    LazyColumn(
        Modifier.fillMaxSize().padding(horizontal = 16.dp).testTag("planning_calendar"),
        contentPadding = PaddingValues(vertical = 14.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                OutlinedButton(onClick = {
                    val target = shiftedPlanningAnchor(anchorDate, monthMode, -1)
                    anchor = target.toString()
                    selected = target.toString()
                }) { Text("Anterior") }
                Text(
                    if (monthMode) YearMonth.from(anchorDate).format(DateTimeFormatter.ofPattern("MMMM yyyy"))
                    else "${range.start.format(shortDate)} – ${range.endInclusive.format(shortDate)}",
                    style = MaterialTheme.typography.titleMedium,
                )
                OutlinedButton(onClick = {
                    val target = shiftedPlanningAnchor(anchorDate, monthMode, 1)
                    anchor = target.toString()
                    selected = target.toString()
                }) { Text("Siguiente") }
            }
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(selected = !monthMode, onClick = {
                    monthMode = false
                    anchor = selectedDate.toString()
                }, label = { Text("Semana") })
                FilterChip(selected = monthMode, onClick = {
                    monthMode = true
                    anchor = selectedDate.toString()
                }, label = { Text("Mes") })
                TextButton(onClick = {
                    anchor = today.toString()
                    selected = today.toString()
                }) { Text(if (monthMode) "Mes actual" else "Hoy") }
            }
        }
        if (monthMode) {
            item {
                Row(Modifier.fillMaxWidth()) {
                    listOf("L", "M", "X", "J", "V", "S", "D").forEach { label ->
                        Text(label, Modifier.weight(1f), style = MaterialTheme.typography.labelMedium)
                    }
                }
            }
            items(displayDates.chunked(7)) { week ->
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    week.forEach { date ->
                        val events = byDate[date.toString()].orEmpty()
                        val inMonth = YearMonth.from(date) == YearMonth.from(anchorDate)
                        OutlinedCard(
                            onClick = { selected = date.toString() },
                            modifier = Modifier.weight(1f).heightIn(min = 62.dp),
                            colors = CardDefaults.outlinedCardColors(
                                containerColor = if (date == selectedDate) MaterialTheme.colorScheme.secondaryContainer
                                else MaterialTheme.colorScheme.surface,
                            ),
                        ) {
                            Column(Modifier.padding(6.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                                Text(if (inMonth) date.dayOfMonth.toString() else "·${date.dayOfMonth}")
                                if (events.isNotEmpty()) Text("●".repeat(events.size.coerceAtMost(3)), style = MaterialTheme.typography.labelSmall)
                            }
                        }
                    }
                }
            }
        } else {
            item {
                LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(displayDates) { date ->
                        val events = byDate[date.toString()].orEmpty()
                        FilterChip(
                            selected = date == selectedDate,
                            onClick = { selected = date.toString() },
                            label = {
                                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                    Text(date.format(weekday))
                                    Text(date.dayOfMonth.toString())
                                    if (events.isNotEmpty()) Text("${events.size} evento${if (events.size == 1) "" else "s"}")
                                }
                            },
                        )
                    }
                }
            }
        }
        item {
            Text(selectedDate.format(longDate), style = MaterialTheme.typography.titleLarge)
        }
        if (selectedEntries.isEmpty()) item {
            Card(Modifier.fillMaxWidth()) {
                Text("No hay entrenamientos programados para este día.", Modifier.padding(16.dp))
            }
        }
        items(selectedEntries, key = { it.id }) { item ->
            ElevatedCard(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(item.title, style = MaterialTheme.typography.titleMedium)
                    val visibleStatus = when {
                        item.id == activePlannedId -> "active"
                        item.id in downloadedIds && item.status == "planned" -> "downloaded"
                        else -> item.status
                    }
                    Text(humanWorkoutStatus(visibleStatus), style = MaterialTheme.typography.bodySmall)
                    if (item.status in setOf("planned", "locally_pending", "syncing", "conflict")) {
                        Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                            TextButton(onClick = {
                                rescheduleId = item.id
                                rescheduleDate = item.scheduledForDate
                            }, enabled = item.status != "syncing") { Text("Cambiar fecha") }
                            TextButton(onClick = { cancelId = item.id }, enabled = item.status != "syncing") { Text("Cancelar") }
                        }
                    }
                }
            }
        }
    }
    if (rescheduleId != null) AlertDialog(
        onDismissRequest = { rescheduleId = null },
        title = { Text("Cambiar fecha") },
        text = { OutlinedTextField(value = rescheduleDate, onValueChange = { rescheduleDate = it.take(10) }, label = { Text("Fecha (AAAA-MM-DD)") }) },
        confirmButton = {
            Button(
                onClick = {
                    val id = rescheduleId ?: return@Button
                    val date = runCatching { LocalDate.parse(rescheduleDate) }.getOrNull() ?: return@Button
                    rescheduleId = null
                    selected = date.toString()
                    anchor = date.toString()
                    onReschedule(id, date)
                },
                enabled = runCatching { LocalDate.parse(rescheduleDate) }.isSuccess,
            ) { Text("Cambiar") }
        },
        dismissButton = { TextButton(onClick = { rescheduleId = null }) { Text("Volver") } },
    )
    if (cancelId != null) ConfirmationDialog(
        title = "¿Cancelar programación?",
        text = "Se quitará de la agenda al confirmarse en el servidor. Si aún era solo local, se descartará sin crearla.",
        confirm = "Cancelar programación",
        onDismiss = { cancelId = null },
        onConfirm = { cancelId?.let(onCancel); cancelId = null },
        destructive = true,
    )
}

@Composable
@OptIn(ExperimentalMaterial3Api::class)
private fun PlanDetailScreen(viewModel: CompanionViewModel, close: () -> Unit, openWorkout: (String) -> Unit) {
    val lifecycleOwner = LocalLifecycleOwner.current
    val plan by viewModel.selectedPlan.collectAsState()
    val workouts by viewModel.planWorkouts.collectAsState()
    var name by rememberSaveable(plan?.publicId) { mutableStateOf(plan?.name.orEmpty()) }
    var description by rememberSaveable(plan?.publicId) { mutableStateOf(plan?.description.orEmpty()) }
    var showArchive by remember { mutableStateOf(false) }
    var showCreate by remember { mutableStateOf(false) }
    var workoutName by rememberSaveable { mutableStateOf("") }
    LaunchedEffect(plan?.publicId) { plan?.let { viewModel.refreshPlanning() } }
    LaunchedEffect(name, description) {
        delay(700)
        if (name.isNotBlank()) viewModel.editSelectedPlan(name, description)
    }
    val latestName by rememberUpdatedState(name)
    val latestDescription by rememberUpdatedState(description)
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_STOP && latestName.isNotBlank()) {
                viewModel.flushSelectedPlan(latestName, latestDescription)
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }
    BackHandler {
        if (name.isNotBlank()) viewModel.flushSelectedPlan(name, description, close) else close()
    }
    if (plan == null) { LoadingScreen("Cargando rutina…"); return }
    Scaffold(
        topBar = { TopAppBar(title = { Text("Editar rutina") }, navigationIcon = { TextButton(onClick = {
            if (name.isNotBlank()) viewModel.flushSelectedPlan(name, description, close) else close()
        }) { Text("Atrás") } }) },
    ) { padding ->
        LazyColumn(
            Modifier.fillMaxSize().padding(padding).padding(horizontal = 20.dp).imePadding().testTag("plan_detail"),
            contentPadding = PaddingValues(vertical = 16.dp), verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item {
                OutlinedTextField(value = name, onValueChange = { name = it.take(120) }, label = { Text("Nombre") }, modifier = Modifier.fillMaxWidth())
            }
            item {
                OutlinedTextField(value = description, onValueChange = { description = it.take(2000) }, label = { Text("Descripción") }, modifier = Modifier.fillMaxWidth(), minLines = 2)
                Text("Guardado automático · ${humanPlanningSync(plan?.syncStatus.orEmpty())}", style = MaterialTheme.typography.bodySmall)
            }
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { showCreate = true }, enabled = plan?.status == "active", modifier = Modifier.weight(1f)) { Text("Añadir entrenamiento") }
                    OutlinedButton(onClick = viewModel::duplicateSelectedPlan, modifier = Modifier.weight(1f)) { Text("Duplicar rutina") }
                }
            }
            item {
                OutlinedButton(onClick = { name = plan?.name.orEmpty(); description = plan?.description.orEmpty() }, modifier = Modifier.fillMaxWidth()) {
                    Text("Descartar texto aún no guardado")
                }
            }
            items(workouts, key = { it.publicId }) { workout ->
                ElevatedCard(onClick = { openWorkout(workout.publicId) }, modifier = Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text(workout.name, style = MaterialTheme.typography.titleMedium)
                        Text("${workout.estimatedDurationSeconds?.let { "~${it / 60} min · " }.orEmpty()}${humanPlanningSync(workout.syncStatus)}")
                        Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                            TextButton(onClick = { viewModel.movePlanWorkout(workout.publicId, -1) }, enabled = workout.position > 1) { Text("Subir") }
                            TextButton(onClick = { viewModel.movePlanWorkout(workout.publicId, 1) }, enabled = workout.position < workouts.size) { Text("Bajar") }
                        }
                    }
                }
            }
            item {
                if (plan?.status == "archived") {
                    TextButton(onClick = viewModel::restoreSelectedPlan, modifier = Modifier.fillMaxWidth()) { Text("Restaurar rutina") }
                } else {
                    TextButton(onClick = { showArchive = true }, modifier = Modifier.fillMaxWidth()) { Text("Archivar rutina") }
                }
            }
        }
    }
    if (showCreate) AlertDialog(
        onDismissRequest = { showCreate = false }, title = { Text("Nuevo entrenamiento") },
        text = { OutlinedTextField(value = workoutName, onValueChange = { workoutName = it.take(120) }, label = { Text("Nombre") }) },
        confirmButton = { Button(onClick = { val value = workoutName.trim(); showCreate = false; workoutName = ""; viewModel.createPlanWorkout(value, openWorkout) }, enabled = workoutName.isNotBlank()) { Text("Crear") } },
        dismissButton = { TextButton(onClick = { showCreate = false }) { Text("Cancelar") } },
    )
    if (showArchive) ConfirmationDialog(
        title = "¿Archivar rutina?", text = "Se ocultará de la lista activa. Para proteger la agenda, primero debes cancelar sus programaciones activas.",
        confirm = "Archivar", onDismiss = { showArchive = false }, onConfirm = { showArchive = false; viewModel.archiveSelectedPlan(close) }, destructive = true,
    )
}

@Composable
@OptIn(ExperimentalMaterial3Api::class)
private fun PlanWorkoutEditor(viewModel: CompanionViewModel, close: () -> Unit) {
    val lifecycleOwner = LocalLifecycleOwner.current
    val workout by viewModel.selectedPlanWorkout.collectAsState()
    val exercises by viewModel.planExercises.collectAsState()
    val sets by viewModel.planSets.collectAsState()
    val catalog by viewModel.exerciseCatalog.collectAsState()
    val query by viewModel.catalogQuery.collectAsState()
    var name by rememberSaveable(workout?.publicId) { mutableStateOf(workout?.name.orEmpty()) }
    var notes by rememberSaveable(workout?.publicId) { mutableStateOf(workout?.notes.orEmpty()) }
    var scheduleDate by rememberSaveable { mutableStateOf(LocalDate.now().toString()) }
    var removeId by remember { mutableStateOf<String?>(null) }
    val selectedCatalog = remember { mutableStateListOf<String>() }
    LaunchedEffect(name, notes) {
        delay(700)
        if (name.isNotBlank()) viewModel.saveSelectedPlanWorkout(name, notes)
    }
    val latestName by rememberUpdatedState(name)
    val latestNotes by rememberUpdatedState(notes)
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_STOP && latestName.isNotBlank()) {
                viewModel.flushSelectedPlanWorkout(latestName, latestNotes)
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }
    BackHandler {
        if (name.isNotBlank()) viewModel.flushSelectedPlanWorkout(name, notes, close) else close()
    }
    if (workout == null) { LoadingScreen("Cargando entrenamiento…"); return }
    Scaffold(topBar = {
        TopAppBar(
            title = { Text("Editar entrenamiento") },
            navigationIcon = { TextButton(onClick = {
                if (name.isNotBlank()) viewModel.flushSelectedPlanWorkout(name, notes, close) else close()
            }) { Text("Atrás") } },
            actions = { TextButton(onClick = viewModel::duplicateSelectedPlanWorkout) { Text("Duplicar") } },
        )
    }) { padding ->
        LazyColumn(
            Modifier.fillMaxSize().padding(padding).padding(horizontal = 16.dp).imePadding().testTag("plan_workout_editor"),
            contentPadding = PaddingValues(vertical = 12.dp), verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item {
                OutlinedTextField(value = name, onValueChange = { name = it.take(120) }, label = { Text("Nombre") }, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(value = notes, onValueChange = { notes = it.take(2000) }, label = { Text("Notas") }, modifier = Modifier.fillMaxWidth(), minLines = 2)
                Text("Guardado automático · ${humanPlanningSync(workout?.syncStatus.orEmpty())}", style = MaterialTheme.typography.bodySmall)
                TextButton(onClick = { name = workout?.name.orEmpty(); notes = workout?.notes.orEmpty() }) { Text("Descartar texto aún no guardado") }
            }
            item {
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("Programar", style = MaterialTheme.typography.titleMedium)
                        OutlinedTextField(value = scheduleDate, onValueChange = { scheduleDate = it.take(10) }, label = { Text("Fecha (AAAA-MM-DD)") }, singleLine = true)
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Button(onClick = { runCatching { LocalDate.parse(scheduleDate) }.getOrNull()?.let(viewModel::scheduleSelectedWorkout) }, enabled = runCatching { LocalDate.parse(scheduleDate) }.isSuccess) { Text("Programar") }
                            TextButton(onClick = { scheduleDate = LocalDate.now().toString() }) { Text("Hoy") }
                        }
                    }
                }
            }
            item {
                Text("Añadir ejercicios", style = MaterialTheme.typography.titleLarge)
                OutlinedTextField(
                    value = query, onValueChange = viewModel::searchExercises, label = { Text("Buscar catálogo") },
                    modifier = Modifier.fillMaxWidth(), singleLine = true,
                )
                Button(
                    onClick = {
                        viewModel.addCatalogExercises(catalog.filter { it.publicId in selectedCatalog })
                        selectedCatalog.clear()
                    },
                    enabled = selectedCatalog.isNotEmpty(),
                    modifier = Modifier.fillMaxWidth(),
                ) { Text("Añadir seleccionados (${selectedCatalog.size})") }
            }
            items(catalog, key = { "catalog-${it.publicId}" }) { item ->
                ListItem(
                    headlineContent = { Text(item.name) },
                    supportingContent = { Text(item.aliases.replace("|", " · ").ifBlank { "Sin alias" }) },
                    trailingContent = {
                        val available = item.selectable && exercises.none { it.catalogExerciseId == item.publicId }
                        Checkbox(
                            checked = item.publicId in selectedCatalog,
                            onCheckedChange = { checked -> if (checked) selectedCatalog.add(item.publicId) else selectedCatalog.remove(item.publicId) },
                            enabled = available,
                        )
                    },
                )
            }
            item {
                OutlinedButton(onClick = viewModel::loadMoreExercises, modifier = Modifier.fillMaxWidth()) { Text("Cargar más ejercicios") }
            }
            item { HorizontalDivider(); Text("Ejercicios (${exercises.size})", style = MaterialTheme.typography.titleLarge) }
            items(exercises, key = { it.publicId }) { exercise ->
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(exercise.name, style = MaterialTheme.typography.titleMedium)
                        Row(horizontalArrangement = Arrangement.spacedBy(2.dp)) {
                            TextButton(onClick = { viewModel.movePlanExercise(exercise.publicId, -1) }, enabled = exercise.position > 1) { Text("Subir") }
                            TextButton(onClick = { viewModel.movePlanExercise(exercise.publicId, 1) }, enabled = exercise.position < exercises.size) { Text("Bajar") }
                            TextButton(onClick = { viewModel.duplicatePlanExercise(exercise.publicId) }) { Text("Duplicar") }
                            TextButton(onClick = { removeId = exercise.publicId }) { Text("Quitar") }
                        }
                        sets.filter { it.exercisePublicId == exercise.publicId }.forEach { set ->
                            PlanningSetEditor(set, onSave = viewModel::updatePlanSet, onDelete = { viewModel.deletePlanSet(set.publicId) })
                        }
                        OutlinedButton(onClick = { viewModel.addPlanSet(exercise.publicId) }, modifier = Modifier.fillMaxWidth()) { Text("Añadir serie") }
                    }
                }
            }
        }
    }
    removeId?.let { id ->
        ConfirmationDialog(
            title = "¿Quitar ejercicio?", text = "También se quitarán sus prescripciones de esta rutina.", confirm = "Quitar",
            onDismiss = { removeId = null }, onConfirm = { removeId = null; viewModel.removePlanExercise(id) }, destructive = true,
        )
    }
}

@Composable
private fun PlanningSetEditor(set: MobilePlanSetEntity, onSave: (MobilePlanSetEntity) -> Unit, onDelete: () -> Unit) {
    val lifecycleOwner = LocalLifecycleOwner.current
    var reps by rememberSaveable(set.publicId) { mutableStateOf(set.reps?.toString().orEmpty()) }
    var weight by rememberSaveable(set.publicId) { mutableStateOf(set.loadValue ?: set.weightKg.orEmpty()) }
    var mode by rememberSaveable(set.publicId) { mutableStateOf(set.loadMode) }
    var rir by rememberSaveable(set.publicId) { mutableStateOf(set.rir.orEmpty()) }
    var rpe by rememberSaveable(set.publicId) { mutableStateOf(set.rpe.orEmpty()) }
    var rest by rememberSaveable(set.publicId) { mutableStateOf(set.restSeconds?.toString().orEmpty()) }
    var duration by rememberSaveable(set.publicId) { mutableStateOf(set.durationSeconds?.toString().orEmpty()) }
    var distance by rememberSaveable(set.publicId) { mutableStateOf(set.distanceMeters.orEmpty()) }
    var notes by rememberSaveable(set.publicId) { mutableStateOf(set.notes.orEmpty()) }
    var modeExpanded by remember { mutableStateOf(false) }
    val hasTimedMetric = duration.toIntOrNull()?.let { it in 1..86400 } == true ||
        distance.toBigDecimalOrNull()?.signum()?.let { it > 0 } == true
    val hasRequiredMetric = if (mode == "duration_distance") hasTimedMetric else reps.toIntOrNull()?.let { it > 0 } == true || hasTimedMetric
    val valid = validPrescription(reps, weight, rir, rpe, rest) && hasRequiredMetric
    val draftSet = set.copy(
        reps = reps.toIntOrNull(), loadValue = weight.takeIf(String::isNotBlank),
        weightKg = if (set.loadUnit == "kg") weight.takeIf(String::isNotBlank) else set.weightKg,
        loadMode = mode.trim(), rir = rir.takeIf(String::isNotBlank), rpe = rpe.takeIf(String::isNotBlank), restSeconds = rest.toIntOrNull(),
        durationSeconds = duration.toIntOrNull(), distanceMeters = distance.takeIf(String::isNotBlank), notes = notes.trim().ifBlank { null },
    )
    LaunchedEffect(reps, weight, mode, rir, rpe, rest, duration, distance, notes) {
        delay(700)
        if (valid) onSave(draftSet)
    }
    val latestDraftSet by rememberUpdatedState(draftSet)
    val latestDraftValid by rememberUpdatedState(valid)
    DisposableEffect(lifecycleOwner, set.publicId) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_STOP && latestDraftValid) onSave(latestDraftSet)
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
            if (latestDraftValid) onSave(latestDraftSet)
        }
    }
    Surface(tonalElevation = 2.dp, shape = MaterialTheme.shapes.medium) {
        Column(Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("Serie ${set.setNumber}", style = MaterialTheme.typography.titleSmall)
                TextButton(onClick = onDelete) { Text("Eliminar") }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                OutlinedTextField(value = reps, onValueChange = { reps = it.take(6) }, label = { Text("Reps") }, modifier = Modifier.weight(1f), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number))
                OutlinedTextField(value = weight, onValueChange = { weight = decimalDraft(it) }, label = { Text("Carga ${set.loadUnit}") }, modifier = Modifier.weight(1f), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal))
            }
            Box(Modifier.fillMaxWidth()) {
                OutlinedButton(onClick = { modeExpanded = true }, modifier = Modifier.fillMaxWidth()) {
                    Text("Modo de carga: $mode")
                }
                DropdownMenu(expanded = modeExpanded, onDismissRequest = { modeExpanded = false }) {
                    LoadMode.entries.forEach { option ->
                        DropdownMenuItem(
                            text = { Text(option.wireName) },
                            onClick = { mode = option.wireName; modeExpanded = false },
                        )
                    }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                OutlinedTextField(value = rir, onValueChange = { rir = decimalDraft(it) }, label = { Text("RIR") }, modifier = Modifier.weight(1f))
                OutlinedTextField(value = rpe, onValueChange = { rpe = decimalDraft(it) }, label = { Text("RPE") }, modifier = Modifier.weight(1f))
                OutlinedTextField(value = rest, onValueChange = { rest = it.take(5) }, label = { Text("Descanso s") }, modifier = Modifier.weight(1f))
            }
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                OutlinedTextField(value = duration, onValueChange = { duration = it.take(5) }, label = { Text("Duración s") }, modifier = Modifier.weight(1f), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number))
                OutlinedTextField(value = distance, onValueChange = { distance = decimalDraft(it) }, label = { Text("Distancia m") }, modifier = Modifier.weight(1f), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal))
            }
            OutlinedTextField(value = notes, onValueChange = { notes = it.take(2000) }, label = { Text("Notas de la serie") }, modifier = Modifier.fillMaxWidth())
            Text(if (valid) "Objetivo: ${reps.ifBlank { "libre" }} reps · ${weight.ifBlank { "sin carga" }} ${set.loadUnit}" else "Revisa los valores de la serie.", style = MaterialTheme.typography.bodySmall, color = if (valid) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.error)
        }
    }
}

private val shortDate: DateTimeFormatter = DateTimeFormatter.ofPattern("dd/MM")
private val longDate: DateTimeFormatter = DateTimeFormatter.ofPattern("EEE d MMM")
internal fun humanPlanningSync(value: String) = when (value) {
    "pending" -> "guardado local, pendiente"
    "syncing" -> "sincronizando"
    "conflict" -> "requiere atención"
    else -> "sincronizado"
}

@Composable
@OptIn(ExperimentalMaterial3Api::class)
private fun WorkoutScreen(viewModel: CompanionViewModel, close: () -> Unit) {
    val draft by viewModel.activeDraft.collectAsState()
    val allSets by viewModel.draftSets.collectAsState()
    val exercises by viewModel.workoutExercises.collectAsState()
    val preferences by viewModel.preferences.collectAsState()
    val connected by viewModel.connected.collectAsState()
    val finalActionInProgress by viewModel.finalActionInProgress.collectAsState()
    val setActions by viewModel.setActions.collectAsState()
    val autosaveState by viewModel.autosaveState.collectAsState()
    val lifecycleOwner = LocalLifecycleOwner.current
    val unit = preferences.unit
    var exerciseIndex by rememberSaveable { mutableIntStateOf(0) }
    var restRemaining by rememberSaveable { mutableIntStateOf(0) }
    var showAbort by remember { mutableStateOf(false) }
    var showComplete by remember { mutableStateOf(false) }
    var heartRate by rememberSaveable(draft?.deliveryId, draft?.averageHeartRateBpm) {
        mutableStateOf(draft?.averageHeartRateBpm?.toString().orEmpty())
    }
    var calories by rememberSaveable(draft?.deliveryId, draft?.caloriesBurned) {
        mutableStateOf(draft?.caloriesBurned.orEmpty())
    }
    var sessionNotes by rememberSaveable(draft?.deliveryId, draft?.notes) {
        mutableStateOf(draft?.notes.orEmpty())
    }
    LaunchedEffect(restRemaining) {
        if (restRemaining > 0) { delay(1_000); restRemaining-- }
    }
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_STOP) viewModel.flushAutosaves()
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }
    BackHandler { viewModel.flushAutosaves(close) }
    if (draft?.status == "corrupt") {
        IsolatedDraftScreen(
            reasonCode = draft?.corruptReasonCode,
            onBack = close,
            onDiscard = viewModel::discardCorruptDraft,
        )
        return
    }
    if (draft == null || exercises.isEmpty()) {
        LoadingScreen("Recuperando borrador local…")
        return
    }
    if (draft?.status == "completion_pending" || draft?.status == "aborted_pending") {
        Box(Modifier.fillMaxSize().padding(24.dp), contentAlignment = Alignment.Center) {
            Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("La operación final está pendiente de confirmación; la captura quedó bloqueada.")
                Button(onClick = close, modifier = Modifier.heightIn(min = 48.dp)) { Text("Volver a Hoy") }
            }
        }
        return
    }
    val current = exercises[exerciseIndex.coerceIn(0, exercises.lastIndex)]
    val sets = allSets.filter { it.exerciseOrder == current.exerciseOrder }
    val completed = allSets.count { it.completed }
    val heartRateError = when {
        heartRate.isBlank() -> null
        heartRate.toIntOrNull() == null -> "Usa un número entero."
        heartRate.toInt() !in 20..250 -> "Usa un valor entre 20 y 250."
        else -> null
    }
    val caloriesError = when {
        calories.isBlank() -> null
        calories.toBigDecimalOrNull() == null -> "Usa un número no negativo."
        calories.toBigDecimal().signum() < 0 -> "No puede ser negativo."
        else -> null
    }
    LaunchedEffect(heartRate, calories, sessionNotes, heartRateError, caloriesError) {
        if (heartRateError == null && caloriesError == null) {
            viewModel.queueSummaryAutosave(heartRate.toIntOrNull(), calories, sessionNotes)
        }
    }
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Entrenamiento") },
                navigationIcon = { TextButton(onClick = close) { Text("Atrás") } },
                actions = {
                    TextButton(onClick = { viewModel.pauseResume(draft?.status != "paused") }) {
                        Text(if (draft?.status == "paused") "Continuar" else "Pausar")
                    }
                },
            )
        },
    ) { padding ->
        LazyColumn(
            Modifier.fillMaxSize().padding(padding).padding(horizontal = 16.dp).imePadding().testTag("workout_screen"),
            contentPadding = PaddingValues(vertical = 12.dp), verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item {
                LinearProgressIndicator(
                    progress = { if (allSets.isEmpty()) 0f else completed.toFloat() / allSets.size },
                    modifier = Modifier.fillMaxWidth().height(8.dp),
                )
                Text("$completed de ${allSets.size} series · ejercicio ${exerciseIndex + 1} de ${exercises.size}")
                Text(
                    if (connected) "Los cambios se guardan primero en este dispositivo."
                    else "Modo offline: los cambios quedarán pendientes hasta recuperar la red.",
                    style = MaterialTheme.typography.bodySmall,
                )
                Text(
                    autosaveStatusText(autosaveState),
                    style = MaterialTheme.typography.bodySmall,
                    modifier = Modifier.testTag("autosave_status").semantics { liveRegion = LiveRegionMode.Polite },
                )
                if (restRemaining > 0) Text("Descanso: ${restRemaining}s", style = MaterialTheme.typography.titleLarge)
            }
            item {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    OutlinedButton(
                        onClick = { viewModel.flushAutosaves { exerciseIndex = (exerciseIndex - 1).coerceAtLeast(0) } },
                        enabled = exerciseIndex > 0, modifier = Modifier.heightIn(min = 48.dp),
                    ) { Text("Anterior") }
                    OutlinedButton(
                        onClick = { viewModel.flushAutosaves { exerciseIndex = (exerciseIndex + 1).coerceAtMost(exercises.lastIndex) } },
                        enabled = exerciseIndex < exercises.lastIndex, modifier = Modifier.heightIn(min = 48.dp),
                    ) { Text("Siguiente") }
                }
            }
            item {
                Text(current.name, style = MaterialTheme.typography.headlineSmall)
                current.notes?.let { Text(it) }
            }
            items(sets, key = { "${it.exerciseOrder}-${it.setNumber}" }) { set ->
                SetEditor(
                    value = set,
                    unit = unit,
                    previous = allSets.filter { it.exerciseOrder == set.exerciseOrder && it.setNumber < set.setNumber }.maxByOrNull { it.setNumber },
                    actionInProgress = setActions.any { it.contains(":${set.deliveryId}:${set.exerciseOrder}:${set.setNumber}") },
                    onSave = viewModel::queueSaveLoad,
                    onComplete = { source, reps, rir, rpe, notes, preview, duration, distance, rest ->
                        viewModel.checkpointLoad(source, reps, rir, rpe, notes, preview, duration, distance, rest)
                        restRemaining = rest ?: 0
                    },
                    onFlush = { viewModel.flushAutosaves() },
                    onCopy = viewModel::copyLoad,
                    onDuplicate = viewModel::duplicate,
                )
            }
            item {
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("Resumen opcional", style = MaterialTheme.typography.titleMedium)
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            OutlinedTextField(
                                value = heartRate, onValueChange = { heartRate = it.take(3) },
                                label = { Text("FC media") }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                                modifier = Modifier.weight(1f).onFocusChanged { if (!it.isFocused) viewModel.flushAutosaves() },
                                isError = heartRateError != null,
                                supportingText = heartRateError?.let { message -> { Text(message) } },
                            )
                            OutlinedTextField(
                                value = calories, onValueChange = { calories = decimalDraft(it) },
                                label = { Text("Calorías") }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                                modifier = Modifier.weight(1f).onFocusChanged { if (!it.isFocused) viewModel.flushAutosaves() },
                                isError = caloriesError != null,
                                supportingText = caloriesError?.let { message -> { Text(message) } },
                            )
                        }
                        OutlinedTextField(
                            value = sessionNotes, onValueChange = { sessionNotes = it.take(5000) },
                            label = { Text("Notas de la sesión") },
                            modifier = Modifier.fillMaxWidth().onFocusChanged { if (!it.isFocused) viewModel.flushAutosaves() },
                            minLines = 2,
                        )
                        Text("El resumen también se guarda automáticamente.", style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
            item {
                Button(
                    onClick = { showComplete = true },
                    enabled = completed > 0 && !finalActionInProgress,
                    modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp),
                ) { Text("Completar entrenamiento") }
            }
            item {
                TextButton(
                    onClick = { showAbort = true },
                    enabled = !finalActionInProgress,
                    modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
                ) {
                    Text("Abortar entrenamiento")
                }
            }
            item { Spacer(Modifier.height(24.dp)) }
        }
    }
    if (showComplete) ConfirmationDialog(
        title = "¿Completar entrenamiento?",
        text = "El resultado quedará guardado localmente y se enviará de forma idempotente.",
        confirm = "Completar",
        onDismiss = { showComplete = false },
        onConfirm = { showComplete = false; viewModel.completeWorkout(close) },
    )
    if (showAbort) ConfirmationDialog(
        title = "¿Abortar entrenamiento?", text = "Se conservará la operación hasta que el servidor confirme la cancelación.",
        confirm = "Abortar", onDismiss = { showAbort = false },
        onConfirm = { showAbort = false; viewModel.abortWorkout(close) },
    )
}

@Composable
internal fun IsolatedDraftScreen(
    reasonCode: String?,
    onBack: () -> Unit,
    onDiscard: () -> Unit,
) {
    var showReason by remember { mutableStateOf(false) }
    var confirmDiscard by remember { mutableStateOf(false) }
    Box(
        Modifier.fillMaxSize().padding(24.dp).testTag("isolated_draft_screen"),
        contentAlignment = Alignment.Center,
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Borrador aislado", style = MaterialTheme.typography.headlineSmall, modifier = Modifier.semantics { heading() })
            Text("No se enviará ni descartará automáticamente.")
            if (showReason) {
                Text(
                    humanDraftIsolationReason(reasonCode),
                    modifier = Modifier.testTag("isolated_reason"),
                    color = MaterialTheme.colorScheme.error,
                )
            }
            Button(onClick = onBack, modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)) { Text("Volver a Hoy") }
            OutlinedButton(
                onClick = { showReason = !showReason },
                modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
            ) { Text(if (showReason) "Ocultar motivo" else "Ver motivo sanitizado") }
            TextButton(
                onClick = { confirmDiscard = true },
                modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
            ) { Text("Descartar borrador") }
        }
    }
    if (confirmDiscard) ConfirmationDialog(
        title = "¿Descartar borrador aislado?",
        text = "Se eliminará únicamente este borrador local. No se puede deshacer.",
        confirm = "Descartar",
        onDismiss = { confirmDiscard = false },
        onConfirm = { confirmDiscard = false; onDiscard(); onBack() },
        requireAcknowledgement = true,
        destructive = true,
    )
}

private typealias SaveLoad = (
    DraftSetEntity,
    Int,
    String?,
    String?,
    String?,
    io.healthtracker.companion.core.load.LoadPreview,
    Int?,
    String?,
    Int?,
) -> Unit

@Composable
private fun SetEditor(
    value: DraftSetEntity,
    unit: UnitPreference,
    previous: DraftSetEntity?,
    actionInProgress: Boolean,
    onSave: SaveLoad,
    onComplete: SaveLoad,
    onFlush: () -> Unit,
    onCopy: (DraftSetEntity, DraftSetEntity) -> Unit,
    onDuplicate: (DraftSetEntity) -> Unit,
) {
    val json = remember { Json { ignoreUnknownKeys = true } }
    val existing = remember(value.loadDetailsJson) {
        value.loadDetailsJson?.let { runCatching { json.decodeFromString<LoadDetailsDto>(it) }.getOrNull() }
    }
    var mode by remember(value.deliveryId, value.exerciseOrder, value.setNumber) {
        mutableStateOf(
            initialLoadMode(existing?.loadMode, value.durationSeconds, value.distanceMeters),
        )
    }
    val displayUnit = unit.name.lowercase()
    var menu by remember { mutableStateOf(false) }
    var components by remember(value.loadDetailsJson, mode) {
        mutableStateOf(
            mode.components.associateWith { name ->
                existing?.components?.get(name)?.value ?: when (name) {
                    "direct_total" -> value.weightKg
                    "duration_seconds" -> value.durationSeconds?.toString() ?: "0"
                    "distance_meters" -> value.distanceMeters ?: "0"
                    else -> "0"
                }
            },
        )
    }
    var componentUnits by remember(value.loadDetailsJson, mode, displayUnit) {
        mutableStateOf(
            mode.components.associateWith { name ->
                when (name) {
                    "duration_seconds" -> "s"
                    "distance_meters" -> "m"
                    else -> existing?.components?.get(name)?.unit ?: displayUnit
                }
            },
        )
    }
    var reps by remember(value.reps) { mutableStateOf(value.reps.toString()) }
    var rir by remember(value.rir) { mutableStateOf(value.rir.orEmpty()) }
    var rpe by remember(value.rpe) { mutableStateOf(value.rpe.orEmpty()) }
    var notes by remember(value.notes) { mutableStateOf(value.notes.orEmpty()) }
    var rest by remember(value.restSeconds) { mutableStateOf(value.restSeconds?.toString().orEmpty()) }
    val preview = runCatching {
        LoadCalculator.calculate(
            mode, displayUnit,
            mode.components.associateWith { name ->
                val componentUnit = componentUnits.getValue(name)
                ComponentInput(components.getValue(name).toBigDecimal(), componentUnit)
            },
        )
    }
    val repsNumber = reps.toIntOrNull()
    val durationValue = components["duration_seconds"]?.toBigDecimalOrNull()
    val restNumber = rest.toIntOrNull()
    val repsError = when {
        reps.isBlank() -> "Indica las repeticiones."
        repsNumber == null -> "Usa un número entero."
        repsNumber !in 1..10_000 -> "Debe estar entre 1 y 10 000."
        else -> null
    }
    val rirError = if (rir.isNotBlank() && rir.toBigDecimalOrNull()?.let { it in BigDecimal.ZERO..BigDecimal.TEN } != true) {
        "RIR debe estar entre 0 y 10."
    } else null
    val rpeError = if (rpe.isNotBlank() && rpe.toBigDecimalOrNull()?.let { it in BigDecimal.ONE..BigDecimal.TEN } != true) {
        "RPE debe estar entre 1 y 10."
    } else null
    val durationError = if (durationValue != null && durationValue > BigDecimal("86400")) "La duración máxima es 86 400 s." else null
    val restError = if (rest.isNotBlank() && (restNumber == null || restNumber !in 0..86_400)) {
        "El descanso debe estar entre 0 y 86 400 s."
    } else null
    val validMetrics = repsError == null && rirError == null && rpeError == null && durationError == null && restError == null &&
        (rir.isBlank() || rir.toBigDecimalOrNull()?.let { it >= BigDecimal.ZERO && it <= BigDecimal.TEN } == true) &&
        (rpe.isBlank() || rpe.toBigDecimalOrNull()?.let { it >= BigDecimal.ONE && it <= BigDecimal.TEN } == true) &&
        (durationValue == null || durationValue <= BigDecimal("86400"))
    val duration = durationValue?.toInt()?.takeIf { it > 0 }
    val distance = components["distance_meters"]?.takeIf { it.isNotBlank() }
    LaunchedEffect(mode, components, componentUnits, reps, rir, rpe, notes, rest) {
        preview.getOrNull()?.let { current ->
            repsNumber?.let { validReps ->
                if (validMetrics) onSave(value, validReps, rir, rpe, notes, current, duration, distance, restNumber)
            }
        }
    }
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Text("Serie ${value.setNumber}", style = MaterialTheme.typography.titleMedium)
                if (value.completed) AssistChip(onClick = {}, label = { Text("Completada") })
            }
            Box {
                OutlinedButton(onClick = { menu = true }, modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)) {
                    Text(humanLoadMode(mode))
                }
                DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                    LoadMode.entries.forEach { candidate ->
                        DropdownMenuItem(
                            text = { Text(humanLoadMode(candidate)) },
                            onClick = {
                                mode = candidate
                                components = components + candidate.components.associateWith { components[it] ?: "0" }
                                componentUnits = componentUnits + candidate.components.associateWith {
                                    componentUnits[it] ?: when (it) {
                                        "duration_seconds" -> "s"
                                        "distance_meters" -> "m"
                                        else -> displayUnit
                                    }
                                }
                                menu = false
                            },
                        )
                    }
                }
            }
            mode.components.forEach { name ->
                val componentUnit = componentUnits.getValue(name)
                OutlinedTextField(
                    value = components[name].orEmpty(),
                    onValueChange = { components = components + (name to decimalDraft(it)) },
                    label = { Text("${humanComponent(name)} ($componentUnit)") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth().onFocusChanged { if (!it.isFocused) onFlush() },
                    isError = name == "duration_seconds" && durationError != null,
                    supportingText = if (name == "duration_seconds" && durationError != null) {
                        { Text(durationError) }
                    } else null,
                )
                if (name !in setOf("duration_seconds", "distance_meters")) {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        listOf("kg", "lb").forEach { candidate ->
                            FilterChip(
                                selected = componentUnit == candidate,
                                onClick = { componentUnits = componentUnits + (name to candidate) },
                                label = { Text(candidate) },
                            )
                        }
                    }
                }
            }
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = {
                    val key = mode.components.firstOrNull { it !in setOf("duration_seconds", "distance_meters") } ?: return@OutlinedButton
                    val next = (components[key]?.toBigDecimalOrNull() ?: BigDecimal.ZERO) - BigDecimal("2.5")
                    components = components + (key to next.max(BigDecimal.ZERO).stripTrailingZeros().toPlainString())
                }, modifier = Modifier.heightIn(min = 48.dp)) { Text("−2.5") }
                OutlinedButton(onClick = {
                    val key = mode.components.firstOrNull { it !in setOf("duration_seconds", "distance_meters") } ?: return@OutlinedButton
                    val next = (components[key]?.toBigDecimalOrNull() ?: BigDecimal.ZERO) + BigDecimal("2.5")
                    components = components + (key to next.stripTrailingZeros().toPlainString())
                }, modifier = Modifier.heightIn(min = 48.dp)) { Text("+2.5") }
                previous?.let { OutlinedButton(onClick = { onCopy(it, value) }, modifier = Modifier.heightIn(min = 48.dp)) { Text("Copiar carga") } }
                OutlinedButton(
                    onClick = { onDuplicate(value) },
                    enabled = !actionInProgress,
                    modifier = Modifier.heightIn(min = 48.dp),
                ) { Text("Duplicar") }
            }
            preview.getOrNull()?.let {
                Text("Total: ${it.totalKg.setScale(2, java.math.RoundingMode.HALF_UP)} kg · ${it.totalLb.setScale(2, java.math.RoundingMode.HALF_UP)} lb")
            } ?: Text(preview.exceptionOrNull()?.message ?: "Carga inválida", color = MaterialTheme.colorScheme.error)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                MetricField("Reps", reps, { reps = it.take(5) }, Modifier.weight(1f).onFocusChanged { if (!it.isFocused) onFlush() }, KeyboardType.Number, repsError)
                MetricField("RIR", rir, { rir = decimalDraft(it, 5) }, Modifier.weight(1f).onFocusChanged { if (!it.isFocused) onFlush() }, error = rirError)
                MetricField("RPE", rpe, { rpe = decimalDraft(it, 5) }, Modifier.weight(1f).onFocusChanged { if (!it.isFocused) onFlush() }, error = rpeError)
            }
            MetricField(
                "Descanso (s)", rest, { rest = it.take(5) },
                Modifier.fillMaxWidth().onFocusChanged { if (!it.isFocused) onFlush() },
                KeyboardType.Number, restError,
            )
            OutlinedTextField(
                value = notes, onValueChange = { notes = it.take(2000) }, label = { Text("Notas") },
                modifier = Modifier.fillMaxWidth().onFocusChanged { if (!it.isFocused) onFlush() }, minLines = 2,
            )
            Button(
                onClick = { preview.getOrNull()?.let { calculated -> repsNumber?.let { onComplete(value, it, rir, rpe, notes, calculated, duration, distance, restNumber) } } },
                enabled = preview.isSuccess && validMetrics && !actionInProgress,
                modifier = Modifier.fillMaxWidth().heightIn(min = 50.dp),
            ) { Text(if (actionInProgress) "Guardando…" else if (value.completed) "Actualizar serie" else "Completar serie") }
            value.restSeconds?.let { Text("Descanso planeado: ${it}s", style = MaterialTheme.typography.bodySmall) }
        }
    }
}

@Composable
private fun MetricField(
    label: String,
    value: String,
    onChange: (String) -> Unit,
    modifier: Modifier,
    keyboard: KeyboardType = KeyboardType.Decimal,
    error: String? = null,
) {
    OutlinedTextField(
        value = value, onValueChange = onChange, label = { Text(label) }, singleLine = true,
        keyboardOptions = KeyboardOptions(keyboardType = keyboard), modifier = modifier,
        isError = error != null,
        supportingText = error?.let { message -> { Text(message) } },
    )
}

@Composable
private fun HistoryScreen(viewModel: CompanionViewModel, openDetail: (String) -> Unit) {
    val history by viewModel.history.collectAsState()
    val connected by viewModel.connected.collectAsState()
    val refreshing by viewModel.historyRefreshing.collectAsState()
    val error by viewModel.historyError.collectAsState()
    val pending by viewModel.pendingCount.collectAsState()
    val filters by viewModel.historyFilters.collectAsState()
    val queryState by viewModel.historyQueryState.collectAsState()
    val exercises by viewModel.progressExercises.collectAsState()
    var dateFrom by rememberSaveable(filters.cacheKey) { mutableStateOf(filters.dateFrom.orEmpty()) }
    var dateTo by rememberSaveable(filters.cacheKey) { mutableStateOf(filters.dateTo.orEmpty()) }
    var exerciseId by rememberSaveable(filters.cacheKey) { mutableStateOf(filters.exercisePublicId) }
    LaunchedEffect(Unit) { if (connected) viewModel.refreshHistory() }
    LazyColumn(
        Modifier.fillMaxSize().padding(horizontal = 20.dp).testTag("history_screen"),
        contentPadding = PaddingValues(vertical = 20.dp), verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item { Text("Historial", style = MaterialTheme.typography.headlineMedium, modifier = Modifier.semantics { heading() }) }
        item {
            Text(if (connected) "Room muestra la copia local mientras se actualiza." else "Sin conexión: datos guardados en este dispositivo.")
            if (pending > 0) Text("Hay cambios pendientes; el historial se actualizará al sincronizar.")
            Button(
                onClick = { viewModel.refreshHistory() }, enabled = connected && !refreshing,
                modifier = Modifier.fillMaxWidth().heightIn(min = 50.dp),
            ) { Text(if (refreshing) "Actualizando…" else "Actualizar historial") }
        }
        item {
            Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Filtros", style = MaterialTheme.typography.titleMedium)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(dateFrom, { dateFrom = it.take(10) }, label = { Text("Desde (AAAA-MM-DD)") }, modifier = Modifier.weight(1f), singleLine = true)
                    OutlinedTextField(dateTo, { dateTo = it.take(10) }, label = { Text("Hasta (AAAA-MM-DD)") }, modifier = Modifier.weight(1f), singleLine = true)
                }
                if (exercises.isNotEmpty()) {
                    Text("Ejercicio", style = MaterialTheme.typography.bodySmall)
                    Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        exercises.take(20).forEach { exercise ->
                            FilterChip(selected = exerciseId == exercise.publicId, onClick = { exerciseId = if (exerciseId == exercise.publicId) null else exercise.publicId }, label = { Text(exercise.name) })
                        }
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { viewModel.setHistoryFilters(dateFrom, dateTo, exerciseId) }, enabled = !refreshing) { Text("Aplicar") }
                    TextButton(onClick = { dateFrom = ""; dateTo = ""; exerciseId = null; viewModel.clearHistoryFilters() }) { Text("Limpiar") }
                }
            } }
        }
        error?.let { message -> item { Text("No se pudo actualizar: $message. Se conserva la caché.", color = MaterialTheme.colorScheme.error) } }
        if (history.isEmpty()) item {
            Text(if (refreshing) "Buscando sesiones…" else "No hay sesiones para estos filtros.")
        }
        items(history, key = { it.publicId }) { session ->
            Card(onClick = { openDetail(session.publicId) }, modifier = Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(session.name, style = MaterialTheme.typography.titleMedium)
                    Text(readableInstant(session.completedAt))
                    Text("${session.exerciseCount} ejercicios · ${session.setCount} series")
                    Text(session.volumeKg?.let { "Volumen ${it} kg${if (session.volumePartial) " (parcial)" else ""}" } ?: "Volumen no comparable")
                    Text("${session.source} · ${humanSyncStatus(session.syncStatus)}", style = MaterialTheme.typography.bodySmall)
                    Text(humanDuration(session.durationSeconds), style = MaterialTheme.typography.bodySmall)
                }
            }
        }
        if (queryState?.hasMore == true) item {
            OutlinedButton(onClick = { viewModel.refreshHistory(reset = false) }, enabled = connected && !refreshing, modifier = Modifier.fillMaxWidth()) {
                Text(if (refreshing) "Cargando…" else "Cargar más")
            }
        } else if (history.isNotEmpty()) item { Text("Fin del historial disponible.", style = MaterialTheme.typography.bodySmall) }
        item { Spacer(Modifier.height(72.dp)) }
    }
}

@Composable
private fun HistoryDetailScreen(viewModel: CompanionViewModel, close: () -> Unit) {
    val session by viewModel.selectedHistory.collectAsState()
    val exercises by viewModel.selectedHistoryExercises.collectAsState()
    val sets by viewModel.selectedHistorySets.collectAsState()
    BackHandler(onBack = close)
    LazyColumn(Modifier.fillMaxSize().padding(horizontal = 20.dp), contentPadding = PaddingValues(vertical = 16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { TextButton(onClick = close) { Text("← Historial") } }
        val value = session
        if (value == null) item { Text("Cargando detalle guardado…") } else {
            item {
                Text(value.name, style = MaterialTheme.typography.headlineSmall, modifier = Modifier.semantics { heading() })
                Text(readableInstant(value.completedAt))
                Text(humanDuration(value.durationSeconds))
                Text("${value.source} · ${humanSyncStatus(value.syncStatus)}")
                value.volumeKg?.let { Text("Volumen: $it kg${if (value.volumePartial) " (parcial)" else ""}") }
                value.notes?.let { Text("Notas: $it") }
                value.plannedWorkoutId?.let { Text("Vinculada al entrenamiento planificado") }
            }
            exercises.forEach { exercise ->
                item {
                    Text(exercise.name, style = MaterialTheme.typography.titleLarge)
                    exercise.notes?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                }
                items(sets.filter { it.exerciseOrder == exercise.exerciseOrder }, key = { "${it.exerciseOrder}:${it.setNumber}" }) { set ->
                    Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                        Text("Serie ${set.setNumber}", style = MaterialTheme.typography.titleMedium)
                        Text(set.displayValue?.let { "$it ${set.displayUnit}" } ?: set.weightKg?.let { "$it kg" } ?: "Carga no disponible")
                        Text("${set.reps} reps${set.rir?.let { " · RIR $it" }.orEmpty()}${set.rpe?.let { " · RPE $it" }.orEmpty()}")
                        set.restSeconds?.let { Text("Descanso: $it s") }
                        set.durationSeconds?.let { Text("Duración: $it s") }
                        set.distanceMeters?.let { Text("Distancia: $it m") }
                        Text("Modo: ${set.loadMode}", style = MaterialTheme.typography.bodySmall)
                        set.notes?.let { Text("Notas: $it", style = MaterialTheme.typography.bodySmall) }
                    } }
                }
            }
            if (!value.detailCached) item { Text("El resumen está disponible offline; conecta para descargar el detalle completo.") }
        }
        item { Spacer(Modifier.height(32.dp)) }
    }
}

@Composable
private fun ProgressScreen(viewModel: CompanionViewModel, openExercise: (String) -> Unit) {
    val section by viewModel.progressSection.collectAsState()
    if (section == "health") {
        HealthProgressScreen(viewModel)
        return
    }
    val range by viewModel.progressRange.collectAsState()
    val summary by viewModel.progressSummary.collectAsState()
    val exercises by viewModel.progressExercises.collectAsState()
    val refreshing by viewModel.progressRefreshing.collectAsState()
    val connected by viewModel.connected.collectAsState()
    val error by viewModel.progressError.collectAsState()
    val recentRecord by viewModel.latestPersonalRecord.collectAsState()
    LaunchedEffect(Unit) { if (connected) viewModel.refreshProgress() }
    LazyColumn(Modifier.fillMaxSize().padding(horizontal = 20.dp).testTag("progress_screen"), contentPadding = PaddingValues(vertical = 20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { Text("Progreso", style = MaterialTheme.typography.headlineMedium, modifier = Modifier.semantics { heading() }) }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(selected = true, onClick = {}, label = { Text("Entrenamiento") })
                FilterChip(selected = false, onClick = { viewModel.setProgressSection("health") }, label = { Text("Salud") })
            }
        }
        item {
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf("7", "30", "90", "180", "365", "all").forEach { value ->
                    FilterChip(selected = range == value, onClick = { viewModel.setProgressRange(value) }, label = { Text(if (value == "all") "Todo" else "$value días") })
                }
            }
        }
        item {
            Text(if (connected) "Datos locales con actualización automática." else "Sin conexión: se muestra la última actualización guardada.")
            OutlinedButton(onClick = viewModel::refreshProgress, enabled = connected && !refreshing) { Text(if (refreshing) "Actualizando…" else "Actualizar") }
        }
        item { AdherenceSection(viewModel) }
        error?.let { message -> item { Text("Actualización temporal fallida: $message", color = MaterialTheme.colorScheme.error) } }
        summary?.let { metrics ->
            item {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        ProgressMetricCard("Sesiones", metrics.sessions.toString(), Modifier.weight(1f))
                        ProgressMetricCard("Días", metrics.trainingDays.toString(), Modifier.weight(1f))
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        ProgressMetricCard("Series", metrics.completedSets.toString(), Modifier.weight(1f))
                        ProgressMetricCard("Duración", humanDuration(metrics.durationSeconds), Modifier.weight(1f))
                    }
                    ProgressMetricCard("Volumen", metrics.volumeKg?.let { "$it kg${if (metrics.volumePartial) " · parcial" else ""}" } ?: "No comparable", Modifier.fillMaxWidth())
                    metrics.comparisonJson?.let { Text("Comparación con el periodo anterior disponible; no se muestran porcentajes con base cero.", style = MaterialTheme.typography.bodySmall) }
                }
            }
        } ?: item { Text(if (refreshing) "Calculando resumen…" else "No hay resumen guardado para este periodo.") }
        recentRecord?.let { record -> item {
            Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(14.dp)) {
                Text("Mejor marca reciente", style = MaterialTheme.typography.titleMedium)
                Text("${humanRecordType(record.type)} · ${record.value} ${record.unit}")
                Text(readableDate(record.date), style = MaterialTheme.typography.bodySmall)
            } }
        } }
        item { Text("Ejercicios", style = MaterialTheme.typography.titleLarge) }
        if (exercises.isEmpty()) item { Text("Aún no hay datos suficientes para mostrar ejercicios.") }
        items(exercises, key = { it.publicId }) { exercise ->
            Card(onClick = { openExercise(exercise.publicId) }, modifier = Modifier.fillMaxWidth()) { Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(exercise.name, style = MaterialTheme.typography.titleMedium)
                Text("${exercise.sessionCount} sesiones · ${exercise.setCount} series")
                Text(exercise.bestLoadKg?.let { "Mejor carga: $it kg" } ?: "Carga no comparable")
                Text(exercise.volumeKg?.let { "Volumen: $it kg${if (exercise.volumePartial) " (parcial)" else ""}" } ?: "Volumen no disponible")
                Text(humanTrend(exercise.trend), style = MaterialTheme.typography.bodySmall)
            } }
        }
        item { Spacer(Modifier.height(72.dp)) }
    }
}

@Composable
private fun ProgressMetricCard(label: String, value: String, modifier: Modifier) {
    Card(modifier) { Column(Modifier.padding(14.dp)) { Text(label, style = MaterialTheme.typography.bodySmall); Text(value, style = MaterialTheme.typography.titleLarge) } }
}

@Composable
private fun ExerciseDetailScreen(viewModel: CompanionViewModel, close: () -> Unit) {
    val exercise by viewModel.selectedProgressExercise.collectAsState()
    val points by viewModel.progressPoints.collectAsState()
    val records by viewModel.personalRecords.collectAsState()
    BackHandler(onBack = close)
    LazyColumn(Modifier.fillMaxSize().padding(horizontal = 20.dp), contentPadding = PaddingValues(vertical = 16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { TextButton(onClick = close) { Text("← Progreso") } }
        val value = exercise
        if (value == null) item { Text("Cargando progreso guardado…") } else {
            item {
                Text(value.name, style = MaterialTheme.typography.headlineSmall, modifier = Modifier.semantics { heading() })
                Text(value.lastPerformedAt?.let(::readableInstant) ?: "Sin sesiones en el periodo")
                Text("${value.sessionCount} sesiones · ${value.setCount} series")
                Text(value.bestLoadKg?.let { "Mejor carga: $it kg" } ?: "Mejor carga no comparable")
                value.bestReps?.let { Text("Mejor serie: $it reps${value.bestRepsWeightKg?.let { weight -> " con $weight kg" }.orEmpty()}") }
                Text(value.volumeKg?.let { "Volumen: $it kg${if (value.volumePartial) " (parcial)" else ""}" } ?: "Volumen no disponible")
                Text(humanTrend(value.trend))
            }
            item { TrendChart("Mejor carga por fecha", points, { it.bestLoadKg?.toFloatOrNull() }, "kg") }
            item { TrendChart("Volumen por sesión", points, { it.volumeKg?.toFloatOrNull() }, "kg") }
            if (records.isNotEmpty()) item {
                Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                    Text("Mejores marcas", style = MaterialTheme.typography.titleMedium)
                    records.forEach { Text("${humanRecordType(it.type)}: ${it.value} ${it.unit} · ${readableDate(it.date)}") }
                } }
            }
            item { Text("Últimas sesiones", style = MaterialTheme.typography.titleLarge) }
            items(points.asReversed().take(10), key = { it.sessionPublicId }) { point ->
                Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(12.dp)) {
                    Text(readableInstant(point.performedAt))
                    Text("${point.setCount} series · ${point.volumeKg?.let { "$it kg" } ?: "volumen no comparable"}")
                    Text("RIR ${point.averageRir ?: "—"} · RPE ${point.averageRpe ?: "—"}", style = MaterialTheme.typography.bodySmall)
                } }
            }
        }
        item { Spacer(Modifier.height(32.dp)) }
    }
}

@Composable
private fun TrendChart(
    title: String,
    points: List<io.healthtracker.companion.core.database.ProgressPointEntity>,
    value: (io.healthtracker.companion.core.database.ProgressPointEntity) -> Float?,
    unit: String,
) {
    val plotted = points.mapNotNull { point -> value(point)?.takeIf(Float::isFinite)?.let { point to it } }
    val color = MaterialTheme.colorScheme.primary
    val grid = MaterialTheme.colorScheme.outlineVariant
    Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(title, style = MaterialTheme.typography.titleMedium)
        if (plotted.isEmpty()) Text("Datos insuficientes para esta gráfica.") else {
            val scale = requireNotNull(chartScale(plotted.map { it.second }))
            val minimum = scale.minimum
            val maximum = scale.maximum
            val span = scale.span
            Canvas(Modifier.fillMaxWidth().height(170.dp).semantics { contentDescription = "$title: ${plotted.size} puntos, de $minimum a $maximum $unit" }) {
                drawLine(grid, Offset(0f, size.height), Offset(size.width, size.height), strokeWidth = 2f)
                val coordinates = plotted.mapIndexed { index, item ->
                    val x = if (plotted.size == 1) size.width / 2f else size.width * index / (plotted.size - 1)
                    val y = size.height - ((item.second - minimum) / span) * (size.height - 12f) - 6f
                    Offset(x, y)
                }
                coordinates.zipWithNext().forEach { (start, end) -> drawLine(color, start, end, strokeWidth = 4f) }
                coordinates.forEach { drawCircle(color, radius = 6f, center = it) }
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(readableDate(plotted.first().first.date), style = MaterialTheme.typography.labelSmall)
                Text(readableDate(plotted.last().first.date), style = MaterialTheme.typography.labelSmall)
            }
            Text("Resumen: ${plotted.size} ${if (plotted.size == 1) "punto" else "puntos"}; mínimo $minimum $unit y máximo $maximum $unit.", style = MaterialTheme.typography.bodySmall)
        }
    } }
}

@Composable
private fun SettingsScreen(
    viewModel: CompanionViewModel,
    openExternalSources: () -> Unit,
    openDataPrivacy: () -> Unit,
    openEngagement: () -> Unit,
) {
    val context = LocalContext.current
    val preferences by viewModel.preferences.collectAsState()
    val profile by viewModel.profile.collectAsState()
    val connected by viewModel.connected.collectAsState()
    val pending by viewModel.pendingCount.collectAsState()
    val conflicts by viewModel.conflictCount.collectAsState()
    val syncInProgress by viewModel.syncInProgress.collectAsState()
    val healthConnect by viewModel.healthConnect.collectAsState()
    val permissionContract = remember { viewModel.healthConnectPermissionContract() }
    val permissionLauncher = rememberLauncherForActivityResult(permissionContract) {
        viewModel.onHealthConnectPermissionsResult()
    }
    var confirmation by remember { mutableStateOf<String?>(null) }
    val deviceLabel = preferences.deviceId.take(8).takeIf { it.isNotBlank() }?.let { "$it…" } ?: "Sin identificar"
    LazyColumn(
        Modifier.fillMaxSize().padding(horizontal = 20.dp).testTag("settings_screen"),
        contentPadding = PaddingValues(vertical = 20.dp), verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item { Text("Ajustes", style = MaterialTheme.typography.headlineMedium, modifier = Modifier.semantics { heading() }) }
        item { SettingsCard("Servidor", preferences.serverUrl ?: "Sin configurar") }
        item { SettingsCard("Usuario", profile?.email ?: "Sin sesión") }
        item { SettingsCard("Dispositivo", "Android $deviceLabel · ${if (connected) "con red" else "offline"}") }
        item { SettingsCard("Versión", "App ${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE}) · API 1 · Sync 1.0 · Companion 1.0") }
        item {
            Card(onClick = openEngagement, modifier = Modifier.fillMaxWidth().testTag("open_goals_reminders")) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text("Objetivos y recordatorios", style = MaterialTheme.typography.titleLarge)
                    Text("Objetivos personales, horarios, quiet hours y centro de notificaciones local.")
                    Text("Abrir", color = MaterialTheme.colorScheme.primary)
                }
            }
        }
        item {
            Card(onClick = openExternalSources, modifier = Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text("Fuentes externas", style = MaterialTheme.typography.titleLarge)
                    Text("Diagnóstico de báscula, asociaciones y Bluetooth experimental.")
                    Text("Abrir", color = MaterialTheme.colorScheme.primary)
                }
            }
        }
        item {
            Card(onClick = openDataPrivacy, modifier = Modifier.fillMaxWidth().testTag("open_data_privacy")) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text("Datos y privacidad", style = MaterialTheme.typography.titleLarge)
                    Text("Exportar, verificar e importar paquetes portables.")
                    Text("Abrir", color = MaterialTheme.colorScheme.primary)
                }
            }
        }
        item {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Row(
                        Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text("Health Connect", style = MaterialTheme.typography.titleLarge)
                            Text(humanHealthConnectStatus(healthConnect.status), style = MaterialTheme.typography.bodySmall)
                        }
                        Switch(
                            checked = healthConnect.status !in setOf(
                                HealthConnectUiStatus.AVAILABLE_NOT_CONNECTED,
                                HealthConnectUiStatus.UNAVAILABLE_DEVICE,
                                HealthConnectUiStatus.UNAVAILABLE_PROVIDER,
                                HealthConnectUiStatus.UPDATE_REQUIRED,
                            ),
                            onCheckedChange = { enabled ->
                                if (enabled) viewModel.connectHealthConnect(permissionLauncher::launch)
                                else viewModel.disconnectHealthConnect()
                            },
                            enabled = healthConnect.status !in setOf(
                                HealthConnectUiStatus.UNAVAILABLE_DEVICE,
                                HealthConnectUiStatus.UNAVAILABLE_PROVIDER,
                                HealthConnectUiStatus.UPDATE_REQUIRED,
                            ),
                        )
                    }
                    Text("Importación voluntaria y de solo lectura. Primero se guarda en Room; el servidor puede estar offline.")
                    HealthConnectRecordType.entries.forEach { type ->
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Checkbox(
                                checked = type in healthConnect.selectedTypes,
                                onCheckedChange = { viewModel.setHealthConnectType(type, it) },
                                enabled = type.importSupported,
                            )
                            Column {
                                Text(humanHealthConnectType(type))
                                Text(
                                    when {
                                        !type.importSupported -> "No compatible con la semántica actual; no se solicitará permiso."
                                        type in healthConnect.grantedTypes -> "Lectura concedida"
                                        type in healthConnect.selectedTypes -> "Acceso insuficiente"
                                        else -> "No seleccionado"
                                    },
                                    style = MaterialTheme.typography.bodySmall,
                                )
                            }
                        }
                    }
                    Text("Última importación: ${readableInstant(healthConnect.lastImportAt)}")
                    Text("Importados: ${healthConnect.importedCount} · eliminaciones procesadas: ${healthConnect.deletedCount}")
                    Text(healthConnectNextStep(healthConnect.status), style = MaterialTheme.typography.bodySmall)
                    when (healthConnect.status) {
                        HealthConnectUiStatus.UNAVAILABLE_PROVIDER,
                        HealthConnectUiStatus.UPDATE_REQUIRED -> Button(
                            onClick = { runCatching { context.startActivity(viewModel.healthConnectProviderIntent()) } },
                            modifier = Modifier.fillMaxWidth(),
                        ) { Text("Instalar o actualizar Health Connect") }
                        HealthConnectUiStatus.AVAILABLE_NOT_CONNECTED -> Button(
                            onClick = { viewModel.connectHealthConnect(permissionLauncher::launch) },
                            modifier = Modifier.fillMaxWidth(),
                        ) { Text("Conectar") }
                        else -> Unit
                    }
                    if (healthConnect.status !in setOf(HealthConnectUiStatus.UNAVAILABLE_DEVICE, HealthConnectUiStatus.UNAVAILABLE_PROVIDER)) {
                        OutlinedButton(
                            onClick = { runCatching { context.startActivity(viewModel.healthConnectManageAccessIntent()) } },
                            modifier = Modifier.fillMaxWidth(),
                        ) { Text("Administrar acceso") }
                    }
                    if (healthConnect.backgroundAvailable && !healthConnect.backgroundGranted && healthConnect.status !in setOf(HealthConnectUiStatus.AVAILABLE_NOT_CONNECTED, HealthConnectUiStatus.UNAVAILABLE_DEVICE, HealthConnectUiStatus.UNAVAILABLE_PROVIDER)) {
                        OutlinedButton(
                            onClick = { viewModel.requestHealthConnectBackground(permissionLauncher::launch) },
                            modifier = Modifier.fillMaxWidth(),
                        ) { Text("Permitir importación en segundo plano") }
                    }
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(
                            onClick = viewModel::syncHealthConnectNow,
                            enabled = healthConnect.status in setOf(HealthConnectUiStatus.CONNECTED, HealthConnectUiStatus.PERMISSIONS_PARTIAL, HealthConnectUiStatus.ACCESS_REVOKED, HealthConnectUiStatus.ERROR_RECOVERABLE),
                            modifier = Modifier.weight(1f),
                        ) { Text("Sincronizar ahora") }
                        OutlinedButton(
                            onClick = { viewModel.pauseHealthConnect(healthConnect.status != HealthConnectUiStatus.PAUSED) },
                            enabled = healthConnect.status !in setOf(HealthConnectUiStatus.AVAILABLE_NOT_CONNECTED, HealthConnectUiStatus.UNAVAILABLE_DEVICE, HealthConnectUiStatus.UNAVAILABLE_PROVIDER, HealthConnectUiStatus.UPDATE_REQUIRED),
                            modifier = Modifier.weight(1f),
                        ) { Text(if (healthConnect.status == HealthConnectUiStatus.PAUSED) "Reanudar" else "Pausar") }
                    }
                    TextButton(onClick = viewModel::disconnectHealthConnect, modifier = Modifier.fillMaxWidth()) {
                        Text("Desconectar sin borrar datos")
                    }
                    TextButton(onClick = { confirmation = "delete_health_connect" }, modifier = Modifier.fillMaxWidth()) {
                        Text("Borrar solo datos importados")
                    }
                }
            }
        }
        item {
            Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Unidad preferida", style = MaterialTheme.typography.titleMedium)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    FilterChip(selected = preferences.unit == UnitPreference.KG, onClick = { viewModel.setUnit(UnitPreference.KG) }, label = { Text("kg") })
                    FilterChip(selected = preferences.unit == UnitPreference.LB, onClick = { viewModel.setUnit(UnitPreference.LB) }, label = { Text("lb") })
                }
                Text("Tema", style = MaterialTheme.typography.titleMedium)
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    ThemePreference.entries.forEach { theme ->
                        FilterChip(selected = preferences.theme == theme, onClick = { viewModel.setTheme(theme) }, label = { Text(humanTheme(theme)) })
                    }
                }
            } }
        }
        item {
            Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text("Diagnóstico sanitizado", style = MaterialTheme.typography.titleMedium)
                Text("App ${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})")
                Text("API 1 · Sync 1.0 · Companion 1.0")
                Text("Última sincronización: ${readableInstant(preferences.lastSyncAt)}")
                Text("Pendientes: $pending")
                Text("Conflictos: $conflicts")
                Text("No incluye tokens, headers, hashes, notas ni payloads.", style = MaterialTheme.typography.bodySmall)
            } }
        }
        item {
            Button(
                onClick = viewModel::syncNow,
                enabled = connected && !syncInProgress,
                modifier = Modifier.fillMaxWidth().heightIn(min = 50.dp),
            ) { Text(if (syncInProgress) "Sincronizando…" else if (connected) "Sincronizar ahora" else "Sincronización sin conexión") }
        }
        item {
            OutlinedButton(
                onClick = {
                    val diagnostic = sanitizedHealthConnectDiagnostic(
                        HealthConnectDiagnosticContext(
                            BuildConfig.VERSION_NAME,
                            BuildConfig.VERSION_CODE,
                            Build.VERSION.RELEASE,
                            Build.VERSION.SDK_INT,
                        ),
                        healthConnect,
                    )
                    context.startActivity(
                        Intent.createChooser(
                            Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, diagnostic),
                            "Compartir diagnóstico sanitizado",
                        ),
                    )
                },
                modifier = Modifier.fillMaxWidth().heightIn(min = 50.dp),
            ) { Text("Compartir diagnóstico sanitizado") }
        }
        item {
            Text("Sesiones y datos locales", style = MaterialTheme.typography.titleLarge)
            Text("Cerrar sesión elimina esta cuenta del teléfono. Cerrar todas revoca todas las sesiones API. Revocar bloquea este dispositivo. Borrar local no cambia el servidor.")
        }
        item { OutlinedButton(onClick = { confirmation = "switch_server" }, modifier = Modifier.fillMaxWidth().heightIn(min = 50.dp)) { Text("Cambiar servidor") } }
        item { OutlinedButton(onClick = { confirmation = "logout" }, modifier = Modifier.fillMaxWidth().heightIn(min = 50.dp)) { Text("Cerrar sesión en este teléfono") } }
        item { OutlinedButton(onClick = { confirmation = "logout_all" }, modifier = Modifier.fillMaxWidth().heightIn(min = 50.dp)) { Text("Cerrar todas las sesiones API") } }
        item { OutlinedButton(onClick = { confirmation = "revoke" }, modifier = Modifier.fillMaxWidth().heightIn(min = 50.dp)) { Text("Revocar este dispositivo") } }
        item { TextButton(onClick = { confirmation = "clear" }, modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)) { Text("Borrar solo datos locales") } }
        item { Spacer(Modifier.height(72.dp)) }
    }
    confirmation?.let { action ->
        if (action == "delete_health_connect") {
            ConfirmationDialog(
                title = "¿Borrar datos importados?",
                text = "Se borrarán solo recursos vinculados a Health Connect y se encolarán sus eliminaciones. Los datos manuales y las copias editadas se conservarán.",
                confirm = "Borrar importados",
                onDismiss = { confirmation = null },
                onConfirm = { confirmation = null; viewModel.deleteHealthConnectImportedData() },
                requireAcknowledgement = true,
                destructive = true,
            )
            return@let
        }
        ConfirmationDialog(
            title = when (action) { "switch_server" -> "¿Cambiar de servidor?"; "revoke" -> "¿Revocar dispositivo?"; "clear" -> "¿Borrar datos locales?"; "logout_all" -> "¿Cerrar todas las sesiones?"; else -> "¿Cerrar sesión?" },
            text = when (action) {
                "switch_server" -> "Se cerrará la sesión activa y se invalidarán sus tokens locales. Los datos Room se conservarán bajo su servidor y cuenta actuales; después deberás confirmar la nueva URL e iniciar sesión."
                "clear" -> "Se borrarán cache, drafts y pendientes de esta cuenta. Esta acción no se puede deshacer."
                "revoke" -> "El servidor revocará sesiones del dispositivo y se borrarán sus datos locales."
                "logout_all" -> "El servidor revocará todas tus sesiones API. Esta operación requiere red."
                else -> "Los drafts y datos locales de esta cuenta se borrarán por privacidad."
            },
            confirm = "Confirmar", onDismiss = { confirmation = null },
            requireAcknowledgement = action in setOf("switch_server", "clear", "revoke", "logout_all"),
            destructive = action in setOf("clear", "revoke", "logout_all"),
            onConfirm = {
                confirmation = null
                when (action) { "switch_server" -> viewModel.switchServer(); "revoke" -> viewModel.logout(revoke = true); "clear" -> viewModel.logout(localOnly = true); "logout_all" -> viewModel.logoutAll(); else -> viewModel.logout() }
            },
        )
    }
}

private fun humanHealthConnectStatus(value: HealthConnectUiStatus) = when (value) {
    HealthConnectUiStatus.UNAVAILABLE_DEVICE -> "No disponible"
    HealthConnectUiStatus.UNAVAILABLE_PROVIDER -> "Requiere instalación"
    HealthConnectUiStatus.UPDATE_REQUIRED -> "Requiere instalación o actualización"
    HealthConnectUiStatus.AVAILABLE_NOT_CONNECTED -> "Sin conectar"
    HealthConnectUiStatus.PERMISSIONS_PARTIAL -> "Permisos parciales"
    HealthConnectUiStatus.ACCESS_REVOKED -> "Acceso revocado"
    HealthConnectUiStatus.CONNECTED -> "Actualizado"
    HealthConnectUiStatus.SYNCING -> "Importando"
    HealthConnectUiStatus.PAUSED -> "Pausado"
    HealthConnectUiStatus.ERROR_RECOVERABLE -> "Error temporal"
}

private fun humanHealthConnectType(value: HealthConnectRecordType) = when (value) {
    HealthConnectRecordType.WEIGHT -> "Peso"
    HealthConnectRecordType.BODY_FAT -> "Grasa corporal"
    HealthConnectRecordType.LEAN_BODY_MASS -> "Masa magra"
    HealthConnectRecordType.BODY_WATER_MASS -> "Agua corporal"
    HealthConnectRecordType.STEPS -> "Pasos"
    HealthConnectRecordType.NUTRITION -> "Nutrición (opcional)"
}

private fun healthConnectNextStep(value: HealthConnectUiStatus) = when (value) {
    HealthConnectUiStatus.PERMISSIONS_PARTIAL -> "Próximo paso: concede solo los tipos que quieras desde Administrar acceso."
    HealthConnectUiStatus.ACCESS_REVOKED -> "Próximo paso: administra el acceso; los datos ya importados permanecen."
    HealthConnectUiStatus.SYNCING -> "Próximo paso: los datos aparecerán desde Room sin bloquear esta pantalla."
    HealthConnectUiStatus.PAUSED -> "Próximo paso: reanuda cuando quieras; lo ya importado permanece."
    HealthConnectUiStatus.ERROR_RECOVERABLE -> "Próximo paso: vuelve a intentar; no se ha descartado la importación local."
    HealthConnectUiStatus.CONNECTED -> "Próximo paso: se importarán cambios y eliminaciones de forma incremental."
    else -> "Puedes conectar la integración cuando quieras."
}

@Composable
private fun SettingsCard(title: String, value: String) {
    Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(16.dp)) {
        Text(title, style = MaterialTheme.typography.titleMedium)
        Text(value)
    } }
}

private fun humanHealthStatus(value: String?) = when (value) {
    "pending" -> "Pendiente"
    "syncing" -> "Sincronizando"
    "attention", "conflict" -> "Requiere atención"
    "synced" -> "Sincronizado"
    else -> "Guardado localmente"
}

@Composable
private fun ConfirmationDialog(
    title: String,
    text: String,
    confirm: String,
    onDismiss: () -> Unit,
    onConfirm: () -> Unit,
    requireAcknowledgement: Boolean = false,
    destructive: Boolean = false,
) {
    var acknowledged by remember(title) { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text(text)
                if (requireAcknowledgement) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(checked = acknowledged, onCheckedChange = { acknowledged = it })
                        Text("Entiendo el alcance de esta acción")
                    }
                }
            }
        },
        confirmButton = {
            Button(
                onClick = onConfirm,
                enabled = !requireAcknowledgement || acknowledged,
                colors = if (destructive) ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error) else ButtonDefaults.buttonColors(),
            ) { Text(confirm) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancelar") } },
    )
}
