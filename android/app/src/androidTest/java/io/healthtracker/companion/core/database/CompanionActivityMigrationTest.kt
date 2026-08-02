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

    @Test fun migration1To10RunsEveryExplicitStep() = migrateFrom(1)
    @Test fun migration2To10RunsEveryExplicitStep() = migrateFrom(2)
    @Test fun migration3To10RunsEveryExplicitStep() = migrateFrom(3)
    @Test fun migration4To10RunsEveryExplicitStep() = migrateFrom(4)
    @Test fun migration5To10RunsEveryExplicitStep() = migrateFrom(5)
    @Test fun migration6To10RunsEveryExplicitStep() = migrateFrom(6)
    @Test fun migration7To10RunsEveryExplicitStep() = migrateFrom(7)
    @Test fun migration8To10RunsEveryExplicitStep() = migrateFrom(8)

    @Test fun migratedVersion10ReopensWithoutSchemaMutation() {
        val name = "beta1-activity-reopen-v10"
        migrateFrom(1, name)
        assertPreservedAccountAndActivityTables(helper.runMigrationsAndValidate(name, 10, true))
    }

    private fun migrateFrom(from: Int, name: String = "beta1-activity-v$from") {
        helper.createDatabase(name, from).apply {
            execSQL("INSERT INTO accounts(scope,serverUrl,userPublicId,displayEmail,deviceId,timezone,createdAt) VALUES('qa-scope-$from','https://qa.invalid','qa-user-$from','qa-$from@example.invalid','qa-device-$from','UTC','2026-08-01T00:00:00Z')")
            close()
        }
        val migrations = listOf<Migration>(
            CompanionDatabase.MIGRATION_1_2, CompanionDatabase.MIGRATION_2_3,
            CompanionDatabase.MIGRATION_3_4, CompanionDatabase.MIGRATION_4_5,
            CompanionDatabase.MIGRATION_5_6, CompanionDatabase.MIGRATION_6_7,
            CompanionDatabase.MIGRATION_7_8, CompanionDatabase.MIGRATION_8_9,
            CompanionDatabase.MIGRATION_9_10,
        )
        val migrated = helper.runMigrationsAndValidate(name, 10, true, *migrations.drop(from - 1).toTypedArray())
        migrated.query("SELECT COUNT(*) FROM accounts WHERE scope='qa-scope-$from'").use {
            assertTrue(it.moveToFirst()); assertEquals(1, it.getInt(0))
        }
        assertActivityTables(migrated)
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

    private fun assertPreservedAccountAndActivityTables(database: androidx.sqlite.db.SupportSQLiteDatabase) {
        database.query("SELECT COUNT(*) FROM accounts WHERE scope='qa-scope-1'").use {
            assertTrue(it.moveToFirst()); assertEquals(1, it.getInt(0))
        }
        assertActivityTables(database)
    }
}
