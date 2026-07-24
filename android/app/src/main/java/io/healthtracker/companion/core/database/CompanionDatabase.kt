package io.healthtracker.companion.core.database

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase

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
        SyncStateEntity::class,
    ],
    version = 1,
    exportSchema = true,
)
abstract class CompanionDatabase : RoomDatabase() {
    abstract fun companionDao(): CompanionDao

    companion object {
        fun create(context: Context): CompanionDatabase = Room.databaseBuilder(
            context.applicationContext,
            CompanionDatabase::class.java,
            "health_tracker_companion_v1.db",
        ).build()
    }
}
