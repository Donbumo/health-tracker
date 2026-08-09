package io.healthtracker.companion.core.database

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PortabilityAccountScopeTest {
    private lateinit var database: CompanionDatabase

    @Before fun create() {
        database = Room.inMemoryDatabaseBuilder(
            ApplicationProvider.getApplicationContext(), CompanionDatabase::class.java,
        ).allowMainThreadQueries().build()
    }

    @After fun close() = database.close()

    @Test fun jobsAreAccountScopedAndLogoutClearsOnlyTheOwnedRows() = runBlocking {
        val dao = database.companionDao()
        listOf("scope-a", "scope-b").forEach { scope ->
            dao.upsertPortableExport(PortableExportJobEntity(
                scope, "00000000-0000-4000-8000-000000000001", "requested", "[]", "{}", null, null,
                "{}", "qa-key-$scope", 1, "pending", "2026-07-30T00:00:00Z", null, null, null,
            ))
            dao.upsertPortableImport(PortableImportJobEntity(
                scope, "00000000-0000-4000-8000-000000000002", "local_inspection_ready", "[]", "{}", null,
                false, "qa-hash", 1, "qa-upload-$scope", "qa-apply-$scope", 1, "pending_upload",
                "2026-07-30T00:00:00Z", null, null, null,
            ))
        }

        assertEquals(1, dao.observePortableExports("scope-a").first().size)
        assertEquals(1, dao.observePortableExports("scope-b").first().size)
        dao.clearAccount("scope-a")
        assertTrue(dao.observePortableExports("scope-a").first().isEmpty())
        assertTrue(dao.observePortableImports("scope-a").first().isEmpty())
        assertEquals(1, dao.observePortableExports("scope-b").first().size)
        assertEquals(1, dao.observePortableImports("scope-b").first().size)
    }

    @Test fun pendingApplyQueueIsDurableAndAccountScoped() = runBlocking {
        val dao = database.companionDao()
        listOf("scope-a", "scope-b").forEach { scope ->
            dao.upsertPortableImport(PortableImportJobEntity(
                scope, "00000000-0000-4000-8000-000000000003", "awaiting_confirmation", "[]", "{}", null,
                false, "qa-hash", 1, "qa-upload-$scope", "qa-apply-$scope", 1, "pending_apply",
                "2026-07-30T00:00:00Z", null, null, null,
            ))
        }

        assertEquals(listOf("scope-a"), dao.pendingPortableApplies("scope-a").map { it.accountScope })
        assertEquals(listOf("scope-b"), dao.pendingPortableApplies("scope-b").map { it.accountScope })
    }
}
