package io.healthtracker.companion.core.database

import androidx.room.testing.MigrationTestHelper
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class CompanionPlanningMigrationTest {
    @get:Rule
    val helper = MigrationTestHelper(
        InstrumentationRegistry.getInstrumentation(),
        CompanionDatabase::class.java,
    )

    @Test
    fun migration1To3RunsTheFullChainWithoutLosingRecentHistory() {
        helper.createDatabase(DATABASE_V1_NAME, 1).apply {
            execSQL(
                "INSERT INTO accounts(scope,serverUrl,userPublicId,displayEmail,deviceId,timezone,createdAt) " +
                    "VALUES('qa-scope','https://qa.invalid','qa-user','qa@example.invalid','qa-device','UTC','2026-07-25T00:00:00Z')",
            )
            execSQL(
                "INSERT INTO recent_sessions(accountScope,id,clientEventId,plannedWorkoutId,title,completedAt," +
                    "durationSeconds,exerciseCount,setCount,totalLoadKg,origin,syncStatus,summary) " +
                    "VALUES('qa-scope','qa-session','qa-event',NULL,'QA Session','2026-07-25T00:00:00Z'," +
                    "1200,1,3,'42.0','qa','synced','Fictitious migration fixture')",
            )
            close()
        }

        val migrated = helper.runMigrationsAndValidate(
            DATABASE_V1_NAME,
            3,
            true,
            CompanionDatabase.MIGRATION_1_2,
            CompanionDatabase.MIGRATION_2_3,
        )
        migrated.query("SELECT COUNT(*) FROM recent_sessions WHERE accountScope='qa-scope' AND id='qa-session'").use { cursor ->
            cursor.moveToFirst()
            assertEquals(1, cursor.getInt(0))
        }
        migrated.close()
    }

    @Test
    fun migration2To3CreatesPlanningTablesAndPreservesCompatibility() {
        helper.createDatabase(DATABASE_V2_NAME, 2).close()

        val migrated = helper.runMigrationsAndValidate(
            DATABASE_V2_NAME,
            3,
            true,
            CompanionDatabase.MIGRATION_2_3,
        )
        migrated.query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN " +
                "('exercise_catalog','mobile_plans','mobile_plan_workouts','mobile_plan_exercises','mobile_plan_sets','planning_conflicts')",
        ).use { cursor ->
            assertEquals(6, cursor.count)
        }
        migrated.query("PRAGMA table_info(package_sets)").use { cursor ->
            val name = cursor.getColumnIndexOrThrow("name")
            val columns = buildSet { while (cursor.moveToNext()) add(cursor.getString(name)) }
            assertEquals(
                true,
                setOf("prescribedWeightKg", "prescribedLoadValue", "prescribedLoadMode", "prescribedLoadDetailsJson").all(columns::contains),
            )
        }
        migrated.query("PRAGMA table_info(planned_workouts)").use { cursor ->
            val name = cursor.getColumnIndexOrThrow("name")
            val columns = buildSet { while (cursor.moveToNext()) add(cursor.getString(name)) }
            assertEquals(true, "sourceWorkoutId" in columns)
        }
        migrated.close()
    }

    private companion object {
        const val DATABASE_V1_NAME = "alpha13-planning-migration-v1-test"
        const val DATABASE_V2_NAME = "alpha13-planning-migration-v2-test"
    }
}
