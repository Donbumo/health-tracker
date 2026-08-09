package io.healthtracker.companion.core.database

import androidx.room.testing.MigrationTestHelper
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class CompanionHealthConnectMigrationTest {
    @get:Rule
    val helper = MigrationTestHelper(
        InstrumentationRegistry.getInstrumentation(),
        CompanionDatabase::class.java,
    )

    @Test fun migration1To5RunsAllExplicitSteps() = migrateFrom(1)
    @Test fun migration2To5RunsAllExplicitSteps() = migrateFrom(2)
    @Test fun migration3To5RunsAllExplicitSteps() = migrateFrom(3)
    @Test fun migration4To5PreservesManualHealthRows() {
        val name = "alpha15-health-connect-v4"
        helper.createDatabase(name, 4).apply {
            execSQL(
                "INSERT INTO body_stats(accountScope,publicId,recordedAt,weightKg,bodyFatPercent,muscleMassKg,waterPercent,visceralFat,bmrKcal,bmi,notes,source,revision,localRevision,syncStatus,createdAt,updatedAt) " +
                    "VALUES('qa-scope','qa-body','2026-07-26T00:00:00Z','70',NULL,NULL,NULL,NULL,NULL,NULL,NULL,'manual',1,1,'synced','2026-07-26T00:00:00Z','2026-07-26T00:00:00Z')",
            )
            execSQL(
                "INSERT INTO planned_workouts(accountScope,id,planId,planVersionId,scheduledForDate,timezone,status,title,revision,updatedAt,deleted,sourceWorkoutId) " +
                    "VALUES('qa-scope','qa-workout','qa-plan','qa-version','2026-07-27','UTC','planned','QA retained',1,'2026-07-26T00:00:00Z',0,NULL)",
            )
            execSQL(
                "INSERT INTO workout_drafts(accountScope,deliveryId,packageId,clientSubmissionId,clientEventId,schemaVersion,packageHash,status,startedAt,pausedAt,elapsedSeconds,averageHeartRateBpm,caloriesBurned,notes,checkpointSequence,payloadHash,updatedAt,expiresAt,corruptReasonCode) " +
                    "VALUES('qa-scope','qa-delivery','qa-package','qa-submission','qa-event','1.0','qa-hash','active','2026-07-26T00:00:00Z',NULL,30,NULL,NULL,NULL,1,'qa-payload-hash','2026-07-26T00:01:00Z','2099-01-01T00:00:00Z',NULL)",
            )
            execSQL(
                "INSERT INTO pending_actions(accountScope,actionType,entityId,idempotencyKey,payloadJson,payloadHash,status,attemptCount,notBeforeEpochMs,createdAt,lastErrorCode) " +
                    "VALUES('qa-scope','HEALTH_BODY_CREATE','qa-body-pending','qa-key','{}','qa-payload','pending',0,0,'2026-07-26T00:00:00Z',NULL)",
            )
            execSQL(
                "INSERT INTO history_sessions(accountScope,publicId,clientEventId,plannedWorkoutId,trainingPlanId,trainingPlanVersionId,name,performedAt,startedAt,completedAt,timezone,durationSeconds,exerciseCount,setCount,volumeKg,volumePartial,source,syncStatus,notes,detailCached,updatedAt) " +
                    "VALUES('qa-scope','qa-history','qa-history-event',NULL,NULL,NULL,'QA history','2026-07-25T00:00:00Z',NULL,'2026-07-25T00:30:00Z','UTC',1800,1,1,'100',0,'server','synced',NULL,0,'2026-07-25T00:30:00Z')",
            )
            close()
        }
        val migrated = helper.runMigrationsAndValidate(name, 5, true, CompanionDatabase.MIGRATION_4_5)
        migrated.query("SELECT source,sourceZoneOffset FROM body_stats WHERE publicId='qa-body'").use { cursor ->
            cursor.moveToFirst()
            assertEquals("manual", cursor.getString(0))
            assertEquals(true, cursor.isNull(1))
        }
        assertHealthConnectTables(migrated)
        listOf(
            "SELECT COUNT(*) FROM planned_workouts WHERE id='qa-workout'",
            "SELECT COUNT(*) FROM workout_drafts WHERE deliveryId='qa-delivery'",
            "SELECT COUNT(*) FROM pending_actions WHERE idempotencyKey='qa-key'",
            "SELECT COUNT(*) FROM history_sessions WHERE publicId='qa-history'",
        ).forEach { query ->
            migrated.query(query).use { cursor -> cursor.moveToFirst(); assertEquals(1, cursor.getInt(0)) }
        }
        migrated.close()
        val reopened = helper.runMigrationsAndValidate(name, 5, true)
        assertHealthConnectTables(reopened)
        reopened.query("SELECT COUNT(*) FROM body_stats WHERE publicId='qa-body'").use {
            it.moveToFirst()
            assertEquals(1, it.getInt(0))
        }
        reopened.close()
    }

    private fun migrateFrom(version: Int) {
        val name = "alpha15-health-connect-v$version"
        helper.createDatabase(name, version).close()
        val migrations = when (version) {
            1 -> arrayOf(CompanionDatabase.MIGRATION_1_2, CompanionDatabase.MIGRATION_2_3, CompanionDatabase.MIGRATION_3_4, CompanionDatabase.MIGRATION_4_5)
            2 -> arrayOf(CompanionDatabase.MIGRATION_2_3, CompanionDatabase.MIGRATION_3_4, CompanionDatabase.MIGRATION_4_5)
            else -> arrayOf(CompanionDatabase.MIGRATION_3_4, CompanionDatabase.MIGRATION_4_5)
        }
        val migrated = helper.runMigrationsAndValidate(name, 5, true, *migrations)
        assertHealthConnectTables(migrated)
        migrated.close()
    }

    private fun assertHealthConnectTables(database: androidx.sqlite.db.SupportSQLiteDatabase) {
        database.query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN " +
                "('health_connect_settings','health_connect_permission_state','health_connect_sync_state','health_connect_record_ledger')",
        ).use { assertEquals(4, it.count) }
    }
}
