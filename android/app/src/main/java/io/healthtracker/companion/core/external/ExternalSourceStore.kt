package io.healthtracker.companion.core.external

import androidx.room.withTransaction
import io.healthtracker.companion.core.database.CompanionDatabase
import io.healthtracker.companion.core.database.ExternalSourceCapabilityEntity
import io.healthtracker.companion.core.database.ExternalSourceEntity
import io.healthtracker.companion.core.database.HealthConnectSourceAssociationEntity
import io.healthtracker.companion.core.database.BleDeviceAssociationEntity
import io.healthtracker.companion.core.database.BleCaptureMetadataEntity
import io.healthtracker.companion.core.database.PossibleDuplicateEntity
import java.time.Instant
import kotlinx.coroutines.flow.Flow

enum class SourceAssociationState { UNCONFIRMED, USER_CONFIRMED, AMBIGUOUS, REVOKED, UNAVAILABLE }
enum class ConfirmedScaleKind { GENERIC_SCALE, XIAOMI_S400, OTHER_DEVICE, NOT_SURE }

class ExternalSourceStore(
    private val database: CompanionDatabase,
    private val registry: ExternalSourceRegistry = ExternalSourceRegistry(),
) {
    private val dao = database.companionDao()

    suspend fun ensureDefaults(scope: String) = database.withTransaction {
        val now = Instant.now().toString()
        registry.defaults().forEach { source ->
            dao.upsertExternalSource(
                ExternalSourceEntity(
                    accountScope = scope,
                    sourceId = source.id,
                    sourceType = source.type.name.lowercase(),
                    displayName = source.displayName,
                    availability = source.availability.name.lowercase(),
                    experimental = source.experimental,
                    requiredPermissions = source.requiredPermissions.sorted().joinToString(","),
                    supportedMetrics = source.supportedMetrics.sorted().joinToString(","),
                    identityQuality = source.identityQuality.name.lowercase(),
                    deduplicationStrategy = source.deduplicationStrategy,
                    visualPriority = source.visualPriority,
                    editable = source.editable,
                    userOverrideAllowed = source.userOverrideAllowed,
                    lastDetectedAt = source.lastDetectedAt?.toString(),
                    syncState = source.syncState.name.lowercase(),
                    updatedAt = now,
                ),
            )
            dao.replaceExternalSourceCapabilities(
                scope,
                source.id,
                source.capabilities.map { ExternalSourceCapabilityEntity(scope, source.id, it.name.lowercase()) },
            )
        }
    }

    fun observeSources(scope: String): Flow<List<ExternalSourceEntity>> = dao.observeExternalSources(scope)
    fun observeHealthConnectAssociations(scope: String): Flow<List<HealthConnectSourceAssociationEntity>> =
        dao.observeHealthConnectSourceAssociations(scope)
    fun observeBleDeviceAssociations(scope: String): Flow<List<BleDeviceAssociationEntity>> = dao.observeBleDeviceAssociations(scope)
    fun observeBleCaptures(scope: String, associationKey: String): Flow<List<BleCaptureMetadataEntity>> =
        dao.observeBleCaptureMetadata(scope, associationKey)
    fun observePossibleDuplicates(scope: String): Flow<List<PossibleDuplicateEntity>> = dao.observePossibleDuplicates(scope)

    suspend fun observeOrigin(scope: String, rawOrigin: String, safeLabel: String = "Aplicación de salud"): HealthConnectSourceAssociationEntity {
        val fingerprint = shortFingerprint("health-connect-origin:$rawOrigin")
        val now = Instant.now().toString()
        val current = dao.healthConnectSourceAssociation(scope, fingerprint)
        val association = current?.copy(lastSeenAt = now) ?: HealthConnectSourceAssociationEntity(
            accountScope = scope,
            sourceFingerprint = fingerprint,
            sourceId = "health_connect_generic",
            safeLabel = safeLabel.take(80),
            state = SourceAssociationState.UNCONFIRMED.name.lowercase(),
            confirmedModel = null,
            identityQuality = ExternalSourceIdentityQuality.WEAK.name.lowercase(),
            firstSeenAt = now,
            lastSeenAt = now,
            confirmedAt = null,
            revokedAt = null,
        )
        dao.upsertHealthConnectSourceAssociation(association)
        return association
    }

    suspend fun confirmHealthConnectOrigin(scope: String, fingerprint: String, kind: ConfirmedScaleKind) {
        val current = dao.healthConnectSourceAssociation(scope, fingerprint) ?: return
        val now = Instant.now().toString()
        val uncertain = kind == ConfirmedScaleKind.NOT_SURE
        val sourceId = when (kind) {
            ConfirmedScaleKind.GENERIC_SCALE, ConfirmedScaleKind.OTHER_DEVICE -> "health_connect_confirmed_scale"
            ConfirmedScaleKind.XIAOMI_S400 -> "health_connect_confirmed_xiaomi_s400"
            ConfirmedScaleKind.NOT_SURE -> "health_connect_generic"
        }
        dao.upsertHealthConnectSourceAssociation(
            current.copy(
                sourceId = sourceId,
                state = if (uncertain) SourceAssociationState.AMBIGUOUS.name.lowercase() else SourceAssociationState.USER_CONFIRMED.name.lowercase(),
                confirmedModel = when (kind) {
                    ConfirmedScaleKind.GENERIC_SCALE -> "generic_scale"
                    ConfirmedScaleKind.XIAOMI_S400 -> "xiaomi_s400_user_confirmed"
                    ConfirmedScaleKind.OTHER_DEVICE -> "other_device"
                    ConfirmedScaleKind.NOT_SURE -> null
                },
                identityQuality = if (uncertain) ExternalSourceIdentityQuality.WEAK.name.lowercase() else ExternalSourceIdentityQuality.USER_CONFIRMED.name.lowercase(),
                confirmedAt = if (uncertain) null else now,
                revokedAt = null,
            ),
        )
    }

    suspend fun revokeHealthConnectOrigin(scope: String, fingerprint: String) {
        val current = dao.healthConnectSourceAssociation(scope, fingerprint) ?: return
        val now = Instant.now().toString()
        dao.upsertHealthConnectSourceAssociation(
            current.copy(
                sourceId = "health_connect_generic",
                state = SourceAssociationState.REVOKED.name.lowercase(),
                confirmedModel = null,
                identityQuality = ExternalSourceIdentityQuality.WEAK.name.lowercase(),
                revokedAt = now,
            ),
        )
    }

    suspend fun forgetBleAssociation(scope: String, fingerprint: String) {
        dao.deleteBleDeviceAssociation(scope, fingerprint)
    }

    suspend fun resolvePossibleDuplicate(scope: String, duplicateId: String, sameMeasurement: Boolean) {
        dao.resolvePossibleDuplicate(
            scope,
            duplicateId,
            if (sameMeasurement) "same_measurement" else "keep_both",
            Instant.now().toString(),
        )
    }
}
