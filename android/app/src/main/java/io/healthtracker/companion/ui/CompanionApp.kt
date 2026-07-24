package io.healthtracker.companion.ui

import android.os.Build
import android.content.Intent
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
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
import io.healthtracker.companion.core.load.ComponentInput
import io.healthtracker.companion.core.load.LoadCalculator
import io.healthtracker.companion.core.load.LoadMode
import io.healthtracker.companion.core.model.AuthState
import io.healthtracker.companion.core.model.LoadDetailsDto
import java.math.BigDecimal
import kotlinx.coroutines.delay
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.json.Json

private enum class Destination(val route: String, val label: String, val symbol: String) {
    TODAY("today", "Hoy", "●"), HISTORY("history", "Historial", "◷"), SETTINGS("settings", "Ajustes", "⚙"),
    WORKOUT("workout", "Entrenamiento", "▶")
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
                Text("Android Companion Alpha 1.1", style = MaterialTheme.typography.titleMedium)
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
            if (route != Destination.WORKOUT.route) NavigationBar {
                listOf(Destination.TODAY, Destination.HISTORY, Destination.SETTINGS).forEach { destination ->
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
            composable(Destination.TODAY.route) { TodayScreen(viewModel) { nav.navigate(Destination.WORKOUT.route) } }
            composable(Destination.HISTORY.route) { HistoryScreen(viewModel) }
            composable(Destination.SETTINGS.route) { SettingsScreen(viewModel) }
            composable(Destination.WORKOUT.route) { WorkoutScreen(viewModel) { nav.popBackStack() } }
        }
    }
}

@Composable
private fun TodayScreen(viewModel: CompanionViewModel, openWorkout: () -> Unit) {
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
    val history by viewModel.history.collectAsState()
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
        next?.let { workout -> item {
            Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(16.dp)) {
                Text("Siguiente", style = MaterialTheme.typography.titleMedium)
                Text(workout.title)
                Text(readableDate(workout.scheduledForDate))
            } }
        } }
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
private fun HistoryScreen(viewModel: CompanionViewModel) {
    val history by viewModel.history.collectAsState()
    val connected by viewModel.connected.collectAsState()
    val syncInProgress by viewModel.syncInProgress.collectAsState()
    val pending by viewModel.pendingCount.collectAsState()
    LazyColumn(
        Modifier.fillMaxSize().padding(horizontal = 20.dp).testTag("history_screen"),
        contentPadding = PaddingValues(vertical = 20.dp), verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item { Text("Sesiones recientes", style = MaterialTheme.typography.headlineMedium, modifier = Modifier.semantics { heading() }) }
        item {
            Text(
                if (connected) "Historial guardado localmente y actualizado por sincronización."
                else "Sin conexión: se muestra la copia guardada en este dispositivo.",
            )
            if (pending > 0) Text("Hay cambios pendientes; el historial se actualizará al sincronizar.")
            Button(
                onClick = viewModel::syncNow,
                enabled = connected && !syncInProgress,
                modifier = Modifier.fillMaxWidth().heightIn(min = 50.dp),
            ) { Text(if (syncInProgress) "Actualizando…" else "Actualizar historial") }
        }
        if (history.isEmpty()) item {
            Text(if (syncInProgress) "Buscando sesiones…" else "Aún no hay sesiones recientes guardadas.")
        }
        items(history, key = { it.id }) { session ->
            var expanded by remember { mutableStateOf(false) }
            Card(onClick = { expanded = !expanded }, modifier = Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(session.title, style = MaterialTheme.typography.titleMedium)
                    Text(readableInstant(session.completedAt))
                    Text("${session.exerciseCount} ejercicios · ${session.setCount} series · ${session.totalLoadKg} kg")
                    Text("${session.origin} · ${humanSyncStatus(session.syncStatus)}", style = MaterialTheme.typography.bodySmall)
                    Text(humanDuration(session.durationSeconds), style = MaterialTheme.typography.bodySmall)
                    if (expanded) Text(session.summary.ifBlank { "Sin detalle adicional" })
                }
            }
        }
        item { Text("La app conserva una ventana reciente; no descarga todo el historial.", style = MaterialTheme.typography.bodySmall) }
        item { Spacer(Modifier.height(72.dp)) }
    }
}

@Composable
private fun SettingsScreen(viewModel: CompanionViewModel) {
    val context = LocalContext.current
    val preferences by viewModel.preferences.collectAsState()
    val profile by viewModel.profile.collectAsState()
    val connected by viewModel.connected.collectAsState()
    val pending by viewModel.pendingCount.collectAsState()
    val conflicts by viewModel.conflictCount.collectAsState()
    val syncInProgress by viewModel.syncInProgress.collectAsState()
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
                    val diagnostic = buildString {
                        appendLine("Health Tracker Android ${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})")
                        appendLine("API=1 Sync=1.0 Companion=1.0")
                        appendLine("network=${if (connected) "connected" else "offline"}")
                        appendLine("last_sync=${preferences.lastSyncAt ?: "never"}")
                        appendLine("pending=$pending conflicts=$conflicts")
                    }
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
        item { OutlinedButton(onClick = { confirmation = "logout" }, modifier = Modifier.fillMaxWidth().heightIn(min = 50.dp)) { Text("Cerrar sesión en este teléfono") } }
        item { OutlinedButton(onClick = { confirmation = "logout_all" }, modifier = Modifier.fillMaxWidth().heightIn(min = 50.dp)) { Text("Cerrar todas las sesiones API") } }
        item { OutlinedButton(onClick = { confirmation = "revoke" }, modifier = Modifier.fillMaxWidth().heightIn(min = 50.dp)) { Text("Revocar este dispositivo") } }
        item { TextButton(onClick = { confirmation = "clear" }, modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)) { Text("Borrar solo datos locales") } }
        item { Spacer(Modifier.height(72.dp)) }
    }
    confirmation?.let { action ->
        ConfirmationDialog(
            title = when (action) { "revoke" -> "¿Revocar dispositivo?"; "clear" -> "¿Borrar datos locales?"; "logout_all" -> "¿Cerrar todas las sesiones?"; else -> "¿Cerrar sesión?" },
            text = when (action) {
                "clear" -> "Se borrarán cache, drafts y pendientes de esta cuenta. Esta acción no se puede deshacer."
                "revoke" -> "El servidor revocará sesiones del dispositivo y se borrarán sus datos locales."
                "logout_all" -> "El servidor revocará todas tus sesiones API. Esta operación requiere red."
                else -> "Los drafts y datos locales de esta cuenta se borrarán por privacidad."
            },
            confirm = "Confirmar", onDismiss = { confirmation = null },
            requireAcknowledgement = action in setOf("clear", "revoke", "logout_all"),
            destructive = action in setOf("clear", "revoke", "logout_all"),
            onConfirm = {
                confirmation = null
                when (action) { "revoke" -> viewModel.logout(revoke = true); "clear" -> viewModel.logout(localOnly = true); "logout_all" -> viewModel.logoutAll(); else -> viewModel.logout() }
            },
        )
    }
}

@Composable
private fun SettingsCard(title: String, value: String) {
    Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(16.dp)) {
        Text(title, style = MaterialTheme.typography.titleMedium)
        Text(value)
    } }
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
