package io.healthtracker.companion.core.database

import androidx.room.testing.MigrationTestHelper
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class CompanionHealthMigrationTest {
    @get:Rule
    val helper = MigrationTestHelper(
        InstrumentationRegistry.getInstrumentation(),
        CompanionDatabase::class.java,
    )

    @Test fun migration1To4RunsEveryExplicitStep() = migrateFrom(1, "alpha14-health-v1")

    @Test fun migration2To4RunsEveryExplicitStep() = migrateFrom(2, "alpha14-health-v2")

    @Test fun migration3To4CreatesStructuredHealthCache() = migrateFrom(3, "alpha14-health-v3")

    @Test fun immediatePreviousVersionPreservesExistingPlanningRows() {
        val name = "alpha14-health-immediate"
        helper.createDatabase(name, 3).apply {
            execSQL(
                "INSERT INTO mobile_plans(accountScope,publicId,name,description,status,revision,activeVersionId,archivedAt,syncStatus,createdAt,updatedAt,lastErrorCode) " +
                    "VALUES('qa-scope','qa-plan','Plan QA',NULL,'active',1,NULL,NULL,'synced','2026-07-26T00:00:00Z','2026-07-26T00:00:00Z',NULL)",
            )
            close()
        }
        val migrated = helper.runMigrationsAndValidate(name, 4, true, CompanionDatabase.MIGRATION_3_4)
        migrated.query("SELECT COUNT(*) FROM mobile_plans WHERE publicId='qa-plan'").use { cursor ->
            cursor.moveToFirst()
            assertEquals(1, cursor.getInt(0))
        }
        assertHealthTables(migrated)
        migrated.close()
    }

    private fun migrateFrom(version: Int, name: String) {
        helper.createDatabase(name, version).close()
        val migrations = when (version) {
            1 -> arrayOf(CompanionDatabase.MIGRATION_1_2, CompanionDatabase.MIGRATION_2_3, CompanionDatabase.MIGRATION_3_4)
            2 -> arrayOf(CompanionDatabase.MIGRATION_2_3, CompanionDatabase.MIGRATION_3_4)
            else -> arrayOf(CompanionDatabase.MIGRATION_3_4)
        }
        val migrated = helper.runMigrationsAndValidate(name, 4, true, *migrations)
        assertHealthTables(migrated)
        migrated.close()
    }

    private fun assertHealthTables(database: androidx.sqlite.db.SupportSQLiteDatabase) {
        database.query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN " +
                "('daily_health_summaries','body_stats','nutrition_days','nutrition_entries'," +
                "'food_catalog','food_catalog_state','daily_steps','health_conflicts','health_progress_points')",
        ).use { cursor -> assertEquals(9, cursor.count) }
        database.query("PRAGMA index_list('daily_steps')").use { cursor ->
            assertEquals(true, cursor.count >= 2)
        }
    }
}
