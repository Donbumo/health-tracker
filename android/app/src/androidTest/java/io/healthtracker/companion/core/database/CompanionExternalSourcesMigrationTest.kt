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
class CompanionExternalSourcesMigrationTest {
    @get:Rule
    val helper = MigrationTestHelper(
        InstrumentationRegistry.getInstrumentation(),
        CompanionDatabase::class.java,
    )

    @Test fun migration1To6RunsEveryExplicitStep() = migrateFrom(1)
    @Test fun migration2To6RunsEveryExplicitStep() = migrateFrom(2)
    @Test fun migration3To6RunsEveryExplicitStep() = migrateFrom(3)
    @Test fun migration4To6RunsEveryExplicitStep() = migrateFrom(4)

    @Test fun migration5To6PreservesHealthConnectLedgerAndAddsExternalTables() {
        val name = "alpha16-external-v5"
        helper.createDatabase(name, 5).apply {
            execSQL("INSERT INTO health_connect_settings(accountScope,enabled,paused,selectedTypes,initialLookbackDays,permissionGeneration,lastAvailability,updatedAt) VALUES('qa-a',1,0,'weight',30,1,'available','2026-07-28T00:00:00Z')")
            execSQL("INSERT INTO health_connect_record_ledger(accountScope,recordType,healthConnectRecordId,clientRecordId,dataOrigin,localResourceUuid,serverResourceUuid,lastModifiedTime,clientRecordVersion,contentFingerprint,importedAt,lastSeenAt,state,detachedByUser,deletedAt,sourceStartTime,sourceEndTime) VALUES('qa-a','weight','fictional-record',NULL,'fixture.origin','local-fixture',NULL,'2026-07-28T00:00:00Z',NULL,'fixture-hash','2026-07-28T00:00:00Z','2026-07-28T00:00:00Z','active',0,NULL,'2026-07-28T00:00:00Z',NULL)")
            close()
        }
        val migrated = helper.runMigrationsAndValidate(name, 6, true, CompanionDatabase.MIGRATION_5_6)
        assertExternalTables(migrated)
        migrated.query("SELECT COUNT(*) FROM health_connect_record_ledger WHERE accountScope='qa-a' AND healthConnectRecordId='fictional-record'").use {
            it.moveToFirst(); assertEquals(1, it.getInt(0))
        }
        migrated.close()
    }

    @Test fun externalRowsArePartitionedByAccountScope() {
        val name = "alpha16-account-scope"
        helper.createDatabase(name, 5).close()
        val database = helper.runMigrationsAndValidate(name, 6, true, CompanionDatabase.MIGRATION_5_6)
        listOf("scope-a", "scope-b").forEach { scope ->
            database.execSQL("INSERT INTO external_sources(accountScope,sourceId,sourceType,displayName,availability,experimental,requiredPermissions,supportedMetrics,identityQuality,deduplicationStrategy,visualPriority,editable,userOverrideAllowed,lastDetectedAt,syncState,updatedAt) VALUES('$scope','manual','manual','QA manual','available',0,'','weight_kg','none','identity',1,1,1,NULL,'local_only','2026-07-28T00:00:00Z')")
        }
        database.execSQL("DELETE FROM external_sources WHERE accountScope='scope-a'")
        database.query("SELECT accountScope FROM external_sources").use {
            assertTrue(it.moveToFirst())
            assertEquals("scope-b", it.getString(0))
            assertEquals(false, it.moveToNext())
        }
        database.close()
    }

    private fun migrateFrom(version: Int) {
        val name = "alpha16-chain-v$version"
        helper.createDatabase(name, version).close()
        val migrations = when (version) {
            1 -> arrayOf(CompanionDatabase.MIGRATION_1_2, CompanionDatabase.MIGRATION_2_3, CompanionDatabase.MIGRATION_3_4, CompanionDatabase.MIGRATION_4_5, CompanionDatabase.MIGRATION_5_6)
            2 -> arrayOf(CompanionDatabase.MIGRATION_2_3, CompanionDatabase.MIGRATION_3_4, CompanionDatabase.MIGRATION_4_5, CompanionDatabase.MIGRATION_5_6)
            3 -> arrayOf(CompanionDatabase.MIGRATION_3_4, CompanionDatabase.MIGRATION_4_5, CompanionDatabase.MIGRATION_5_6)
            else -> arrayOf(CompanionDatabase.MIGRATION_4_5, CompanionDatabase.MIGRATION_5_6)
        }
        val migrated = helper.runMigrationsAndValidate(name, 6, true, *migrations)
        assertExternalTables(migrated)
        migrated.close()
    }

    private fun assertExternalTables(database: androidx.sqlite.db.SupportSQLiteDatabase) {
        database.query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN " +
                "('external_sources','external_source_capabilities','health_connect_source_associations','ble_device_associations','ble_gatt_snapshots','ble_capture_metadata','external_measurement_ledger','possible_duplicates','protocol_evidence')",
        ).use { assertEquals(9, it.count) }
        database.query("PRAGMA foreign_key_list('external_source_capabilities')").use { assertTrue(it.count > 0) }
    }
}
