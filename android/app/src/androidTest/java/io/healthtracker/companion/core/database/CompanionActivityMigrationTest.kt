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
class CompanionActivityMigrationTest {
    @get:Rule val helper = MigrationTestHelper(
        InstrumentationRegistry.getInstrumentation(), CompanionDatabase::class.java,
    )

    @Test fun migration1To10RunsEveryExplicitStep() {
        val name = "alpha20-activity-v1"
        helper.createDatabase(name, 1).close()
        val migrations = arrayOf<Migration>(
            CompanionDatabase.MIGRATION_1_2, CompanionDatabase.MIGRATION_2_3,
            CompanionDatabase.MIGRATION_3_4, CompanionDatabase.MIGRATION_4_5,
            CompanionDatabase.MIGRATION_5_6, CompanionDatabase.MIGRATION_6_7,
            CompanionDatabase.MIGRATION_7_8, CompanionDatabase.MIGRATION_8_9,
            CompanionDatabase.MIGRATION_9_10,
        )
        assertActivityTables(helper.runMigrationsAndValidate(name, 10, true, *migrations))
    }

    @Test fun migration9To10IsAdditiveAndPreservesExistingData() {
        val name = "alpha20-activity-v9"
        helper.createDatabase(name, 9).apply {
            execSQL("INSERT INTO accounts(scope,serverUrl,userPublicId,displayEmail,deviceId,timezone,createdAt) VALUES('qa-scope','https://qa.invalid','qa-user','qa@example.invalid','qa-device','UTC','2026-07-31T00:00:00Z')")
            close()
        }
        val migrated = helper.runMigrationsAndValidate(name, 10, true, CompanionDatabase.MIGRATION_9_10)
        migrated.query("SELECT COUNT(*) FROM accounts WHERE scope='qa-scope'").use {
            assertTrue(it.moveToFirst()); assertEquals(1, it.getInt(0))
        }
        assertActivityTables(migrated)
    }

    @Test fun sameImportUuidIsIsolatedByAccountAndServerIdentity() {
        val name = "alpha20-activity-identity"
        val database = helper.createDatabase(name, 9)
        CompanionDatabase.MIGRATION_9_10.migrate(database)
        val sql = "INSERT INTO activity_imports(accountScope,serverIdentity,publicId,serverPublicId,displayName,detectedFormat,mimeType,sizeBytes,sha256,sourceUri,uriPermissionPersisted,partialFileName,routePolicy,redactStartMeters,redactEndMeters,state,warningsJson,errorCode,createdAt,updatedAt) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
        val common = arrayOf<Any?>("same", null, "Fictional QA.fit", "fit", "application/octet-stream", 100, "qa-hash", null, 0, null, "drop", 0, 0, "pending_upload", "[]", null, "2026-07-31T00:00:00Z", "2026-07-31T00:00:00Z")
        database.execSQL(sql, arrayOf<Any?>("scope-a", "server-a", *common))
        database.execSQL(sql, arrayOf<Any?>("scope-a", "server-b", *common))
        database.execSQL(sql, arrayOf<Any?>("scope-b", "server-a", *common))
        database.query("SELECT COUNT(*) FROM activity_imports WHERE publicId='same'").use {
            assertTrue(it.moveToFirst()); assertEquals(3, it.getInt(0))
        }
        database.close()
    }

    private fun assertActivityTables(database: androidx.sqlite.db.SupportSQLiteDatabase) {
        database.query("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('activity_imports','activities','activity_laps','activity_series_metadata','activity_routes','activity_duplicate_candidates','plan_activity_links','plan_actual_comparisons','activity_operations')")
            .use { assertEquals(9, it.count) }
        database.close()
    }
}
