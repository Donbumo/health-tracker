package io.healthtracker.companion.core.database

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction
import androidx.room.Update
import androidx.room.Upsert
import kotlinx.coroutines.flow.Flow

@Dao
interface CompanionDao {
    @Upsert
    suspend fun upsertGoals(values: List<GoalEntity>)

    @Upsert
    suspend fun upsertGoal(value: GoalEntity)

    @Query("SELECT * FROM goals WHERE accountScope=:scope AND serverIdentity=:serverIdentity AND state!='archived' ORDER BY updatedAt DESC")
    fun observeGoals(scope: String, serverIdentity: String): Flow<List<GoalEntity>>

    @Query("SELECT * FROM goals WHERE accountScope=:scope AND serverIdentity=:serverIdentity AND publicId=:publicId")
    suspend fun goal(scope: String, serverIdentity: String, publicId: String): GoalEntity?

    @Query("DELETE FROM goals WHERE accountScope=:scope AND serverIdentity=:serverIdentity AND publicId=:publicId")
    suspend fun deleteGoal(scope: String, serverIdentity: String, publicId: String)

    @Upsert
    suspend fun upsertReminderRules(values: List<ReminderRuleEntity>)

    @Upsert
    suspend fun upsertReminderRule(value: ReminderRuleEntity)

    @Query("SELECT * FROM reminder_rules WHERE accountScope=:scope AND serverIdentity=:serverIdentity ORDER BY enabled DESC, updatedAt DESC")
    fun observeReminderRules(scope: String, serverIdentity: String): Flow<List<ReminderRuleEntity>>

    @Query("SELECT * FROM reminder_rules WHERE accountScope=:scope AND serverIdentity=:serverIdentity AND enabled=1 AND requiresDeviceConfirmation=0")
    suspend fun enabledReminderRules(scope: String, serverIdentity: String): List<ReminderRuleEntity>

    @Query("SELECT * FROM reminder_rules WHERE accountScope=:scope AND serverIdentity=:serverIdentity AND publicId=:publicId")
    suspend fun reminderRule(scope: String, serverIdentity: String, publicId: String): ReminderRuleEntity?

    @Query("DELETE FROM reminder_rules WHERE accountScope=:scope AND serverIdentity=:serverIdentity AND publicId=:publicId")
    suspend fun deleteReminderRule(scope: String, serverIdentity: String, publicId: String)

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertReminderEvent(value: ReminderEventEntity): Long

    @Upsert
    suspend fun upsertReminderEvents(values: List<ReminderEventEntity>)

    @Upsert
    suspend fun upsertReminderEvent(value: ReminderEventEntity)

    @Query("SELECT * FROM reminder_events WHERE accountScope=:scope AND serverIdentity=:serverIdentity ORDER BY scheduledFor DESC LIMIT :limit")
    fun observeReminderEvents(scope: String, serverIdentity: String, limit: Int = 100): Flow<List<ReminderEventEntity>>

    @Query("SELECT * FROM reminder_events WHERE accountScope=:scope AND serverIdentity=:serverIdentity AND publicId=:publicId")
    suspend fun reminderEvent(scope: String, serverIdentity: String, publicId: String): ReminderEventEntity?

    @Query("SELECT * FROM reminder_events WHERE accountScope=:scope AND serverIdentity=:serverIdentity AND deduplicationKey=:key LIMIT 1")
    suspend fun reminderEventByDedupe(scope: String, serverIdentity: String, key: String): ReminderEventEntity?

    @Query("SELECT COUNT(*) FROM reminder_events WHERE accountScope=:scope AND serverIdentity=:serverIdentity AND eventType=:eventType AND triggeredAt>=:dayStart AND state IN ('triggered','acknowledged','dismissed','snoozed')")
    suspend fun reminderCountSince(scope: String, serverIdentity: String, eventType: String, dayStart: String): Int

    @Query("SELECT COUNT(*) FROM reminder_events WHERE accountScope=:scope AND serverIdentity=:serverIdentity AND triggeredAt>=:dayStart AND state IN ('triggered','acknowledged','dismissed','snoozed')")
    suspend fun reminderGlobalCountSince(scope: String, serverIdentity: String, dayStart: String): Int

    @Query("SELECT COUNT(*) FROM reminder_events WHERE accountScope=:scope AND serverIdentity=:serverIdentity AND eventType IN (:eventTypes) AND triggeredAt>=:dayStart AND state IN ('triggered','acknowledged','dismissed','snoozed')")
    suspend fun reminderChannelCountSince(scope: String, serverIdentity: String, eventTypes: List<String>, dayStart: String): Int

    @Query("SELECT MAX(triggeredAt) FROM reminder_events WHERE accountScope=:scope AND serverIdentity=:serverIdentity AND eventType=:eventType")
    suspend fun lastReminderTrigger(scope: String, serverIdentity: String, eventType: String): String?

    @Query("DELETE FROM reminder_events WHERE accountScope=:scope AND serverIdentity=:serverIdentity AND scheduledFor<:before AND state IN ('acknowledged','dismissed','cancelled','suppressed','failed')")
    suspend fun deleteOldReminderEvents(scope: String, serverIdentity: String, before: String): Int

    @Upsert
    suspend fun upsertReminderSchedule(value: ReminderScheduleEntity)

    @Query("SELECT * FROM reminder_schedules WHERE accountScope=:scope AND serverIdentity=:serverIdentity AND rulePublicId=:ruleId")
    suspend fun reminderSchedule(scope: String, serverIdentity: String, ruleId: String): ReminderScheduleEntity?

    @Query("DELETE FROM reminder_schedules WHERE accountScope=:scope AND serverIdentity=:serverIdentity AND rulePublicId=:ruleId")
    suspend fun deleteReminderSchedule(scope: String, serverIdentity: String, ruleId: String)

    @Upsert
    suspend fun upsertReminderPermissionState(value: ReminderPermissionStateEntity)

    @Query("SELECT * FROM reminder_permission_state WHERE accountScope=:scope AND serverIdentity=:serverIdentity")
    fun observeReminderPermissionState(scope: String, serverIdentity: String): Flow<ReminderPermissionStateEntity?>

    @Query("SELECT * FROM reminder_permission_state WHERE accountScope=:scope AND serverIdentity=:serverIdentity")
    suspend fun reminderPermissionState(scope: String, serverIdentity: String): ReminderPermissionStateEntity?

    @Upsert
    suspend fun upsertAdherenceCache(value: AdherenceCacheEntity)

    @Query("SELECT * FROM adherence_cache WHERE accountScope=:scope AND serverIdentity=:serverIdentity AND rangeDays=:days")
    fun observeAdherence(scope: String, serverIdentity: String, days: Int): Flow<AdherenceCacheEntity?>

    @Query("SELECT * FROM pending_actions WHERE accountScope=:scope AND actionType LIKE 'engagement_%' AND status='pending' AND notBeforeEpochMs<=:now ORDER BY localId LIMIT :limit")
    suspend fun readyEngagementPending(scope: String, now: Long, limit: Int = 50): List<PendingActionEntity>

    @Upsert
    suspend fun upsertPortableExport(value: PortableExportJobEntity)

    @Upsert
    suspend fun upsertPortableImport(value: PortableImportJobEntity)

    @Upsert
    suspend fun upsertPortableInspection(value: PortableInspectionEntity)

    @Upsert
    suspend fun upsertPortableImportPlan(value: PortableImportPlanEntity)

    @Upsert
    suspend fun upsertPortableImportDecision(value: PortableImportDecisionEntity)

    @Upsert
    suspend fun upsertPortableDownload(value: PortableDownloadEntity)

    @Upsert
    suspend fun upsertPortableTempFile(value: PortableTempFileEntity)

    @Query("SELECT * FROM portable_export_jobs WHERE accountScope = :scope ORDER BY createdAt DESC")
    fun observePortableExports(scope: String): Flow<List<PortableExportJobEntity>>

    @Query("SELECT * FROM portable_import_jobs WHERE accountScope = :scope ORDER BY createdAt DESC")
    fun observePortableImports(scope: String): Flow<List<PortableImportJobEntity>>

    @Query("SELECT * FROM portable_inspections WHERE accountScope = :scope ORDER BY verifiedAt DESC")
    fun observePortableInspections(scope: String): Flow<List<PortableInspectionEntity>>

    @Query("SELECT * FROM portable_import_plans WHERE accountScope = :scope ORDER BY expiresAt DESC")
    fun observePortableImportPlans(scope: String): Flow<List<PortableImportPlanEntity>>

    @Query("SELECT * FROM portable_downloads WHERE accountScope = :scope ORDER BY updatedAt DESC")
    fun observePortableDownloads(scope: String): Flow<List<PortableDownloadEntity>>

    @Query("SELECT * FROM portable_import_decisions WHERE accountScope = :scope AND importPublicId = :importId ORDER BY section, sourcePublicId")
    fun observePortableDecisions(scope: String, importId: String): Flow<List<PortableImportDecisionEntity>>

    @Query("SELECT * FROM portable_export_jobs WHERE accountScope = :scope AND publicId = :publicId")
    suspend fun portableExport(scope: String, publicId: String): PortableExportJobEntity?

    @Query("SELECT * FROM portable_import_jobs WHERE accountScope = :scope AND publicId = :publicId")
    suspend fun portableImport(scope: String, publicId: String): PortableImportJobEntity?

    @Query("SELECT * FROM portable_import_plans WHERE accountScope = :scope AND importPublicId = :importId")
    suspend fun portableImportPlan(scope: String, importId: String): PortableImportPlanEntity?

    @Query("SELECT * FROM portable_downloads WHERE accountScope = :scope AND exportPublicId = :exportId")
    suspend fun portableDownload(scope: String, exportId: String): PortableDownloadEntity?

    @Query("SELECT * FROM portable_export_jobs WHERE accountScope = :scope AND syncStatus = 'pending' ORDER BY createdAt")
    suspend fun pendingPortableExports(scope: String): List<PortableExportJobEntity>

    @Query("SELECT * FROM portable_import_jobs WHERE accountScope = :scope AND syncStatus = 'pending_upload' ORDER BY createdAt")
    suspend fun pendingPortableImports(scope: String): List<PortableImportJobEntity>

    @Query("SELECT * FROM portable_import_jobs WHERE accountScope = :scope AND syncStatus = 'pending_apply' ORDER BY createdAt")
    suspend fun pendingPortableApplies(scope: String): List<PortableImportJobEntity>

    @Query("DELETE FROM portable_export_jobs WHERE accountScope = :scope AND publicId = :publicId")
    suspend fun deletePortableExport(scope: String, publicId: String)

    @Query("DELETE FROM portable_import_jobs WHERE accountScope = :scope AND publicId = :publicId")
    suspend fun deletePortableImport(scope: String, publicId: String)

    @Query("DELETE FROM portable_inspections WHERE accountScope = :scope AND importPublicId = :importId")
    suspend fun deletePortableInspection(scope: String, importId: String)

    @Query("DELETE FROM portable_import_plans WHERE accountScope = :scope AND importPublicId = :importId")
    suspend fun deletePortableImportPlan(scope: String, importId: String)

    @Query("DELETE FROM portable_import_decisions WHERE accountScope = :scope AND importPublicId = :importId")
    suspend fun deletePortableImportDecisions(scope: String, importId: String)

    @Query("DELETE FROM portable_export_jobs WHERE accountScope = :scope")
    suspend fun deletePortableExportsForAccount(scope: String)

    @Query("DELETE FROM portable_import_jobs WHERE accountScope = :scope")
    suspend fun deletePortableImportsForAccount(scope: String)

    @Query("DELETE FROM portable_inspections WHERE accountScope = :scope")
    suspend fun deletePortableInspectionsForAccount(scope: String)

    @Query("DELETE FROM portable_import_plans WHERE accountScope = :scope")
    suspend fun deletePortablePlansForAccount(scope: String)

    @Query("DELETE FROM portable_import_decisions WHERE accountScope = :scope")
    suspend fun deletePortableDecisionsForAccount(scope: String)

    @Query("DELETE FROM portable_downloads WHERE accountScope = :scope")
    suspend fun deletePortableDownloadsForAccount(scope: String)

    @Query("DELETE FROM portable_temp_files WHERE accountScope = :scope")
    suspend fun deletePortableTempFilesForAccount(scope: String)

    @Upsert
    suspend fun upsertAccount(value: AccountEntity)

    @Upsert
    suspend fun upsertProfile(value: LocalProfileEntity)

    @Upsert
    suspend fun upsertPlanned(values: List<PlannedWorkoutEntity>)

    @Upsert
    suspend fun upsertDelivery(values: List<DeliveryEntity>)

    @Upsert
    suspend fun upsertPackage(value: WorkoutPackageEntity)

    @Upsert
    suspend fun upsertExercises(values: List<PackageExerciseEntity>)

    @Upsert
    suspend fun upsertSets(values: List<PackageSetEntity>)

    @Upsert
    suspend fun upsertDraft(value: WorkoutDraftEntity)

    @Upsert
    suspend fun upsertDraftSet(value: DraftSetEntity)

    @Upsert
    suspend fun upsertRecent(values: List<RecentSessionEntity>)

    @Upsert
    suspend fun upsertHistorySessions(values: List<HistorySessionEntity>)

    @Upsert
    suspend fun upsertHistoryExercises(values: List<HistoryExerciseEntity>)

    @Upsert
    suspend fun upsertHistorySets(values: List<HistorySetEntity>)

    @Upsert
    suspend fun upsertHistoryPages(values: List<HistoryPageEntity>)

    @Upsert
    suspend fun upsertHistoryQueryState(value: HistoryQueryStateEntity)

    @Upsert
    suspend fun upsertProgressSummary(value: ProgressSummaryEntity)

    @Upsert
    suspend fun upsertProgressExercises(values: List<ProgressExerciseEntity>)

    @Upsert
    suspend fun upsertProgressPoints(values: List<ProgressPointEntity>)

    @Upsert
    suspend fun upsertPersonalRecords(values: List<PersonalRecordEntity>)

    @Upsert
    suspend fun upsertCatalog(values: List<ExerciseCatalogEntity>)

    @Upsert
    suspend fun upsertCatalogState(value: PlanningCatalogStateEntity)

    @Upsert
    suspend fun upsertPlans(values: List<MobilePlanEntity>)

    @Upsert
    suspend fun upsertPlanWorkouts(values: List<MobilePlanWorkoutEntity>)

    @Upsert
    suspend fun upsertPlanExercises(values: List<MobilePlanExerciseEntity>)

    @Upsert
    suspend fun upsertPlanSets(values: List<MobilePlanSetEntity>)

    @Upsert
    suspend fun upsertPlanningConflict(value: PlanningConflictEntity)

    @Upsert
    suspend fun upsertDailyHealthSummary(value: DailyHealthSummaryEntity)

    @Upsert
    suspend fun upsertBodyStats(values: List<BodyStatEntity>)

    @Upsert
    suspend fun upsertNutritionDay(value: NutritionDayEntity)

    @Upsert
    suspend fun upsertNutritionEntries(values: List<NutritionEntryEntity>)

    @Upsert
    suspend fun upsertFoodCatalog(values: List<FoodCatalogEntity>)

    @Upsert
    suspend fun upsertFoodCatalogState(value: FoodCatalogStateEntity)

    @Upsert
    suspend fun upsertDailySteps(values: List<DailyStepEntity>)

    @Upsert
    suspend fun upsertHealthConflict(value: HealthConflictEntity)

    @Upsert
    suspend fun upsertHealthProgressPoints(values: List<HealthProgressPointEntity>)

    @Upsert
    suspend fun upsertHealthConnectSettings(value: HealthConnectSettingsEntity)

    @Upsert
    suspend fun upsertHealthConnectPermissions(values: List<HealthConnectPermissionStateEntity>)

    @Upsert
    suspend fun upsertHealthConnectSyncState(value: HealthConnectSyncStateEntity)

    @Upsert
    suspend fun upsertHealthConnectLedger(values: List<HealthConnectRecordLedgerEntity>)

    @Upsert
    suspend fun upsertExternalSource(value: ExternalSourceEntity)

    @Upsert
    suspend fun upsertExternalSourceCapabilities(values: List<ExternalSourceCapabilityEntity>)

    @Upsert
    suspend fun upsertHealthConnectSourceAssociation(value: HealthConnectSourceAssociationEntity)

    @Upsert
    suspend fun upsertBleDeviceAssociation(value: BleDeviceAssociationEntity)

    @Upsert
    suspend fun upsertBleGattSnapshot(value: BleGattSnapshotEntity)

    @Upsert
    suspend fun upsertBleCaptureMetadata(value: BleCaptureMetadataEntity)

    @Upsert
    suspend fun upsertExternalMeasurementLedger(value: ExternalMeasurementLedgerEntity)

    @Upsert
    suspend fun upsertPossibleDuplicate(value: PossibleDuplicateEntity)

    @Upsert
    suspend fun upsertProtocolEvidence(value: ProtocolEvidenceEntity)

    @Upsert
    suspend fun upsertSyncState(value: SyncStateEntity)

    @Insert(onConflict = OnConflictStrategy.ABORT)
    suspend fun insertPending(value: PendingActionEntity): Long

    @Update
    suspend fun updatePendingEntity(value: PendingActionEntity)

    @Query("SELECT * FROM accounts WHERE scope=:scope LIMIT 1")
    suspend fun account(scope: String): AccountEntity?

    @Query("SELECT * FROM local_profiles WHERE accountScope=:scope LIMIT 1")
    suspend fun localProfile(scope: String): LocalProfileEntity?

    @Query("SELECT * FROM daily_health_summaries WHERE accountScope=:scope AND date=:date LIMIT 1")
    fun observeDailyHealthSummary(scope: String, date: String): Flow<DailyHealthSummaryEntity?>

    @Query("SELECT * FROM daily_health_summaries WHERE accountScope=:scope AND date=:date LIMIT 1")
    suspend fun dailyHealthSummary(scope: String, date: String): DailyHealthSummaryEntity?

    @Query("SELECT * FROM body_stats WHERE accountScope=:scope ORDER BY recordedAt DESC LIMIT :limit")
    fun observeBodyStats(scope: String, limit: Int = 100): Flow<List<BodyStatEntity>>

    @Query("SELECT * FROM body_stats WHERE accountScope=:scope ORDER BY recordedAt DESC")
    suspend fun bodyStats(scope: String): List<BodyStatEntity>

    @Query("SELECT * FROM body_stats WHERE accountScope=:scope AND publicId=:publicId LIMIT 1")
    suspend fun bodyStat(scope: String, publicId: String): BodyStatEntity?

    @Query("SELECT * FROM body_stats WHERE accountScope=:scope AND recordedAt=:recordedAt AND source='health_connect' LIMIT 1")
    suspend fun healthConnectBodyStatAt(scope: String, recordedAt: String): BodyStatEntity?

    @Query("""SELECT body_stats.* FROM body_stats INNER JOIN health_connect_record_ledger AS ledger ON ledger.accountScope=body_stats.accountScope AND ledger.localResourceUuid=body_stats.publicId WHERE body_stats.accountScope=:scope AND ledger.recordType='weight' AND ledger.sourceStartTime=:recordedAt AND ledger.dataOrigin=:dataOrigin AND ledger.state='active' LIMIT 1""")
    suspend fun healthConnectBodyStatAtOrigin(scope: String, recordedAt: String, dataOrigin: String): BodyStatEntity?

    @Query("SELECT * FROM nutrition_days WHERE accountScope=:scope AND date=:date LIMIT 1")
    fun observeNutritionDay(scope: String, date: String): Flow<NutritionDayEntity?>

    @Query("SELECT * FROM nutrition_days WHERE accountScope=:scope AND date=:date LIMIT 1")
    suspend fun nutritionDay(scope: String, date: String): NutritionDayEntity?

    @Query("SELECT * FROM nutrition_entries WHERE accountScope=:scope AND date=:date ORDER BY mealType,updatedAt,publicId")
    fun observeNutritionEntries(scope: String, date: String): Flow<List<NutritionEntryEntity>>

    @Query("SELECT * FROM nutrition_entries WHERE accountScope=:scope AND date=:date ORDER BY mealType,updatedAt,publicId")
    suspend fun nutritionEntries(scope: String, date: String): List<NutritionEntryEntity>

    @Query("SELECT * FROM nutrition_entries WHERE accountScope=:scope AND publicId=:publicId LIMIT 1")
    suspend fun nutritionEntry(scope: String, publicId: String): NutritionEntryEntity?

    @Query("SELECT * FROM food_catalog WHERE accountScope=:scope AND archived=0 AND (normalizedName LIKE :query OR lower(COALESCE(brand,'')) LIKE :query) ORDER BY normalizedName LIMIT :limit")
    fun observeFoodCatalog(scope: String, query: String, limit: Int = 100): Flow<List<FoodCatalogEntity>>

    @Query("SELECT * FROM food_catalog WHERE accountScope=:scope AND publicId=:publicId LIMIT 1")
    suspend fun food(scope: String, publicId: String): FoodCatalogEntity?

    @Query("SELECT * FROM food_catalog_state WHERE accountScope=:scope AND `query`=:query LIMIT 1")
    suspend fun foodCatalogState(scope: String, query: String): FoodCatalogStateEntity?

    @Query("SELECT * FROM daily_steps WHERE accountScope=:scope AND date BETWEEN :from AND :to ORDER BY date DESC,source")
    fun observeDailySteps(scope: String, from: String, to: String): Flow<List<DailyStepEntity>>

    @Query("SELECT * FROM daily_steps WHERE accountScope=:scope AND date=:date ORDER BY CASE WHEN source='manual' THEN 0 ELSE 1 END,updatedAt DESC")
    suspend fun dailyStepsForDate(scope: String, date: String): List<DailyStepEntity>

    @Query("SELECT * FROM daily_steps WHERE accountScope=:scope AND publicId=:publicId LIMIT 1")
    suspend fun dailyStep(scope: String, publicId: String): DailyStepEntity?

    @Query("SELECT * FROM daily_steps WHERE accountScope=:scope AND date=:date AND source=:source LIMIT 1")
    suspend fun dailyStepBySource(scope: String, date: String, source: String): DailyStepEntity?

    @Query("SELECT * FROM health_connect_settings WHERE accountScope=:scope LIMIT 1")
    fun observeHealthConnectSettings(scope: String): Flow<HealthConnectSettingsEntity?>

    @Query("SELECT * FROM health_connect_settings WHERE accountScope=:scope LIMIT 1")
    suspend fun healthConnectSettings(scope: String): HealthConnectSettingsEntity?

    @Query("SELECT * FROM health_connect_permission_state WHERE accountScope=:scope ORDER BY recordType")
    fun observeHealthConnectPermissions(scope: String): Flow<List<HealthConnectPermissionStateEntity>>

    @Query("SELECT * FROM health_connect_permission_state WHERE accountScope=:scope ORDER BY recordType")
    suspend fun healthConnectPermissions(scope: String): List<HealthConnectPermissionStateEntity>

    @Query("SELECT * FROM health_connect_sync_state WHERE accountScope=:scope ORDER BY recordType")
    fun observeHealthConnectSyncStates(scope: String): Flow<List<HealthConnectSyncStateEntity>>

    @Query("SELECT * FROM health_connect_sync_state WHERE accountScope=:scope AND recordType=:recordType LIMIT 1")
    suspend fun healthConnectSyncState(scope: String, recordType: String): HealthConnectSyncStateEntity?

    @Query("SELECT * FROM health_connect_record_ledger WHERE accountScope=:scope AND recordType=:recordType AND healthConnectRecordId=:recordId LIMIT 1")
    suspend fun healthConnectLedger(scope: String, recordType: String, recordId: String): HealthConnectRecordLedgerEntity?

    @Query("SELECT * FROM health_connect_record_ledger WHERE accountScope=:scope AND localResourceUuid=:resourceId")
    suspend fun healthConnectLedgersForResource(scope: String, resourceId: String): List<HealthConnectRecordLedgerEntity>

    @Query("SELECT * FROM health_connect_record_ledger WHERE accountScope=:scope AND recordType=:recordType AND sourceStartTime>=:from AND state='active'")
    suspend fun activeHealthConnectLedgersSince(scope: String, recordType: String, from: String): List<HealthConnectRecordLedgerEntity>

    @Query("SELECT * FROM health_connect_record_ledger WHERE accountScope=:scope AND state='active'")
    suspend fun activeHealthConnectLedgers(scope: String): List<HealthConnectRecordLedgerEntity>

    @Query("UPDATE health_connect_record_ledger SET detachedByUser=1,state='detached',localResourceUuid=NULL,lastSeenAt=:now WHERE accountScope=:scope AND localResourceUuid=:resourceId")
    suspend fun detachHealthConnectLedgers(scope: String, resourceId: String, now: String)

    @Query("SELECT * FROM external_sources WHERE accountScope=:scope ORDER BY visualPriority DESC,displayName")
    fun observeExternalSources(scope: String): Flow<List<ExternalSourceEntity>>

    @Query("DELETE FROM external_source_capabilities WHERE accountScope=:scope AND sourceId=:sourceId")
    suspend fun deleteExternalSourceCapabilities(scope: String, sourceId: String)

    @Query("SELECT * FROM health_connect_source_associations WHERE accountScope=:scope ORDER BY lastSeenAt DESC")
    fun observeHealthConnectSourceAssociations(scope: String): Flow<List<HealthConnectSourceAssociationEntity>>

    @Query("SELECT * FROM health_connect_source_associations WHERE accountScope=:scope AND sourceFingerprint=:fingerprint LIMIT 1")
    suspend fun healthConnectSourceAssociation(scope: String, fingerprint: String): HealthConnectSourceAssociationEntity?

    @Query("SELECT * FROM ble_device_associations WHERE accountScope=:scope ORDER BY lastSeenAt DESC")
    fun observeBleDeviceAssociations(scope: String): Flow<List<BleDeviceAssociationEntity>>

    @Query("SELECT * FROM ble_device_associations WHERE accountScope=:scope AND associationKey=:associationKey LIMIT 1")
    suspend fun bleDeviceAssociation(scope: String, associationKey: String): BleDeviceAssociationEntity?

    @Query("SELECT * FROM ble_device_associations WHERE accountScope=:scope AND deviceFingerprint=:fingerprint LIMIT 1")
    suspend fun bleDeviceAssociationByFingerprint(scope: String, fingerprint: String): BleDeviceAssociationEntity?

    @Query("DELETE FROM ble_device_associations WHERE accountScope=:scope AND deviceFingerprint=:fingerprint")
    suspend fun deleteBleDeviceAssociation(scope: String, fingerprint: String)

    @Query("SELECT * FROM ble_gatt_snapshots WHERE accountScope=:scope AND associationKey=:associationKey ORDER BY observedDate DESC")
    fun observeBleGattSnapshots(scope: String, associationKey: String): Flow<List<BleGattSnapshotEntity>>

    @Query("SELECT * FROM ble_capture_metadata WHERE accountScope=:scope AND associationKey=:associationKey ORDER BY createdDate DESC")
    fun observeBleCaptureMetadata(scope: String, associationKey: String): Flow<List<BleCaptureMetadataEntity>>

    @Query("SELECT * FROM ble_capture_metadata WHERE accountScope=:scope")
    suspend fun bleCaptureMetadataForAccount(scope: String): List<BleCaptureMetadataEntity>

    @Query("SELECT * FROM ble_capture_metadata WHERE accountScope=:scope AND captureId=:captureId LIMIT 1")
    suspend fun bleCaptureMetadata(scope: String, captureId: String): BleCaptureMetadataEntity?

    @Query("DELETE FROM ble_capture_metadata WHERE accountScope=:scope AND captureId=:captureId")
    suspend fun deleteBleCaptureMetadata(scope: String, captureId: String)

    @Query("SELECT * FROM possible_duplicates WHERE accountScope=:scope AND resolution='unresolved' ORDER BY createdAt")
    fun observePossibleDuplicates(scope: String): Flow<List<PossibleDuplicateEntity>>

    @Query("UPDATE possible_duplicates SET resolution=:resolution,resolvedAt=:resolvedAt WHERE accountScope=:scope AND duplicateId=:duplicateId")
    suspend fun resolvePossibleDuplicate(scope: String, duplicateId: String, resolution: String, resolvedAt: String)

    @Query("SELECT * FROM protocol_evidence WHERE accountScope=:scope AND captureId=:captureId ORDER BY relativeTimestampMs")
    fun observeProtocolEvidence(scope: String, captureId: String): Flow<List<ProtocolEvidenceEntity>>

    @Query("SELECT * FROM health_conflicts WHERE accountScope=:scope ORDER BY createdAt")
    fun observeHealthConflicts(scope: String): Flow<List<HealthConflictEntity>>

    @Query("SELECT * FROM health_progress_points WHERE accountScope=:scope AND date BETWEEN :from AND :to ORDER BY date")
    fun observeHealthProgress(scope: String, from: String, to: String): Flow<List<HealthProgressPointEntity>>

    @Query("SELECT * FROM planned_workouts WHERE accountScope=:scope AND deleted=0 ORDER BY scheduledForDate")
    fun observePlanned(scope: String): Flow<List<PlannedWorkoutEntity>>

    @Query("SELECT * FROM planned_workouts WHERE accountScope=:scope AND id=:id LIMIT 1")
    suspend fun planned(scope: String, id: String): PlannedWorkoutEntity?

    @Query("SELECT * FROM exercise_catalog WHERE accountScope=:scope AND (normalizedName LIKE :query OR lower(aliases) LIKE :query) ORDER BY normalizedName LIMIT :limit")
    fun observeCatalog(scope: String, query: String, limit: Int = 100): Flow<List<ExerciseCatalogEntity>>

    @Query("SELECT * FROM planning_catalog_state WHERE accountScope=:scope AND `query`=:query LIMIT 1")
    suspend fun catalogState(scope: String, query: String): PlanningCatalogStateEntity?

    @Query("SELECT * FROM mobile_plans WHERE accountScope=:scope AND status=:status ORDER BY updatedAt DESC,name")
    fun observePlans(scope: String, status: String = "active"): Flow<List<MobilePlanEntity>>

    @Query("SELECT * FROM mobile_plans WHERE accountScope=:scope AND publicId=:publicId LIMIT 1")
    fun observePlan(scope: String, publicId: String): Flow<MobilePlanEntity?>

    @Query("SELECT * FROM mobile_plans WHERE accountScope=:scope AND publicId=:publicId LIMIT 1")
    suspend fun plan(scope: String, publicId: String): MobilePlanEntity?

    @Query("SELECT * FROM mobile_plan_workouts WHERE accountScope=:scope AND planPublicId=:planId ORDER BY position")
    fun observePlanWorkouts(scope: String, planId: String): Flow<List<MobilePlanWorkoutEntity>>

    @Query("SELECT * FROM mobile_plan_workouts WHERE accountScope=:scope AND planPublicId=:planId ORDER BY position")
    suspend fun planWorkouts(scope: String, planId: String): List<MobilePlanWorkoutEntity>

    @Query("UPDATE mobile_plan_workouts SET position=position+1000 WHERE accountScope=:scope AND planPublicId=:planId")
    suspend fun offsetPlanWorkoutPositions(scope: String, planId: String)

    @Query("SELECT * FROM mobile_plan_workouts WHERE accountScope=:scope AND publicId=:publicId LIMIT 1")
    fun observePlanWorkout(scope: String, publicId: String): Flow<MobilePlanWorkoutEntity?>

    @Query("SELECT * FROM mobile_plan_workouts WHERE accountScope=:scope AND publicId=:publicId LIMIT 1")
    suspend fun planWorkout(scope: String, publicId: String): MobilePlanWorkoutEntity?

    @Query("SELECT * FROM mobile_plan_exercises WHERE accountScope=:scope AND workoutPublicId=:workoutId ORDER BY position")
    fun observePlanExercises(scope: String, workoutId: String): Flow<List<MobilePlanExerciseEntity>>

    @Query("SELECT * FROM mobile_plan_exercises WHERE accountScope=:scope AND workoutPublicId=:workoutId ORDER BY position")
    suspend fun planExercises(scope: String, workoutId: String): List<MobilePlanExerciseEntity>

    @Query("SELECT * FROM mobile_plan_sets WHERE accountScope=:scope AND workoutPublicId=:workoutId ORDER BY exercisePublicId,setNumber")
    fun observePlanSets(scope: String, workoutId: String): Flow<List<MobilePlanSetEntity>>

    @Query("SELECT * FROM mobile_plan_sets WHERE accountScope=:scope AND workoutPublicId=:workoutId ORDER BY exercisePublicId,setNumber")
    suspend fun planSets(scope: String, workoutId: String): List<MobilePlanSetEntity>

    @Query("SELECT * FROM planning_conflicts WHERE accountScope=:scope ORDER BY createdAt")
    fun observePlanningConflicts(scope: String): Flow<List<PlanningConflictEntity>>

    @Query("SELECT * FROM planning_conflicts WHERE accountScope=:scope AND entityId=:entityId LIMIT 1")
    suspend fun planningConflict(scope: String, entityId: String): PlanningConflictEntity?

    @Query("SELECT * FROM planned_workouts WHERE accountScope=:scope AND scheduledForDate=:date AND deleted=0 LIMIT 1")
    fun observeToday(scope: String, date: String): Flow<PlannedWorkoutEntity?>

    @Query("SELECT * FROM planned_workouts WHERE accountScope=:scope AND scheduledForDate=:date AND deleted=0 ORDER BY id")
    fun observeScheduledDate(scope: String, date: String): Flow<List<PlannedWorkoutEntity>>

    @Query("SELECT * FROM recent_sessions WHERE accountScope=:scope ORDER BY completedAt DESC LIMIT :limit OFFSET :offset")
    fun observeRecent(scope: String, limit: Int, offset: Int): Flow<List<RecentSessionEntity>>

    @Query("SELECT h.* FROM history_sessions h INNER JOIN history_pages p ON h.accountScope=p.accountScope AND h.publicId=p.sessionPublicId WHERE h.accountScope=:scope AND p.cacheKey=:cacheKey ORDER BY p.position,h.completedAt DESC")
    fun observeHistoryPage(scope: String, cacheKey: String): Flow<List<HistorySessionEntity>>

    @Query("SELECT * FROM history_sessions WHERE accountScope=:scope AND publicId=:publicId LIMIT 1")
    fun observeHistorySession(scope: String, publicId: String): Flow<HistorySessionEntity?>

    @Query("SELECT * FROM history_sessions WHERE accountScope=:scope AND publicId=:publicId LIMIT 1")
    suspend fun historySession(scope: String, publicId: String): HistorySessionEntity?

    @Query("SELECT * FROM history_sessions WHERE accountScope=:scope AND clientEventId=:clientEventId LIMIT 1")
    suspend fun historyByClientEvent(scope: String, clientEventId: String): HistorySessionEntity?

    @Query("SELECT * FROM history_sessions WHERE accountScope=:scope")
    suspend fun historySessions(scope: String): List<HistorySessionEntity>

    @Query("SELECT * FROM history_exercises WHERE accountScope=:scope")
    suspend fun historyExercises(scope: String): List<HistoryExerciseEntity>

    @Query("SELECT * FROM history_sets WHERE accountScope=:scope")
    suspend fun historySets(scope: String): List<HistorySetEntity>

    @Query("SELECT * FROM history_exercises WHERE accountScope=:scope AND sessionPublicId=:publicId ORDER BY exerciseOrder")
    fun observeHistoryExercises(scope: String, publicId: String): Flow<List<HistoryExerciseEntity>>

    @Query("SELECT * FROM history_sets WHERE accountScope=:scope AND sessionPublicId=:publicId ORDER BY exerciseOrder,setNumber")
    fun observeHistorySets(scope: String, publicId: String): Flow<List<HistorySetEntity>>

    @Query("SELECT * FROM history_query_state WHERE accountScope=:scope AND cacheKey=:cacheKey LIMIT 1")
    fun observeHistoryQueryState(scope: String, cacheKey: String): Flow<HistoryQueryStateEntity?>

    @Query("SELECT * FROM history_query_state WHERE accountScope=:scope AND cacheKey=:cacheKey LIMIT 1")
    suspend fun historyQueryState(scope: String, cacheKey: String): HistoryQueryStateEntity?

    @Query("SELECT COALESCE(MAX(position),-1) FROM history_pages WHERE accountScope=:scope AND cacheKey=:cacheKey")
    suspend fun maxHistoryPosition(scope: String, cacheKey: String): Int

    @Query("SELECT * FROM progress_summaries WHERE accountScope=:scope AND `range`=:range LIMIT 1")
    fun observeProgressSummary(scope: String, range: String): Flow<ProgressSummaryEntity?>

    @Query("SELECT * FROM progress_exercises WHERE accountScope=:scope AND `range`=:range ORDER BY lastPerformedAt DESC,name")
    fun observeProgressExercises(scope: String, range: String): Flow<List<ProgressExerciseEntity>>

    @Query("SELECT * FROM progress_exercises WHERE accountScope=:scope AND `range`=:range AND publicId=:publicId LIMIT 1")
    fun observeProgressExercise(scope: String, range: String, publicId: String): Flow<ProgressExerciseEntity?>

    @Query("SELECT * FROM progress_points WHERE accountScope=:scope AND `range`=:range AND exercisePublicId=:publicId ORDER BY performedAt")
    fun observeProgressPoints(scope: String, range: String, publicId: String): Flow<List<ProgressPointEntity>>

    @Query("SELECT * FROM personal_records WHERE accountScope=:scope AND `range`=:range AND exercisePublicId=:publicId ORDER BY type")
    fun observePersonalRecords(scope: String, range: String, publicId: String): Flow<List<PersonalRecordEntity>>

    @Query("SELECT * FROM personal_records WHERE accountScope=:scope ORDER BY date DESC LIMIT 1")
    fun observeLatestPersonalRecord(scope: String): Flow<PersonalRecordEntity?>

    @Query("SELECT * FROM workout_drafts WHERE accountScope=:scope AND status NOT IN ('completed','discarded') ORDER BY updatedAt DESC LIMIT 1")
    fun observeActiveDraft(scope: String): Flow<WorkoutDraftEntity?>

    @Query("SELECT * FROM workout_drafts WHERE accountScope=:scope AND deliveryId=:deliveryId LIMIT 1")
    suspend fun draft(scope: String, deliveryId: String): WorkoutDraftEntity?

    @Query("SELECT * FROM draft_sets WHERE accountScope=:scope AND deliveryId=:deliveryId ORDER BY exerciseOrder,setNumber")
    fun observeDraftSets(scope: String, deliveryId: String): Flow<List<DraftSetEntity>>

    @Query("SELECT * FROM draft_sets WHERE accountScope=:scope AND deliveryId=:deliveryId ORDER BY exerciseOrder,setNumber")
    suspend fun draftSets(scope: String, deliveryId: String): List<DraftSetEntity>

    @Query("SELECT * FROM draft_sets WHERE accountScope=:scope AND deliveryId=:deliveryId AND exerciseOrder=:exerciseOrder AND setNumber=:setNumber LIMIT 1")
    suspend fun draftSet(scope: String, deliveryId: String, exerciseOrder: Int, setNumber: Int): DraftSetEntity?

    @Query("SELECT * FROM package_exercises WHERE accountScope=:scope AND packageId=:packageId ORDER BY exerciseOrder")
    suspend fun packageExercises(scope: String, packageId: String): List<PackageExerciseEntity>

    @Query("SELECT * FROM workout_packages WHERE accountScope=:scope AND deliveryId=:deliveryId LIMIT 1")
    suspend fun packageForDelivery(scope: String, deliveryId: String): WorkoutPackageEntity?

    @Query("SELECT * FROM workout_packages WHERE accountScope=:scope AND plannedWorkoutId=:plannedId LIMIT 1")
    suspend fun packageForPlanned(scope: String, plannedId: String): WorkoutPackageEntity?

    @Query("SELECT * FROM workout_packages WHERE accountScope=:scope AND plannedWorkoutId=:plannedId LIMIT 1")
    fun observePackageForPlanned(scope: String, plannedId: String): Flow<WorkoutPackageEntity?>

    @Query("SELECT * FROM workout_packages WHERE accountScope=:scope ORDER BY scheduledForDate,plannedWorkoutId")
    fun observePackages(scope: String): Flow<List<WorkoutPackageEntity>>

    @Query("SELECT * FROM package_sets WHERE accountScope=:scope AND packageId=:packageId ORDER BY exerciseOrder,setNumber")
    suspend fun packageSets(scope: String, packageId: String): List<PackageSetEntity>

    @Query("SELECT MAX(setNumber) FROM draft_sets WHERE accountScope=:scope AND deliveryId=:deliveryId AND exerciseOrder=:exerciseOrder")
    suspend fun maxSetNumber(scope: String, deliveryId: String, exerciseOrder: Int): Int?

    @Query("SELECT * FROM deliveries WHERE accountScope=:scope AND id=:id LIMIT 1")
    suspend fun delivery(scope: String, id: String): DeliveryEntity?

    @Query("SELECT * FROM sync_state WHERE accountScope=:scope LIMIT 1")
    suspend fun syncState(scope: String): SyncStateEntity?

    @Query("SELECT * FROM pending_actions WHERE accountScope=:scope AND status='pending' AND notBeforeEpochMs<=:now ORDER BY localId LIMIT :limit")
    suspend fun readyPending(scope: String, now: Long, limit: Int): List<PendingActionEntity>

    @Query("SELECT * FROM pending_actions WHERE accountScope=:scope AND status IN ('pending','conflict') ORDER BY localId LIMIT :limit")
    suspend fun queuedActions(scope: String, limit: Int): List<PendingActionEntity>

    @Query("SELECT * FROM pending_actions WHERE accountScope=:scope AND actionType='companion_start' AND status='conflict' ORDER BY localId")
    suspend fun conflictedStarts(scope: String): List<PendingActionEntity>

    @Query("SELECT * FROM pending_actions WHERE accountScope=:scope AND idempotencyKey=:key LIMIT 1")
    suspend fun pendingByKey(scope: String, key: String): PendingActionEntity?

    @Query("SELECT * FROM pending_actions WHERE accountScope=:scope AND entityId=:entityId AND actionType=:actionType AND status='pending' ORDER BY localId LIMIT 1")
    suspend fun pendingAction(scope: String, entityId: String, actionType: String): PendingActionEntity?

    @Query("SELECT * FROM pending_actions WHERE accountScope=:scope AND entityId=:entityId AND status IN ('pending','conflict') ORDER BY localId LIMIT 1")
    suspend fun pendingActionForEntity(scope: String, entityId: String): PendingActionEntity?

    @Query("SELECT * FROM pending_actions WHERE accountScope=:scope AND actionType=:actionType AND status='pending' ORDER BY localId")
    suspend fun pendingActionsByType(scope: String, actionType: String): List<PendingActionEntity>

    @Query("SELECT * FROM pending_actions WHERE accountScope=:scope AND entityId=:entityId AND actionType='companion_start' AND status IN ('pending','conflict') ORDER BY localId LIMIT 1")
    suspend fun pendingStart(scope: String, entityId: String): PendingActionEntity?

    @Query("SELECT COUNT(*) FROM pending_actions WHERE accountScope=:scope AND status='pending'")
    fun observePendingCount(scope: String): Flow<Int>

    @Query("SELECT COUNT(*) FROM pending_actions WHERE accountScope=:scope AND status='pending'")
    suspend fun pendingCount(scope: String): Int

    @Query("SELECT COUNT(*) FROM pending_actions WHERE accountScope=:scope AND status='conflict'")
    fun observeConflictCount(scope: String): Flow<Int>

    @Query("SELECT COUNT(*) FROM pending_actions WHERE accountScope=:scope AND status='conflict'")
    suspend fun conflictCount(scope: String): Int

    @Query("UPDATE pending_actions SET status=:status,lastErrorCode=:errorCode,attemptCount=attemptCount+1,notBeforeEpochMs=:notBefore WHERE localId=:id")
    suspend fun updatePending(id: Long, status: String, errorCode: String?, notBefore: Long)

    @Query("DELETE FROM pending_actions WHERE localId=:id")
    suspend fun deletePending(id: Long)

    @Query("DELETE FROM workout_drafts WHERE accountScope=:scope AND deliveryId=:deliveryId")
    suspend fun deleteDraft(scope: String, deliveryId: String)

    @Query("DELETE FROM workout_packages WHERE accountScope=:scope AND packageId=:packageId")
    suspend fun deletePackage(scope: String, packageId: String)

    @Query("DELETE FROM planned_workouts WHERE accountScope=:scope AND id=:id")
    suspend fun deletePlanned(scope: String, id: String)

    @Query("DELETE FROM pending_actions WHERE accountScope=:scope")
    suspend fun deletePendingForAccount(scope: String)

    @Query("DELETE FROM pending_actions WHERE accountScope=:scope AND entityId=:entityId")
    suspend fun deletePendingForEntity(scope: String, entityId: String)

    @Query("DELETE FROM workout_drafts WHERE accountScope=:scope")
    suspend fun deleteDraftsForAccount(scope: String)

    @Query("DELETE FROM deliveries WHERE accountScope=:scope")
    suspend fun deleteDeliveriesForAccount(scope: String)

    @Query("DELETE FROM workout_packages WHERE accountScope=:scope")
    suspend fun deletePackagesForAccount(scope: String)

    @Query("DELETE FROM planned_workouts WHERE accountScope=:scope")
    suspend fun deletePlannedForAccount(scope: String)

    @Query("DELETE FROM recent_sessions WHERE accountScope=:scope")
    suspend fun deleteRecentForAccount(scope: String)

    @Query("DELETE FROM history_sessions WHERE accountScope=:scope AND publicId=:publicId")
    suspend fun deleteHistorySession(scope: String, publicId: String)

    @Query("DELETE FROM history_pages WHERE accountScope=:scope AND cacheKey=:cacheKey")
    suspend fun deleteHistoryPages(scope: String, cacheKey: String)

    @Query("DELETE FROM history_exercises WHERE accountScope=:scope AND sessionPublicId=:publicId")
    suspend fun deleteHistoryExercises(scope: String, publicId: String)

    @Query("DELETE FROM progress_exercises WHERE accountScope=:scope AND `range`=:range")
    suspend fun deleteProgressExercises(scope: String, range: String)

    @Query("DELETE FROM progress_points WHERE accountScope=:scope AND `range`=:range AND exercisePublicId=:publicId")
    suspend fun deleteProgressPoints(scope: String, range: String, publicId: String)

    @Query("DELETE FROM personal_records WHERE accountScope=:scope AND `range`=:range AND exercisePublicId=:publicId")
    suspend fun deletePersonalRecords(scope: String, range: String, publicId: String)

    @Query("DELETE FROM personal_records WHERE accountScope=:scope AND `range`=:range")
    suspend fun deletePersonalRecordsForRange(scope: String, range: String)

    @Query("DELETE FROM history_pages WHERE accountScope=:scope")
    suspend fun deleteHistoryPagesForAccount(scope: String)

    @Query("DELETE FROM history_query_state WHERE accountScope=:scope")
    suspend fun deleteHistoryStateForAccount(scope: String)

    @Query("DELETE FROM history_sessions WHERE accountScope=:scope")
    suspend fun deleteHistoryForAccount(scope: String)

    @Query("DELETE FROM progress_summaries WHERE accountScope=:scope")
    suspend fun deleteProgressSummariesForAccount(scope: String)

    @Query("DELETE FROM progress_exercises WHERE accountScope=:scope")
    suspend fun deleteProgressExercisesForAccount(scope: String)

    @Query("DELETE FROM progress_points WHERE accountScope=:scope")
    suspend fun deleteProgressPointsForAccount(scope: String)

    @Query("DELETE FROM personal_records WHERE accountScope=:scope")
    suspend fun deletePersonalRecordsForAccount(scope: String)

    @Query("DELETE FROM exercise_catalog WHERE accountScope=:scope")
    suspend fun deleteCatalogForAccount(scope: String)

    @Query("DELETE FROM planning_catalog_state WHERE accountScope=:scope")
    suspend fun deleteCatalogStateForAccount(scope: String)

    @Query("DELETE FROM mobile_plan_sets WHERE accountScope=:scope AND workoutPublicId=:workoutId")
    suspend fun deletePlanSets(scope: String, workoutId: String)

    @Query("DELETE FROM mobile_plan_exercises WHERE accountScope=:scope AND workoutPublicId=:workoutId")
    suspend fun deletePlanExercises(scope: String, workoutId: String)

    @Query("DELETE FROM mobile_plan_workouts WHERE accountScope=:scope AND planPublicId=:planId")
    suspend fun deletePlanWorkouts(scope: String, planId: String)

    @Query("DELETE FROM mobile_plans WHERE accountScope=:scope")
    suspend fun deletePlansForAccount(scope: String)

    @Query("DELETE FROM planning_conflicts WHERE accountScope=:scope")
    suspend fun deletePlanningConflictsForAccount(scope: String)

    @Query("DELETE FROM planning_conflicts WHERE accountScope=:scope AND entityId=:entityId")
    suspend fun deletePlanningConflict(scope: String, entityId: String)

    @Query("DELETE FROM body_stats WHERE accountScope=:scope AND publicId=:publicId")
    suspend fun deleteBodyStat(scope: String, publicId: String)

    @Query("DELETE FROM nutrition_entries WHERE accountScope=:scope AND publicId=:publicId")
    suspend fun deleteNutritionEntry(scope: String, publicId: String)

    @Query("DELETE FROM food_catalog WHERE accountScope=:scope AND publicId=:publicId")
    suspend fun deleteFood(scope: String, publicId: String)

    @Query("DELETE FROM nutrition_entries WHERE accountScope=:scope AND date=:date AND syncStatus='synced'")
    suspend fun deleteSyncedNutritionEntriesForDate(scope: String, date: String)

    @Query("DELETE FROM daily_steps WHERE accountScope=:scope AND publicId=:publicId")
    suspend fun deleteDailyStep(scope: String, publicId: String)

    @Query("DELETE FROM health_conflicts WHERE accountScope=:scope AND entityId=:entityId")
    suspend fun deleteHealthConflict(scope: String, entityId: String)

    @Query("DELETE FROM daily_health_summaries WHERE accountScope=:scope")
    suspend fun deleteDailyHealthSummariesForAccount(scope: String)

    @Query("DELETE FROM body_stats WHERE accountScope=:scope")
    suspend fun deleteBodyStatsForAccount(scope: String)

    @Query("DELETE FROM nutrition_entries WHERE accountScope=:scope")
    suspend fun deleteNutritionEntriesForAccount(scope: String)

    @Query("DELETE FROM nutrition_days WHERE accountScope=:scope")
    suspend fun deleteNutritionDaysForAccount(scope: String)

    @Query("DELETE FROM food_catalog WHERE accountScope=:scope")
    suspend fun deleteFoodCatalogForAccount(scope: String)

    @Query("DELETE FROM food_catalog_state WHERE accountScope=:scope")
    suspend fun deleteFoodCatalogStateForAccount(scope: String)

    @Query("DELETE FROM daily_steps WHERE accountScope=:scope")
    suspend fun deleteDailyStepsForAccount(scope: String)

    @Query("DELETE FROM health_conflicts WHERE accountScope=:scope")
    suspend fun deleteHealthConflictsForAccount(scope: String)

    @Query("DELETE FROM health_progress_points WHERE accountScope=:scope")
    suspend fun deleteHealthProgressForAccount(scope: String)

    @Query("DELETE FROM health_connect_record_ledger WHERE accountScope=:scope")
    suspend fun deleteHealthConnectLedgerForAccount(scope: String)

    @Query("DELETE FROM health_connect_sync_state WHERE accountScope=:scope")
    suspend fun deleteHealthConnectSyncForAccount(scope: String)

    @Query("DELETE FROM health_connect_permission_state WHERE accountScope=:scope")
    suspend fun deleteHealthConnectPermissionsForAccount(scope: String)

    @Query("DELETE FROM health_connect_settings WHERE accountScope=:scope")
    suspend fun deleteHealthConnectSettingsForAccount(scope: String)

    @Query("DELETE FROM protocol_evidence WHERE accountScope=:scope")
    suspend fun deleteProtocolEvidenceForAccount(scope: String)

    @Query("DELETE FROM possible_duplicates WHERE accountScope=:scope")
    suspend fun deletePossibleDuplicatesForAccount(scope: String)

    @Query("DELETE FROM external_measurement_ledger WHERE accountScope=:scope")
    suspend fun deleteExternalMeasurementLedgerForAccount(scope: String)

    @Query("DELETE FROM ble_capture_metadata WHERE accountScope=:scope")
    suspend fun deleteBleCaptureMetadataForAccount(scope: String)

    @Query("DELETE FROM ble_gatt_snapshots WHERE accountScope=:scope")
    suspend fun deleteBleGattSnapshotsForAccount(scope: String)

    @Query("DELETE FROM ble_device_associations WHERE accountScope=:scope")
    suspend fun deleteBleDeviceAssociationsForAccount(scope: String)

    @Query("DELETE FROM health_connect_source_associations WHERE accountScope=:scope")
    suspend fun deleteHealthConnectSourceAssociationsForAccount(scope: String)

    @Query("DELETE FROM external_sources WHERE accountScope=:scope")
    suspend fun deleteExternalSourcesForAccount(scope: String)

    @Query("DELETE FROM sync_state WHERE accountScope=:scope")
    suspend fun deleteSyncStateForAccount(scope: String)

    @Query("DELETE FROM local_profiles WHERE accountScope=:scope")
    suspend fun deleteProfileForAccount(scope: String)

    @Query("DELETE FROM accounts WHERE scope=:scope")
    suspend fun deleteAccount(scope: String)

    @Query("DELETE FROM adherence_cache WHERE accountScope=:scope")
    suspend fun deleteAdherenceForAccount(scope: String)

    @Query("DELETE FROM reminder_permission_state WHERE accountScope=:scope")
    suspend fun deleteReminderPermissionForAccount(scope: String)

    @Query("DELETE FROM reminder_schedules WHERE accountScope=:scope")
    suspend fun deleteReminderSchedulesForAccount(scope: String)

    @Query("DELETE FROM reminder_events WHERE accountScope=:scope")
    suspend fun deleteReminderEventsForAccount(scope: String)

    @Query("DELETE FROM reminder_rules WHERE accountScope=:scope")
    suspend fun deleteReminderRulesForAccount(scope: String)

    @Query("DELETE FROM goals WHERE accountScope=:scope")
    suspend fun deleteGoalsForAccount(scope: String)

    @Transaction
    suspend fun replacePackage(
        packageEntity: WorkoutPackageEntity,
        exercises: List<PackageExerciseEntity>,
        sets: List<PackageSetEntity>,
    ) {
        upsertPackage(packageEntity)
        upsertExercises(exercises)
        upsertSets(sets)
    }

    @Transaction
    suspend fun replaceExternalSourceCapabilities(
        scope: String,
        sourceId: String,
        values: List<ExternalSourceCapabilityEntity>,
    ) {
        deleteExternalSourceCapabilities(scope, sourceId)
        upsertExternalSourceCapabilities(values)
    }

    @Transaction
    suspend fun replaceHistorySession(
        session: HistorySessionEntity,
        exercises: List<HistoryExerciseEntity> = emptyList(),
        sets: List<HistorySetEntity> = emptyList(),
    ) {
        val local = historyByClientEvent(session.accountScope, session.clientEventId)
        if (local != null && local.publicId != session.publicId) deleteHistorySession(session.accountScope, local.publicId)
        upsertHistorySessions(listOf(session))
        if (session.detailCached) {
            deleteHistoryExercises(session.accountScope, session.publicId)
            upsertHistoryExercises(exercises)
            upsertHistorySets(sets)
        }
    }

    @Transaction
    suspend fun replaceProgressExercise(
        exercise: ProgressExerciseEntity,
        points: List<ProgressPointEntity>,
        records: List<PersonalRecordEntity>,
    ) {
        upsertProgressExercises(listOf(exercise))
        deleteProgressPoints(exercise.accountScope, exercise.range, exercise.publicId)
        deletePersonalRecords(exercise.accountScope, exercise.range, exercise.publicId)
        upsertProgressPoints(points)
        upsertPersonalRecords(records)
    }

    @Transaction
    suspend fun replacePlan(
        plan: MobilePlanEntity,
        workouts: List<MobilePlanWorkoutEntity>,
        exercises: List<MobilePlanExerciseEntity>,
        sets: List<MobilePlanSetEntity>,
    ) {
        upsertPlans(listOf(plan))
        val old = planWorkouts(plan.accountScope, plan.publicId)
        old.forEach {
            deletePlanSets(plan.accountScope, it.publicId)
            deletePlanExercises(plan.accountScope, it.publicId)
        }
        deletePlanWorkouts(plan.accountScope, plan.publicId)
        upsertPlanWorkouts(workouts)
        upsertPlanExercises(exercises)
        upsertPlanSets(sets)
        deletePlanningConflict(plan.accountScope, plan.publicId)
    }

    @Transaction
    suspend fun clearAccount(scope: String) {
        deleteAdherenceForAccount(scope)
        deleteReminderPermissionForAccount(scope)
        deleteReminderSchedulesForAccount(scope)
        deleteReminderEventsForAccount(scope)
        deleteReminderRulesForAccount(scope)
        deleteGoalsForAccount(scope)
        deletePortableDecisionsForAccount(scope)
        deletePortablePlansForAccount(scope)
        deletePortableInspectionsForAccount(scope)
        deletePortableDownloadsForAccount(scope)
        deletePortableTempFilesForAccount(scope)
        deletePortableImportsForAccount(scope)
        deletePortableExportsForAccount(scope)
        deletePendingForAccount(scope)
        deleteProtocolEvidenceForAccount(scope)
        deletePossibleDuplicatesForAccount(scope)
        deleteExternalMeasurementLedgerForAccount(scope)
        deleteBleCaptureMetadataForAccount(scope)
        deleteBleGattSnapshotsForAccount(scope)
        deleteBleDeviceAssociationsForAccount(scope)
        deleteHealthConnectSourceAssociationsForAccount(scope)
        deleteExternalSourcesForAccount(scope)
        deleteHealthConnectLedgerForAccount(scope)
        deleteHealthConnectSyncForAccount(scope)
        deleteHealthConnectPermissionsForAccount(scope)
        deleteHealthConnectSettingsForAccount(scope)
        deleteHealthConflictsForAccount(scope)
        deleteHealthProgressForAccount(scope)
        deleteDailyStepsForAccount(scope)
        deleteFoodCatalogStateForAccount(scope)
        deleteFoodCatalogForAccount(scope)
        deleteNutritionEntriesForAccount(scope)
        deleteNutritionDaysForAccount(scope)
        deleteBodyStatsForAccount(scope)
        deleteDailyHealthSummariesForAccount(scope)
        deleteDraftsForAccount(scope)
        deleteDeliveriesForAccount(scope)
        deletePackagesForAccount(scope)
        deletePlannedForAccount(scope)
        deleteRecentForAccount(scope)
        deleteHistoryPagesForAccount(scope)
        deleteHistoryStateForAccount(scope)
        deleteHistoryForAccount(scope)
        deletePersonalRecordsForAccount(scope)
        deletePlanningConflictsForAccount(scope)
        deletePlansForAccount(scope)
        deleteCatalogStateForAccount(scope)
        deleteCatalogForAccount(scope)
        deleteProgressPointsForAccount(scope)
        deleteProgressExercisesForAccount(scope)
        deleteProgressSummariesForAccount(scope)
        deleteSyncStateForAccount(scope)
        deleteProfileForAccount(scope)
        deleteAccount(scope)
    }
}
