package io.healthtracker.companion.ui

import android.os.Build
import android.content.Intent
import android.content.Context
import android.net.Uri
import androidx.activity.result.contract.ActivityResultContract
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.createSavedStateHandle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.CreationExtras
import io.healthtracker.companion.AppContainer
import io.healthtracker.companion.core.config.ThemePreference
import io.healthtracker.companion.core.config.UnitPreference
import io.healthtracker.companion.core.database.DraftSetEntity
import io.healthtracker.companion.core.database.PackageExerciseEntity
import io.healthtracker.companion.core.database.HistorySessionEntity
import io.healthtracker.companion.core.database.HistoryExerciseEntity
import io.healthtracker.companion.core.database.HistorySetEntity
import io.healthtracker.companion.core.database.ProgressSummaryEntity
import io.healthtracker.companion.core.database.ProgressExerciseEntity
import io.healthtracker.companion.core.database.ProgressPointEntity
import io.healthtracker.companion.core.database.PersonalRecordEntity
import io.healthtracker.companion.core.database.ExerciseCatalogEntity
import io.healthtracker.companion.core.database.MobilePlanEntity
import io.healthtracker.companion.core.database.MobilePlanExerciseEntity
import io.healthtracker.companion.core.database.MobilePlanSetEntity
import io.healthtracker.companion.core.database.MobilePlanWorkoutEntity
import io.healthtracker.companion.core.database.PlanningConflictEntity
import io.healthtracker.companion.core.database.BodyStatEntity
import io.healthtracker.companion.core.database.NutritionEntryEntity
import io.healthtracker.companion.core.database.GoalEntity
import io.healthtracker.companion.core.database.ReminderRuleEntity
import io.healthtracker.companion.core.database.ReminderEventEntity
import io.healthtracker.companion.core.network.CanonicalJson
import io.healthtracker.companion.core.notifications.NotificationPublisher
import io.healthtracker.companion.core.health.canonicalWeightKg
import io.healthtracker.companion.core.healthconnect.HealthConnectManager
import io.healthtracker.companion.core.healthconnect.HealthConnectRecordType
import io.healthtracker.companion.core.healthconnect.HealthConnectScheduler
import io.healthtracker.companion.core.healthconnect.HealthConnectTrigger
import io.healthtracker.companion.core.healthconnect.HealthConnectUiState
import io.healthtracker.companion.core.healthconnect.ScaleDiagnosticResult
import io.healthtracker.companion.core.external.ConfirmedScaleKind
import io.healthtracker.companion.core.external.ExternalDeviceUiState
import io.healthtracker.companion.core.external.shortFingerprint
import io.healthtracker.companion.core.load.LoadPreview
import io.healthtracker.companion.core.planning.reorderedIds
import io.healthtracker.companion.core.planning.PlanningEditorState
import io.healthtracker.companion.core.model.AppFailure
import io.healthtracker.companion.core.model.AuthState
import io.healthtracker.companion.core.model.LoadDetailsDto
import io.healthtracker.companion.core.model.SyncStatus
import io.healthtracker.companion.core.model.UserProfile
import io.healthtracker.companion.core.portability.PortableExportRequest
import io.healthtracker.companion.core.sync.SyncScheduler
import io.healthtracker.companion.core.sync.SyncTrigger
import io.healthtracker.companion.core.sync.HistoryFilters
import java.time.LocalDate
import java.time.ZoneId
import java.time.Instant
import java.util.UUID
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.filter
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.mapLatest
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

enum class AutosaveUiState { SAVING, SAVED, SAVED_LOCAL, ERROR }

private sealed interface AutosaveCommand {
    data class SetValue(val value: DraftSetEntity) : AutosaveCommand
    data class Summary(
        val scope: String,
        val deliveryId: String,
        val heartRate: Int?,
        val calories: String?,
        val notes: String?,
    ) : AutosaveCommand
}

@OptIn(ExperimentalCoroutinesApi::class)
class CompanionViewModel(
    private val container: AppContainer,
    private val savedStateHandle: SavedStateHandle = SavedStateHandle(),
) : ViewModel() {
    private val repository = container.repository
    private val healthConnectManager: HealthConnectManager = container.healthConnectManager
    private val externalSourceStore = container.externalSourceStore
    private val portabilityRepository = container.portabilityRepository
    private val engagementRepository = container.engagementRepository
    private val medicalRepository = container.medicalRepository
    private val planningEditorState = PlanningEditorState(savedStateHandle)
    private val mutableAuth = MutableStateFlow(AuthState.SIGNED_OUT)
    private val mutableProfile = MutableStateFlow<UserProfile?>(null)
    private val mutableBusy = MutableStateFlow(false)
    private val mutableStartInProgress = MutableStateFlow(false)
    private val mutableDownloadInProgress = MutableStateFlow(false)
    private val mutableManualSyncInProgress = MutableStateFlow(false)
    private val mutableFinalActionInProgress = MutableStateFlow(false)
    private val mutableSetActions = MutableStateFlow<Set<String>>(emptySet())
    private val mutableMessage = MutableStateFlow<String?>(null)
    private val mutableAutosaveState = MutableStateFlow(AutosaveUiState.SAVED)
    private val mutableHistoryFilters = MutableStateFlow(HistoryFilters())
    private val mutableHistoryRefreshing = MutableStateFlow(false)
    private val mutableHistoryError = MutableStateFlow<String?>(null)
    private val mutableSelectedHistoryId = MutableStateFlow<String?>(null)
    private val mutableProgressRange = MutableStateFlow("30")
    private val mutableProgressRefreshing = MutableStateFlow(false)
    private val mutableProgressError = MutableStateFlow<String?>(null)
    private val mutableSelectedExerciseId = MutableStateFlow<String?>(null)
    private val mutableSelectedPlanId = planningEditorState.planId
    private val mutableSelectedPlanWorkoutId = planningEditorState.workoutId
    private val mutableCatalogQuery = MutableStateFlow("")
    private val mutablePlanningRefreshing = MutableStateFlow(false)
    private val mutableShowArchivedPlans = MutableStateFlow(false)
    private val mutableHealthDate = MutableStateFlow(LocalDate.now())
    private val mutableHealthRefreshing = MutableStateFlow(false)
    private val mutableFoodQuery = MutableStateFlow("")
    private val mutableFoodHasMore = MutableStateFlow(false)
    private val mutableFoodLoading = MutableStateFlow(false)
    private val mutableProgressSection = MutableStateFlow("training")
    private val mutableScaleDiagnostic = MutableStateFlow(ScaleDiagnosticResult())
    private val mutableAdherenceDays = MutableStateFlow(7)
    private val mutableSelectedMedicalStudyId = MutableStateFlow<String?>(null)
    private val mutableMedicalHistoryKey = MutableStateFlow<String?>(null)
    private val mutableMedicalHistoryPeriod = MutableStateFlow("all")
    private var catalogSearchJob: Job? = null
    private val serializer = Json { explicitNulls = false; encodeDefaults = true }
    private val autosaveController: DebouncedAutosave<AutosaveCommand>

    val auth: StateFlow<AuthState> = mutableAuth
    val profile: StateFlow<UserProfile?> = mutableProfile
    val busy: StateFlow<Boolean> = mutableBusy
    val startInProgress: StateFlow<Boolean> = mutableStartInProgress
    val downloadInProgress: StateFlow<Boolean> = mutableDownloadInProgress
    val syncInProgress: StateFlow<Boolean> = combine(mutableManualSyncInProgress, repository.syncStatus) { manual, status ->
        manual || status == SyncStatus.SYNCING
    }.stateIn(viewModelScope, SharingStarted.Eagerly, false)
    val finalActionInProgress: StateFlow<Boolean> = mutableFinalActionInProgress
    val setActions: StateFlow<Set<String>> = mutableSetActions
    val message: StateFlow<String?> = mutableMessage
    val autosaveState: StateFlow<AutosaveUiState> = mutableAutosaveState
    val historyFilters: StateFlow<HistoryFilters> = mutableHistoryFilters
    val historyRefreshing: StateFlow<Boolean> = mutableHistoryRefreshing
    val historyError: StateFlow<String?> = mutableHistoryError
    val selectedHistoryId: StateFlow<String?> = mutableSelectedHistoryId
    val progressRange: StateFlow<String> = mutableProgressRange
    val progressRefreshing: StateFlow<Boolean> = mutableProgressRefreshing
    val progressError: StateFlow<String?> = mutableProgressError
    val selectedExerciseId: StateFlow<String?> = mutableSelectedExerciseId
    val selectedPlanId: StateFlow<String?> = mutableSelectedPlanId
    val selectedPlanWorkoutId: StateFlow<String?> = mutableSelectedPlanWorkoutId
    val catalogQuery: StateFlow<String> = mutableCatalogQuery
    val planningRefreshing: StateFlow<Boolean> = mutablePlanningRefreshing
    val showArchivedPlans: StateFlow<Boolean> = mutableShowArchivedPlans
    val healthDate: StateFlow<LocalDate> = mutableHealthDate
    val healthRefreshing: StateFlow<Boolean> = mutableHealthRefreshing
    val foodQuery: StateFlow<String> = mutableFoodQuery
    val foodHasMore: StateFlow<Boolean> = mutableFoodHasMore
    val foodLoading: StateFlow<Boolean> = mutableFoodLoading
    val progressSection: StateFlow<String> = mutableProgressSection
    val scaleDiagnostic: StateFlow<ScaleDiagnosticResult> = mutableScaleDiagnostic
    val adherenceDays: StateFlow<Int> = mutableAdherenceDays
    val selectedMedicalStudyId: StateFlow<String?> = mutableSelectedMedicalStudyId
    val medicalHistoryKey: StateFlow<String?> = mutableMedicalHistoryKey
    val medicalHistoryPeriod: StateFlow<String> = mutableMedicalHistoryPeriod
    val externalDevice: StateFlow<ExternalDeviceUiState> = container.externalDeviceManager.state
    val preferences = container.preferences.values.stateIn(
        viewModelScope, SharingStarted.WhileSubscribed(5_000),
        io.healthtracker.companion.core.config.AppPreferences(deviceId = ""),
    )
    val connected = container.connectivity.connected.stateIn(
        viewModelScope, SharingStarted.WhileSubscribed(5_000), false,
    )
    private val scope = preferences.mapLatest { it.accountScope }
    private val engagementScope = preferences.mapLatest { local ->
        val account = local.accountScope
        val server = local.serverUrl
        if (account == null || server == null) null else account to CanonicalJson.serverIdentity(server)
    }

    val goals = engagementScope.flatMapLatest { value ->
        if (value == null) flowOf(emptyList()) else engagementRepository.observeGoals(value.first, value.second)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val reminderRules = engagementScope.flatMapLatest { value ->
        if (value == null) flowOf(emptyList()) else engagementRepository.observeRules(value.first, value.second)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val reminderEvents = engagementScope.flatMapLatest { value ->
        if (value == null) flowOf(emptyList()) else engagementRepository.observeEvents(value.first, value.second)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val reminderPermission = engagementScope.flatMapLatest { value ->
        if (value == null) flowOf(null) else engagementRepository.observePermission(value.first, value.second)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    val adherence = combine(engagementScope, mutableAdherenceDays) { value, days -> value to days }.flatMapLatest { (value, days) ->
        if (value == null) flowOf(null) else engagementRepository.observeAdherence(value.first, value.second, days)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    val medicalStudies = engagementScope.flatMapLatest { value ->
        if (value == null) flowOf(emptyList()) else medicalRepository.observeStudies(value.first, value.second)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val selectedMedicalStudy = combine(engagementScope, mutableSelectedMedicalStudyId) { value, id -> value to id }
        .flatMapLatest { (value, id) ->
            if (value == null || id == null) flowOf(null) else medicalRepository.observeStudy(value.first, value.second, id)
        }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    val medicalPanels = combine(engagementScope, mutableSelectedMedicalStudyId) { value, id -> value to id }
        .flatMapLatest { (value, id) ->
            if (value == null || id == null) flowOf(emptyList()) else medicalRepository.observePanels(value.first, value.second, id)
        }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val medicalResults = combine(engagementScope, medicalPanels) { value, panels -> value to panels.map { it.publicId } }
        .flatMapLatest { (value, ids) ->
            if (value == null || ids.isEmpty()) flowOf(emptyList()) else medicalRepository.observeResults(value.first, value.second, ids)
        }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val medicalDocuments = combine(engagementScope, mutableSelectedMedicalStudyId) { value, id -> value to id }
        .flatMapLatest { (value, id) ->
            if (value == null || id == null) flowOf(emptyList()) else medicalRepository.observeDocuments(value.first, value.second, id)
        }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val labMarkers = engagementScope.flatMapLatest { value ->
        if (value == null) flowOf(emptyList()) else medicalRepository.observeMarkers(value.first, value.second)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val medicalHistory = combine(engagementScope, mutableMedicalHistoryKey, mutableMedicalHistoryPeriod) { value, key, period -> Triple(value, key, period) }
        .flatMapLatest { (value, key, period) ->
            if (value == null || key == null) flowOf(null) else medicalRepository.observeHistory(value.first, value.second, key, period)
        }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    val medicalDuplicates = engagementScope.flatMapLatest { value ->
        if (value == null) flowOf(emptyList()) else medicalRepository.observeDuplicates(value.first, value.second)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val portableExports = scope.flatMapLatest { account ->
        if (account == null) flowOf(emptyList()) else portabilityRepository.observeExports(account)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val portableImports = scope.flatMapLatest { account ->
        if (account == null) flowOf(emptyList()) else portabilityRepository.observeImports(account)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val portableInspections = scope.flatMapLatest { account ->
        if (account == null) flowOf(emptyList()) else portabilityRepository.observeInspections(account)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val portablePlans = scope.flatMapLatest { account ->
        if (account == null) flowOf(emptyList()) else portabilityRepository.observePlans(account)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val portableDownloads = scope.flatMapLatest { account ->
        if (account == null) flowOf(emptyList()) else portabilityRepository.observeDownloads(account)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val healthConnect = scope.flatMapLatest { account ->
        if (account == null) flowOf(HealthConnectUiState()) else healthConnectManager.observe(account)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), HealthConnectUiState())

    val externalSources = scope.flatMapLatest { account ->
        if (account == null) flowOf(emptyList()) else externalSourceStore.observeSources(account)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val healthConnectSourceAssociations = scope.flatMapLatest { account ->
        if (account == null) flowOf(emptyList()) else externalSourceStore.observeHealthConnectAssociations(account)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val bleDeviceAssociations = scope.flatMapLatest { account ->
        if (account == null) flowOf(emptyList()) else externalSourceStore.observeBleDeviceAssociations(account)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val bleCaptureMetadata = combine(scope, bleDeviceAssociations) { account, associations -> account to associations.firstOrNull() }
        .flatMapLatest { (account, association) ->
            if (account == null || association == null) flowOf(emptyList()) else externalSourceStore.observeBleCaptures(account, association.associationKey)
        }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val possibleExternalDuplicates = scope.flatMapLatest { account ->
        if (account == null) flowOf(emptyList()) else externalSourceStore.observePossibleDuplicates(account)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val planned = scope.flatMapLatest { value ->
        if (value == null) flowOf(emptyList()) else repository.observePlanned(value)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val planningToday = mutableProfile.mapLatest { current ->
        val zone = runCatching { current?.timezone?.let(ZoneId::of) ?: ZoneId.systemDefault() }
            .getOrDefault(ZoneId.systemDefault())
        LocalDate.now(zone)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), LocalDate.now())

    val dailyHealth = combine(scope, mutableHealthDate) { account, date -> account to date }.flatMapLatest { (account, date) ->
        if (account == null) flowOf(null) else repository.observeDailyHealth(account, date)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    val bodyStats = scope.flatMapLatest { account ->
        if (account == null) flowOf(emptyList()) else repository.observeBodyStats(account)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val confirmedScaleBodyStatIds = combine(scope, bodyStats, healthConnectSourceAssociations) { account, stats, associations ->
        Triple(account, stats, associations)
    }.mapLatest { (account, stats, associations) ->
        if (account == null) return@mapLatest emptySet()
        val confirmed = associations.filter { it.state == "user_confirmed" }.mapTo(mutableSetOf()) { it.sourceFingerprint }
        stats.filterTo(mutableSetOf()) { stat ->
            stat.source == "health_connect" && container.database.companionDao()
                .healthConnectLedgersForResource(account, stat.publicId)
                .any { ledger -> shortFingerprint("health-connect-origin:${ledger.dataOrigin}") in confirmed }
        }.mapTo(mutableSetOf()) { it.publicId }
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptySet())

    val confirmedScaleDates = combine(confirmedScaleBodyStatIds, bodyStats, mutableProfile) { ids, stats, currentProfile ->
        val zone = runCatching { currentProfile?.timezone?.let(ZoneId::of) ?: ZoneId.systemDefault() }.getOrDefault(ZoneId.systemDefault())
        stats.filter { it.publicId in ids }.mapNotNullTo(mutableSetOf()) { stat ->
            runCatching { Instant.parse(stat.recordedAt).atZone(zone).toLocalDate().toString() }.getOrNull()
        }
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptySet())

    val nutritionDay = combine(scope, mutableHealthDate) { account, date -> account to date }.flatMapLatest { (account, date) ->
        if (account == null) flowOf(null) else repository.observeNutritionDay(account, date)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    val nutritionEntries = combine(scope, mutableHealthDate) { account, date -> account to date }.flatMapLatest { (account, date) ->
        if (account == null) flowOf(emptyList()) else repository.observeNutritionEntries(account, date)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val foodCatalog = combine(scope, mutableFoodQuery) { account, query -> account to query }.flatMapLatest { (account, query) ->
        if (account == null) flowOf(emptyList()) else repository.observeFoodCatalog(account, query)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val stepHistory = combine(scope, mutableHealthDate) { account, date -> account to date }.flatMapLatest { (account, date) ->
        if (account == null) flowOf(emptyList()) else repository.observeDailySteps(account, date.minusDays(29), date)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val healthConflicts = scope.flatMapLatest { account ->
        if (account == null) flowOf(emptyList()) else repository.observeHealthConflicts(account)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val healthProgress = combine(scope, planningToday, mutableProgressRange) { account, today, range -> Triple(account, today, range) }.flatMapLatest { (account, today, range) ->
        val days = range.toLongOrNull()?.coerceAtMost(365) ?: 365
        if (account == null) flowOf(emptyList()) else repository.observeHealthProgress(account, today.minusDays(days - 1), today)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val todayWorkouts = combine(planned, planningToday) { values, operationalDate ->
        values.filter {
            it.scheduledForDate == operationalDate.toString() &&
                it.status in setOf("planned", "locally_pending", "syncing", "in_progress", "completed", "conflict")
        }.sortedBy { if (it.status == "completed") 1 else 0 }
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val today = todayWorkouts.mapLatest { it.firstOrNull() }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    val nextWorkout = combine(planned, planningToday) { values, operationalDate ->
        values.firstOrNull {
            it.scheduledForDate > operationalDate.toString() &&
                it.status in setOf("planned", "locally_pending", "syncing")
        }
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    val activeDraft = scope.flatMapLatest { value ->
        if (value == null) flowOf(null) else repository.observeActiveDraft(value)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    val pendingCount = scope.flatMapLatest { value ->
        if (value == null) flowOf(0) else repository.observePendingCount(value)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), 0)

    val conflictCount = scope.flatMapLatest { value ->
        if (value == null) flowOf(0) else repository.observeConflictCount(value)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), 0)

    val history = combine(scope, mutableHistoryFilters) { account, filters -> account to filters }.flatMapLatest { (account, filters) ->
        if (account == null) flowOf(emptyList()) else repository.observeHistory(account, filters)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val historyQueryState = combine(scope, mutableHistoryFilters) { account, filters -> account to filters }.flatMapLatest { (account, filters) ->
        if (account == null) flowOf(null) else repository.observeHistoryState(account, filters)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    val selectedHistory = combine(scope, mutableSelectedHistoryId) { account, id -> account to id }.flatMapLatest { (account, id) ->
        if (account == null || id == null) flowOf(null) else repository.observeHistorySession(account, id)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    val selectedHistoryExercises = combine(scope, mutableSelectedHistoryId) { account, id -> account to id }.flatMapLatest { (account, id) ->
        if (account == null || id == null) flowOf(emptyList()) else repository.observeHistoryExercises(account, id)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val selectedHistorySets = combine(scope, mutableSelectedHistoryId) { account, id -> account to id }.flatMapLatest { (account, id) ->
        if (account == null || id == null) flowOf(emptyList()) else repository.observeHistorySets(account, id)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val progressSummary = combine(scope, mutableProgressRange) { account, range -> account to range }.flatMapLatest { (account, range) ->
        if (account == null) flowOf(null) else repository.observeProgressSummary(account, range)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    val progressExercises = combine(scope, mutableProgressRange) { account, range -> account to range }.flatMapLatest { (account, range) ->
        if (account == null) flowOf(emptyList()) else repository.observeProgressExercises(account, range)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val selectedProgressExercise = combine(scope, mutableProgressRange, mutableSelectedExerciseId) { account, range, id -> Triple(account, range, id) }.flatMapLatest { (account, range, id) ->
        if (account == null || id == null) flowOf(null) else repository.observeProgressExercise(account, range, id)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    val progressPoints = combine(scope, mutableProgressRange, mutableSelectedExerciseId) { account, range, id -> Triple(account, range, id) }.flatMapLatest { (account, range, id) ->
        if (account == null || id == null) flowOf(emptyList()) else repository.observeProgressPoints(account, range, id)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val personalRecords = combine(scope, mutableProgressRange, mutableSelectedExerciseId) { account, range, id -> Triple(account, range, id) }.flatMapLatest { (account, range, id) ->
        if (account == null || id == null) flowOf(emptyList()) else repository.observePersonalRecords(account, range, id)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val weeklyProgress = scope.flatMapLatest { account ->
        if (account == null) flowOf(null) else repository.observeProgressSummary(account, "7")
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    val latestPersonalRecord = scope.flatMapLatest { account ->
        if (account == null) flowOf(null) else repository.observeLatestPersonalRecord(account)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    val plans = combine(scope, mutableShowArchivedPlans) { account, archived -> account to archived }.flatMapLatest { (account, archived) ->
        if (account == null) flowOf(emptyList()) else repository.observePlans(account, if (archived) "archived" else "active")
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val downloadedPackages = scope.flatMapLatest { account ->
        if (account == null) flowOf(emptyList()) else repository.observePackages(account)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val selectedPlan = combine(scope, mutableSelectedPlanId) { account, id -> account to id }.flatMapLatest { (account, id) ->
        if (account == null || id == null) flowOf(null) else repository.observePlan(account, id)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    val planWorkouts = combine(scope, mutableSelectedPlanId) { account, id -> account to id }.flatMapLatest { (account, id) ->
        if (account == null || id == null) flowOf(emptyList()) else repository.observePlanWorkouts(account, id)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val selectedPlanWorkout = combine(scope, mutableSelectedPlanWorkoutId) { account, id -> account to id }.flatMapLatest { (account, id) ->
        if (account == null || id == null) flowOf(null) else repository.observePlanWorkout(account, id)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    val planExercises = combine(scope, mutableSelectedPlanWorkoutId) { account, id -> account to id }.flatMapLatest { (account, id) ->
        if (account == null || id == null) flowOf(emptyList()) else repository.observePlanExercises(account, id)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val planSets = combine(scope, mutableSelectedPlanWorkoutId) { account, id -> account to id }.flatMapLatest { (account, id) ->
        if (account == null || id == null) flowOf(emptyList()) else repository.observePlanSets(account, id)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val exerciseCatalog = combine(scope, mutableCatalogQuery) { account, query -> account to query }.flatMapLatest { (account, query) ->
        if (account == null) flowOf(emptyList()) else repository.observeExerciseCatalog(account, query)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val planningConflicts = scope.flatMapLatest { account ->
        if (account == null) flowOf(emptyList()) else repository.observePlanningConflicts(account)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val draftSets = activeDraft.flatMapLatest { draft ->
        if (draft == null) flowOf(emptyList()) else repository.observeDraftSets(draft.accountScope, draft.deliveryId)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val workoutExercises = activeDraft.mapLatest { draft ->
        if (draft == null) emptyList() else repository.packageExercises(draft.accountScope, draft.packageId)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val downloadedDelivery = combine(scope, today) { account, workout -> account to workout }.flatMapLatest { (account, workout) ->
        if (account == null || workout == null) flowOf(null)
        else repository.observeDownloadedDelivery(account, workout.id)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    init {
        autosaveController = DebouncedAutosave(
            scope = viewModelScope,
            persist = { command ->
                when (command) {
                    is AutosaveCommand.SetValue -> repository.saveSet(command.value)
                    is AutosaveCommand.Summary -> repository.updateDraftSummary(
                        command.scope,
                        command.deliveryId,
                        command.heartRate,
                        command.calories,
                        command.notes,
                    )
                }
            },
            onSaving = { mutableAutosaveState.value = AutosaveUiState.SAVING },
            onSettled = { error ->
                mutableAutosaveState.value = when {
                    error != null -> AutosaveUiState.ERROR
                    connected.value -> AutosaveUiState.SAVED
                    else -> AutosaveUiState.SAVED_LOCAL
                }
            },
        )
        viewModelScope.launch {
            val actual = container.preferences.values.first()
            container.tokens.bindLegacyServerIfMissing(actual.serverUrl)
            if (actual.serverUrl == null) mutableAuth.value = AuthState.NO_SERVER
            else if (actual.accountScope != null && container.tokens.refreshToken(actual.serverUrl) != null) {
                val localProfile = repository.restoreLocalSession()
                if (localProfile == null) {
                    mutableAuth.value = AuthState.SIGNED_OUT
                } else {
                    mutableProfile.value = localProfile
                    mutableAuth.value = AuthState.AUTHENTICATED
                    SyncScheduler.schedulePeriodic()
                    HealthConnectScheduler.schedulePeriodic()
                    if (container.connectivity.connected.first()) restoreOnline(actual.accountScope)
                }
            } else mutableAuth.value = AuthState.SIGNED_OUT
        }
        viewModelScope.launch {
            container.connectivity.connected
                .distinctUntilChanged()
                .filter { it }
                .collect {
                    if (mutableAuth.value == AuthState.AUTHENTICATED && container.tokens.accessToken(preferences.value.serverUrl) == null) {
                        preferences.value.accountScope?.let { restoreOnline(it) }
                    } else {
                        SyncScheduler.enqueueNow(SyncTrigger.CONNECTIVITY_RECOVERED)
                    }
                }
        }
        viewModelScope.launch {
            container.preferences.values.collect { current ->
                if (current.accountScope == null && mutableAuth.value == AuthState.AUTHENTICATED) {
                    mutableProfile.value = null
                    mutableAuth.value = if (current.serverUrl == null) AuthState.NO_SERVER else AuthState.SIGNED_OUT
                }
            }
        }
        viewModelScope.launch {
            container.preferences.values.mapLatest { it.accountScope }
                .distinctUntilChanged()
                .collectLatest { account ->
                    if (account != null) runCatching {
                        healthConnectManager.ensure(account)
                        externalSourceStore.ensureDefaults(account)
                    }
                }
        }
        viewModelScope.launch {
            mutableFoodQuery.collectLatest { query ->
                delay(350)
                if (query == mutableFoodQuery.value && connected.value) {
                    preferences.value.accountScope?.let { account ->
                        runCatching { repository.refreshFoods(account, query) }
                            .onSuccess { mutableFoodHasMore.value = it }
                    }
                }
            }
        }
    }

    fun login(url: String, localHttp: Boolean, email: String, password: String, deviceName: String) = action {
        mutableAuth.value = AuthState.AUTHENTICATING
        val outcome = repository.login(url, localHttp, email, password, deviceName, "Android ${Build.VERSION.RELEASE}")
        mutableProfile.value = outcome.profile
        mutableAuth.value = AuthState.AUTHENTICATED
        mutableMessage.value = "Sesión iniciada y dispositivo registrado."
    }

    fun testServer(url: String, localHttp: Boolean) = action {
        repository.testServer(url, localHttp)
        mutableMessage.value = "Conexión verificada con Health Tracker."
    }

    fun downloadToday() {
        val plannedId = today.value?.id ?: return
        downloadScheduled(plannedId)
    }

    fun downloadScheduled(plannedId: String) {
        if (!mutableDownloadInProgress.compareAndSet(expect = false, update = true)) return
        action(showBusy = false, onFinally = { mutableDownloadInProgress.value = false }) {
            val account = preferences.value.accountScope ?: return@action
            repository.downloadWorkout(account, plannedId)
            mutableMessage.value = "Entrenamiento descargado y verificado."
        }
    }

    fun startToday(onStarted: () -> Unit) {
        val plannedId = today.value?.id ?: return
        startScheduled(plannedId, onStarted)
    }

    fun startScheduled(plannedId: String, onStarted: () -> Unit) {
        if (!mutableStartInProgress.compareAndSet(expect = false, update = true)) return
        action(onFinally = { mutableStartInProgress.value = false }) {
            val account = preferences.value.accountScope ?: return@action
            val deliveryId = downloadedPackages.value.firstOrNull { it.plannedWorkoutId == plannedId }?.deliveryId
                ?: return@action
            repository.startWorkout(account, deliveryId)
            mutableMessage.value = "Entrenamiento listo para uso offline."
            onStarted()
        }
    }

    fun syncNow() {
        if (!mutableManualSyncInProgress.compareAndSet(expect = false, update = true)) return
        action(showBusy = false, onFinally = { mutableManualSyncInProgress.value = false }) {
            val account = preferences.value.accountScope ?: return@action
            autosaveController.flush()
            repository.synchronize(account)
            mutableMessage.value = "Sincronización completada."
        }
    }

    fun refreshHistory(reset: Boolean = true) {
        if (!mutableHistoryRefreshing.compareAndSet(false, true)) return
        viewModelScope.launch {
            try {
                val account = preferences.value.accountScope ?: return@launch
                repository.refreshHistory(account, mutableHistoryFilters.value, reset)
                mutableHistoryError.value = null
            } catch (failure: AppFailure) {
                mutableHistoryError.value = failure.userMessage
            } finally {
                mutableHistoryRefreshing.value = false
            }
        }
    }

    fun setHistoryFilters(dateFrom: String?, dateTo: String?, exercisePublicId: String?) {
        mutableHistoryFilters.value = HistoryFilters(
            dateFrom?.takeIf(String::isNotBlank), dateTo?.takeIf(String::isNotBlank),
            exercisePublicId?.takeIf(String::isNotBlank),
        )
        refreshHistory(reset = true)
    }

    fun clearHistoryFilters() = setHistoryFilters(null, null, null)

    fun openHistory(publicId: String) {
        mutableSelectedHistoryId.value = publicId
        if (connected.value) viewModelScope.launch {
            runCatching { preferences.value.accountScope?.let { repository.refreshHistoryDetail(it, publicId) } }
                .onFailure { if (it is AppFailure) mutableHistoryError.value = it.userMessage }
        }
    }

    fun closeHistory() { mutableSelectedHistoryId.value = null }

    fun setProgressRange(range: String) {
        if (range !in setOf("7", "30", "90", "180", "365", "all")) return
        mutableProgressRange.value = range
        refreshProgress()
    }

    fun refreshProgress() {
        if (!mutableProgressRefreshing.compareAndSet(false, true)) return
        viewModelScope.launch {
            try {
                val account = preferences.value.accountScope ?: return@launch
                repository.refreshProgress(account, mutableProgressRange.value)
                val today = planningToday.value
                val days = mutableProgressRange.value.toLongOrNull()?.coerceAtMost(365) ?: 365
                repository.refreshHealthProgress(account, today.minusDays(days - 1), today, mutableProfile.value?.timezone ?: "UTC")
                mutableProgressError.value = null
            } catch (failure: AppFailure) {
                mutableProgressError.value = failure.userMessage
            } finally {
                mutableProgressRefreshing.value = false
            }
        }
    }

    fun openProgressExercise(publicId: String) {
        mutableSelectedExerciseId.value = publicId
        if (connected.value) viewModelScope.launch {
            runCatching {
                preferences.value.accountScope?.let {
                    repository.refreshProgressExercise(it, mutableProgressRange.value, publicId)
                }
            }.onFailure { if (it is AppFailure) mutableProgressError.value = it.userMessage }
        }
    }

    fun closeProgressExercise() { mutableSelectedExerciseId.value = null }

    fun setProgressSection(value: String) {
        if (value in setOf("training", "health")) mutableProgressSection.value = value
    }

    fun setHealthDate(value: LocalDate) { mutableHealthDate.value = value }

    fun shiftHealthDate(days: Long) { mutableHealthDate.value = mutableHealthDate.value.plusDays(days) }

    fun setFoodQuery(value: String) {
        mutableFoodHasMore.value = false
        mutableFoodQuery.value = value.take(200)
    }

    fun loadMoreFoods() {
        if (!connected.value || !mutableFoodHasMore.value || !mutableFoodLoading.compareAndSet(false, true)) return
        viewModelScope.launch {
            try {
                val account = preferences.value.accountScope ?: return@launch
                mutableFoodHasMore.value = repository.refreshFoods(account, mutableFoodQuery.value, reset = false)
            } catch (failure: AppFailure) {
                mutableMessage.value = failure.userMessage
            } finally {
                mutableFoodLoading.value = false
            }
        }
    }

    fun refreshHealth() {
        if (!mutableHealthRefreshing.compareAndSet(false, true)) return
        viewModelScope.launch {
            try {
                val account = preferences.value.accountScope ?: return@launch
                repository.refreshHealth(account, mutableHealthDate.value, mutableProfile.value?.timezone ?: "UTC")
            } catch (failure: AppFailure) {
                mutableMessage.value = failure.userMessage
            } finally {
                mutableHealthRefreshing.value = false
            }
        }
    }

    fun recordWeight(value: String, unit: String, bodyFat: String?, notes: String?) = healthAction("Medición guardada en este dispositivo.") { account ->
        val kilograms = canonicalWeightKg(value, unit)
            ?: throw AppFailure(io.healthtracker.companion.core.model.AppErrorCode.VALIDATION_ERROR, "El peso o la unidad no son válidos.", false)
        val zone = runCatching { ZoneId.of(mutableProfile.value?.timezone ?: "UTC") }.getOrDefault(ZoneId.of("UTC"))
        val recordedAt = if (mutableHealthDate.value == LocalDate.now(zone)) Instant.now().toString()
        else mutableHealthDate.value.atTime(12, 0).atZone(zone).toInstant().toString()
        repository.createBodyStatOffline(account, recordedAt, kilograms, bodyFat?.takeIf(String::isNotBlank), notes)
    }

    fun updateBodyStat(value: BodyStatEntity) = healthAction("Cambio corporal guardado localmente.") { repository.updateBodyStatOffline(value) }

    fun deleteBodyStat(publicId: String) = healthAction("Medición eliminada localmente.") { repository.deleteBodyStatOffline(it, publicId) }

    fun addNutritionEntry(
        mealType: String, name: String, quantity: String?, unit: String?, calories: String?,
        protein: String?, carbs: String?, fat: String?, fiber: String?, foodId: String?, notes: String?,
    ) = healthAction("Comida guardada en este dispositivo.") { account ->
        repository.createNutritionEntryOffline(
            account, mutableHealthDate.value, mealType, name, quantity?.takeIf(String::isNotBlank),
            unit?.takeIf(String::isNotBlank), calories?.takeIf(String::isNotBlank), protein?.takeIf(String::isNotBlank),
            carbs?.takeIf(String::isNotBlank), fat?.takeIf(String::isNotBlank), fiber?.takeIf(String::isNotBlank), foodId,
            notes?.takeIf(String::isNotBlank),
        )
    }

    fun updateNutritionEntry(value: NutritionEntryEntity) = healthAction("Entrada actualizada localmente.") { repository.updateNutritionEntryOffline(value) }

    fun duplicateNutritionEntry(publicId: String) = healthAction("Entrada duplicada localmente.") { repository.duplicateNutritionEntryOffline(it, publicId) }

    fun deleteNutritionEntry(publicId: String) = healthAction("Entrada eliminada localmente.") { repository.deleteNutritionEntryOffline(it, publicId) }

    fun registerSteps(value: String) = healthAction("Pasos guardados en este dispositivo.") { account ->
        val count = value.toLongOrNull()
            ?: throw AppFailure(io.healthtracker.companion.core.model.AppErrorCode.VALIDATION_ERROR, "Los pasos no son válidos.", false)
        repository.setStepsOffline(account, mutableHealthDate.value, count)
    }

    fun deleteSteps(publicId: String) = healthAction("Registro de pasos eliminado localmente.") { repository.deleteStepsOffline(it, publicId) }

    fun createFood(name: String, servingSize: String?, calories: String?, protein: String?, carbs: String?, fat: String?) =
        healthAction("Alimento guardado en el catálogo local.") { account ->
            repository.createFoodOffline(account, name, servingSize?.takeIf(String::isNotBlank), calories?.takeIf(String::isNotBlank), protein?.takeIf(String::isNotBlank), carbs?.takeIf(String::isNotBlank), fat?.takeIf(String::isNotBlank))
        }

    fun useServerHealthConflict(entityId: String) = healthAction("Se descartó el cambio local en conflicto.") { account ->
        repository.resolveHealthConflictUseServer(account, entityId)
        if (connected.value) repository.refreshHealth(account, mutableHealthDate.value, mutableProfile.value?.timezone ?: "UTC")
    }

    fun retryHealthConflict(entityId: String) = healthAction("El cambio volverá a sincronizarse.") { account ->
        repository.retryHealthConflict(account, entityId)
    }

    fun duplicateHealthConflict(entityId: String) = healthAction("Se creó una copia local nueva.") { account ->
        repository.duplicateHealthConflict(account, entityId)
    }

    fun cancelHealthConflict(entityId: String) = useServerHealthConflict(entityId)

    fun refreshPlanning() {
        if (!mutablePlanningRefreshing.compareAndSet(false, true)) return
        viewModelScope.launch {
            try {
                val account = preferences.value.accountScope ?: return@launch
                repository.refreshPlans(account)
                repository.refreshSchedule(account)
                repository.refreshExerciseCatalog(account, mutableCatalogQuery.value)
            } catch (failure: AppFailure) {
                mutableMessage.value = failure.userMessage
            } finally {
                mutablePlanningRefreshing.value = false
            }
        }
    }

    fun searchExercises(query: String) {
        mutableCatalogQuery.value = query.take(120)
        catalogSearchJob?.cancel()
        if (connected.value) catalogSearchJob = viewModelScope.launch {
            delay(300)
            val requestedQuery = mutableCatalogQuery.value
            runCatching {
                preferences.value.accountScope?.let { repository.refreshExerciseCatalog(it, requestedQuery) }
            }.onFailure { if (it is AppFailure) mutableMessage.value = it.userMessage }
        }
    }

    fun loadMoreExercises() = action(showBusy = false) {
        val account = preferences.value.accountScope ?: return@action
        repository.refreshExerciseCatalog(account, mutableCatalogQuery.value, reset = false)
    }

    fun selectPlan(id: String?) { planningEditorState.selectPlan(id) }
    fun selectPlanWorkout(id: String?) { planningEditorState.selectWorkout(id) }
    fun showArchivedPlans(show: Boolean) {
        mutableShowArchivedPlans.value = show
        if (show && connected.value) viewModelScope.launch {
            preferences.value.accountScope?.let { account ->
                runCatching { repository.refreshPlans(account, "archived") }
                    .onFailure { if (it is AppFailure) mutableMessage.value = it.userMessage }
            }
        }
    }

    fun createPlan(name: String, description: String? = null, onCreated: (String) -> Unit = {}) = action {
        val account = preferences.value.accountScope ?: return@action
        val id = repository.createPlanOffline(account, name, description)
        selectPlan(id)
        mutableMessage.value = "Rutina guardada en este dispositivo."
        onCreated(id)
    }

    fun editSelectedPlan(name: String, description: String?) = action(showBusy = false) {
        persistSelectedPlan(name, description)
    }

    fun flushSelectedPlan(name: String, description: String?, onFlushed: () -> Unit = {}) = action(showBusy = false) {
        persistSelectedPlan(name, description)
        onFlushed()
    }

    private suspend fun persistSelectedPlan(name: String, description: String?) {
        val account = preferences.value.accountScope ?: return
        val plan = selectedPlan.value ?: return
        if (name.isBlank() || (name == plan.name && description?.trim()?.ifBlank { null } == plan.description)) return
        repository.editPlanOffline(account, plan.publicId, name, description)
    }

    fun archiveSelectedPlan(onArchived: () -> Unit = {}) = action {
        val account = preferences.value.accountScope ?: return@action
        val plan = selectedPlan.value ?: return@action
        if (planned.value.any { it.planId == plan.publicId && it.status in setOf("planned", "locally_pending", "syncing", "in_progress") }) {
            throw AppFailure(
                io.healthtracker.companion.core.model.AppErrorCode.REVISION_CONFLICT,
                "Cancela las programaciones activas antes de archivar la rutina.",
                false,
            )
        }
        repository.editPlanOffline(account, plan.publicId, plan.name, plan.description, "archived")
        selectPlan(null)
        mutableMessage.value = "Rutina archivada."
        onArchived()
    }

    fun restoreSelectedPlan() = action {
        val account = preferences.value.accountScope ?: return@action
        val plan = selectedPlan.value ?: return@action
        repository.editPlanOffline(account, plan.publicId, plan.name, plan.description, "active")
        mutableMessage.value = "Rutina restaurada."
    }

    fun duplicateSelectedPlan() = action {
        val account = preferences.value.accountScope ?: return@action
        val plan = selectedPlan.value ?: return@action
        selectPlan(repository.duplicatePlanOffline(account, plan.publicId, "${plan.name} (copia)"))
        mutableMessage.value = "Copia de la rutina guardada."
    }

    fun createPlanWorkout(name: String, onCreated: (String) -> Unit = {}) = action {
        val account = preferences.value.accountScope ?: return@action
        val plan = selectedPlan.value ?: return@action
        val id = repository.createWorkoutOffline(account, plan.publicId, name)
        selectPlanWorkout(id)
        onCreated(id)
    }

    fun duplicateSelectedPlanWorkout() = action {
        val account = preferences.value.accountScope ?: return@action
        val workout = selectedPlanWorkout.value ?: return@action
        selectPlanWorkout(repository.duplicateWorkoutOffline(account, workout.publicId))
        mutableMessage.value = "Entrenamiento duplicado."
    }

    fun movePlanWorkout(id: String, delta: Int) = action(showBusy = false) {
        val account = preferences.value.accountScope ?: return@action
        val plan = selectedPlan.value ?: return@action
        val ids = reorderedIds(planWorkouts.value.map { it.publicId }, id, delta) ?: return@action
        repository.reorderWorkoutsOffline(account, plan.publicId, ids)
    }

    fun saveSelectedPlanWorkout(name: String, notes: String?) = action(showBusy = false) {
        persistPlanWorkout(name, notes, planExercises.value, planSets.value)
    }

    fun flushSelectedPlanWorkout(name: String, notes: String?, onFlushed: () -> Unit = {}) = action(showBusy = false) {
        persistPlanWorkout(name, notes, planExercises.value, planSets.value)
        onFlushed()
    }

    fun addCatalogExercise(item: ExerciseCatalogEntity) = addCatalogExercises(listOf(item))

    fun addCatalogExercises(items: List<ExerciseCatalogEntity>) = action(showBusy = false) {
        val workout = selectedPlanWorkout.value ?: return@action
        val current = planExercises.value
        val additions = items.distinctBy { it.publicId }.filter { item ->
            item.selectable && current.none { it.catalogExerciseId == item.publicId }
        }
        if (additions.isEmpty()) return@action
        val newExercises = mutableListOf<MobilePlanExerciseEntity>()
        val newSets = mutableListOf<MobilePlanSetEntity>()
        additions.forEachIndexed { index, item ->
            val exerciseId = UUID.randomUUID().toString()
            newExercises += MobilePlanExerciseEntity(
                workout.accountScope, workout.publicId, exerciseId, item.publicId, item.name, null, current.size + index + 1,
            )
            val loadMode = item.preferredLoadMode ?: "direct_total"
            newSets += MobilePlanSetEntity(
                workout.accountScope, workout.publicId, exerciseId, UUID.randomUUID().toString(), 1,
                if (loadMode == "duration_distance") null else 8, null, null, null, null,
                item.preferredUnit ?: "kg", loadMode, null, null, null, 90,
                if (loadMode == "duration_distance") 600 else null, null, null,
            )
        }
        persistPlanWorkout(workout.name, workout.notes, current + newExercises, planSets.value + newSets)
    }

    fun removePlanExercise(id: String) = action(showBusy = false) {
        val workout = selectedPlanWorkout.value ?: return@action
        val remaining = planExercises.value.filterNot { it.publicId == id }.mapIndexed { index, item -> item.copy(position = index + 1) }
        persistPlanWorkout(workout.name, workout.notes, remaining, planSets.value.filterNot { it.exercisePublicId == id })
    }

    fun duplicatePlanExercise(id: String) = action(showBusy = false) {
        val workout = selectedPlanWorkout.value ?: return@action
        val source = planExercises.value.firstOrNull { it.publicId == id } ?: return@action
        val newId = UUID.randomUUID().toString()
        val copy = source.copy(publicId = newId, name = "${source.name} (copia)", position = planExercises.value.size + 1)
        val copiedSets = planSets.value.filter { it.exercisePublicId == id }.map {
            it.copy(exercisePublicId = newId, publicId = UUID.randomUUID().toString())
        }
        persistPlanWorkout(workout.name, workout.notes, planExercises.value + copy, planSets.value + copiedSets)
    }

    fun movePlanExercise(id: String, delta: Int) = action(showBusy = false) {
        val workout = selectedPlanWorkout.value ?: return@action
        val values = planExercises.value.toMutableList()
        val from = values.indexOfFirst { it.publicId == id }
        val to = from + delta
        if (from < 0 || to !in values.indices) return@action
        val moved = values.removeAt(from)
        values.add(to, moved)
        persistPlanWorkout(workout.name, workout.notes, values.mapIndexed { index, item -> item.copy(position = index + 1) }, planSets.value)
    }

    fun addPlanSet(exerciseId: String) = action(showBusy = false) {
        val workout = selectedPlanWorkout.value ?: return@action
        val previous = planSets.value.filter { it.exercisePublicId == exerciseId }.maxByOrNull { it.setNumber }
        val next = previous?.copy(publicId = UUID.randomUUID().toString(), setNumber = previous.setNumber + 1)
            ?: MobilePlanSetEntity(workout.accountScope, workout.publicId, exerciseId, UUID.randomUUID().toString(), 1, 8, null, null, null, null, "kg", "direct_total", null, null, null, 90, null, null, null)
        persistPlanWorkout(workout.name, workout.notes, planExercises.value, planSets.value + next)
    }

    fun deletePlanSet(setId: String) = action(showBusy = false) {
        val workout = selectedPlanWorkout.value ?: return@action
        val target = planSets.value.firstOrNull { it.publicId == setId } ?: return@action
        val remaining = planSets.value.filterNot { it.publicId == setId }.map {
            if (it.exercisePublicId == target.exercisePublicId && it.setNumber > target.setNumber) it.copy(setNumber = it.setNumber - 1) else it
        }
        persistPlanWorkout(workout.name, workout.notes, planExercises.value, remaining)
    }

    fun updatePlanSet(value: MobilePlanSetEntity) = action(showBusy = false) {
        repository.updatePlanSetOffline(value)
    }

    fun scheduleSelectedWorkout(date: LocalDate) = action {
        val account = preferences.value.accountScope ?: return@action
        val workout = selectedPlanWorkout.value ?: return@action
        repository.scheduleWorkoutOffline(account, workout.publicId, date, planningTimezone())
        mutableMessage.value = "Entrenamiento programado para $date."
    }

    fun cancelScheduledWorkout(id: String) = action {
        val account = preferences.value.accountScope ?: return@action
        repository.cancelScheduleOffline(account, id)
        mutableMessage.value = "Programación cancelada."
    }

    fun rescheduleWorkout(id: String, date: LocalDate) = action {
        val account = preferences.value.accountScope ?: return@action
        repository.rescheduleWorkoutOffline(account, id, date, planningTimezone())
        mutableMessage.value = "Programación cambiada al $date."
    }

    fun keepRemoteConflict(entityId: String) = action {
        val account = preferences.value.accountScope ?: return@action
        repository.resolvePlanningConflictKeepRemote(account, entityId)
    }

    fun retryPlanningConflict(entityId: String) = action {
        val account = preferences.value.accountScope ?: return@action
        repository.retryPlanningConflict(account, entityId)
    }

    fun duplicatePlanningConflict(entityId: String) = action {
        val account = preferences.value.accountScope ?: return@action
        repository.duplicatePlanningConflict(account, entityId)
        mutableMessage.value = "La copia local se conservó como un recurso nuevo."
    }

    private fun planningTimezone(): String = profile.value?.timezone ?: ZoneId.systemDefault().id

    private suspend fun persistPlanWorkout(
        name: String,
        notes: String?,
        exercises: List<MobilePlanExerciseEntity>,
        sets: List<MobilePlanSetEntity>,
    ) {
        val account = preferences.value.accountScope ?: return
        val workout = selectedPlanWorkout.value ?: return
        repository.saveWorkoutOffline(account, workout.publicId, name, notes, exercises, sets)
    }

    fun saveSet(value: DraftSetEntity) = action(showBusy = false) { repository.saveSet(value) }

    fun queueSaveLoad(
        source: DraftSetEntity,
        reps: Int,
        rir: String?,
        rpe: String?,
        notes: String?,
        preview: LoadPreview,
        durationSeconds: Int? = source.durationSeconds,
        distanceMeters: String? = source.distanceMeters,
        restSeconds: Int? = source.restSeconds,
    ) {
        val updated = source.copy(
            reps = reps,
            rir = rir?.takeIf { it.isNotBlank() },
            rpe = rpe?.takeIf { it.isNotBlank() },
            notes = notes?.take(2000),
            weightKg = preview.weightKg.toPlainString(),
            loadDetailsJson = serializer.encodeToString<LoadDetailsDto>(preview.details),
            durationSeconds = durationSeconds,
            distanceMeters = distanceMeters,
            restSeconds = restSeconds,
        )
        autosaveController.submit(setAutosaveKey(source), AutosaveCommand.SetValue(updated))
    }

    fun checkpoint(value: DraftSetEntity) = action(showBusy = false) {
        repository.checkpointSet(value.accountScope, value.deliveryId, value)
    }

    fun checkpointLoad(
        source: DraftSetEntity,
        reps: Int,
        rir: String?,
        rpe: String?,
        notes: String?,
        preview: LoadPreview,
        durationSeconds: Int? = source.durationSeconds,
        distanceMeters: String? = source.distanceMeters,
        restSeconds: Int? = source.restSeconds,
    ) {
        val actionKey = setActionKey(source, "complete")
        if (!claimSetAction(actionKey)) return
        autosaveController.discard(setAutosaveKey(source))
        action(showBusy = false, onFinally = { releaseSetAction(actionKey) }) {
            val updated = source.copy(
                reps = reps,
                rir = rir?.takeIf { it.isNotBlank() },
                rpe = rpe?.takeIf { it.isNotBlank() },
                notes = notes?.take(2000),
                weightKg = preview.weightKg.toPlainString(),
                loadDetailsJson = serializer.encodeToString<LoadDetailsDto>(preview.details),
                durationSeconds = durationSeconds,
                distanceMeters = distanceMeters,
                restSeconds = restSeconds,
                completed = true,
            )
            repository.checkpointSet(updated.accountScope, updated.deliveryId, updated)
        }
    }

    fun duplicate(value: DraftSetEntity) {
        val actionKey = setActionKey(value, "duplicate")
        if (!claimSetAction(actionKey)) return
        action(showBusy = false, onFinally = { releaseSetAction(actionKey) }) { repository.duplicateSet(value) }
    }

    fun copyLoad(from: DraftSetEntity, to: DraftSetEntity) = action(showBusy = false) {
        repository.saveSet(to.copy(weightKg = from.weightKg, loadDetailsJson = from.loadDetailsJson))
    }

    fun pauseResume(pause: Boolean) = action {
        autosaveController.flush()
        val draft = activeDraft.value ?: return@action
        repository.pauseOrResume(draft.accountScope, draft.deliveryId, pause)
    }

    fun queueSummaryAutosave(heartRate: Int?, calories: String?, notes: String?) {
        val draft = activeDraft.value ?: return
        autosaveController.submit(
            "summary:${draft.deliveryId}",
            AutosaveCommand.Summary(draft.accountScope, draft.deliveryId, heartRate, calories, notes),
        )
    }

    fun flushAutosaves(onFlushed: () -> Unit = {}) {
        viewModelScope.launch {
            runCatching { autosaveController.flush() }
                .onSuccess { onFlushed() }
                .onFailure { mutableAutosaveState.value = AutosaveUiState.ERROR }
        }
    }

    fun completeWorkout(onQueued: () -> Unit) {
        if (!mutableFinalActionInProgress.compareAndSet(expect = false, update = true)) return
        action(showBusy = false, onFinally = { mutableFinalActionInProgress.value = false }) {
            autosaveController.flush()
            val draft = activeDraft.value ?: return@action
            repository.completeWorkout(draft.accountScope, draft.deliveryId)
            mutableMessage.value = "Finalización guardada; se enviará una sola vez al recuperar conexión."
            onQueued()
        }
    }

    fun abortWorkout(onQueued: () -> Unit) {
        if (!mutableFinalActionInProgress.compareAndSet(expect = false, update = true)) return
        action(showBusy = false, onFinally = { mutableFinalActionInProgress.value = false }) {
            autosaveController.flush()
            val draft = activeDraft.value ?: return@action
            repository.abortWorkout(draft.accountScope, draft.deliveryId)
            mutableMessage.value = "Cancelación pendiente de confirmar con el servidor."
            onQueued()
        }
    }

    fun discardCorruptDraft() = action {
        val draft = activeDraft.value ?: return@action
        repository.discardCorruptDraft(draft.accountScope, draft.deliveryId)
        mutableMessage.value = "El borrador corrupto se descartó sin enviar su contenido."
    }

    fun setTheme(value: ThemePreference) = action(showBusy = false) { container.preferences.setTheme(value) }
    fun setUnit(value: UnitPreference) = action(showBusy = false) { container.preferences.setUnit(value) }

    fun healthConnectPermissionContract(): ActivityResultContract<Set<String>, Set<String>> =
        healthConnectManager.permissionRequestContract()

    fun connectHealthConnect(requestPermissions: (Set<String>) -> Unit) = action(showBusy = false) {
        val account = preferences.value.accountScope ?: return@action
        healthConnectManager.connect(account)
        HealthConnectScheduler.schedulePeriodic()
        val permissions = healthConnectManager.permissionsToRequest(account)
        if (permissions.isEmpty()) HealthConnectScheduler.enqueue(HealthConnectTrigger.INITIAL_CONNECTION)
        else requestPermissions(permissions)
    }

    fun requestHealthConnectBackground(requestPermissions: (Set<String>) -> Unit) = action(showBusy = false) {
        val account = preferences.value.accountScope ?: return@action
        requestPermissions(healthConnectManager.permissionsToRequest(account, includeBackground = true))
    }

    fun onHealthConnectPermissionsResult() = action(showBusy = false) {
        val account = preferences.value.accountScope ?: return@action
        healthConnectManager.permissionResult(account)
        HealthConnectScheduler.enqueue(HealthConnectTrigger.PERMISSIONS_GRANTED)
    }

    fun setHealthConnectType(type: HealthConnectRecordType, selected: Boolean) = action(showBusy = false) {
        val account = preferences.value.accountScope ?: return@action
        healthConnectManager.setType(account, type, selected)
        HealthConnectScheduler.enqueue(HealthConnectTrigger.SELECTION_CHANGED)
    }

    fun syncHealthConnectNow() {
        HealthConnectScheduler.enqueue(HealthConnectTrigger.MANUAL)
        mutableMessage.value = "Importación de Health Connect encolada."
    }

    fun pauseHealthConnect(paused: Boolean) = action(showBusy = false) {
        val account = preferences.value.accountScope ?: return@action
        healthConnectManager.pause(account, paused)
        if (!paused) HealthConnectScheduler.enqueue(HealthConnectTrigger.MANUAL)
    }

    fun disconnectHealthConnect() = action(showBusy = false) {
        val account = preferences.value.accountScope ?: return@action
        healthConnectManager.disconnect(account)
        HealthConnectScheduler.cancelAll()
        mutableMessage.value = "Health Connect se desconectó sin borrar datos ni revocar permisos."
    }

    fun deleteHealthConnectImportedData() = action(showBusy = false) {
        val account = preferences.value.accountScope ?: return@action
        val result = healthConnectManager.deleteImported(account)
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
        mutableMessage.value = "Se retiraron ${result.deleted} recursos importados; las copias editadas se conservaron."
    }

    fun healthConnectManageAccessIntent(): Intent = healthConnectManager.manageAccessIntent()
    fun healthConnectProviderIntent(): Intent = healthConnectManager.providerIntent()

    fun inspectHealthConnectScaleSources() = action(showBusy = false) {
        val account = preferences.value.accountScope ?: return@action
        mutableScaleDiagnostic.value = container.healthConnectScaleDiagnostic.inspect(account)
    }

    fun confirmHealthConnectScale(fingerprint: String, kind: ConfirmedScaleKind) = action(showBusy = false) {
        val account = preferences.value.accountScope ?: return@action
        externalSourceStore.confirmHealthConnectOrigin(account, fingerprint, kind)
        mutableMessage.value = if (kind == ConfirmedScaleKind.NOT_SURE) "El origen quedó marcado como ambiguo." else "Confirmación local actualizada."
    }

    fun revokeHealthConnectScale(fingerprint: String) = action(showBusy = false) {
        val account = preferences.value.accountScope ?: return@action
        externalSourceStore.revokeHealthConnectOrigin(account, fingerprint)
        mutableMessage.value = "La confirmación local se revocó sin cambiar mediciones históricas."
    }

    fun requiredBlePermissions(): Set<String> = container.externalDeviceManager.requiredPermissions()
    fun onBlePermissionResult() = container.externalDeviceManager.refresh()
    fun startBleScan() = container.externalDeviceManager.startScan()
    fun cancelBleScan() = container.externalDeviceManager.cancelScan()
    fun cancelExperimentalCapture() = container.externalDeviceManager.cancelCapture()

    fun associateBleCandidate(sessionDeviceId: String) = action(showBusy = false) {
        val account = preferences.value.accountScope ?: return@action
        if (container.externalDeviceManager.selectAndAssociate(account, sessionDeviceId)) {
            mutableMessage.value = "Dispositivo asociado localmente. El protocolo S400 sigue sin validar."
        }
    }

    fun inspectAssociatedBleDevice() = action(showBusy = false) {
        val account = preferences.value.accountScope ?: return@action
        val result = container.externalDeviceManager.inspect(account)
        mutableMessage.value = if (result.state == io.healthtracker.companion.core.bluetooth.BleGattState.DISCOVERED) {
            "Inspección GATT completada sin escribir características."
        } else {
            "La inspección terminó con estado ${result.resultCode}."
        }
    }

    fun forgetAssociatedBleDevice() = action(showBusy = false) {
        val account = preferences.value.accountScope ?: return@action
        val persisted = bleDeviceAssociations.value.firstOrNull()
        if (persisted != null) externalSourceStore.forgetBleAssociation(account, persisted.deviceFingerprint)
        container.externalDeviceManager.forget(account)
        mutableMessage.value = "Se olvidó la asociación local; las mediciones y capturas se conservan por separado."
    }

    fun explainExperimentalCapture() {
        val account = preferences.value.accountScope ?: return
        container.externalDeviceManager.startCapture(account)
        mutableMessage.value = "Captura privada iniciada. Se detendrá por cancelación, desconexión, límite o timeout; no se interpretará peso."
    }

    fun selectBleCaptureCharacteristic(serviceUuid: String, characteristicUuid: String) {
        if (container.externalDeviceManager.selectCaptureCharacteristic(serviceUuid, characteristicUuid)) {
            mutableMessage.value = "Característica seleccionada para la captura experimental."
        }
    }

    fun deleteLatestBleCapture() = action(showBusy = false) {
        val account = preferences.value.accountScope ?: return@action
        mutableMessage.value = if (container.externalDeviceManager.deleteLatestCapture(account)) "Captura privada eliminada." else "No se encontró una captura para borrar."
    }

    fun prepareLatestBleCaptureExport(onReady: (Uri) -> Unit) = action(showBusy = false) {
        val captureId = container.externalDeviceManager.latestCaptureId() ?: return@action
        onReady(container.bleCaptureExporter.prepareExplicitExport(captureId))
    }

    fun revokeBleCaptureExport(uri: Uri) = container.bleCaptureExporter.revokeAndDelete(uri)

    fun resolveExternalDuplicate(duplicateId: String, sameMeasurement: Boolean) = action(showBusy = false) {
        val account = preferences.value.accountScope ?: return@action
        externalSourceStore.resolvePossibleDuplicate(account, duplicateId, sameMeasurement)
        mutableMessage.value = if (sameMeasurement) "Las mediciones quedaron enlazadas sin borrado silencioso." else "Se conservarán ambas mediciones."
    }

    fun requestPortableExport(request: PortableExportRequest) = action {
        val account = preferences.value.accountScope ?: return@action
        portabilityRepository.queueExport(account, request)
        mutableMessage.value = if (connected.value) {
            "Solicitud de exportación guardada; se enviará ahora."
        } else {
            "Solicitud guardada offline; se enviará al recuperar la red."
        }
    }

    fun refreshPortability() = action(showBusy = false) {
        val account = preferences.value.accountScope ?: return@action
        if (!connected.value) {
            mutableMessage.value = "Sin conexión: se muestran los estados guardados."
            return@action
        }
        portabilityRepository.processPending(account)
        portabilityRepository.refreshExports(account)
        portabilityRepository.refreshImports(account)
    }

    fun inspectPortablePackage(uri: Uri, permissionPersisted: Boolean) = action {
        val account = preferences.value.accountScope ?: return@action
        portabilityRepository.inspectLocal(account, uri, permissionPersisted)
        mutableMessage.value = if (connected.value) {
            "Inspección local correcta; el paquete se enviará para simulación."
        } else {
            "Inspección local correcta; upload y simulación quedan pendientes."
        }
    }

    fun uploadPortableImport(localId: String) = action {
        val account = preferences.value.accountScope ?: return@action
        if (!connected.value) {
            mutableMessage.value = "El upload queda pendiente hasta recuperar la red."
            return@action
        }
        portabilityRepository.uploadImport(account, localId)
        mutableMessage.value = "Simulación de importación lista."
    }

    fun resolvePortableConflictsSafely(importId: String) = action {
        val account = preferences.value.accountScope ?: return@action
        portabilityRepository.resolveConflictsSafely(account, importId)
        mutableMessage.value = "Los conflictos se conservarán en el destino."
    }

    fun applyPortableImport(importId: String) = action {
        val account = preferences.value.accountScope ?: return@action
        if (!connected.value) {
            portabilityRepository.queueApply(account, importId)
            mutableMessage.value = "La confirmación queda pendiente y se aplicará al recuperar la red."
            return@action
        }
        portabilityRepository.applyImport(account, importId)
        mutableMessage.value = "Importación completada sin escritura parcial."
    }

    fun downloadPortableExport(exportId: String) = action {
        val account = preferences.value.accountScope ?: return@action
        portabilityRepository.download(account, exportId)
        mutableMessage.value = "Paquete descargado y SHA-256 verificado."
    }

    fun sharePortableIntent(exportId: String): Intent {
        val account = preferences.value.accountScope ?: error("account_scope_required")
        return portabilityRepository.shareIntent(account, exportId)
    }

    fun savePortableExport(exportId: String, destination: Uri) = action {
        val account = preferences.value.accountScope ?: return@action
        portabilityRepository.fileStore.copyTo(account, exportId, destination)
        mutableMessage.value = "Paquete guardado en el destino elegido."
    }

    fun deleteLocalPortableExport(exportId: String) = action {
        val account = preferences.value.accountScope ?: return@action
        portabilityRepository.deleteLocalExport(account, exportId)
        mutableMessage.value = "Copia local eliminada."
    }

    fun deleteServerPortableExport(exportId: String) = action {
        val account = preferences.value.accountScope ?: return@action
        portabilityRepository.deleteServerExport(account, exportId)
        mutableMessage.value = "Artefacto del servidor eliminado."
    }

    fun cancelPortableExport(exportId: String) = action {
        val account = preferences.value.accountScope ?: return@action
        portabilityRepository.cancelExport(account, exportId)
        mutableMessage.value = "Solicitud de exportacion cancelada."
    }

    fun deleteServerPortableImport(importId: String) = action {
        val account = preferences.value.accountScope ?: return@action
        portabilityRepository.deleteServerImport(account, importId)
        mutableMessage.value = "Paquete temporal de importación eliminado."
    }

    fun deleteLocalPortableImport(importId: String) = action {
        val account = preferences.value.accountScope ?: return@action
        portabilityRepository.deleteLocalImport(account, importId)
        mutableMessage.value = "Inspeccion local eliminada."
    }

    fun createWeeklySessionsGoal() = action(showBusy = false) {
        val account = preferences.value.accountScope ?: return@action
        val timezone = profile.value?.timezone ?: "UTC"
        engagementRepository.createGoal(account, buildJsonObject {
            put("public_id", UUID.randomUUID().toString()); put("goal_type", "training_sessions_per_week")
            put("target_value", "3"); put("unit", "session"); put("period", "weekly")
            put("applicable_days", JsonArray((1..7).map(::JsonPrimitive))); put("timezone", timezone)
            put("start_date", LocalDate.now(ZoneId.of(timezone)).toString())
        })
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
        mutableMessage.value = "Objetivo guardado en este dispositivo."
    }

    fun createDailyStepsGoal() = action(showBusy = false) {
        val account = preferences.value.accountScope ?: return@action
        val timezone = profile.value?.timezone ?: "UTC"
        engagementRepository.createGoal(account, buildJsonObject {
            put("public_id", UUID.randomUUID().toString()); put("goal_type", "daily_steps")
            put("target_value", "5000"); put("unit", "step"); put("period", "daily")
            put("applicable_days", JsonArray((1..7).map(::JsonPrimitive))); put("timezone", timezone)
            put("start_date", LocalDate.now(ZoneId.of(timezone)).toString())
        })
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
        mutableMessage.value = "Objetivo diario guardado en este dispositivo."
    }

    fun setGoalPaused(goal: GoalEntity, paused: Boolean) = action(showBusy = false) {
        engagementRepository.updateGoal(goal.accountScope, goal.publicId, buildJsonObject { put("state", if (paused) "paused" else "active") })
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
    }

    fun updateGoalTarget(goal: GoalEntity, target: String) = action(showBusy = false) {
        engagementRepository.updateGoal(goal.accountScope, goal.publicId, buildJsonObject { put("target_value", target) })
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
    }

    fun archiveGoal(goal: GoalEntity) = action(showBusy = false) {
        engagementRepository.archiveGoal(goal.accountScope, goal.publicId)
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
        mutableMessage.value = "Objetivo archivado."
    }

    fun createTrainingReminder() = action(showBusy = false) {
        val account = preferences.value.accountScope ?: return@action
        val timezone = profile.value?.timezone ?: "UTC"
        engagementRepository.createRule(account, buildJsonObject {
            put("public_id", UUID.randomUUID().toString()); put("reminder_type", "scheduled_workout_pending")
            put("local_time", "18:00"); put("applicable_days", JsonArray((1..7).map(::JsonPrimitive)))
            put("lead_minutes", 0); put("quiet_start", "22:00"); put("quiet_end", "07:00"); put("quiet_timezone", timezone)
            put("snooze_options", JsonArray(listOf(JsonPrimitive(15), JsonPrimitive(30), JsonPrimitive(60), JsonPrimitive("tomorrow"))))
            put("max_per_day", 1); put("cooldown_minutes", 120); put("enabled", false); put("timezone", timezone)
        })
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
        mutableMessage.value = "Recordatorio creado desactivado; revisa horario y permiso antes de activarlo."
    }

    fun createWeightReminder() = action(showBusy = false) {
        val account = preferences.value.accountScope ?: return@action
        val timezone = profile.value?.timezone ?: "UTC"
        engagementRepository.createRule(account, buildJsonObject {
            put("public_id", UUID.randomUUID().toString()); put("reminder_type", "log_weight")
            put("local_time", "08:00"); put("applicable_days", JsonArray(listOf(JsonPrimitive(1))))
            put("lead_minutes", 0); put("quiet_start", "22:00"); put("quiet_end", "07:00"); put("quiet_timezone", timezone)
            put("snooze_options", JsonArray(listOf(JsonPrimitive(15), JsonPrimitive(30), JsonPrimitive(60), JsonPrimitive("tomorrow"))))
            put("max_per_day", 1); put("cooldown_minutes", 180); put("enabled", false); put("timezone", timezone)
        })
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
    }

    fun setReminderEnabled(rule: ReminderRuleEntity, enabled: Boolean) = action(showBusy = false) {
        engagementRepository.updateRule(rule.accountScope, rule.publicId, buildJsonObject { put("enabled", enabled) })
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
    }

    fun updateReminderSchedule(rule: ReminderRuleEntity, time: String, quietStart: String, quietEnd: String) = action(showBusy = false) {
        engagementRepository.updateRule(rule.accountScope, rule.publicId, buildJsonObject {
            put("local_time", time); put("quiet_start", quietStart); put("quiet_end", quietEnd)
            put("quiet_timezone", rule.timezone)
        })
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
    }

    fun deleteReminder(rule: ReminderRuleEntity) = action(showBusy = false) {
        engagementRepository.deleteRule(rule.accountScope, rule.publicId)
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
    }

    fun acknowledgeReminder(event: ReminderEventEntity) = action(showBusy = false) {
        engagementRepository.acknowledge(event.accountScope, event.serverIdentity, event.publicId)
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
    }

    fun snoozeReminder(event: ReminderEventEntity, minutes: Int?) = action(showBusy = false) {
        engagementRepository.snooze(event.accountScope, event.serverIdentity, event.publicId, minutes)
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
    }

    fun cleanOldReminderEvents() = action(showBusy = false) {
        val account = preferences.value.accountScope ?: return@action
        val count = engagementRepository.cleanOldEvents(account)
        mutableMessage.value = "$count eventos locales antiguos eliminados."
    }

    fun recordNotificationPermission(requested: Boolean, rationaleShown: Boolean, granted: Boolean) = action(showBusy = false) {
        val account = preferences.value.accountScope ?: return@action
        engagementRepository.recordPermission(account, requested, rationaleShown, granted)
    }

    fun sendTestNotification(context: Context) {
        mutableMessage.value = if (NotificationPublisher.showTest(context)) "Notificación de prueba enviada localmente." else "Concede el permiso de notificaciones para realizar la prueba."
    }

    fun setAdherenceDays(days: Int) { if (days in setOf(7, 30, 90)) mutableAdherenceDays.value = days }

    fun refreshEngagement() = action(showBusy = false) {
        val account = preferences.value.accountScope ?: return@action
        if (connected.value) engagementRepository.refresh(account)
    }

    fun logout(revoke: Boolean = false, localOnly: Boolean = false) = action {
        val account = preferences.value.accountScope ?: return@action
        if (localOnly) repository.clearLocal(account) else repository.logout(account, revoke)
        selectPlanWorkout(null)
        selectPlan(null)
        mutableProfile.value = null
        mutableAuth.value = AuthState.SIGNED_OUT
    }

    fun logoutAll() = action {
        val account = preferences.value.accountScope ?: return@action
        repository.logoutAll(account)
        selectPlanWorkout(null)
        selectPlan(null)
        mutableProfile.value = null
        mutableAuth.value = AuthState.SIGNED_OUT
    }

    fun switchServer() = action {
        val account = preferences.value.accountScope ?: return@action
        repository.detachForServerSwitch(account)
        selectPlanWorkout(null)
        selectPlan(null)
        mutableProfile.value = null
        mutableAuth.value = AuthState.SIGNED_OUT
        mutableMessage.value = "Sesión separada. Confirma la nueva URL e inicia sesión; los datos anteriores siguen aislados."
    }

    fun openMedicalStudy(publicId: String?) { mutableSelectedMedicalStudyId.value = publicId }

    fun refreshMedicalRecords() = action(showBusy = false) {
        val (account, identity) = medicalIdentity() ?: return@action
        medicalRepository.refresh(account, identity)
    }

    fun createMedicalStudy(title: String, studyType: String, studyDate: String, laboratory: String?, notes: String?, onCreated: (String) -> Unit = {}) = action {
        val (account, identity) = medicalIdentity() ?: return@action
        val id = medicalRepository.createStudy(account, identity, title, studyType, studyDate, laboratory,
            profile.value?.timezone ?: ZoneId.systemDefault().id, notes)
        mutableSelectedMedicalStudyId.value = id
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
        mutableMessage.value = "Estudio guardado en el dispositivo."
        onCreated(id)
    }

    fun editSelectedMedicalStudy(title: String, notes: String?) = action(showBusy = false) {
        val (account, identity) = medicalIdentity() ?: return@action
        val id = mutableSelectedMedicalStudyId.value ?: return@action
        medicalRepository.editStudy(account, identity, id, title, notes)
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
        mutableMessage.value = "Cambios médicos guardados localmente."
    }

    fun archiveSelectedMedicalStudy(onArchived: () -> Unit = {}) = action {
        val (account, identity) = medicalIdentity() ?: return@action
        val id = mutableSelectedMedicalStudyId.value ?: return@action
        medicalRepository.archiveStudy(account, identity, id)
        mutableSelectedMedicalStudyId.value = null
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
        mutableMessage.value = "Estudio archivado."
        onArchived()
    }

    fun completeSelectedMedicalStudy() = action(showBusy = false) {
        val (account, identity) = medicalIdentity() ?: return@action
        val id = mutableSelectedMedicalStudyId.value ?: return@action
        medicalRepository.completeStudy(account, identity, id)
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
        mutableMessage.value = "Captura marcada como completa."
    }

    fun addMedicalResult(panelName: String, displayName: String, valueType: String, originalValue: String,
                         numericValue: String?, unit: String?, lower: String?, upper: String?, sourceStatus: String) = action {
        val (account, identity) = medicalIdentity() ?: return@action
        val studyId = mutableSelectedMedicalStudyId.value ?: return@action
        medicalRepository.addResult(account, identity, studyId, panelName, displayName, valueType,
            originalValue, numericValue, unit, lower, upper, sourceStatus)
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
        mutableMessage.value = "Resultado guardado localmente."
    }

    fun editMedicalResult(publicId: String, originalValue: String, numericValue: String?, unit: String?,
                          lower: String?, upper: String?, sourceStatus: String, reason: String?) = action(showBusy = false) {
        val (account, identity) = medicalIdentity() ?: return@action
        medicalRepository.editResult(account, identity, publicId, originalValue, numericValue, unit, lower, upper, sourceStatus, reason)
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
        mutableMessage.value = "Corrección guardada localmente."
    }

    fun deleteMedicalResult(publicId: String) = action {
        val (account, identity) = medicalIdentity() ?: return@action
        medicalRepository.deleteResult(account, identity, publicId)
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
        mutableMessage.value = "Resultado eliminado."
    }

    fun attachMedicalDocument(uri: Uri, filename: String, mimeType: String) = action {
        val (account, identity) = medicalIdentity() ?: return@action
        val studyId = mutableSelectedMedicalStudyId.value ?: return@action
        medicalRepository.attachDocument(account, identity, studyId, uri, filename, mimeType)
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
        mutableMessage.value = "Documento guardado para carga segura."
    }

    fun deleteMedicalDocument(publicId: String) = action {
        val (account, identity) = medicalIdentity() ?: return@action
        medicalRepository.deleteDocument(account, identity, publicId)
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
        mutableMessage.value = "Documento eliminado; el estudio estructurado se conserva."
    }

    fun shareMedicalDocument(publicId: String, onReady: (Intent) -> Unit) = action {
        val (account, identity) = medicalIdentity() ?: return@action
        onReady(medicalRepository.explicitShareIntent(account, identity, publicId))
        mutableMessage.value = "Selecciona explícitamente dónde compartir el documento."
    }

    fun permanentlyDeleteSelectedMedicalStudy(onDeleted: () -> Unit = {}) = action {
        val (account, identity) = medicalIdentity() ?: return@action
        val id = mutableSelectedMedicalStudyId.value ?: return@action
        medicalRepository.permanentlyDeleteStudy(account, identity, id)
        mutableSelectedMedicalStudyId.value = null
        SyncScheduler.enqueueNow(SyncTrigger.PENDING_OPERATION)
        mutableMessage.value = "Eliminación definitiva guardada."
        onDeleted()
    }

    fun selectMedicalHistory(key: String, period: String = "all") = action(showBusy = false) {
        mutableMedicalHistoryKey.value = key
        mutableMedicalHistoryPeriod.value = period
        val (account, identity) = medicalIdentity() ?: return@action
        if (connected.value) medicalRepository.refreshHistory(account, identity, key, period)
    }

    fun setMedicalHistoryPeriod(period: String) {
        val key = mutableMedicalHistoryKey.value ?: return
        selectMedicalHistory(key, period)
    }

    private fun medicalIdentity(): Pair<String, String>? {
        val local = preferences.value
        val account = local.accountScope ?: return null
        val server = local.serverUrl ?: return null
        return account to CanonicalJson.serverIdentity(server)
    }

    fun clearMessage() { mutableMessage.value = null }

    private fun setActionKey(value: DraftSetEntity, action: String) =
        "$action:${value.deliveryId}:${value.exerciseOrder}:${value.setNumber}"

    private fun setAutosaveKey(value: DraftSetEntity) =
        "set:${value.deliveryId}:${value.exerciseOrder}:${value.setNumber}"

    private suspend fun restoreOnline(accountScope: String) {
        runCatching { repository.restoreOnlineSession(accountScope) }
            .onSuccess { restored ->
                mutableProfile.value = restored
                mutableAuth.value = AuthState.AUTHENTICATED
                SyncScheduler.enqueueNow(SyncTrigger.REFRESH_SUCCESS)
            }
            .onFailure { error ->
                val decision = classifyRestoreFailure(error)
                if (decision.clearLocalSession) repository.clearConfirmedInvalidSession(accountScope)
                if (decision.clearLocalSession) mutableProfile.value = null
                mutableAuth.value = decision.state
                mutableMessage.value = decision.message
            }
    }

    private fun claimSetAction(key: String): Boolean = synchronized(mutableSetActions) {
        if (key in mutableSetActions.value) false else {
            mutableSetActions.value = mutableSetActions.value + key
            true
        }
    }

    private fun releaseSetAction(key: String) = synchronized(mutableSetActions) {
        mutableSetActions.value = mutableSetActions.value - key
    }

    private fun healthAction(successMessage: String, block: suspend (String) -> Unit) {
        action(showBusy = false) {
            mutableAutosaveState.value = AutosaveUiState.SAVING
            try {
                val account = preferences.value.accountScope ?: return@action
                block(account)
                mutableAutosaveState.value = if (connected.value) AutosaveUiState.SAVED else AutosaveUiState.SAVED_LOCAL
                mutableMessage.value = successMessage
            } catch (error: Exception) {
                mutableAutosaveState.value = AutosaveUiState.ERROR
                throw error
            }
        }
    }

    private fun action(
        showBusy: Boolean = true,
        onFinally: () -> Unit = {},
        block: suspend () -> Unit,
    ) {
        if (showBusy && !mutableBusy.compareAndSet(expect = false, update = true)) {
            onFinally()
            return
        }
        viewModelScope.launch {
            try {
                block()
            } catch (failure: AppFailure) {
                mutableMessage.value = failure.userMessage
                if (mutableAuth.value == AuthState.AUTHENTICATING || failure.code.name.contains("REVOKED")) {
                    mutableAuth.value = when (failure.code) {
                        io.healthtracker.companion.core.model.AppErrorCode.DEVICE_REVOKED -> AuthState.DEVICE_REVOKED
                        io.healthtracker.companion.core.model.AppErrorCode.SERVER_INCOMPATIBLE,
                        io.healthtracker.companion.core.model.AppErrorCode.SCHEMA_INCOMPATIBLE -> AuthState.SERVER_INCOMPATIBLE
                        io.healthtracker.companion.core.model.AppErrorCode.NETWORK_UNAVAILABLE,
                        io.healthtracker.companion.core.model.AppErrorCode.TIMEOUT -> AuthState.OFFLINE
                        io.healthtracker.companion.core.model.AppErrorCode.REFRESH_FAILED -> AuthState.TOKEN_EXPIRED
                        else -> AuthState.SIGNED_OUT
                    }
                }
            } catch (_: Exception) {
                mutableMessage.value = "No fue posible completar la operación."
                if (mutableAuth.value == AuthState.AUTHENTICATING) mutableAuth.value = AuthState.SIGNED_OUT
            } finally {
                if (showBusy) mutableBusy.value = false
                onFinally()
            }
        }
    }

    class Factory(private val container: AppContainer) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T = CompanionViewModel(container) as T

        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>, extras: CreationExtras): T =
            CompanionViewModel(container, extras.createSavedStateHandle()) as T
    }

}
