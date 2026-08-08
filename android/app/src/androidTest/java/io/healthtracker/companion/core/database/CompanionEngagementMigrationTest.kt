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
class CompanionEngagementMigrationTest {
    @get:Rule val helper = MigrationTestHelper(
        InstrumentationRegistry.getInstrumentation(), CompanionDatabase::class.java,
    )

    @Test fun migration1To8RunsEveryExplicitStep() = chain(1)
    @Test fun migration2To8RunsEveryExplicitStep() = chain(2)
    @Test fun migration3To8RunsEveryExplicitStep() = chain(3)
    @Test fun migration4To8RunsEveryExplicitStep() = chain(4)
    @Test fun migration5To8RunsEveryExplicitStep() = chain(5)
    @Test fun migration6To8RunsEveryExplicitStep() = chain(6)

    @Test fun migration7To8IsAdditiveAndPreservesOfflineQueue() {
        val name = "alpha18-engagement-v7"
        helper.createDatabase(name, 7).apply {
            execSQL("INSERT INTO accounts(scope,serverUrl,userPublicId,displayEmail,deviceId,timezone,createdAt) VALUES('qa-scope','https://qa.invalid','qa-user','qa@example.invalid','qa-device','UTC','2026-07-31T00:00:00Z')")
            execSQL("INSERT INTO pending_actions(accountScope,actionType,entityId,idempotencyKey,payloadJson,payloadHash,status,attemptCount,notBeforeEpochMs,createdAt,lastErrorCode) VALUES('qa-scope','companion_start','qa-entity','qa-key','{}','qa-hash','pending',0,0,'2026-07-31T00:00:00Z',NULL)")
            close()
        }
        val migrated = helper.runMigrationsAndValidate(name, 8, true, CompanionDatabase.MIGRATION_7_8)
        migrated.query("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('goals','reminder_rules','reminder_events','reminder_schedules','reminder_permission_state','adherence_cache')")
            .use { assertEquals(6, it.count) }
        migrated.query("SELECT COUNT(*) FROM pending_actions WHERE accountScope='qa-scope'").use {
            assertTrue(it.moveToFirst()); assertEquals(1, it.getInt(0))
        }
        migrated.close()
    }

    @Test fun sameUuidIsIsolatedByAccountAndServerIdentity() {
        val name = "alpha18-identity"
        val db = helper.createDatabase(name, 7)
        CompanionDatabase.MIGRATION_7_8.migrate(db)
        val sql = "INSERT INTO goals(accountScope,serverIdentity,publicId,goalType,targetValue,unit,period,applicableDaysJson,timezone,startDate,endDate,state,revision,source,relatedPublicId,syncStatus,createdAt,updatedAt) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
        db.execSQL(sql, arrayOf<Any?>("scope-a","server-a","same","daily_steps","5000","step","daily","[1]","UTC","2026-07-31",null,"active",1,"manual",null,"synced","2026-07-31T00:00:00Z","2026-07-31T00:00:00Z"))
        db.execSQL(sql, arrayOf<Any?>("scope-a","server-b","same","daily_steps","6000","step","daily","[1]","UTC","2026-07-31",null,"active",1,"manual",null,"synced","2026-07-31T00:00:00Z","2026-07-31T00:00:00Z"))
        db.query("SELECT COUNT(*) FROM goals WHERE accountScope='scope-a'").use { assertTrue(it.moveToFirst()); assertEquals(2, it.getInt(0)) }
        db.close()
    }

    private fun chain(from: Int) {
        val name = "alpha18-chain-v$from"
        helper.createDatabase(name, from).close()
        val all = listOf(
            CompanionDatabase.MIGRATION_1_2, CompanionDatabase.MIGRATION_2_3,
            CompanionDatabase.MIGRATION_3_4, CompanionDatabase.MIGRATION_4_5,
            CompanionDatabase.MIGRATION_5_6, CompanionDatabase.MIGRATION_6_7,
            CompanionDatabase.MIGRATION_7_8,
        )
        val migrated = helper.runMigrationsAndValidate(name, 8, true, *all.drop(from - 1).toTypedArray<Migration>())
        migrated.query("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('goals','reminder_rules','reminder_events','reminder_schedules','reminder_permission_state','adherence_cache')")
            .use { assertTrue(it.moveToFirst()); assertEquals(6, it.getInt(0)) }
        migrated.close()
    }
}
