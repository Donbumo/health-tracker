package io.healthtracker.companion.core.database

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

@Database(
    entities = [
        AccountEntity::class,
        LocalProfileEntity::class,
        PlannedWorkoutEntity::class,
        WorkoutPackageEntity::class,
        PackageExerciseEntity::class,
        PackageSetEntity::class,
        DeliveryEntity::class,
        WorkoutDraftEntity::class,
        DraftSetEntity::class,
        PendingActionEntity::class,
        RecentSessionEntity::class,
        HistorySessionEntity::class,
        HistoryExerciseEntity::class,
        HistorySetEntity::class,
        HistoryPageEntity::class,
        HistoryQueryStateEntity::class,
        ProgressSummaryEntity::class,
        ProgressExerciseEntity::class,
        ProgressPointEntity::class,
        PersonalRecordEntity::class,
        ExerciseCatalogEntity::class,
        PlanningCatalogStateEntity::class,
        MobilePlanEntity::class,
        MobilePlanWorkoutEntity::class,
        MobilePlanExerciseEntity::class,
        MobilePlanSetEntity::class,
        PlanningConflictEntity::class,
        DailyHealthSummaryEntity::class,
        BodyStatEntity::class,
        NutritionDayEntity::class,
        NutritionEntryEntity::class,
        FoodCatalogEntity::class,
        FoodCatalogStateEntity::class,
        DailyStepEntity::class,
        HealthConflictEntity::class,
        HealthProgressPointEntity::class,
        HealthConnectSettingsEntity::class,
        HealthConnectPermissionStateEntity::class,
        HealthConnectSyncStateEntity::class,
        HealthConnectRecordLedgerEntity::class,
        ExternalSourceEntity::class,
        ExternalSourceCapabilityEntity::class,
        HealthConnectSourceAssociationEntity::class,
        BleDeviceAssociationEntity::class,
        BleGattSnapshotEntity::class,
        BleCaptureMetadataEntity::class,
        ExternalMeasurementLedgerEntity::class,
        PossibleDuplicateEntity::class,
        ProtocolEvidenceEntity::class,
        PortableExportJobEntity::class,
        PortableImportJobEntity::class,
        PortableInspectionEntity::class,
        PortableImportPlanEntity::class,
        PortableImportDecisionEntity::class,
        PortableDownloadEntity::class,
        PortableTempFileEntity::class,
        SyncStateEntity::class,
    ],
    version = 7,
    exportSchema = true,
)
abstract class CompanionDatabase : RoomDatabase() {
    abstract fun companionDao(): CompanionDao

    companion object {
        fun create(context: Context): CompanionDatabase = Room.databaseBuilder(
            context.applicationContext,
            CompanionDatabase::class.java,
            "health_tracker_companion_v1.db",
        ).addMigrations(MIGRATION_1_2, MIGRATION_2_3, MIGRATION_3_4, MIGRATION_4_5, MIGRATION_5_6, MIGRATION_6_7).build()

        val MIGRATION_1_2 = object : Migration(1, 2) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("""CREATE TABLE IF NOT EXISTS `history_sessions` (`accountScope` TEXT NOT NULL, `publicId` TEXT NOT NULL, `clientEventId` TEXT NOT NULL, `plannedWorkoutId` TEXT, `trainingPlanId` TEXT, `trainingPlanVersionId` TEXT, `name` TEXT NOT NULL, `performedAt` TEXT NOT NULL, `startedAt` TEXT, `completedAt` TEXT NOT NULL, `timezone` TEXT NOT NULL, `durationSeconds` INTEGER, `exerciseCount` INTEGER NOT NULL, `setCount` INTEGER NOT NULL, `volumeKg` TEXT, `volumePartial` INTEGER NOT NULL, `source` TEXT NOT NULL, `syncStatus` TEXT NOT NULL, `notes` TEXT, `detailCached` INTEGER NOT NULL, `updatedAt` TEXT NOT NULL, PRIMARY KEY(`accountScope`, `publicId`))""")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_history_sessions_accountScope_completedAt` ON `history_sessions` (`accountScope`, `completedAt`)")
                db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS `index_history_sessions_accountScope_clientEventId` ON `history_sessions` (`accountScope`, `clientEventId`)")
                db.execSQL("""INSERT OR IGNORE INTO history_sessions (accountScope,publicId,clientEventId,plannedWorkoutId,trainingPlanId,trainingPlanVersionId,name,performedAt,startedAt,completedAt,timezone,durationSeconds,exerciseCount,setCount,volumeKg,volumePartial,source,syncStatus,notes,detailCached,updatedAt) SELECT accountScope,id,clientEventId,plannedWorkoutId,NULL,NULL,title,completedAt,NULL,completedAt,'UTC',durationSeconds,exerciseCount,setCount,NULL,1,origin,syncStatus,NULL,0,completedAt FROM recent_sessions""")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `history_exercises` (`accountScope` TEXT NOT NULL, `sessionPublicId` TEXT NOT NULL, `exerciseOrder` INTEGER NOT NULL, `exercisePublicId` TEXT, `name` TEXT NOT NULL, `notes` TEXT, PRIMARY KEY(`accountScope`, `sessionPublicId`, `exerciseOrder`), FOREIGN KEY(`accountScope`, `sessionPublicId`) REFERENCES `history_sessions`(`accountScope`, `publicId`) ON UPDATE NO ACTION ON DELETE CASCADE)""")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_history_exercises_accountScope_sessionPublicId` ON `history_exercises` (`accountScope`, `sessionPublicId`)")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_history_exercises_accountScope_exercisePublicId` ON `history_exercises` (`accountScope`, `exercisePublicId`)")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `history_sets` (`accountScope` TEXT NOT NULL, `sessionPublicId` TEXT NOT NULL, `exerciseOrder` INTEGER NOT NULL, `setNumber` INTEGER NOT NULL, `weightKg` TEXT, `displayValue` TEXT, `displayUnit` TEXT, `loadMode` TEXT NOT NULL, `reps` INTEGER NOT NULL, `rir` TEXT, `rpe` TEXT, `restSeconds` INTEGER, `durationSeconds` TEXT, `distanceMeters` TEXT, `notes` TEXT, PRIMARY KEY(`accountScope`, `sessionPublicId`, `exerciseOrder`, `setNumber`), FOREIGN KEY(`accountScope`, `sessionPublicId`, `exerciseOrder`) REFERENCES `history_exercises`(`accountScope`, `sessionPublicId`, `exerciseOrder`) ON UPDATE NO ACTION ON DELETE CASCADE)""")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_history_sets_accountScope_sessionPublicId_exerciseOrder` ON `history_sets` (`accountScope`, `sessionPublicId`, `exerciseOrder`)")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `history_pages` (`accountScope` TEXT NOT NULL, `cacheKey` TEXT NOT NULL, `sessionPublicId` TEXT NOT NULL, `position` INTEGER NOT NULL, PRIMARY KEY(`accountScope`, `cacheKey`, `sessionPublicId`))""")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `history_query_state` (`accountScope` TEXT NOT NULL, `cacheKey` TEXT NOT NULL, `nextCursor` TEXT, `hasMore` INTEGER NOT NULL, `updatedAt` TEXT NOT NULL, PRIMARY KEY(`accountScope`, `cacheKey`))""")
                db.execSQL("""INSERT OR IGNORE INTO history_query_state (accountScope,cacheKey,nextCursor,hasMore,updatedAt) SELECT DISTINCT accountScope,'history:::',NULL,1,MAX(completedAt) FROM recent_sessions GROUP BY accountScope""")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `progress_summaries` (`accountScope` TEXT NOT NULL, `range` TEXT NOT NULL, `sessions` INTEGER NOT NULL, `trainingDays` INTEGER NOT NULL, `distinctExercises` INTEGER NOT NULL, `completedSets` INTEGER NOT NULL, `totalReps` INTEGER NOT NULL, `volumeKg` TEXT, `volumePartial` INTEGER NOT NULL, `durationSeconds` INTEGER NOT NULL, `comparisonJson` TEXT, `updatedAt` TEXT NOT NULL, PRIMARY KEY(`accountScope`, `range`))""")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `progress_exercises` (`accountScope` TEXT NOT NULL, `range` TEXT NOT NULL, `publicId` TEXT NOT NULL, `name` TEXT NOT NULL, `lastPerformedAt` TEXT, `sessionCount` INTEGER NOT NULL, `setCount` INTEGER NOT NULL, `bestLoadKg` TEXT, `bestReps` INTEGER, `bestRepsWeightKg` TEXT, `volumeKg` TEXT, `volumePartial` INTEGER NOT NULL, `loadComparable` INTEGER NOT NULL, `loadModes` TEXT NOT NULL, `trend` TEXT NOT NULL, `updatedAt` TEXT NOT NULL, PRIMARY KEY(`accountScope`, `range`, `publicId`))""")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_progress_exercises_accountScope_range_lastPerformedAt` ON `progress_exercises` (`accountScope`, `range`, `lastPerformedAt`)")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `progress_points` (`accountScope` TEXT NOT NULL, `range` TEXT NOT NULL, `exercisePublicId` TEXT NOT NULL, `sessionPublicId` TEXT NOT NULL, `date` TEXT NOT NULL, `performedAt` TEXT NOT NULL, `bestLoadKg` TEXT, `bestReps` INTEGER, `volumeKg` TEXT, `setCount` INTEGER NOT NULL, `averageRir` TEXT, `averageRpe` TEXT, `loadComparable` INTEGER NOT NULL, PRIMARY KEY(`accountScope`, `range`, `exercisePublicId`, `sessionPublicId`))""")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `personal_records` (`accountScope` TEXT NOT NULL, `range` TEXT NOT NULL, `exercisePublicId` TEXT NOT NULL, `type` TEXT NOT NULL, `value` TEXT NOT NULL, `unit` TEXT NOT NULL, `date` TEXT NOT NULL, `sessionPublicId` TEXT NOT NULL, `setIndex` INTEGER, PRIMARY KEY(`accountScope`, `range`, `exercisePublicId`, `type`))""")
            }
        }

        val MIGRATION_2_3 = object : Migration(2, 3) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE `planned_workouts` ADD COLUMN `sourceWorkoutId` TEXT")
                db.execSQL("ALTER TABLE `package_sets` ADD COLUMN `prescribedWeightKg` TEXT")
                db.execSQL("ALTER TABLE `package_sets` ADD COLUMN `prescribedLoadValue` TEXT")
                db.execSQL("ALTER TABLE `package_sets` ADD COLUMN `prescribedLoadUnit` TEXT")
                db.execSQL("ALTER TABLE `package_sets` ADD COLUMN `prescribedLoadMode` TEXT")
                db.execSQL("ALTER TABLE `package_sets` ADD COLUMN `prescribedRir` TEXT")
                db.execSQL("ALTER TABLE `package_sets` ADD COLUMN `prescribedRpe` TEXT")
                db.execSQL("ALTER TABLE `package_sets` ADD COLUMN `prescribedNotes` TEXT")
                db.execSQL("ALTER TABLE `package_sets` ADD COLUMN `prescribedLoadDetailsJson` TEXT")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `exercise_catalog` (`accountScope` TEXT NOT NULL, `publicId` TEXT NOT NULL, `name` TEXT NOT NULL, `normalizedName` TEXT NOT NULL, `aliases` TEXT NOT NULL, `selectable` INTEGER NOT NULL, `archived` INTEGER NOT NULL, `preferredLoadMode` TEXT, `preferredUnit` TEXT, `updatedAt` TEXT NOT NULL, PRIMARY KEY(`accountScope`, `publicId`))""")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_exercise_catalog_accountScope_normalizedName` ON `exercise_catalog` (`accountScope`, `normalizedName`)")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `planning_catalog_state` (`accountScope` TEXT NOT NULL, `query` TEXT NOT NULL, `nextCursor` TEXT, `hasMore` INTEGER NOT NULL, `updatedAt` TEXT NOT NULL, PRIMARY KEY(`accountScope`, `query`))""")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `mobile_plans` (`accountScope` TEXT NOT NULL, `publicId` TEXT NOT NULL, `name` TEXT NOT NULL, `description` TEXT, `status` TEXT NOT NULL, `revision` INTEGER NOT NULL, `activeVersionId` TEXT, `activeVersion` INTEGER, `syncStatus` TEXT NOT NULL, `createdAt` TEXT NOT NULL, `updatedAt` TEXT NOT NULL, `archivedAt` TEXT, PRIMARY KEY(`accountScope`, `publicId`))""")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_mobile_plans_accountScope_status_updatedAt` ON `mobile_plans` (`accountScope`, `status`, `updatedAt`)")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `mobile_plan_workouts` (`accountScope` TEXT NOT NULL, `publicId` TEXT NOT NULL, `planPublicId` TEXT NOT NULL, `name` TEXT NOT NULL, `notes` TEXT, `position` INTEGER NOT NULL, `estimatedDurationSeconds` INTEGER, `revision` INTEGER NOT NULL, `syncStatus` TEXT NOT NULL, `createdAt` TEXT NOT NULL, `updatedAt` TEXT NOT NULL, PRIMARY KEY(`accountScope`, `publicId`), FOREIGN KEY(`accountScope`, `planPublicId`) REFERENCES `mobile_plans`(`accountScope`, `publicId`) ON UPDATE NO ACTION ON DELETE CASCADE)""")
                db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS `index_mobile_plan_workouts_accountScope_planPublicId_position` ON `mobile_plan_workouts` (`accountScope`, `planPublicId`, `position`)")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `mobile_plan_exercises` (`accountScope` TEXT NOT NULL, `workoutPublicId` TEXT NOT NULL, `publicId` TEXT NOT NULL, `catalogExerciseId` TEXT, `name` TEXT NOT NULL, `notes` TEXT, `position` INTEGER NOT NULL, PRIMARY KEY(`accountScope`, `workoutPublicId`, `publicId`), FOREIGN KEY(`accountScope`, `workoutPublicId`) REFERENCES `mobile_plan_workouts`(`accountScope`, `publicId`) ON UPDATE NO ACTION ON DELETE CASCADE)""")
                db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS `index_mobile_plan_exercises_accountScope_workoutPublicId_position` ON `mobile_plan_exercises` (`accountScope`, `workoutPublicId`, `position`)")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `mobile_plan_sets` (`accountScope` TEXT NOT NULL, `workoutPublicId` TEXT NOT NULL, `exercisePublicId` TEXT NOT NULL, `publicId` TEXT NOT NULL, `setNumber` INTEGER NOT NULL, `reps` INTEGER, `repsMin` INTEGER, `repsMax` INTEGER, `weightKg` TEXT, `loadValue` TEXT, `loadUnit` TEXT NOT NULL, `loadMode` TEXT NOT NULL, `loadDetailsJson` TEXT, `rir` TEXT, `rpe` TEXT, `restSeconds` INTEGER, `durationSeconds` INTEGER, `distanceMeters` TEXT, `notes` TEXT, PRIMARY KEY(`accountScope`, `workoutPublicId`, `exercisePublicId`, `publicId`), FOREIGN KEY(`accountScope`, `workoutPublicId`, `exercisePublicId`) REFERENCES `mobile_plan_exercises`(`accountScope`,`workoutPublicId`,`publicId`) ON UPDATE NO ACTION ON DELETE CASCADE)""")
                db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS `index_mobile_plan_sets_accountScope_workoutPublicId_exercisePublicId_setNumber` ON `mobile_plan_sets` (`accountScope`, `workoutPublicId`, `exercisePublicId`, `setNumber`)")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `planning_conflicts` (`accountScope` TEXT NOT NULL, `entityId` TEXT NOT NULL, `entityType` TEXT NOT NULL, `localRevision` INTEGER NOT NULL, `serverRevision` INTEGER, `changedFields` TEXT NOT NULL, `localName` TEXT, `remoteName` TEXT, `createdAt` TEXT NOT NULL, PRIMARY KEY(`accountScope`, `entityId`))""")
            }
        }

        val MIGRATION_3_4 = object : Migration(3, 4) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("""CREATE TABLE IF NOT EXISTS `daily_health_summaries` (`accountScope` TEXT NOT NULL, `date` TEXT NOT NULL, `timezone` TEXT NOT NULL, `weightId` TEXT, `weightKg` TEXT, `weightIsExactDate` INTEGER NOT NULL, `caloriesKcal` TEXT, `proteinG` TEXT, `carbohydrateG` TEXT, `fatG` TEXT, `fiberG` TEXT, `nutritionTargetKcal` TEXT, `stepsEntryId` TEXT, `steps` INTEGER, `stepsGoal` INTEGER, `scheduledWorkouts` INTEGER NOT NULL, `completedWorkouts` INTEGER NOT NULL, `syncStatus` TEXT NOT NULL, `updatedAt` TEXT, PRIMARY KEY(`accountScope`, `date`))""")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `body_stats` (`accountScope` TEXT NOT NULL, `publicId` TEXT NOT NULL, `recordedAt` TEXT NOT NULL, `weightKg` TEXT NOT NULL, `bodyFatPercent` TEXT, `muscleMassKg` TEXT, `waterPercent` TEXT, `visceralFat` TEXT, `bmrKcal` TEXT, `bmi` TEXT, `notes` TEXT, `source` TEXT NOT NULL, `revision` INTEGER NOT NULL, `localRevision` INTEGER NOT NULL, `syncStatus` TEXT NOT NULL, `createdAt` TEXT NOT NULL, `updatedAt` TEXT NOT NULL, PRIMARY KEY(`accountScope`, `publicId`))""")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_body_stats_accountScope_recordedAt` ON `body_stats` (`accountScope`, `recordedAt`)")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `nutrition_days` (`accountScope` TEXT NOT NULL, `date` TEXT NOT NULL, `caloriesKcal` TEXT, `proteinG` TEXT, `fatG` TEXT, `netCarbsG` TEXT, `totalCarbsG` TEXT, `fiberG` TEXT, `sugarG` TEXT, `sodiumMg` TEXT, `targetCaloriesKcal` TEXT, `updatedAt` TEXT, PRIMARY KEY(`accountScope`, `date`))""")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `nutrition_entries` (`accountScope` TEXT NOT NULL, `publicId` TEXT NOT NULL, `date` TEXT NOT NULL, `mealType` TEXT NOT NULL, `mealName` TEXT, `name` TEXT NOT NULL, `quantity` TEXT, `unit` TEXT, `foodId` TEXT, `caloriesKcal` TEXT, `proteinG` TEXT, `fatG` TEXT, `netCarbsG` TEXT, `totalCarbsG` TEXT, `fiberG` TEXT, `sugarG` TEXT, `sodiumMg` TEXT, `notes` TEXT, `dataComplete` INTEGER NOT NULL, `revision` INTEGER NOT NULL, `localRevision` INTEGER NOT NULL, `syncStatus` TEXT NOT NULL, `createdAt` TEXT NOT NULL, `updatedAt` TEXT NOT NULL, PRIMARY KEY(`accountScope`, `publicId`))""")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_nutrition_entries_accountScope_date_mealType_updatedAt` ON `nutrition_entries` (`accountScope`, `date`, `mealType`, `updatedAt`)")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `food_catalog` (`accountScope` TEXT NOT NULL, `publicId` TEXT NOT NULL, `name` TEXT NOT NULL, `normalizedName` TEXT NOT NULL, `brand` TEXT, `servingSizeG` TEXT, `servingLabel` TEXT, `caloriesPer100g` TEXT, `proteinGPer100g` TEXT, `fatGPer100g` TEXT, `carbsGPer100g` TEXT, `netCarbsGPer100g` TEXT, `fiberGPer100g` TEXT, `sodiumMgPer100g` TEXT, `notes` TEXT, `custom` INTEGER NOT NULL, `archived` INTEGER NOT NULL, `dataComplete` INTEGER NOT NULL, `revision` INTEGER NOT NULL, `syncStatus` TEXT NOT NULL, `updatedAt` TEXT NOT NULL, PRIMARY KEY(`accountScope`, `publicId`))""")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_food_catalog_accountScope_normalizedName` ON `food_catalog` (`accountScope`, `normalizedName`)")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `food_catalog_state` (`accountScope` TEXT NOT NULL, `query` TEXT NOT NULL, `nextCursor` TEXT, `hasMore` INTEGER NOT NULL, `updatedAt` TEXT NOT NULL, PRIMARY KEY(`accountScope`, `query`))""")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `daily_steps` (`accountScope` TEXT NOT NULL, `publicId` TEXT NOT NULL, `date` TEXT NOT NULL, `steps` INTEGER NOT NULL, `source` TEXT NOT NULL, `goal` INTEGER, `revision` INTEGER NOT NULL, `localRevision` INTEGER NOT NULL, `syncStatus` TEXT NOT NULL, `createdAt` TEXT NOT NULL, `updatedAt` TEXT NOT NULL, PRIMARY KEY(`accountScope`, `publicId`))""")
                db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS `index_daily_steps_accountScope_date_source` ON `daily_steps` (`accountScope`, `date`, `source`)")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `health_conflicts` (`accountScope` TEXT NOT NULL, `entityId` TEXT NOT NULL, `entityType` TEXT NOT NULL, `conflictType` TEXT NOT NULL, `localRevision` INTEGER NOT NULL, `serverRevision` INTEGER, `createdAt` TEXT NOT NULL, PRIMARY KEY(`accountScope`, `entityId`))""")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `health_progress_points` (`accountScope` TEXT NOT NULL, `date` TEXT NOT NULL, `weightKg` TEXT, `steps` INTEGER, `caloriesKcal` TEXT, `proteinG` TEXT, `carbohydrateG` TEXT, `fatG` TEXT, `updatedAt` TEXT NOT NULL, PRIMARY KEY(`accountScope`, `date`))""")
            }
        }

        val MIGRATION_4_5 = object : Migration(4, 5) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE `daily_health_summaries` ADD COLUMN `weightSource` TEXT")
                db.execSQL("ALTER TABLE `daily_health_summaries` ADD COLUMN `stepsSource` TEXT")
                db.execSQL("ALTER TABLE `body_stats` ADD COLUMN `sourceZoneOffset` TEXT")
                db.execSQL("ALTER TABLE `nutrition_entries` ADD COLUMN `source` TEXT NOT NULL DEFAULT 'manual'")
                db.execSQL("ALTER TABLE `health_progress_points` ADD COLUMN `weightSource` TEXT")
                db.execSQL("ALTER TABLE `health_progress_points` ADD COLUMN `stepsSource` TEXT")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `health_connect_settings` (`accountScope` TEXT NOT NULL, `enabled` INTEGER NOT NULL, `paused` INTEGER NOT NULL, `selectedTypes` TEXT NOT NULL, `initialLookbackDays` INTEGER NOT NULL, `permissionGeneration` INTEGER NOT NULL, `lastAvailability` TEXT NOT NULL, `updatedAt` TEXT NOT NULL, PRIMARY KEY(`accountScope`))""")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `health_connect_permission_state` (`accountScope` TEXT NOT NULL, `recordType` TEXT NOT NULL, `selected` INTEGER NOT NULL, `granted` INTEGER NOT NULL, `backgroundGranted` INTEGER NOT NULL, `checkedAt` TEXT NOT NULL, `reasonCode` TEXT, PRIMARY KEY(`accountScope`, `recordType`))""")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `health_connect_sync_state` (`accountScope` TEXT NOT NULL, `recordType` TEXT NOT NULL, `token` TEXT, `tokenCreatedAt` TEXT, `lastSuccessfulReadAt` TEXT, `lastFullReconciliationAt` TEXT, `coveredTypes` TEXT NOT NULL, `permissionGeneration` INTEGER NOT NULL, `state` TEXT NOT NULL, `lastAttemptAt` TEXT, `lastImportedAt` TEXT, `importedCount` INTEGER NOT NULL, `deletedCount` INTEGER NOT NULL, `lastErrorCode` TEXT, PRIMARY KEY(`accountScope`, `recordType`))""")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `health_connect_record_ledger` (`accountScope` TEXT NOT NULL, `recordType` TEXT NOT NULL, `healthConnectRecordId` TEXT NOT NULL, `clientRecordId` TEXT, `dataOrigin` TEXT NOT NULL, `localResourceUuid` TEXT, `serverResourceUuid` TEXT, `lastModifiedTime` TEXT NOT NULL, `clientRecordVersion` INTEGER, `contentFingerprint` TEXT NOT NULL, `importedAt` TEXT NOT NULL, `lastSeenAt` TEXT NOT NULL, `state` TEXT NOT NULL, `detachedByUser` INTEGER NOT NULL, `deletedAt` TEXT, `sourceStartTime` TEXT NOT NULL, `sourceEndTime` TEXT, PRIMARY KEY(`accountScope`, `recordType`, `healthConnectRecordId`))""")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_health_connect_record_ledger_accountScope_localResourceUuid` ON `health_connect_record_ledger` (`accountScope`, `localResourceUuid`)")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_health_connect_record_ledger_accountScope_recordType_sourceStartTime` ON `health_connect_record_ledger` (`accountScope`, `recordType`, `sourceStartTime`)")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_health_connect_record_ledger_accountScope_state` ON `health_connect_record_ledger` (`accountScope`, `state`)")
            }
        }

        val MIGRATION_5_6 = object : Migration(5, 6) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("""CREATE TABLE IF NOT EXISTS `external_sources` (`accountScope` TEXT NOT NULL, `sourceId` TEXT NOT NULL, `sourceType` TEXT NOT NULL, `displayName` TEXT NOT NULL, `availability` TEXT NOT NULL, `experimental` INTEGER NOT NULL, `requiredPermissions` TEXT NOT NULL, `supportedMetrics` TEXT NOT NULL, `identityQuality` TEXT NOT NULL, `deduplicationStrategy` TEXT NOT NULL, `visualPriority` INTEGER NOT NULL, `editable` INTEGER NOT NULL, `userOverrideAllowed` INTEGER NOT NULL, `lastDetectedAt` TEXT, `syncState` TEXT NOT NULL, `updatedAt` TEXT NOT NULL, PRIMARY KEY(`accountScope`, `sourceId`))""")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_external_sources_accountScope_sourceType` ON `external_sources` (`accountScope`, `sourceType`)")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `external_source_capabilities` (`accountScope` TEXT NOT NULL, `sourceId` TEXT NOT NULL, `capability` TEXT NOT NULL, PRIMARY KEY(`accountScope`, `sourceId`, `capability`), FOREIGN KEY(`accountScope`, `sourceId`) REFERENCES `external_sources`(`accountScope`, `sourceId`) ON UPDATE NO ACTION ON DELETE CASCADE)""")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_external_source_capabilities_accountScope_sourceId` ON `external_source_capabilities` (`accountScope`, `sourceId`)")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `health_connect_source_associations` (`accountScope` TEXT NOT NULL, `sourceFingerprint` TEXT NOT NULL, `sourceId` TEXT NOT NULL, `safeLabel` TEXT NOT NULL, `state` TEXT NOT NULL, `confirmedModel` TEXT, `identityQuality` TEXT NOT NULL, `firstSeenAt` TEXT NOT NULL, `lastSeenAt` TEXT NOT NULL, `confirmedAt` TEXT, `revokedAt` TEXT, PRIMARY KEY(`accountScope`, `sourceFingerprint`))""")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_health_connect_source_associations_accountScope_state` ON `health_connect_source_associations` (`accountScope`, `state`)")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_health_connect_source_associations_accountScope_sourceId` ON `health_connect_source_associations` (`accountScope`, `sourceId`)")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `ble_device_associations` (`accountScope` TEXT NOT NULL, `associationKey` TEXT NOT NULL, `systemAssociationId` INTEGER, `sanitizedName` TEXT NOT NULL, `alias` TEXT, `deviceFingerprint` TEXT NOT NULL, `serviceUuids` TEXT NOT NULL, `manufacturerFingerprint` TEXT, `firstSeenAt` TEXT NOT NULL, `lastSeenAt` TEXT NOT NULL, `state` TEXT NOT NULL, `userConfirmedModel` TEXT, PRIMARY KEY(`accountScope`, `associationKey`))""")
                db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS `index_ble_device_associations_accountScope_deviceFingerprint` ON `ble_device_associations` (`accountScope`, `deviceFingerprint`)")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_ble_device_associations_accountScope_state` ON `ble_device_associations` (`accountScope`, `state`)")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `ble_gatt_snapshots` (`accountScope` TEXT NOT NULL, `snapshotId` TEXT NOT NULL, `associationKey` TEXT NOT NULL, `serviceFingerprint` TEXT NOT NULL, `servicesJson` TEXT NOT NULL, `observedDate` TEXT NOT NULL, `resultCode` TEXT NOT NULL, PRIMARY KEY(`accountScope`, `snapshotId`))""")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_ble_gatt_snapshots_accountScope_associationKey_observedDate` ON `ble_gatt_snapshots` (`accountScope`, `associationKey`, `observedDate`)")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `ble_capture_metadata` (`accountScope` TEXT NOT NULL, `captureId` TEXT NOT NULL, `associationKey` TEXT NOT NULL, `encryptedFileName` TEXT NOT NULL, `createdDate` TEXT NOT NULL, `eventCount` INTEGER NOT NULL, `byteCount` INTEGER NOT NULL, `durationMs` INTEGER NOT NULL, `checksum` TEXT NOT NULL, `terminalState` TEXT NOT NULL, PRIMARY KEY(`accountScope`, `captureId`))""")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_ble_capture_metadata_accountScope_associationKey_createdDate` ON `ble_capture_metadata` (`accountScope`, `associationKey`, `createdDate`)")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `external_measurement_ledger` (`accountScope` TEXT NOT NULL, `measurementId` TEXT NOT NULL, `sourceId` TEXT NOT NULL, `metricType` TEXT NOT NULL, `observedAt` TEXT NOT NULL, `zoneOffset` TEXT, `canonicalValueHash` TEXT NOT NULL, `precision` INTEGER, `sourceFingerprint` TEXT, `strongIdentity` TEXT, `contentFingerprint` TEXT NOT NULL, `localResourceUuid` TEXT, `state` TEXT NOT NULL, `userOverride` INTEGER NOT NULL, `createdAt` TEXT NOT NULL, `updatedAt` TEXT NOT NULL, PRIMARY KEY(`accountScope`, `measurementId`))""")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_external_measurement_ledger_accountScope_sourceId_observedAt` ON `external_measurement_ledger` (`accountScope`, `sourceId`, `observedAt`)")
                db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS `index_external_measurement_ledger_accountScope_strongIdentity` ON `external_measurement_ledger` (`accountScope`, `strongIdentity`)")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_external_measurement_ledger_accountScope_localResourceUuid` ON `external_measurement_ledger` (`accountScope`, `localResourceUuid`)")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `possible_duplicates` (`accountScope` TEXT NOT NULL, `duplicateId` TEXT NOT NULL, `leftMeasurementId` TEXT NOT NULL, `rightMeasurementId` TEXT NOT NULL, `classification` TEXT NOT NULL, `evidenceJson` TEXT NOT NULL, `resolution` TEXT NOT NULL, `createdAt` TEXT NOT NULL, `resolvedAt` TEXT, PRIMARY KEY(`accountScope`, `duplicateId`))""")
                db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS `index_possible_duplicates_accountScope_leftMeasurementId_rightMeasurementId` ON `possible_duplicates` (`accountScope`, `leftMeasurementId`, `rightMeasurementId`)")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_possible_duplicates_accountScope_resolution` ON `possible_duplicates` (`accountScope`, `resolution`)")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `protocol_evidence` (`accountScope` TEXT NOT NULL, `evidenceId` TEXT NOT NULL, `captureId` TEXT NOT NULL, `relativeTimestampMs` INTEGER NOT NULL, `displayedValue` TEXT NOT NULL, `unit` TEXT NOT NULL, `frameFingerprint` TEXT, `state` TEXT NOT NULL, `createdAt` TEXT NOT NULL, PRIMARY KEY(`accountScope`, `evidenceId`))""")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_protocol_evidence_accountScope_captureId_relativeTimestampMs` ON `protocol_evidence` (`accountScope`, `captureId`, `relativeTimestampMs`)")
            }
        }

        val MIGRATION_6_7 = object : Migration(6, 7) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("""CREATE TABLE IF NOT EXISTS `portable_export_jobs` (`accountScope` TEXT NOT NULL, `publicId` TEXT NOT NULL, `state` TEXT NOT NULL, `sectionsJson` TEXT NOT NULL, `countsJson` TEXT NOT NULL, `sha256` TEXT, `sizeBytes` INTEGER, `requestJson` TEXT NOT NULL, `idempotencyKey` TEXT NOT NULL, `revision` INTEGER NOT NULL, `syncStatus` TEXT NOT NULL, `createdAt` TEXT NOT NULL, `expiresAt` TEXT, `completedAt` TEXT, `errorCode` TEXT, PRIMARY KEY(`accountScope`, `publicId`))""")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_portable_export_jobs_accountScope_createdAt` ON `portable_export_jobs` (`accountScope`, `createdAt`)")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_portable_export_jobs_accountScope_state` ON `portable_export_jobs` (`accountScope`, `state`)")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `portable_import_jobs` (`accountScope` TEXT NOT NULL, `publicId` TEXT NOT NULL, `state` TEXT NOT NULL, `sectionsJson` TEXT NOT NULL, `countsJson` TEXT NOT NULL, `sourceUri` TEXT, `uriPermissionPersisted` INTEGER NOT NULL, `packageSha256` TEXT, `sizeBytes` INTEGER, `uploadIdempotencyKey` TEXT NOT NULL, `applyIdempotencyKey` TEXT NOT NULL, `revision` INTEGER NOT NULL, `syncStatus` TEXT NOT NULL, `createdAt` TEXT NOT NULL, `expiresAt` TEXT, `completedAt` TEXT, `errorCode` TEXT, PRIMARY KEY(`accountScope`, `publicId`))""")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_portable_import_jobs_accountScope_createdAt` ON `portable_import_jobs` (`accountScope`, `createdAt`)")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_portable_import_jobs_accountScope_state` ON `portable_import_jobs` (`accountScope`, `state`)")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `portable_inspections` (`accountScope` TEXT NOT NULL, `importPublicId` TEXT NOT NULL, `packageSha256` TEXT NOT NULL, `format` TEXT NOT NULL, `formatVersion` TEXT NOT NULL, `sectionsJson` TEXT NOT NULL, `countsJson` TEXT NOT NULL, `filesJson` TEXT NOT NULL, `warningsJson` TEXT NOT NULL, `integrity` TEXT NOT NULL, `authenticity` TEXT NOT NULL, `verifiedAt` TEXT NOT NULL, PRIMARY KEY(`accountScope`, `importPublicId`))""")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `portable_import_plans` (`accountScope` TEXT NOT NULL, `importPublicId` TEXT NOT NULL, `planId` TEXT NOT NULL, `revision` INTEGER NOT NULL, `selectedSectionsJson` TEXT NOT NULL, `summaryJson` TEXT NOT NULL, `recordsJson` TEXT NOT NULL, `warningsJson` TEXT NOT NULL, `expiresAt` TEXT NOT NULL, PRIMARY KEY(`accountScope`, `importPublicId`))""")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `portable_import_decisions` (`accountScope` TEXT NOT NULL, `importPublicId` TEXT NOT NULL, `section` TEXT NOT NULL, `sourcePublicId` TEXT NOT NULL, `strategy` TEXT NOT NULL, `updatedAt` TEXT NOT NULL, PRIMARY KEY(`accountScope`, `importPublicId`, `section`, `sourcePublicId`))""")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_portable_import_decisions_accountScope_importPublicId` ON `portable_import_decisions` (`accountScope`, `importPublicId`)")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `portable_downloads` (`accountScope` TEXT NOT NULL, `exportPublicId` TEXT NOT NULL, `partialFileName` TEXT, `finalFileName` TEXT, `expectedSha256` TEXT NOT NULL, `calculatedSha256` TEXT, `expectedBytes` INTEGER, `downloadedBytes` INTEGER NOT NULL, `state` TEXT NOT NULL, `updatedAt` TEXT NOT NULL, `errorCode` TEXT, PRIMARY KEY(`accountScope`, `exportPublicId`))""")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_portable_downloads_accountScope_state` ON `portable_downloads` (`accountScope`, `state`)")
                db.execSQL("""CREATE TABLE IF NOT EXISTS `portable_temp_files` (`accountScope` TEXT NOT NULL, `fileId` TEXT NOT NULL, `kind` TEXT NOT NULL, `fileName` TEXT NOT NULL, `sha256` TEXT, `sizeBytes` INTEGER, `createdAt` TEXT NOT NULL, `expiresAt` TEXT NOT NULL, PRIMARY KEY(`accountScope`, `fileId`))""")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_portable_temp_files_accountScope_expiresAt` ON `portable_temp_files` (`accountScope`, `expiresAt`)")
            }
        }
    }
}
