package io.healthtracker.companion.ui

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import io.healthtracker.companion.core.database.GoalEntity
import io.healthtracker.companion.core.database.ReminderEventEntity
import io.healthtracker.companion.core.database.ReminderRuleEntity
import io.healthtracker.companion.core.notifications.ReminderPermissionPolicy
import io.healthtracker.companion.core.notifications.ReminderPermissionSnapshot
import io.healthtracker.companion.core.notifications.ReminderPermissionController
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

@Composable
fun GoalsAndRemindersScreen(viewModel: CompanionViewModel, onBack: () -> Unit) {
    val context = LocalContext.current
    val goals by viewModel.goals.collectAsState()
    val rules by viewModel.reminderRules.collectAsState()
    val events by viewModel.reminderEvents.collectAsState()
    val permission by viewModel.reminderPermission.collectAsState()
    var pendingActivation by remember { mutableStateOf<ReminderRuleEntity?>(null) }
    var explainPermission by remember { mutableStateOf(false) }
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        viewModel.recordNotificationPermission(true, true, granted)
        pendingActivation?.let { viewModel.setReminderEnabled(it, true) }
        pendingActivation = null
    }
    if (explainPermission) AlertDialog(
        onDismissRequest = { explainPermission = false; pendingActivation = null },
        title = { Text("Avisos locales opcionales") },
        text = { Text("Android necesita permiso para mostrar los recordatorios que actives. La configuración seguirá guardada aunque lo deniegues; no se solicita durante el inicio de sesión.") },
        confirmButton = { TextButton(onClick = { explainPermission = false; launcher.launch(Manifest.permission.POST_NOTIFICATIONS) }) { Text("Continuar") } },
        dismissButton = { TextButton(onClick = { explainPermission = false; pendingActivation = null }) { Text("Ahora no") } },
    )
    LazyColumn(
        Modifier.fillMaxSize().padding(horizontal = 20.dp).testTag("goals_reminders_screen"),
        contentPadding = PaddingValues(vertical = 18.dp), verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item { TextButton(onClick = onBack) { Text("← Ajustes") } }
        item { Text("Objetivos y recordatorios", style = MaterialTheme.typography.headlineMedium, modifier = Modifier.semantics { heading() }) }
        item { Text("Todo se guarda primero en este dispositivo. Los objetivos son personales y descriptivos; no son indicaciones médicas.") }
        item {
            Text("Objetivos", style = MaterialTheme.typography.titleLarge)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = viewModel::createWeeklySessionsGoal) { Text("3 sesiones/semana") }
                OutlinedButton(onClick = viewModel::createDailyStepsGoal) { Text("5,000 pasos/día") }
            }
        }
        if (goals.isEmpty()) item { Text("No hay objetivos configurados.") }
        items(goals, key = { "goal-${it.serverIdentity}-${it.publicId}" }) { goal -> GoalCard(goal, viewModel) }
        item {
            Text("Recordatorios", style = MaterialTheme.typography.titleLarge)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = viewModel::createTrainingReminder) { Text("Entrenamiento") }
                OutlinedButton(onClick = viewModel::createWeightReminder) { Text("Registro de peso") }
            }
        }
        if (rules.isEmpty()) item { Text("No hay reglas configuradas.") }
        items(rules, key = { "rule-${it.serverIdentity}-${it.publicId}" }) { rule ->
            RuleCard(rule, onToggle = { enabled ->
                if (!enabled) viewModel.setReminderEnabled(rule, false)
                else {
                    val snapshot = permission?.let { ReminderPermissionSnapshot(it.requested, it.granted) }
                    if (ReminderPermissionController.isGranted(context) || !ReminderPermissionPolicy.shouldRequestOnActivation(Build.VERSION.SDK_INT, true, snapshot)) {
                        viewModel.setReminderEnabled(rule, true)
                    } else { pendingActivation = rule; explainPermission = true }
                }
            }, onSave = { time, start, end -> viewModel.updateReminderSchedule(rule, time, start, end) }, onDelete = { viewModel.deleteReminder(rule) })
        }
        item {
            Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Permiso y canales Android", style = MaterialTheme.typography.titleMedium)
                Text(if (ReminderPermissionController.isGranted(context)) "Notificaciones permitidas." else "Notificaciones no permitidas; las reglas permanecen guardadas sin romper la app.")
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { context.startActivity(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)) }) { Text("Abrir ajustes") }
                    OutlinedButton(onClick = { viewModel.sendTestNotification(context) }) { Text("Enviar prueba") }
                }
                Text("La prueba es explícita, genérica y no crea adherencia ni un evento real.", style = MaterialTheme.typography.bodySmall)
            } }
        }
        item { Text("Centro de notificaciones", style = MaterialTheme.typography.titleLarge) }
        if (events.isEmpty()) item { Text("Sin eventos locales.") }
        items(events, key = { "event-${it.serverIdentity}-${it.publicId}" }) { event -> EventCard(event, viewModel) }
        item { OutlinedButton(onClick = viewModel::cleanOldReminderEvents) { Text("Limpiar eventos locales antiguos") } }
    }
}

@Composable private fun GoalCard(goal: GoalEntity, viewModel: CompanionViewModel) {
    var target by remember(goal.publicId, goal.targetValue) { mutableStateOf(goal.targetValue) }
    Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(7.dp)) {
        Text(goalLabel(goal.goalType), style = MaterialTheme.typography.titleMedium)
        Text("${goal.state} · ${goal.period} · ${goal.syncStatus}", style = MaterialTheme.typography.bodySmall)
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(target, { target = it.take(12) }, label = { Text("Objetivo (${goal.unit})") }, modifier = Modifier.width(170.dp), singleLine = true)
            OutlinedButton(onClick = { viewModel.updateGoalTarget(goal, target) }, enabled = target.toDoubleOrNull()?.let { it > 0 } == true) { Text("Guardar") }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = { viewModel.setGoalPaused(goal, goal.state != "paused") }) { Text(if (goal.state == "paused") "Reanudar" else "Pausar") }
            TextButton(onClick = { viewModel.archiveGoal(goal) }) { Text("Archivar") }
        }
    } }
}

@Composable private fun RuleCard(
    rule: ReminderRuleEntity, onToggle: (Boolean) -> Unit, onSave: (String, String, String) -> Unit, onDelete: () -> Unit,
) {
    var time by remember(rule.publicId, rule.localTime) { mutableStateOf(rule.localTime) }
    var quietStart by remember(rule.publicId, rule.quietStart) { mutableStateOf(rule.quietStart ?: "22:00") }
    var quietEnd by remember(rule.publicId, rule.quietEnd) { mutableStateOf(rule.quietEnd ?: "07:00") }
    val valid = listOf(time, quietStart, quietEnd).all { it.matches(Regex("(?:[01][0-9]|2[0-3]):[0-5][0-9]")) }
    Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(7.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) { Text(reminderLabel(rule.reminderType), style = MaterialTheme.typography.titleMedium); Text("${rule.timezone} · ${rule.syncStatus}", style = MaterialTheme.typography.bodySmall) }
            Switch(checked = rule.enabled, onCheckedChange = onToggle)
        }
        if (rule.requiresDeviceConfirmation) Text("Importado: confirma permiso y horario antes de programar.", color = MaterialTheme.colorScheme.primary)
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            OutlinedTextField(time, { time = it.take(5) }, label = { Text("Hora") }, modifier = Modifier.weight(1f))
            OutlinedTextField(quietStart, { quietStart = it.take(5) }, label = { Text("Silencio desde") }, modifier = Modifier.weight(1f))
            OutlinedTextField(quietEnd, { quietEnd = it.take(5) }, label = { Text("Hasta") }, modifier = Modifier.weight(1f))
        }
        Text("Días ${rule.applicableDaysJson} · anticipación ${rule.leadMinutes} min · máximo ${rule.maxPerDay}/día · cooldown ${rule.cooldownMinutes} min")
        Text("Snooze: 15 min, 30 min, 1 hora o mañana.", style = MaterialTheme.typography.bodySmall)
        Row { OutlinedButton(onClick = { onSave(time, quietStart, quietEnd) }, enabled = valid) { Text("Guardar horario") }; TextButton(onClick = onDelete) { Text("Eliminar") } }
    } }
}

@Composable private fun EventCard(event: ReminderEventEntity, viewModel: CompanionViewModel) {
    Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
        Text(reminderLabel(event.eventType), style = MaterialTheme.typography.titleMedium)
        Text("${event.state} · ${event.scheduledLocal.take(16)}", style = MaterialTheme.typography.bodySmall)
        if (event.eventType in setOf("pending_sync_attention", "conflict_attention")) Text("Requiere atención")
        if (event.state in setOf("triggered", "scheduled", "snoozed")) Row {
            TextButton(onClick = { viewModel.acknowledgeReminder(event) }) { Text("Marcar revisado") }
            TextButton(onClick = { viewModel.snoozeReminder(event, 15) }) { Text("Posponer") }
        }
    } }
}

internal fun goalLabel(type: String) = when (type) {
    "training_sessions_per_week" -> "Sesiones de entrenamiento"
    "active_days_per_week" -> "Días activos"
    "daily_steps" -> "Pasos diarios"
    "nutrition_calories" -> "Calorías registradas"
    "nutrition_protein" -> "Proteína registrada"
    "nutrition_carbohydrates" -> "Carbohidratos registrados"
    "nutrition_fat" -> "Grasas registradas"
    "weight_logging_frequency" -> "Frecuencia de peso"
    "active_plan_tracking" -> "Rutina activa"
    else -> "Entrenamientos programados"
}

internal fun reminderLabel(type: String) = when (type) {
    "scheduled_workout_upcoming" -> "Entrenamiento próximo"
    "scheduled_workout_pending" -> "Entrenamiento pendiente"
    "log_weight" -> "Registrar peso"
    "log_nutrition" -> "Registrar nutrición"
    "review_steps" -> "Revisar pasos"
    "weekly_summary" -> "Resumen semanal"
    "pending_sync_attention" -> "Sincronización pendiente"
    else -> "Conflicto pendiente"
}

@Composable
internal fun AdherenceSection(viewModel: CompanionViewModel) {
    val days by viewModel.adherenceDays.collectAsState()
    val cache by viewModel.adherence.collectAsState()
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Adherencia", style = MaterialTheme.typography.titleLarge)
        Text("Resumen descriptivo; no es una puntuación global de salud.", style = MaterialTheme.typography.bodySmall)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf(7, 30, 90).forEach { value ->
                FilterChip(selected = days == value, onClick = { viewModel.setAdherenceDays(value) }, label = { Text("$value días") })
            }
        }
        val root = remember(cache?.summaryJson) {
            cache?.summaryJson?.let { runCatching { Json.parseToJsonElement(it).jsonObject }.getOrNull() }
        }
        if (root == null) Text("Sin resumen guardado. Se actualizará al recuperar conexión.") else {
            Text(root["summary"]?.jsonPrimitive?.contentOrNull ?: "Sin datos suficientes")
            root["items"]?.jsonArray?.forEach { itemElement ->
                val item = itemElement.jsonObject
                val goal = item["goal"]?.jsonObject
                val type = goal?.get("goal_type")?.jsonPrimitive?.contentOrNull.orEmpty()
                val completed = item["completed"]?.jsonPrimitive?.intOrNull ?: 0
                val expected = item["expected"]?.jsonPrimitive?.intOrNull ?: 0
                val summary = item["summary"]?.jsonPrimitive?.contentOrNull ?: "Sin datos suficientes"
                Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(12.dp)) {
                    Text(goalLabel(type), style = MaterialTheme.typography.titleMedium)
                    Text(if (expected > 0) "$completed de $expected · $summary" else summary)
                    val comparison = item["comparison"]?.jsonObject
                    comparison?.get("absolute_change")?.jsonPrimitive?.intOrNull?.let {
                        Text("Cambio frente al periodo anterior: ${if (it >= 0) "+" else ""}$it", style = MaterialTheme.typography.bodySmall)
                    }
                } }
            }
        }
    }
}
