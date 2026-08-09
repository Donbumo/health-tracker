package io.healthtracker.companion.core.database

import androidx.room.testing.MigrationTestHelper
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class CompanionPortabilityMigrationTest {
    @get:Rule
    val helper = MigrationTestHelper(
        InstrumentationRegistry.getInstrumentation(),
        CompanionDatabase::class.java,
    )

    @Test fun migration1To7RunsEveryExplicitStep() = migrateFrom(1)
    @Test fun migration2To7RunsEveryExplicitStep() = migrateFrom(2)
    @Test fun migration3To7RunsEveryExplicitStep() = migrateFrom(3)
    @Test fun migration4To7RunsEveryExplicitStep() = migrateFrom(4)
    @Test fun migration5To7RunsEveryExplicitStep() = migrateFrom(5)

    @Test fun migration6To7IsAdditiveAndPreservesPendingAccountAndDraft() {
        val name = "alpha17-portability-v6"
        helper.createDatabase(name, 6).apply {
            execSQL("INSERT INTO accounts(scope,serverUrl,userPublicId,displayEmail,deviceId,timezone,createdAt) VALUES('qa-scope','https://qa.invalid','qa-user','qa@example.invalid','qa-device','UTC','2026-07-30T00:00:00Z')")
            execSQL("INSERT INTO pending_actions(accountScope,actionType,entityId,idempotencyKey,payloadJson,payloadHash,status,attemptCount,notBeforeEpochMs,createdAt,lastErrorCode) VALUES('qa-scope','companion_start','qa-entity','qa-key','{}','qa-hash','pending',0,0,'2026-07-30T00:00:00Z',NULL)")
            execSQL("INSERT INTO workout_drafts(accountScope,deliveryId,packageId,clientSubmissionId,clientEventId,schemaVersion,packageHash,status,startedAt,pausedAt,elapsedSeconds,averageHeartRateBpm,caloriesBurned,notes,checkpointSequence,payloadHash,updatedAt,expiresAt,corruptReasonCode) VALUES('qa-scope','qa-delivery','qa-package','qa-submission','qa-event','1.0','qa-package-hash','active','2026-07-30T00:00:00Z',NULL,0,NULL,NULL,NULL,1,'qa-payload-hash','2026-07-30T00:00:00Z','2026-08-30T00:00:00Z',NULL)")
            close()
        }

        val migrated = helper.runMigrationsAndValidate(name, 7, true, CompanionDatabase.MIGRATION_6_7)
        migrated.query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN " +
                "('portable_export_jobs','portable_import_jobs','portable_inspections','portable_import_plans','portable_import_decisions','portable_downloads','portable_temp_files')",
        ).use { assertEquals(7, it.count) }
        migrated.query("SELECT COUNT(*) FROM accounts WHERE scope='qa-scope'").use {
            assertTrue(it.moveToFirst()); assertEquals(1, it.getInt(0))
        }
        migrated.query("SELECT COUNT(*) FROM pending_actions WHERE accountScope='qa-scope' AND entityId='qa-entity'").use {
            assertTrue(it.moveToFirst()); assertEquals(1, it.getInt(0))
        }
        migrated.query("SELECT COUNT(*) FROM workout_drafts WHERE accountScope='qa-scope' AND deliveryId='qa-delivery'").use {
            assertTrue(it.moveToFirst()); assertEquals(1, it.getInt(0))
        }
        migrated.close()
    }

    private fun migrateFrom(version: Int) {
        val name = "alpha17-chain-v$version"
        helper.createDatabase(name, version).close()
        val migrations = when (version) {
            1 -> arrayOf(CompanionDatabase.MIGRATION_1_2, CompanionDatabase.MIGRATION_2_3,
                CompanionDatabase.MIGRATION_3_4, CompanionDatabase.MIGRATION_4_5,
                CompanionDatabase.MIGRATION_5_6, CompanionDatabase.MIGRATION_6_7)
            2 -> arrayOf(CompanionDatabase.MIGRATION_2_3, CompanionDatabase.MIGRATION_3_4,
                CompanionDatabase.MIGRATION_4_5, CompanionDatabase.MIGRATION_5_6, CompanionDatabase.MIGRATION_6_7)
            3 -> arrayOf(CompanionDatabase.MIGRATION_3_4, CompanionDatabase.MIGRATION_4_5,
                CompanionDatabase.MIGRATION_5_6, CompanionDatabase.MIGRATION_6_7)
            4 -> arrayOf(CompanionDatabase.MIGRATION_4_5, CompanionDatabase.MIGRATION_5_6, CompanionDatabase.MIGRATION_6_7)
            else -> arrayOf(CompanionDatabase.MIGRATION_5_6, CompanionDatabase.MIGRATION_6_7)
        }
        val migrated = helper.runMigrationsAndValidate(name, 7, true, *migrations)
        migrated.query("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name LIKE 'portable_%'").use {
            assertTrue(it.moveToFirst()); assertEquals(7, it.getInt(0))
        }
        migrated.close()
    }
}
