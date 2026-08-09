package io.healthtracker.companion.core.healthconnect

import android.content.Intent
import androidx.activity.result.contract.ActivityResultContract
import io.healthtracker.companion.core.database.HealthConnectPermissionStateEntity
import io.healthtracker.companion.core.database.HealthConnectSettingsEntity
import io.healthtracker.companion.core.database.HealthConnectSyncStateEntity
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.combine

data class HealthConnectUiState(
    val status: HealthConnectUiStatus = HealthConnectUiStatus.AVAILABLE_NOT_CONNECTED,
    val selectedTypes: Set<HealthConnectRecordType> = HealthConnectRecordType.defaults,
    val grantedTypes: Set<HealthConnectRecordType> = emptySet(),
    val backgroundAvailable: Boolean = false,
    val backgroundGranted: Boolean = false,
    val lastImportAt: String? = null,
    val importedCount: Int = 0,
    val deletedCount: Int = 0,
    val errorCode: String? = null,
)

class HealthConnectManager(
    private val gateway: HealthConnectGateway,
    private val store: HealthConnectStore,
) {
    suspend fun ensure(scope: String) {
        val availability = gateway.availability()
        store.ensureSettings(scope, availability)
        store.updateAvailability(scope, availability)
        if (availability == HealthConnectAvailability.AVAILABLE) refreshPermissions(scope)
    }

    fun observe(scope: String): Flow<HealthConnectUiState> = combine(
        store.observeSettings(scope),
        store.observePermissions(scope),
        store.observeSyncStates(scope),
    ) { settings, permissions, sync -> uiState(settings, permissions, sync) }

    fun permissionRequestContract(): ActivityResultContract<Set<String>, Set<String>> = gateway.permissionRequestContract()

    suspend fun permissionsToRequest(scope: String, includeBackground: Boolean = false): Set<String> {
        val settings = store.settings(scope) ?: store.ensureSettings(scope, gateway.availability())
        return gateway.permissionsFor(HealthConnectStore.decodeTypes(settings.selectedTypes), includeBackground)
    }

    suspend fun connect(scope: String) {
        store.ensureSettings(scope, gateway.availability())
        store.setEnabled(scope, enabled = true, paused = false)
    }

    suspend fun permissionResult(scope: String) { refreshPermissions(scope) }

    suspend fun setType(scope: String, type: HealthConnectRecordType, selected: Boolean) {
        if (!type.importSupported) return
        val settings = store.settings(scope) ?: return
        val current = HealthConnectStore.decodeTypes(settings.selectedTypes).toMutableSet()
        if (selected) current += type else current -= type
        store.setSelectedTypes(scope, current)
        refreshPermissions(scope)
    }

    suspend fun pause(scope: String, paused: Boolean) = store.setPaused(scope, paused)
    suspend fun disconnect(scope: String) = store.setEnabled(scope, enabled = false, paused = false)
    suspend fun deleteImported(scope: String): HealthConnectImportResult = store.deleteImported(scope)
    fun manageAccessIntent(): Intent = gateway.manageAccessIntent()
    fun providerIntent(): Intent = gateway.providerIntent()

    private suspend fun refreshPermissions(scope: String) {
        if (gateway.availability() != HealthConnectAvailability.AVAILABLE) return
        val settings = store.settings(scope) ?: return
        val selected = HealthConnectStore.decodeTypes(settings.selectedTypes)
        val grantedPermissions = gateway.grantedPermissions()
        val granted = selected.filterTo(mutableSetOf()) { gateway.permissionsFor(setOf(it)).all(grantedPermissions::contains) }
        val backgroundPermission = gateway.permissionsFor(emptySet(), includeBackground = true).firstOrNull()
        store.persistPermissions(
            scope,
            selected,
            granted,
            gateway.backgroundReadAvailable() && backgroundPermission != null && backgroundPermission in grantedPermissions,
        )
    }

    private fun uiState(
        settings: HealthConnectSettingsEntity?,
        permissions: List<HealthConnectPermissionStateEntity>,
        sync: List<HealthConnectSyncStateEntity>,
    ): HealthConnectUiState {
        val availability = when (settings?.lastAvailability) {
            "unavailable_device" -> HealthConnectAvailability.UNAVAILABLE_DEVICE
            "update_required" -> HealthConnectAvailability.UPDATE_REQUIRED
            "available" -> HealthConnectAvailability.AVAILABLE
            else -> HealthConnectAvailability.UNAVAILABLE_PROVIDER
        }
        val selected = settings?.selectedTypes?.let(HealthConnectStore::decodeTypes) ?: HealthConnectRecordType.defaults
        val granted = permissions.filter { it.granted }.mapNotNull { HealthConnectRecordType.fromStorage(it.recordType) }.toSet()
        val status = when {
            availability == HealthConnectAvailability.UNAVAILABLE_DEVICE -> HealthConnectUiStatus.UNAVAILABLE_DEVICE
            availability == HealthConnectAvailability.UNAVAILABLE_PROVIDER -> HealthConnectUiStatus.UNAVAILABLE_PROVIDER
            availability == HealthConnectAvailability.UPDATE_REQUIRED -> HealthConnectUiStatus.UPDATE_REQUIRED
            settings?.paused == true -> HealthConnectUiStatus.PAUSED
            settings?.enabled != true -> HealthConnectUiStatus.AVAILABLE_NOT_CONNECTED
            sync.any { it.state == "syncing" } -> HealthConnectUiStatus.SYNCING
            sync.any { it.state == "access_revoked" } -> HealthConnectUiStatus.ACCESS_REVOKED
            sync.any { it.state == "error_recoverable" } -> HealthConnectUiStatus.ERROR_RECOVERABLE
            selected.any { it.importSupported && it !in granted } -> HealthConnectUiStatus.PERMISSIONS_PARTIAL
            else -> HealthConnectUiStatus.CONNECTED
        }
        return HealthConnectUiState(
            status = status,
            selectedTypes = selected,
            grantedTypes = granted,
            backgroundAvailable = gateway.backgroundReadAvailable(),
            backgroundGranted = permissions.any { it.backgroundGranted },
            lastImportAt = sync.mapNotNull { it.lastImportedAt }.maxOrNull(),
            importedCount = sync.sumOf { it.importedCount },
            deletedCount = sync.sumOf { it.deletedCount },
            errorCode = sync.mapNotNull { it.lastErrorCode }.firstOrNull(),
        )
    }
}
