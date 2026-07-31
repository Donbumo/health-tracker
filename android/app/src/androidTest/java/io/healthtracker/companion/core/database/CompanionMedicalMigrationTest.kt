package io.healthtracker.companion.core.database

import androidx.room.migration.Migration
import androidx.room.testing.MigrationTestHelper
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class CompanionMedicalMigrationTest {
    @get:Rule val helper = MigrationTestHelper(
        InstrumentationRegistry.getInstrumentation(), CompanionDatabase::class.java,
    )

    @Test fun migration1To9RunsEveryExplicitStep() {
        val name = "alpha19-medical-v1"
        helper.createDatabase(name, 1).close()
        val migrations = arrayOf<Migration>(
            CompanionDatabase.MIGRATION_1_2, CompanionDatabase.MIGRATION_2_3,
            CompanionDatabase.MIGRATION_3_4, CompanionDatabase.MIGRATION_4_5,
            CompanionDatabase.MIGRATION_5_6, CompanionDatabase.MIGRATION_6_7,
            CompanionDatabase.MIGRATION_7_8, CompanionDatabase.MIGRATION_8_9,
        )
        assertMedicalTables(helper.runMigrationsAndValidate(name, 9, true, *migrations))
    }

    @Test fun migration8To9IsAdditiveAndPreservesOfflineQueue() {
        val name = "alpha19-medical-v8"
        helper.createDatabase(name, 8).apply {
            execSQL("INSERT INTO accounts(scope,serverUrl,userPublicId,displayEmail,deviceId,timezone,createdAt) VALUES('qa-scope','https://qa.invalid','qa-user','qa@example.invalid','qa-device','UTC','2026-07-31T00:00:00Z')")
            execSQL("INSERT INTO pending_actions(accountScope,actionType,entityId,idempotencyKey,payloadJson,payloadHash,status,attemptCount,notBeforeEpochMs,createdAt,lastErrorCode) VALUES('qa-scope','companion_start','qa-entity','qa-key','{}','qa-hash','pending',0,0,'2026-07-31T00:00:00Z',NULL)")
            close()
        }
        val migrated = helper.runMigrationsAndValidate(name, 9, true, CompanionDatabase.MIGRATION_8_9)
        migrated.query("SELECT COUNT(*) FROM pending_actions WHERE accountScope='qa-scope'").use {
            assertTrue(it.moveToFirst()); assertEquals(1, it.getInt(0))
        }
        assertMedicalTables(migrated)
    }

    @Test fun sameUuidIsIsolatedByAccountAndServerIdentity() {
        val name = "alpha19-medical-identity"
        val db = helper.createDatabase(name, 8)
        CompanionDatabase.MIGRATION_8_9.migrate(db)
        val sql = "INSERT INTO medical_studies(accountScope,serverIdentity,publicId,studyType,title,laboratoryName,professionalName,studyDate,issuedDate,timezone,notes,state,source,revision,localRevision,syncStatus,createdAt,updatedAt) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
        val common = arrayOf<Any?>("same", "laboratory", "Estudio QA", null, null, "2026-07-31", null, "UTC", null, "complete", "mobile", 0, 1, "pending", "2026-07-31T00:00:00Z", "2026-07-31T00:00:00Z")
        db.execSQL(sql, arrayOf<Any?>("scope-a", "server-a", *common))
        db.execSQL(sql, arrayOf<Any?>("scope-a", "server-b", *common))
        db.execSQL(sql, arrayOf<Any?>("scope-b", "server-a", *common))
        db.query("SELECT COUNT(*) FROM medical_studies WHERE publicId='same'").use {
            assertTrue(it.moveToFirst()); assertEquals(3, it.getInt(0))
        }
        db.close()
    }

    private fun assertMedicalTables(database: androidx.sqlite.db.SupportSQLiteDatabase) {
        database.query("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('medical_studies','medical_documents','lab_panels','lab_results','lab_result_revisions','lab_markers','medical_operations','medical_history_cache','medical_duplicate_candidates')")
            .use { assertEquals(9, it.count) }
        database.close()
    }
}
