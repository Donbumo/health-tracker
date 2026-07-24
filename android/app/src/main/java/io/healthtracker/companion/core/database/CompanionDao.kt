package io.healthtracker.companion.core.database

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction
import androidx.room.Upsert
import kotlinx.coroutines.flow.Flow

@Dao
interface CompanionDao {
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
    suspend fun upsertSyncState(value: SyncStateEntity)

    @Insert(onConflict = OnConflictStrategy.ABORT)
    suspend fun insertPending(value: PendingActionEntity): Long

    @Query("SELECT * FROM accounts WHERE scope=:scope LIMIT 1")
    suspend fun account(scope: String): AccountEntity?

    @Query("SELECT * FROM local_profiles WHERE accountScope=:scope LIMIT 1")
    suspend fun localProfile(scope: String): LocalProfileEntity?

    @Query("SELECT * FROM planned_workouts WHERE accountScope=:scope AND deleted=0 ORDER BY scheduledForDate")
    fun observePlanned(scope: String): Flow<List<PlannedWorkoutEntity>>

    @Query("SELECT * FROM planned_workouts WHERE accountScope=:scope AND scheduledForDate=:date AND deleted=0 LIMIT 1")
    fun observeToday(scope: String, date: String): Flow<PlannedWorkoutEntity?>

    @Query("SELECT * FROM recent_sessions WHERE accountScope=:scope ORDER BY completedAt DESC LIMIT :limit OFFSET :offset")
    fun observeRecent(scope: String, limit: Int, offset: Int): Flow<List<RecentSessionEntity>>

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

    @Query("DELETE FROM sync_state WHERE accountScope=:scope")
    suspend fun deleteSyncStateForAccount(scope: String)

    @Query("DELETE FROM local_profiles WHERE accountScope=:scope")
    suspend fun deleteProfileForAccount(scope: String)

    @Query("DELETE FROM accounts WHERE scope=:scope")
    suspend fun deleteAccount(scope: String)

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
    suspend fun clearAccount(scope: String) {
        deletePendingForAccount(scope)
        deleteDraftsForAccount(scope)
        deleteDeliveriesForAccount(scope)
        deletePackagesForAccount(scope)
        deletePlannedForAccount(scope)
        deleteRecentForAccount(scope)
        deleteSyncStateForAccount(scope)
        deleteProfileForAccount(scope)
        deleteAccount(scope)
    }
}
