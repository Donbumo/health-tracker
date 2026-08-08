package io.healthtracker.companion.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.unit.dp
import io.healthtracker.companion.core.database.BodyStatEntity
import io.healthtracker.companion.core.database.FoodCatalogEntity
import io.healthtracker.companion.core.database.HealthProgressPointEntity
import io.healthtracker.companion.core.database.NutritionEntryEntity
import io.healthtracker.companion.core.health.canonicalEditedWeight
import io.healthtracker.companion.core.health.displayWeight
import io.healthtracker.companion.core.health.healthChartDescription
import java.math.BigDecimal
import java.math.RoundingMode

private val MEALS = listOf("breakfast", "lunch", "dinner", "snack", "extra", "other")

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun DailyHealthScreen(
    viewModel: CompanionViewModel,
    close: () -> Unit,
    openBody: () -> Unit,
    openNutrition: () -> Unit,
    openSteps: () -> Unit,
    openMedical: () -> Unit,
) {
    val summary by viewModel.dailyHealth.collectAsState()
    val date by viewModel.healthDate.collectAsState()
    val connected by viewModel.connected.collectAsState()
    val refreshing by viewModel.healthRefreshing.collectAsState()
    val conflicts by viewModel.healthConflicts.collectAsState()
    val confirmedScaleBodyStatIds by viewModel.confirmedScaleBodyStatIds.collectAsState()
    LaunchedEffect(date) { if (connected) viewModel.refreshHealth() }
    Scaffold(topBar = { TopAppBar(title = { Text("Salud del día") }, navigationIcon = { TextButton(onClick = close) { Text("Atrás") } }) }) { padding ->
        LazyColumn(Modifier.fillMaxSize().padding(padding).padding(horizontal = 20.dp), contentPadding = PaddingValues(vertical = 16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            item { HealthDateRow(date.toString(), { viewModel.shiftHealthDate(-1) }, { viewModel.shiftHealthDate(1) }) }
            item {
                OutlinedButton(onClick = viewModel::refreshHealth, enabled = connected && !refreshing, modifier = Modifier.fillMaxWidth()) {
                    Text(if (refreshing) "Actualizando…" else if (connected) "Actualizar" else "Disponible offline")
                }
            }
            if (conflicts.isNotEmpty()) item {
                ElevatedCard(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text("Cambios que requieren atención", style = MaterialTheme.typography.titleMedium)
                        conflicts.forEach { conflict ->
                            Text("${conflict.entityType}: ${humanHealthConflict(conflict.conflictType)}", style = MaterialTheme.typography.bodySmall)
                            Row {
                                TextButton(onClick = { viewModel.useServerHealthConflict(conflict.entityId) }, enabled = connected) { Text("Usar servidor") }
                                TextButton(onClick = { viewModel.retryHealthConflict(conflict.entityId) }) { Text("Reintentar") }
                                if (conflict.entityType in setOf("body_stat", "nutrition_entry")) {
                                    TextButton(onClick = { viewModel.duplicateHealthConflict(conflict.entityId) }) { Text("Duplicar") }
                                }
                            }
                            TextButton(onClick = { viewModel.cancelHealthConflict(conflict.entityId) }, enabled = connected) { Text("Cancelar cambio local") }
                        }
                    }
                }
            }
            item { HealthMetricCard("Peso", summary?.weightKg?.let { "$it kg${if (summary?.weightIsExactDate == false) " · último disponible" else ""}" } ?: "Sin registro", summary?.syncStatus, openBody, summary?.weightSource, summary?.weightId?.let { it in confirmedScaleBodyStatIds } == true) }
            item { HealthMetricCard("Nutrición", summary?.caloriesKcal?.let { "$it kcal · P ${summary?.proteinG ?: "—"} g · C ${summary?.carbohydrateG ?: "—"} g · G ${summary?.fatG ?: "—"} g" } ?: "Sin entradas", summary?.syncStatus, openNutrition) }
            item { HealthMetricCard("Pasos", summary?.steps?.toString() ?: "Sin registro", summary?.syncStatus, openSteps, summary?.stepsSource) }
            item { HealthMetricCard("Entrenamiento", "${summary?.completedWorkouts ?: 0} completados de ${summary?.scheduledWorkouts ?: 0} programados", summary?.syncStatus, null) }
            item {
                Card(onClick = openMedical, modifier = Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text("Estudios médicos", style = MaterialTheme.typography.titleMedium)
                        Text("Resultados de laboratorio y documentos, disponibles offline.")
                        Text("Sin diagnóstico ni interpretación clínica.", style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        }
    }
}

@Composable
private fun HealthDateRow(date: String, previous: () -> Unit, next: () -> Unit) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        TextButton(onClick = previous) { Text("← Día anterior") }
        Text(date, style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(top = 12.dp))
        TextButton(onClick = next) { Text("Siguiente →") }
    }
}

@Composable
private fun HealthMetricCard(title: String, value: String, status: String?, open: (() -> Unit)?, source: String? = null, confirmedScale: Boolean = false) {
    ElevatedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            Text(value)
            if (source in setOf("health_connect", "health_connect_aggregate")) Text(
                if (source == "health_connect" && confirmedScale) "Procedencia: Báscula confirmada" else "Procedencia: Health Connect",
                style = MaterialTheme.typography.labelSmall,
            )
            Text(humanHealthSync(status), style = MaterialTheme.typography.bodySmall)
            open?.let { TextButton(onClick = it) { Text("Abrir") } }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun BodyHistoryScreen(viewModel: CompanionViewModel, close: () -> Unit) {
    val rows by viewModel.bodyStats.collectAsState()
    val preferences by viewModel.preferences.collectAsState()
    val connected by viewModel.connected.collectAsState()
    val confirmedScaleBodyStatIds by viewModel.confirmedScaleBodyStatIds.collectAsState()
    var weight by rememberSaveable { mutableStateOf("") }
    var bodyFat by rememberSaveable { mutableStateOf("") }
    var notes by rememberSaveable { mutableStateOf("") }
    var editing by remember { mutableStateOf<BodyStatEntity?>(null) }
    var deleting by remember { mutableStateOf<BodyStatEntity?>(null) }
    LaunchedEffect(Unit) { if (connected) runCatching { viewModel.refreshHealth() } }
    Scaffold(topBar = { TopAppBar(title = { Text("Historial corporal") }, navigationIcon = { TextButton(onClick = close) { Text("Atrás") } }) }) { padding ->
        LazyColumn(Modifier.fillMaxSize().padding(padding).padding(horizontal = 20.dp), contentPadding = PaddingValues(vertical = 16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            item {
                ElevatedCard(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("Registrar peso", style = MaterialTheme.typography.titleMedium)
                        DecimalField(weight, { weight = it }, "Peso (${preferences.unit.name.lowercase()})")
                        DecimalField(bodyFat, { bodyFat = it }, "Grasa corporal % (opcional)")
                        OutlinedTextField(notes, { notes = it.take(2000) }, label = { Text("Notas (opcional)") }, modifier = Modifier.fillMaxWidth())
                        Button(onClick = { viewModel.recordWeight(weight, preferences.unit.name.lowercase(), bodyFat, notes); weight = ""; bodyFat = ""; notes = "" }, enabled = weight.toBigDecimalOrNull()?.let { it > BigDecimal.ZERO } == true, modifier = Modifier.fillMaxWidth()) { Text("Registrar en este dispositivo") }
                    }
                }
            }
            items(rows, key = { it.publicId }) { row ->
                Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text("${displayWeight(row.weightKg, preferences.unit.name.lowercase()) ?: row.weightKg} ${preferences.unit.name.lowercase()}", style = MaterialTheme.typography.titleMedium)
                    Text(healthReadableInstant(row.recordedAt)); row.bodyFatPercent?.let { Text("Grasa corporal: $it %") }
                    Text(if (row.source == "health_connect") {
                        if (row.publicId in confirmedScaleBodyStatIds) "Procedencia: Báscula confirmada" else "Procedencia: Health Connect"
                    } else if (row.source == "user_override") "Copia editada por el usuario" else "Procedencia: manual", style = MaterialTheme.typography.bodySmall)
                    Text(humanHealthSync(row.syncStatus), style = MaterialTheme.typography.bodySmall)
                    Row { TextButton(onClick = { editing = row }) { Text("Editar") }; TextButton(onClick = { deleting = row }) { Text("Eliminar") } }
                } }
            }
        }
    }
    editing?.let { row -> BodyEditDialog(row, preferences.unit.name.lowercase(), { editing = null }) { weightValue, fat, note ->
        val kg = canonicalEditedWeight(weightValue, preferences.unit.name.lowercase(), row.weightKg) ?: return@BodyEditDialog
        viewModel.updateBodyStat(row.copy(weightKg = kg, bodyFatPercent = fat.takeIf(String::isNotBlank), notes = note.takeIf(String::isNotBlank)))
        editing = null
    } }
    deleting?.let { row -> AlertDialog(onDismissRequest = { deleting = null }, title = { Text("Eliminar medición") }, text = { Text("Se eliminará solo esta medición. Si no hay red, el cambio quedará pendiente.") }, confirmButton = { TextButton(onClick = { viewModel.deleteBodyStat(row.publicId); deleting = null }) { Text("Eliminar") } }, dismissButton = { TextButton(onClick = { deleting = null }) { Text("Cancelar") } }) }
}

@Composable
private fun BodyEditDialog(row: BodyStatEntity, unit: String, close: () -> Unit, apply: (String, String, String) -> Unit) {
    var weight by remember(row.publicId) { mutableStateOf(displayWeight(row.weightKg, unit) ?: row.weightKg) }
    var fat by remember(row.publicId) { mutableStateOf(row.bodyFatPercent.orEmpty()) }
    var notes by remember(row.publicId) { mutableStateOf(row.notes.orEmpty()) }
    AlertDialog(onDismissRequest = close, title = { Text("Editar medición") }, text = { Column(verticalArrangement = Arrangement.spacedBy(8.dp)) { DecimalField(weight, { weight = it }, "Peso ($unit)"); DecimalField(fat, { fat = it }, "Grasa corporal %"); OutlinedTextField(notes, { notes = it.take(2000) }, label = { Text("Notas") }) } }, confirmButton = { TextButton(onClick = { apply(weight, fat, notes) }) { Text("Aplicar cambio local") } }, dismissButton = { TextButton(onClick = close) { Text("Cancelar") } })
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun NutritionDayScreen(viewModel: CompanionViewModel, close: () -> Unit, openFoods: () -> Unit) {
    val date by viewModel.healthDate.collectAsState()
    val totals by viewModel.nutritionDay.collectAsState()
    val entries by viewModel.nutritionEntries.collectAsState()
    val foods by viewModel.foodCatalog.collectAsState()
    var meal by rememberSaveable { mutableStateOf("breakfast") }
    var name by rememberSaveable { mutableStateOf("") }
    var quantity by rememberSaveable { mutableStateOf("") }
    var unit by rememberSaveable { mutableStateOf("g") }
    var calories by rememberSaveable { mutableStateOf("") }
    var protein by rememberSaveable { mutableStateOf("") }
    var carbs by rememberSaveable { mutableStateOf("") }
    var fat by rememberSaveable { mutableStateOf("") }
    var fiber by rememberSaveable { mutableStateOf("") }
    var selectedFood by remember { mutableStateOf<FoodCatalogEntity?>(null) }
    var deleting by remember { mutableStateOf<NutritionEntryEntity?>(null) }
    var editing by remember { mutableStateOf<NutritionEntryEntity?>(null) }
    LaunchedEffect(quantity, selectedFood?.publicId) {
        val grams = quantity.toBigDecimalOrNull(); val food = selectedFood
        if (grams != null && food != null && unit == "g") {
            fun scaled(value: String?) = value?.toBigDecimalOrNull()?.multiply(grams)?.divide(BigDecimal("100"), 3, RoundingMode.HALF_UP)?.stripTrailingZeros()?.toPlainString().orEmpty()
            calories = scaled(food.caloriesPer100g); protein = scaled(food.proteinGPer100g); carbs = scaled(food.carbsGPer100g ?: food.netCarbsGPer100g); fat = scaled(food.fatGPer100g); fiber = scaled(food.fiberGPer100g)
        }
    }
    Scaffold(topBar = { TopAppBar(title = { Text("Nutrición del día") }, navigationIcon = { TextButton(onClick = close) { Text("Atrás") } }) }) { padding ->
        LazyColumn(Modifier.fillMaxSize().padding(padding).padding(horizontal = 20.dp), contentPadding = PaddingValues(vertical = 16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            item { HealthDateRow(date.toString(), { viewModel.shiftHealthDate(-1) }, { viewModel.shiftHealthDate(1) }) }
            item { Text("${totals?.caloriesKcal ?: "—"} kcal · P ${totals?.proteinG ?: "—"} g · C ${totals?.totalCarbsG ?: totals?.netCarbsG ?: "—"} g · G ${totals?.fatG ?: "—"} g", modifier = Modifier.semantics { contentDescription = "Resumen textual de nutrición" }) }
            item {
                ElevatedCard(Modifier.fillMaxWidth()) { Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Añadir comida", style = MaterialTheme.typography.titleMedium)
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) { items(MEALS) { value -> FilterChip(selected = meal == value, onClick = { meal = value }, label = { Text(humanMeal(value)) }) } }
                    OutlinedTextField(name, { name = it.take(200) }, label = { Text("Alimento") }, modifier = Modifier.fillMaxWidth())
                    if (foods.isNotEmpty()) { Text("Catálogo offline", style = MaterialTheme.typography.labelMedium); LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) { items(foods.take(8), key = { it.publicId }) { food -> AssistChip(onClick = { selectedFood = food; name = food.name }, label = { Text(food.name) }) } } }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { DecimalField(quantity, { quantity = it }, "Cantidad", Modifier.weight(1f)); OutlinedTextField(unit, { unit = it.take(32) }, label = { Text("Unidad") }, modifier = Modifier.weight(1f)) }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { DecimalField(calories, { calories = it }, "kcal", Modifier.weight(1f)); DecimalField(protein, { protein = it }, "Proteína g", Modifier.weight(1f)) }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { DecimalField(carbs, { carbs = it }, "Carbos g", Modifier.weight(1f)); DecimalField(fat, { fat = it }, "Grasa g", Modifier.weight(1f)) }
                    DecimalField(fiber, { fiber = it }, "Fibra g (opcional)")
                    if (listOf(calories, protein, carbs, fat).any(String::isBlank)) Text("Datos incompletos: solo se sumarán los valores disponibles.", style = MaterialTheme.typography.bodySmall)
                    Button(onClick = { viewModel.addNutritionEntry(meal, name, quantity, unit, calories, protein, carbs, fat, fiber, selectedFood?.publicId, null); name = ""; quantity = ""; calories = ""; protein = ""; carbs = ""; fat = ""; fiber = ""; selectedFood = null }, enabled = name.isNotBlank(), modifier = Modifier.fillMaxWidth()) { Text("Añadir en este dispositivo") }
                    TextButton(onClick = openFoods) { Text("Abrir catálogo de alimentos") }
                } }
            }
            MEALS.forEach { mealType ->
                val group = entries.filter { it.mealType == mealType }
                if (group.isNotEmpty()) {
                    item { Text(humanMeal(mealType), style = MaterialTheme.typography.titleMedium, modifier = Modifier.semantics { heading() }) }
                    items(group, key = { it.publicId }) { entry -> Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(14.dp)) {
                        Text(entry.name, style = MaterialTheme.typography.titleSmall); Text("${entry.caloriesKcal ?: "—"} kcal · P ${entry.proteinG ?: "—"} · C ${entry.totalCarbsG ?: entry.netCarbsG ?: "—"} · G ${entry.fatG ?: "—"}")
                        if (entry.source == "health_connect") Text("Procedencia: Health Connect", style = MaterialTheme.typography.bodySmall)
                        if (entry.source == "user_override") Text("Copia editada; ya no recibe cambios de Health Connect", style = MaterialTheme.typography.bodySmall)
                        if (!entry.dataComplete) Text("Datos incompletos", style = MaterialTheme.typography.bodySmall)
                        Text(humanHealthSync(entry.syncStatus), style = MaterialTheme.typography.bodySmall)
                        Row { TextButton(onClick = { editing = entry }) { Text("Editar") }; TextButton(onClick = { viewModel.updateNutritionEntry(entry.copy(mealType = nextMeal(entry.mealType))) }) { Text("Mover") } }
                        Row { TextButton(onClick = { viewModel.duplicateNutritionEntry(entry.publicId) }) { Text("Duplicar") }; TextButton(onClick = { deleting = entry }) { Text("Eliminar") } }
                    } }
                    }
                }
            }
        }
    }
    deleting?.let { entry -> AlertDialog(onDismissRequest = { deleting = null }, title = { Text("Eliminar entrada") }, text = { Text("La eliminación se guardará localmente y se sincronizará al recuperar conexión.") }, confirmButton = { TextButton(onClick = { viewModel.deleteNutritionEntry(entry.publicId); deleting = null }) { Text("Eliminar") } }, dismissButton = { TextButton(onClick = { deleting = null }) { Text("Cancelar") } }) }
    editing?.let { entry -> NutritionEditDialog(entry, { editing = null }) { updated -> viewModel.updateNutritionEntry(updated); editing = null } }
}

@Composable
private fun NutritionEditDialog(entry: NutritionEntryEntity, close: () -> Unit, apply: (NutritionEntryEntity) -> Unit) {
    var meal by remember(entry.publicId) { mutableStateOf(entry.mealType) }
    var name by remember(entry.publicId) { mutableStateOf(entry.name) }
    var quantity by remember(entry.publicId) { mutableStateOf(entry.quantity.orEmpty()) }
    var unit by remember(entry.publicId) { mutableStateOf(entry.unit.orEmpty()) }
    var calories by remember(entry.publicId) { mutableStateOf(entry.caloriesKcal.orEmpty()) }
    var protein by remember(entry.publicId) { mutableStateOf(entry.proteinG.orEmpty()) }
    var carbs by remember(entry.publicId) { mutableStateOf((entry.totalCarbsG ?: entry.netCarbsG).orEmpty()) }
    var fat by remember(entry.publicId) { mutableStateOf(entry.fatG.orEmpty()) }
    var fiber by remember(entry.publicId) { mutableStateOf(entry.fiberG.orEmpty()) }
    AlertDialog(
        onDismissRequest = close,
        title = { Text("Editar entrada") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                LazyRow(horizontalArrangement = Arrangement.spacedBy(4.dp)) { items(MEALS) { value -> FilterChip(selected = meal == value, onClick = { meal = value }, label = { Text(humanMeal(value)) }) } }
                OutlinedTextField(name, { name = it.take(200) }, label = { Text("Alimento") })
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) { DecimalField(quantity, { quantity = it }, "Cantidad", Modifier.weight(1f)); OutlinedTextField(unit, { unit = it.take(32) }, label = { Text("Unidad") }, modifier = Modifier.weight(1f)) }
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) { DecimalField(calories, { calories = it }, "kcal", Modifier.weight(1f)); DecimalField(protein, { protein = it }, "Proteína", Modifier.weight(1f)) }
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) { DecimalField(carbs, { carbs = it }, "Carbos", Modifier.weight(1f)); DecimalField(fat, { fat = it }, "Grasa", Modifier.weight(1f)) }
                DecimalField(fiber, { fiber = it }, "Fibra")
                if (listOf(calories, protein, carbs, fat).any(String::isBlank)) Text("Datos incompletos", style = MaterialTheme.typography.bodySmall)
            }
        },
        confirmButton = {
            TextButton(
                onClick = {
                    fun optional(value: String) = value.takeIf(String::isNotBlank)
                    apply(entry.copy(mealType = meal, name = name.trim(), quantity = optional(quantity), unit = optional(unit), caloriesKcal = optional(calories), proteinG = optional(protein), totalCarbsG = optional(carbs), netCarbsG = null, fatG = optional(fat), fiberG = optional(fiber), dataComplete = listOf(calories, protein, carbs, fat).none(String::isBlank)))
                },
                enabled = name.isNotBlank(),
            ) { Text("Aplicar cambio local") }
        },
        dismissButton = { TextButton(onClick = close) { Text("Cancelar") } },
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun FoodCatalogScreen(viewModel: CompanionViewModel, close: () -> Unit) {
    val query by viewModel.foodQuery.collectAsState(); val foods by viewModel.foodCatalog.collectAsState()
    val hasMore by viewModel.foodHasMore.collectAsState(); val loading by viewModel.foodLoading.collectAsState()
    var showCreate by remember { mutableStateOf(false) }
    Scaffold(topBar = { TopAppBar(title = { Text("Catálogo de alimentos") }, navigationIcon = { TextButton(onClick = close) { Text("Atrás") } }) }) { padding ->
        LazyColumn(Modifier.fillMaxSize().padding(padding).padding(horizontal = 20.dp), contentPadding = PaddingValues(vertical = 16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            item { OutlinedTextField(query, viewModel::setFoodQuery, label = { Text("Buscar alimento") }, modifier = Modifier.fillMaxWidth(), singleLine = true) }
            item { Button(onClick = { showCreate = true }, modifier = Modifier.fillMaxWidth()) { Text("Crear alimento personalizado") } }
            items(foods, key = { it.publicId }) { food -> Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(14.dp)) { Text(food.name, style = MaterialTheme.typography.titleMedium); food.brand?.let { Text(it) }; Text("${food.caloriesPer100g ?: "—"} kcal/100 g · P ${food.proteinGPer100g ?: "—"} · C ${food.carbsGPer100g ?: food.netCarbsGPer100g ?: "—"} · G ${food.fatGPer100g ?: "—"}"); if (!food.dataComplete) Text("Datos incompletos", style = MaterialTheme.typography.bodySmall); Text(humanHealthSync(food.syncStatus), style = MaterialTheme.typography.bodySmall) } }
            }
            if (hasMore) item { OutlinedButton(onClick = viewModel::loadMoreFoods, enabled = !loading, modifier = Modifier.fillMaxWidth()) { Text(if (loading) "Cargando…" else "Cargar más") } }
        }
    }
    if (showCreate) FoodCreateDialog({ showCreate = false }) { name, serving, calories, protein, carbs, fat -> viewModel.createFood(name, serving, calories, protein, carbs, fat); showCreate = false }
}

@Composable
private fun FoodCreateDialog(close: () -> Unit, create: (String, String, String, String, String, String) -> Unit) {
    var name by remember { mutableStateOf("") }; var serving by remember { mutableStateOf("") }; var calories by remember { mutableStateOf("") }; var protein by remember { mutableStateOf("") }; var carbs by remember { mutableStateOf("") }; var fat by remember { mutableStateOf("") }
    AlertDialog(onDismissRequest = close, title = { Text("Alimento personalizado") }, text = { Column(verticalArrangement = Arrangement.spacedBy(6.dp)) { OutlinedTextField(name, { name = it.take(200) }, label = { Text("Nombre") }); DecimalField(serving, { serving = it }, "Porción g"); DecimalField(calories, { calories = it }, "kcal/100 g"); DecimalField(protein, { protein = it }, "Proteína/100 g"); DecimalField(carbs, { carbs = it }, "Carbohidratos/100 g"); DecimalField(fat, { fat = it }, "Grasa/100 g") } }, confirmButton = { TextButton(onClick = { create(name, serving, calories, protein, carbs, fat) }, enabled = name.isNotBlank()) { Text("Crear localmente") } }, dismissButton = { TextButton(onClick = close) { Text("Cancelar") } })
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun StepsHistoryScreen(viewModel: CompanionViewModel, close: () -> Unit) {
    val date by viewModel.healthDate.collectAsState(); val rows by viewModel.stepHistory.collectAsState(); var value by rememberSaveable { mutableStateOf("") }; var deleting by remember { mutableStateOf<String?>(null) }
    Scaffold(topBar = { TopAppBar(title = { Text("Historial de pasos") }, navigationIcon = { TextButton(onClick = close) { Text("Atrás") } }) }) { padding ->
        LazyColumn(Modifier.fillMaxSize().padding(padding).padding(horizontal = 20.dp), contentPadding = PaddingValues(vertical = 16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            item { HealthDateRow(date.toString(), { viewModel.shiftHealthDate(-1) }, { viewModel.shiftHealthDate(1) }) }
            item { ElevatedCard(Modifier.fillMaxWidth()) { Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) { DecimalField(value, { value = it.filter(Char::isDigit).take(8) }, "Pasos manuales"); Button(onClick = { viewModel.registerSteps(value); value = "" }, enabled = value.toLongOrNull()?.let { it in 0..10_000_000 } == true, modifier = Modifier.fillMaxWidth()) { Text("Registrar o corregir localmente") } } } }
            items(rows, key = { it.publicId }) { row -> Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(14.dp)) { Text("${row.steps} pasos", style = MaterialTheme.typography.titleMedium); Text("${row.date} · ${row.source}"); Text(humanHealthSync(row.syncStatus), style = MaterialTheme.typography.bodySmall); if (row.source == "manual") TextButton(onClick = { deleting = row.publicId }) { Text("Eliminar") } } } }
        }
    }
    deleting?.let { id -> AlertDialog(onDismissRequest = { deleting = null }, title = { Text("Eliminar pasos manuales") }, text = { Text("No se modificarán otras fuentes del mismo día.") }, confirmButton = { TextButton(onClick = { viewModel.deleteSteps(id); deleting = null }) { Text("Eliminar") } }, dismissButton = { TextButton(onClick = { deleting = null }) { Text("Cancelar") } }) }
}

@Composable
internal fun HealthProgressContent(points: List<HealthProgressPointEntity>, confirmedScaleDates: Set<String> = emptySet()) {
    val weights = points.mapNotNull { point -> point.weightKg?.toFloatOrNull()?.let { point.date to it } }
    val steps = points.mapNotNull { point -> point.steps?.toFloat()?.let { point.date to it } }
    val calories = points.mapNotNull { point -> point.caloriesKcal?.toFloatOrNull()?.let { point.date to it } }
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        HealthTrendChart("Peso por fecha", weights, "kg")
        HealthTrendChart("Pasos por día", steps, "pasos")
        HealthTrendChart("Calorías por día", calories, "kcal")
        val avgSteps = steps.map { it.second }.takeIf { it.isNotEmpty() }?.average()?.toLong()
        val avgCalories = calories.map { it.second }.takeIf { it.isNotEmpty() }?.average()?.toLong()
        val avgProtein = points.mapNotNull { it.proteinG?.toDoubleOrNull() }.takeIf { it.isNotEmpty() }?.average()
        val importedWeights = points.count { it.weightSource == "health_connect" }
        val importedSteps = points.count { it.stepsSource == "health_connect_aggregate" }
        Text("Resumen textual: ${weights.size} mediciones de peso; pasos promedio ${avgSteps ?: "sin datos"}; calorías promedio ${avgCalories ?: "sin datos"}; proteína promedio ${avgProtein?.let { "%.1f g".format(it) } ?: "sin datos"}.", modifier = Modifier.semantics { contentDescription = "Alternativa textual de las gráficas de salud" })
        if (importedWeights + importedSteps > 0) Text("Procedencia Health Connect: $importedWeights puntos de peso y $importedSteps totales diarios de pasos.", style = MaterialTheme.typography.bodySmall)
        val confirmedWeights = points.count { it.weightSource == "health_connect" && it.date in confirmedScaleDates }
        if (confirmedWeights > 0) Text("Procedencia Báscula confirmada: $confirmedWeights puntos de peso.", style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
internal fun HealthProgressScreen(viewModel: CompanionViewModel) {
    val range by viewModel.progressRange.collectAsState()
    val points by viewModel.healthProgress.collectAsState()
    val connected by viewModel.connected.collectAsState()
    val refreshing by viewModel.progressRefreshing.collectAsState()
    val confirmedScaleDates by viewModel.confirmedScaleDates.collectAsState()
    LazyColumn(Modifier.fillMaxSize().padding(horizontal = 20.dp), contentPadding = PaddingValues(vertical = 20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { Text("Progreso", style = MaterialTheme.typography.headlineMedium, modifier = Modifier.semantics { heading() }) }
        item { Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { FilterChip(selected = false, onClick = { viewModel.setProgressSection("training") }, label = { Text("Entrenamiento") }); FilterChip(selected = true, onClick = {}, label = { Text("Salud") }) } }
        item { LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) { items(listOf("7", "30", "90", "180", "365", "all")) { value -> FilterChip(selected = range == value, onClick = { viewModel.setProgressRange(value) }, label = { Text(if (value == "all") "Todo (365 días)" else "$value días") }) } } }
        item { Text(if (connected) "Tendencias descriptivas desde la caché local." else "Sin conexión: se muestran las tendencias guardadas."); OutlinedButton(onClick = viewModel::refreshProgress, enabled = connected && !refreshing) { Text(if (refreshing) "Actualizando…" else "Actualizar") } }
        item { HealthProgressContent(points, confirmedScaleDates) }
        item { Text("Estas gráficas no calculan correlaciones médicas ni implican causalidad.", style = MaterialTheme.typography.bodySmall) }
        item { Spacer(Modifier.height(72.dp)) }
    }
}

@Composable
private fun HealthTrendChart(title: String, values: List<Pair<String, Float>>, unit: String) {
    val chartColor = MaterialTheme.colorScheme.primary
    Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(14.dp)) { Text(title, style = MaterialTheme.typography.titleMedium); if (values.isEmpty()) Text("Sin datos") else { val min = values.minOf { it.second }; val max = values.maxOf { it.second }; Canvas(Modifier.fillMaxWidth().height(130.dp).semantics { contentDescription = healthChartDescription(title, values.map { it.second }, unit) }) { val range = (max - min).takeIf { it > 0f } ?: 1f; values.forEachIndexed { index, point -> val x = if (values.size == 1) size.width / 2 else size.width * index / (values.size - 1); val y = size.height - ((point.second - min) / range * size.height); if (index > 0) { val prev = values[index - 1].second; val px = if (values.size == 1) size.width / 2 else size.width * (index - 1) / (values.size - 1); val py = size.height - ((prev - min) / range * size.height); drawLine(chartColor, Offset(px, py), Offset(x, y), 4f) }; drawCircle(chartColor, 6f, Offset(x, y)) } } } } }
}

@Composable
private fun DecimalField(value: String, change: (String) -> Unit, label: String, modifier: Modifier = Modifier.fillMaxWidth()) = OutlinedTextField(value, { change(it.filter { char -> char.isDigit() || char == '.' }.take(16)) }, label = { Text(label) }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), singleLine = true, modifier = modifier)

private fun humanMeal(value: String) = when (value) { "breakfast" -> "Desayuno"; "lunch" -> "Comida"; "dinner" -> "Cena"; "snack" -> "Snack"; "extra" -> "Extra"; else -> "Otra" }
private fun nextMeal(value: String) = MEALS[(MEALS.indexOf(value).coerceAtLeast(0) + 1) % MEALS.size]
private fun humanHealthSync(value: String?) = when (value) { "pending" -> "Pendiente de sincronización"; "syncing" -> "Sincronizando"; "conflict", "attention" -> "Requiere atención"; "synced" -> "Sincronizado"; else -> "Guardado en este dispositivo" }
private fun humanHealthConflict(value: String) = when (value) { "deleted_or_unavailable" -> "el recurso ya no está disponible"; "validation_rejected" -> "el servidor rechazó el cambio"; "access_revoked" -> "el acceso fue revocado"; else -> "la revisión del servidor cambió" }
private fun healthReadableInstant(value: String): String = value.replace('T', ' ').substringBeforeLast(':')
