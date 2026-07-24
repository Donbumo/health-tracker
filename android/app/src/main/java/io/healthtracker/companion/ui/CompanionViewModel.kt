package io.healthtracker.companion.ui

import android.os.Build
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
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
import io.healthtracker.companion.core.load.LoadPreview
import io.healthtracker.companion.core.model.AppFailure
import io.healthtracker.companion.core.model.AuthState
import io.healthtracker.companion.core.model.LoadDetailsDto
import io.healthtracker.companion.core.model.SyncStatus
import io.healthtracker.companion.core.model.UserProfile
import io.healthtracker.companion.core.sync.SyncScheduler
import io.healthtracker.companion.core.sync.SyncTrigger
import io.healthtracker.companion.core.sync.HistoryFilters
import java.time.LocalDate
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.collect
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
class CompanionViewModel(private val container: AppContainer) : ViewModel() {
    private val repository = container.repository
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
    val preferences = container.preferences.values.stateIn(
        viewModelScope, SharingStarted.WhileSubscribed(5_000),
        io.healthtracker.companion.core.config.AppPreferences(deviceId = ""),
    )
    val connected = container.connectivity.connected.stateIn(
        viewModelScope, SharingStarted.WhileSubscribed(5_000), false,
    )
    private val scope = preferences.mapLatest { it.accountScope }

    val planned = scope.flatMapLatest { value ->
        if (value == null) flowOf(emptyList()) else repository.observePlanned(value)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val today = planned.mapLatest { values ->
        values.firstOrNull { it.scheduledForDate == LocalDate.now().toString() && it.status in setOf("planned", "in_progress") }
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    val nextWorkout = planned.mapLatest { values ->
        values.firstOrNull { it.scheduledForDate > LocalDate.now().toString() && it.status == "planned" }
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
            if (actual.serverUrl == null) mutableAuth.value = AuthState.NO_SERVER
            else if (actual.accountScope != null && container.tokens.refreshToken() != null) {
                val localProfile = repository.restoreLocalSession()
                if (localProfile == null) {
                    mutableAuth.value = AuthState.SIGNED_OUT
                } else {
                    mutableProfile.value = localProfile
                    mutableAuth.value = AuthState.AUTHENTICATED
                    SyncScheduler.schedulePeriodic()
                    if (container.connectivity.connected.first()) restoreOnline(actual.accountScope)
                }
            } else mutableAuth.value = AuthState.SIGNED_OUT
        }
        viewModelScope.launch {
            container.connectivity.connected
                .distinctUntilChanged()
                .filter { it }
                .collect {
                    if (mutableAuth.value == AuthState.AUTHENTICATED && container.tokens.accessToken() == null) {
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
        if (!mutableDownloadInProgress.compareAndSet(expect = false, update = true)) return
        action(showBusy = false, onFinally = { mutableDownloadInProgress.value = false }) {
            val account = preferences.value.accountScope ?: return@action
            val workout = today.value ?: return@action
            repository.downloadWorkout(account, workout.id)
            mutableMessage.value = "Entrenamiento descargado y verificado."
        }
    }

    fun startToday(onStarted: () -> Unit) {
        if (!mutableStartInProgress.compareAndSet(expect = false, update = true)) return
        action(onFinally = { mutableStartInProgress.value = false }) {
            val account = preferences.value.accountScope ?: return@action
            val delivery = downloadedDelivery.value ?: return@action
            repository.startWorkout(account, delivery)
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

    fun logout(revoke: Boolean = false, localOnly: Boolean = false) = action {
        val account = preferences.value.accountScope ?: return@action
        if (localOnly) repository.clearLocal(account) else repository.logout(account, revoke)
        mutableProfile.value = null
        mutableAuth.value = AuthState.SIGNED_OUT
    }

    fun logoutAll() = action {
        val account = preferences.value.accountScope ?: return@action
        repository.logoutAll(account)
        mutableProfile.value = null
        mutableAuth.value = AuthState.SIGNED_OUT
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
    }
}
