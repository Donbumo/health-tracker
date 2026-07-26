package io.healthtracker.companion.core.database

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import io.healthtracker.companion.core.config.PreferenceStore
import io.healthtracker.companion.core.network.ApiClient
import io.healthtracker.companion.core.network.CanonicalJson
import io.healthtracker.companion.core.security.SecureTokenStore
import io.healthtracker.companion.core.sync.CompanionRepository
import io.healthtracker.companion.core.sync.SyncScheduler
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.TimeUnit

@RunWith(AndroidJUnit4::class)
class CompanionDatabaseTest {
    private lateinit var database: CompanionDatabase

    @Before fun create() {
        database = Room.inMemoryDatabaseBuilder(
            ApplicationProvider.getApplicationContext(), CompanionDatabase::class.java,
        ).allowMainThreadQueries().build()
    }

    @After fun close() = database.close()

    @Test fun historyAndProgressCachesAreAccountScopedAndPaginated() = runBlocking {
        val dao = database.companionDao()
        val first = history("scope-a", "session-a", "event-a", "2026-07-23T00:00:00Z")
        val second = history("scope-b", "session-b", "event-b", "2026-07-24T00:00:00Z")
        dao.replaceHistorySession(first)
        dao.replaceHistorySession(second)
        dao.upsertHistoryPages(listOf(
            HistoryPageEntity("scope-a", "history:::", first.publicId, 0),
            HistoryPageEntity("scope-b", "history:::", second.publicId, 0),
        ))
        dao.upsertHistoryQueryState(HistoryQueryStateEntity("scope-a", "history:::", "cursor-a", true, "2026-07-24T00:00:00Z"))
        dao.upsertProgressSummary(ProgressSummaryEntity("scope-a", "30", 1, 1, 1, 2, 10, "500", false, 1800, null, "2026-07-24T00:00:00Z"))

        assertEquals(listOf("session-a"), dao.observeHistoryPage("scope-a", "history:::").first().map { it.publicId })
        assertEquals(listOf("session-b"), dao.observeHistoryPage("scope-b", "history:::").first().map { it.publicId })
        assertEquals("cursor-a", dao.historyQueryState("scope-a", "history:::")?.nextCursor)
        assertEquals(1, dao.observeProgressSummary("scope-a", "30").first()?.sessions)
        assertNull(dao.observeProgressSummary("scope-b", "30").first())
    }

    @Test fun authoritativeSessionReconcilesPendingClientEventWithoutDuplicate() = runBlocking {
        val dao = database.companionDao()
        dao.replaceHistorySession(history(TEST_SCOPE, "qa-event", "qa-event", "2026-07-24T00:00:00Z", "pending"))
        dao.upsertHistoryPages(listOf(HistoryPageEntity(TEST_SCOPE, "history:::", "qa-event", -1)))

        dao.replaceHistorySession(history(TEST_SCOPE, "server-session", "qa-event", "2026-07-24T00:00:00Z", "synced"))
        dao.upsertHistoryPages(listOf(HistoryPageEntity(TEST_SCOPE, "history:::", "server-session", -1)))

        val rows = dao.observeHistoryPage(TEST_SCOPE, "history:::").first()
        assertEquals(1, rows.size)
        assertEquals("server-session", rows.single().publicId)
        assertEquals("synced", rows.single().syncStatus)
    }

    @Test fun accountsAreIsolatedAndLogoutCleanupCascades() = runBlocking {
        val dao = database.companionDao()
        dao.upsertAccount(AccountEntity("scope-a", "https://a.test", "user-a", "qa-a", "device-a", "UTC", "2026-07-17T00:00:00Z"))
        dao.upsertAccount(AccountEntity("scope-b", "https://b.test", "user-b", "qa-b", "device-b", "UTC", "2026-07-17T00:00:00Z"))
        dao.upsertPlanned(listOf(
            PlannedWorkoutEntity("scope-a", "workout-a", "plan-a", "version-a", "2026-07-17", "UTC", "planned", "QA A", 1, "2026-07-17T00:00:00Z", false),
            PlannedWorkoutEntity("scope-b", "workout-b", "plan-b", "version-b", "2026-07-17", "UTC", "planned", "QA B", 1, "2026-07-17T00:00:00Z", false),
        ))
        assertEquals("workout-a", dao.observeToday("scope-a", "2026-07-17").first()?.id)
        assertEquals("workout-b", dao.observeToday("scope-b", "2026-07-17").first()?.id)
        dao.clearAccount("scope-a")
        assertNull(dao.observeToday("scope-a", "2026-07-17").first())
        assertEquals("workout-b", dao.observeToday("scope-b", "2026-07-17").first()?.id)
    }

    @Test fun planningAggregatesAreAccountScopedAndCleanupOnlyRemovesOwnedCopy() = runBlocking {
        val dao = database.companionDao()
        val now = "2099-07-24T00:00:00Z"
        listOf("scope-a", "scope-b").forEach { scope ->
            val plan = MobilePlanEntity(scope, "shared-plan", "QA $scope", null, "active", 1, null, null, "pending", now, now, null)
            val workout = MobilePlanWorkoutEntity(scope, "workout-$scope", "shared-plan", "QA workout", null, 1, null, 1, "pending", now, now)
            val exercise = MobilePlanExerciseEntity(scope, workout.publicId, "exercise-$scope", null, "QA squat", null, 1)
            val set = MobilePlanSetEntity(scope, workout.publicId, exercise.publicId, "set-$scope", 1, 5, null, null, "20", "20", "kg", "direct_total", null, "2", null, 60, null, null, null)
            dao.replacePlan(plan, listOf(workout), listOf(exercise), listOf(set))
        }

        assertEquals("QA scope-a", dao.observePlan("scope-a", "shared-plan").first()?.name)
        assertEquals("QA scope-b", dao.observePlan("scope-b", "shared-plan").first()?.name)

        dao.clearAccount("scope-a")

        assertNull(dao.observePlan("scope-a", "shared-plan").first())
        assertEquals(1, dao.observePlanWorkouts("scope-b", "shared-plan").first().size)
        assertEquals("20", dao.observePlanSets("scope-b", "workout-scope-b").first().single().loadValue)
    }

    @Test fun offlineRescheduleKeepsStableIdentityAndCoalescesLatestDestination() = runBlocking {
        val dao = database.companionDao()
        val now = "2099-07-24T00:00:00Z"
        val plan = MobilePlanEntity(TEST_SCOPE, "plan-reschedule", "QA calendar", null, "active", 1, null, null, "synced", now, now, null)
        val workout = MobilePlanWorkoutEntity(TEST_SCOPE, "workout-reschedule", plan.publicId, "QA workout", null, 1, null, 1, "synced", now, now)
        dao.replacePlan(plan, listOf(workout), emptyList(), emptyList())
        dao.upsertPlanned(listOf(PlannedWorkoutEntity(TEST_SCOPE, "schedule-old", plan.publicId, "version-qa", "2099-07-24", "UTC", "planned", workout.name, 1, now, false, workout.publicId)))

        val replacement = repository().rescheduleWorkoutOffline(TEST_SCOPE, "schedule-old", java.time.LocalDate.of(2099, 7, 25), "UTC")
        val repeated = repository().rescheduleWorkoutOffline(TEST_SCOPE, "schedule-old", java.time.LocalDate.of(2099, 7, 26), "UTC")
        SyncScheduler.cancelAll()

        val visible = dao.observePlanned(TEST_SCOPE).first()
        assertEquals("schedule-old", replacement)
        assertEquals("schedule-old", repeated)
        assertEquals(listOf(replacement), visible.map { it.id })
        assertEquals("2099-07-26", visible.single().scheduledForDate)
        assertEquals(
            listOf("planning_schedule_patch"),
            dao.queuedActions(TEST_SCOPE, 10).map { it.actionType },
        )
        assertTrue(dao.queuedActions(TEST_SCOPE, 10).single().payloadJson.contains("2099-07-26"))
    }

    @Test fun offlineCreateThenMoveCoalescesAndCreateThenCancelLeavesNoTrace() = runBlocking {
        val dao = database.companionDao()
        val now = "2099-07-24T00:00:00Z"
        val plan = MobilePlanEntity(TEST_SCOPE, "plan-coalesce", "QA calendar", null, "active", 1, null, null, "synced", now, now, null)
        val workout = MobilePlanWorkoutEntity(TEST_SCOPE, "workout-coalesce", plan.publicId, "QA workout", null, 1, null, 1, "synced", now, now)
        dao.replacePlan(plan, listOf(workout), emptyList(), emptyList())

        val scheduledId = repository().scheduleWorkoutOffline(TEST_SCOPE, workout.publicId, java.time.LocalDate.of(2099, 7, 24), "UTC")
        val duplicateTap = repository().scheduleWorkoutOffline(TEST_SCOPE, workout.publicId, java.time.LocalDate.of(2099, 7, 24), "UTC")
        repository().rescheduleWorkoutOffline(TEST_SCOPE, scheduledId, java.time.LocalDate.of(2099, 7, 27), "UTC")
        SyncScheduler.cancelAll()

        assertEquals(scheduledId, duplicateTap)
        assertEquals("2099-07-27", dao.observePlanned(TEST_SCOPE).first().single().scheduledForDate)
        val create = dao.queuedActions(TEST_SCOPE, 10).single()
        assertEquals("planning_schedule", create.actionType)
        assertEquals(scheduledId, create.entityId)
        assertTrue(create.payloadJson.contains("2099-07-27"))

        repository().cancelScheduleOffline(TEST_SCOPE, scheduledId)
        SyncScheduler.cancelAll()
        assertTrue(dao.observePlanned(TEST_SCOPE).first().isEmpty())
        assertTrue(dao.queuedActions(TEST_SCOPE, 10).isEmpty())
    }

    @Test fun plannedTombstoneOnlyRemovesTheOwnedScope() = runBlocking {
        val dao = database.companionDao()
        val sharedId = "workout-shared-public-id"
        dao.upsertPlanned(listOf(
            PlannedWorkoutEntity("scope-a", sharedId, "plan-a", "version-a", "2026-07-17", "UTC", "planned", "QA A", 1, "2026-07-17T00:00:00Z", false),
            PlannedWorkoutEntity("scope-b", sharedId, "plan-b", "version-b", "2026-07-17", "UTC", "planned", "QA B", 1, "2026-07-17T00:00:00Z", false),
        ))

        dao.deletePlanned("scope-a", sharedId)

        assertNull(dao.observeToday("scope-a", "2026-07-17").first())
        assertEquals(sharedId, dao.observeToday("scope-b", "2026-07-17").first()?.id)
    }

    @Test fun roomExposesEveryWorkoutOnTheSameDayWithoutCrossAccountRows() = runBlocking {
        val dao = database.companionDao()
        val date = "2028-02-29"
        dao.upsertPlanned(
            listOf(
                PlannedWorkoutEntity("scope-a", "schedule-a1", "plan-a", "version-a", date, "UTC", "planned", "QA A1", 1, "2028-02-01T00:00:00Z", false),
                PlannedWorkoutEntity("scope-a", "schedule-a2", "plan-a", "version-a", date, "UTC", "locally_pending", "QA A2", 1, "2028-02-01T00:00:01Z", false),
                PlannedWorkoutEntity("scope-b", "schedule-b", "plan-b", "version-b", date, "UTC", "planned", "QA B", 1, "2028-02-01T00:00:02Z", false),
            ),
        )

        assertEquals(listOf("schedule-a1", "schedule-a2"), dao.observeScheduledDate("scope-a", date).first().map { it.id })
        assertEquals(listOf("schedule-b"), dao.observeScheduledDate("scope-b", date).first().map { it.id })
        assertTrue(dao.observeScheduledDate("scope-a", "2028-03-01").first().isEmpty())
    }

    @Test fun pendingAndConflictCountsRepresentDifferentStates() = runBlocking {
        val dao = database.companionDao()
        dao.insertPending(
            PendingActionEntity(
                accountScope = TEST_SCOPE, actionType = "companion_start", entityId = "qa-delivery-pending",
                idempotencyKey = "qa-pending-key", payloadJson = "{}", payloadHash = "qa-pending-hash",
                status = "pending", createdAt = "2099-07-20T00:00:00Z",
            ),
        )
        dao.insertPending(
            PendingActionEntity(
                accountScope = TEST_SCOPE, actionType = "companion_start", entityId = "qa-delivery-conflict",
                idempotencyKey = "qa-conflict-key", payloadJson = "{}", payloadHash = "qa-conflict-hash",
                status = "conflict", createdAt = "2099-07-20T00:00:00Z",
            ),
        )

        assertEquals(1, dao.observePendingCount(TEST_SCOPE).first())
        assertEquals(1, dao.observeConflictCount(TEST_SCOPE).first())
    }

    @Test fun rebasingConflictKeepsItsFifoPositionAndRotatesIdempotencyKey() = runBlocking {
        val dao = database.companionDao()
        val firstId = dao.insertPending(
            PendingActionEntity(
                accountScope = TEST_SCOPE, actionType = "planning_plan_patch", entityId = "plan-qa",
                idempotencyKey = "stale-key", payloadJson = "{\"base_revision\":1}", payloadHash = "stale-hash",
                status = "conflict", createdAt = "2099-07-20T00:00:00Z",
            ),
        )
        dao.insertPending(
            PendingActionEntity(
                accountScope = TEST_SCOPE, actionType = "planning_plan_patch", entityId = "plan-qa",
                idempotencyKey = "later-key", payloadJson = "{\"base_revision\":2}", payloadHash = "later-hash",
                createdAt = "2099-07-20T00:00:01Z",
            ),
        )

        val stale = dao.queuedActions(TEST_SCOPE, 10).first()
        dao.updatePendingEntity(
            stale.copy(
                idempotencyKey = "rebased-key", payloadJson = "{\"base_revision\":3}", payloadHash = "rebased-hash",
                status = "pending", notBeforeEpochMs = 0, lastErrorCode = null,
            ),
        )

        val queued = dao.queuedActions(TEST_SCOPE, 10)
        assertEquals(firstId, queued.first().localId)
        assertEquals("rebased-key", queued.first().idempotencyKey)
        assertEquals("later-key", queued.last().idempotencyKey)
    }

    @Test fun downloadedPackageFlowUpdatesTodayImmediatelyWithoutPull() = runBlocking {
        val dao = database.companionDao()
        val observed = async { repository().observeDownloadedDelivery(TEST_SCOPE, "qa-workout").filterNotNull().first() }

        dao.upsertPackage(
            WorkoutPackageEntity(
                TEST_SCOPE, TEST_PACKAGE, TEST_DELIVERY, "qa-workout", "qa-plan", "qa-version", "QA offline",
                "2099-07-20", "UTC", 1, "2099-07-20T00:00:00Z", null, TEST_HASH, "2099-07-20T00:00:00Z",
            ),
        )

        assertEquals(TEST_DELIVERY, observed.await())
    }

    @Test fun downloadAndAckPersistReadyStateAtomicallyWithoutSyncPull() = runBlocking {
        val server = MockWebServer().also { it.start() }
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val preferences = PreferenceStore(context)
        val tokens = SecureTokenStore(context).also { it.clear(); it.setTokens("qa-access", "qa-refresh") }
        try {
            preferences.configureServer(server.url("/").toString().trimEnd('/'), true)
            preferences.setAccountScope(TEST_SCOPE)
            val deviceId = preferences.ensureDeviceId()
            val (packageHash, packageEnvelope) = verifiedPackageEnvelope()
            server.enqueue(jsonResponse(deliveryEnvelope(deviceId, packageHash, "created", 1)))
            server.enqueue(jsonResponse(packageEnvelope))
            server.enqueue(jsonResponse(deliveryEnvelope(deviceId, packageHash, "acknowledged", 2)))
            val repository = CompanionRepository(database, preferences, tokens, ApiClient(preferences, tokens))
            database.companionDao().upsertPlanned(
                listOf(
                    PlannedWorkoutEntity(
                        TEST_SCOPE, "qa-workout", "qa-plan", "qa-version", "2099-07-20", "UTC",
                        "planned", "QA offline", 1, "2099-07-20T00:00:00Z", false,
                    ),
                ),
            )
            val observed = async { repository.observeDownloadedDelivery(TEST_SCOPE, "qa-workout").filterNotNull().first() }

            val deliveryId = repository.downloadWorkout(TEST_SCOPE, "qa-workout")
            SyncScheduler.cancelAll()

            assertEquals(TEST_DELIVERY, deliveryId)
            assertEquals(TEST_DELIVERY, observed.await())
            assertEquals("acknowledged", database.companionDao().delivery(TEST_SCOPE, TEST_DELIVERY)?.status)
            assertEquals(packageHash, database.companionDao().packageForDelivery(TEST_SCOPE, TEST_DELIVERY)?.packageHash)
            assertEquals(0, database.companionDao().pendingCount(TEST_SCOPE))
            assertEquals(
                listOf(
                    "/api/v1/companion/deliveries",
                    "/api/v1/companion/deliveries/$TEST_DELIVERY/package",
                    "/api/v1/companion/deliveries/$TEST_DELIVERY/ack",
                ),
                List(3) { server.takeRequest().path.orEmpty() },
            )
        } finally {
            tokens.clear()
            server.shutdown()
        }
    }

    @Test fun priorAuthenticatedAccountRestoresLocallyWithoutNetworkAfterProcessDeath() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val preferences = PreferenceStore(context)
        val serverUrl = "https://qa-offline.example.test"
        preferences.configureServer(serverUrl, false)
        val deviceId = preferences.ensureDeviceId()
        preferences.setAccountScope(TEST_SCOPE)
        preferences.setOfflineSessionEligible(true)
        database.companionDao().upsertAccount(
            AccountEntity(TEST_SCOPE, serverUrl, "qa-user", "qa@example.test", deviceId, "UTC", "2099-07-20T00:00:00Z"),
        )
        SecureTokenStore(context).also { it.clear(); it.setTokens("qa-access", "qa-refresh") }

        val afterProcessDeathTokens = SecureTokenStore(context)
        val restored = CompanionRepository(
            database, preferences, afterProcessDeathTokens, ApiClient(preferences, afterProcessDeathTokens),
        ).restoreLocalSession()

        assertEquals("qa-user", restored?.id)
        assertEquals("qa@example.test", restored?.email)
        assertEquals(null, afterProcessDeathTokens.accessToken())
        assertEquals("qa-refresh", afterProcessDeathTokens.refreshToken())
        afterProcessDeathTokens.clear()
    }

    @Test fun explicitLocalLogoutRemovesOfflineEligibility() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val preferences = PreferenceStore(context)
        preferences.configureServer("https://qa-logout.example.test", false)
        preferences.setAccountScope(TEST_SCOPE)
        preferences.setOfflineSessionEligible(true)
        val tokens = SecureTokenStore(context).also { it.clear(); it.setTokens("qa-access", "qa-refresh") }

        CompanionRepository(database, preferences, tokens, ApiClient(preferences, tokens)).clearLocal(TEST_SCOPE)
        val saved = preferences.values.first()

        assertNull(saved.accountScope)
        assertEquals(false, saved.offlineSessionEligible)
        assertNull(tokens.refreshToken())
    }

    @Test fun incompatibleRecoveredDraftIsIsolatedWithoutCrash() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val dao = database.companionDao()
        dao.upsertPackage(
            WorkoutPackageEntity(
                "scope-a", "package-a", "delivery-a", "workout-a", "plan-a", "version-a", "QA",
                "2026-07-17", "UTC", 1, "2026-07-17T00:00:00Z", null, "server-hash", "2026-07-17T00:00:00Z",
            ),
        )
        dao.upsertDraft(
            WorkoutDraftEntity(
                "scope-a", "delivery-a", "package-a", "submission-a", "event-a", "1.0", "different-hash",
                "active", "2026-07-17T00:00:00Z", null, 0, null, null, null, 0, "payload-hash",
                "2026-07-17T00:00:00Z", "2026-07-24T00:00:00Z", null,
            ),
        )
        val preferences = PreferenceStore(context)
        val tokens = SecureTokenStore(context)
        val repository = CompanionRepository(database, preferences, tokens, ApiClient(preferences, tokens))

        val recovered = repository.observeActiveDraft("scope-a").first()

        assertNotNull(recovered)
        assertEquals("corrupt", recovered?.status)
        assertEquals("draft_package_mismatch", recovered?.corruptReasonCode)
    }

    @Test fun startPersistsPackageDraftAndSetsAtomicallyAndIsIdempotent() = runBlocking {
        val repository = repository()
        seedDownload(status = "downloaded")

        val started = repository.startWorkout(TEST_SCOPE, TEST_DELIVERY)
        val resumed = repository.startWorkout(TEST_SCOPE, TEST_DELIVERY)
        val recovered = repository.observeActiveDraft(TEST_SCOPE).first()

        assertEquals("active", started.status)
        assertEquals(started.clientSubmissionId, resumed.clientSubmissionId)
        assertEquals(TEST_PACKAGE, recovered?.packageId)
        assertEquals(2, database.companionDao().draftSets(TEST_SCOPE, TEST_DELIVERY).size)
        assertNotNull(database.companionDao().packageForDelivery(TEST_SCOPE, TEST_DELIVERY))
        assertEquals(1, database.companionDao().observePendingCount(TEST_SCOPE).first())
        assertEquals(0, database.companionDao().observeConflictCount(TEST_SCOPE).first())
        assertEquals("started_pending", database.companionDao().delivery(TEST_SCOPE, TEST_DELIVERY)?.status)
        assertEquals("companion_start", database.companionDao().pendingStart(TEST_SCOPE, TEST_DELIVERY)?.actionType)
    }

    @Test fun immediateObserverNeverSeesIsolatedDraftOrDraftWithoutSetsAfterOfflineStart() = runBlocking {
        val repository = repository()
        seedDownload(status = "downloaded")

        repository.startWorkout(TEST_SCOPE, TEST_DELIVERY)
        val observed = repository.observeActiveDraft(TEST_SCOPE).first()

        assertEquals("active", observed?.status)
        assertNull(observed?.corruptReasonCode)
        assertTrue(database.companionDao().draftSets(TEST_SCOPE, TEST_DELIVERY).isNotEmpty())
        assertEquals("started_pending", database.companionDao().delivery(TEST_SCOPE, TEST_DELIVERY)?.status)
    }

    @Test fun pendingStartRevalidatesPreviouslyIsolatedDraftAndRepairsDownloadedDeliveryState() = runBlocking {
        val repository = repository()
        seedDownload(status = "downloaded")
        val started = repository.startWorkout(TEST_SCOPE, TEST_DELIVERY)
        val dao = database.companionDao()
        dao.upsertDelivery(listOf(testDelivery(status = "downloaded", revision = 2)))
        dao.upsertDraft(started.copy(status = "corrupt", corruptReasonCode = "draft_start_state_missing"))

        val recovered = repository().observeActiveDraft(TEST_SCOPE).first()

        assertEquals("active", recovered?.status)
        assertNull(recovered?.corruptReasonCode)
        assertEquals(started.clientSubmissionId, recovered?.clientSubmissionId)
        assertEquals("started_pending", dao.delivery(TEST_SCOPE, TEST_DELIVERY)?.status)
        assertEquals(1, dao.pendingCount(TEST_SCOPE))
        assertEquals(0, dao.conflictCount(TEST_SCOPE))
    }

    @Test fun startedDeliverySyncAndRepositoryRecreationKeepDraftRecoverable() = runBlocking {
        val repository = repository()
        seedDownload(status = "acknowledged")
        val started = repository.startWorkout(TEST_SCOPE, TEST_DELIVERY)
        val dao = database.companionDao()
        val firstSet = dao.draftSet(TEST_SCOPE, TEST_DELIVERY, 1, 1)!!
        repository.saveSet(firstSet.copy(reps = 9, weightKg = "12.5", notes = "QA offline"))

        dao.upsertDelivery(listOf(testDelivery(status = "started", revision = 3)))
        dao.upsertDelivery(listOf(testDelivery(status = "started", revision = 3)))
        val afterProcessDeath = repository().observeActiveDraft(TEST_SCOPE).first()

        assertEquals(started.clientSubmissionId, afterProcessDeath?.clientSubmissionId)
        assertEquals("active", afterProcessDeath?.status)
        assertEquals(2, dao.draftSets(TEST_SCOPE, TEST_DELIVERY).size)
        assertEquals(9, dao.draftSet(TEST_SCOPE, TEST_DELIVERY, 1, 1)?.reps)
        assertEquals("12.5", dao.draftSet(TEST_SCOPE, TEST_DELIVERY, 1, 1)?.weightKg)
        assertNotNull(dao.packageForDelivery(TEST_SCOPE, TEST_DELIVERY))
    }

    @Test fun differentConfiguredAccountScopeIsIsolatedWithExactSanitizedReason() = runBlocking {
        val repository = repository()
        seedDownload(status = "acknowledged")
        repository.startWorkout(TEST_SCOPE, TEST_DELIVERY)
        val preferences = PreferenceStore(ApplicationProvider.getApplicationContext())
        preferences.setAccountScope("qa-other-scope")

        val isolated = repository().observeActiveDraft(TEST_SCOPE).first()

        assertEquals("corrupt", isolated?.status)
        assertEquals("draft_account_scope_mismatch", isolated?.corruptReasonCode)
        preferences.setAccountScope(TEST_SCOPE)
    }

    @Test fun differentDeviceIdentityIsIsolatedWithoutTouchingPackageOrCredentials() = runBlocking {
        val repository = repository()
        seedDownload(status = "acknowledged")
        repository.startWorkout(TEST_SCOPE, TEST_DELIVERY)
        val dao = database.companionDao()
        val account = dao.account(TEST_SCOPE)!!
        dao.upsertAccount(account.copy(deviceId = "qa-other-device"))

        val isolated = repository().observeActiveDraft(TEST_SCOPE).first()

        assertEquals("corrupt", isolated?.status)
        assertEquals("draft_device_mismatch", isolated?.corruptReasonCode)
        assertNotNull(dao.packageForDelivery(TEST_SCOPE, TEST_DELIVERY))
    }

    @Test fun unchangedIntegrityFailureDoesNotRepersistOrLoopTheDraftObserver() = runBlocking {
        val repository = repository()
        seedDownload(status = "acknowledged")
        repository.startWorkout(TEST_SCOPE, TEST_DELIVERY)
        val dao = database.companionDao()
        val isolatedAt = "2099-07-20T00:00:00Z"
        val isolated = dao.draft(TEST_SCOPE, TEST_DELIVERY)!!.copy(
            status = "corrupt",
            payloadHash = "qa-invalid-payload-hash",
            updatedAt = isolatedAt,
            corruptReasonCode = "draft_payload_hash_mismatch",
        )
        dao.upsertDraft(isolated)

        val observed = repository.observeActiveDraft(TEST_SCOPE).first()

        assertEquals("corrupt", observed?.status)
        assertEquals("draft_payload_hash_mismatch", observed?.corruptReasonCode)
        assertEquals(isolatedAt, dao.draft(TEST_SCOPE, TEST_DELIVERY)?.updatedAt)
    }

    @Test fun delayedAutosaveCannotUndoCompletedSetOrItsCheckpoint() = runBlocking {
        val repository = repository()
        seedDownload(status = "acknowledged")
        repository.startWorkout(TEST_SCOPE, TEST_DELIVERY)
        val dao = database.companionDao()
        val original = dao.draftSet(TEST_SCOPE, TEST_DELIVERY, 1, 1)!!

        repository.checkpointSet(TEST_SCOPE, TEST_DELIVERY, original.copy(reps = 6, completed = true))
        val completed = dao.draftSet(TEST_SCOPE, TEST_DELIVERY, 1, 1)!!
        repository.saveSet(original.copy(reps = 7, completed = false))
        val afterDelayedAutosave = dao.draftSet(TEST_SCOPE, TEST_DELIVERY, 1, 1)!!

        assertEquals(true, afterDelayedAutosave.completed)
        assertEquals(completed.checkpointSequence, afterDelayedAutosave.checkpointSequence)
        assertEquals(7, afterDelayedAutosave.reps)
    }

    @Test fun offlineCompletionIsDurableRetainsDraftAndCannotDuplicate() = runBlocking {
        val repository = repository()
        seedDownload(status = "acknowledged")
        repository.startWorkout(TEST_SCOPE, TEST_DELIVERY)
        val dao = database.companionDao()
        val set = dao.draftSet(TEST_SCOPE, TEST_DELIVERY, 1, 1)!!
        repository.checkpointSet(TEST_SCOPE, TEST_DELIVERY, set.copy(reps = 5, completed = true))

        repository.completeWorkout(TEST_SCOPE, TEST_DELIVERY)
        val countAfterFirstCompletion = dao.readyPending(TEST_SCOPE, System.currentTimeMillis(), 20).size
        repository.completeWorkout(TEST_SCOPE, TEST_DELIVERY)

        assertEquals("completion_pending", dao.draft(TEST_SCOPE, TEST_DELIVERY)?.status)
        assertEquals(countAfterFirstCompletion, dao.readyPending(TEST_SCOPE, System.currentTimeMillis(), 20).size)
        assertNotNull(dao.packageForDelivery(TEST_SCOPE, TEST_DELIVERY))
        val localHistory = dao.observeHistoryPage(TEST_SCOPE, "history:::").first()
        assertEquals(1, localHistory.size)
        assertEquals("pending", localHistory.single().syncStatus)
        assertEquals(1, dao.observeProgressSummary(TEST_SCOPE, "7").first()?.sessions)
        assertEquals(5, dao.observeProgressSummary(TEST_SCOPE, "7").first()?.totalReps)
        assertEquals(1, dao.observeProgressSummary(TEST_SCOPE, "30").first()?.completedSets)
        listOf("90", "180", "365", "all").forEach { range ->
            assertEquals(1, dao.observeProgressSummary(TEST_SCOPE, range).first()?.sessions)
        }
    }

    @Test fun newerPackageRevisionNeverReplacesAnActiveDraft() = runBlocking {
        val repository = repository()
        seedDownload(status = "acknowledged")
        val dao = database.companionDao()
        dao.upsertPlanned(
            listOf(
                PlannedWorkoutEntity(
                    TEST_SCOPE, "qa-workout", "qa-plan", "qa-version-new", "2099-07-20", "UTC",
                    "planned", "QA offline actualizada", 2, "2099-07-21T00:00:00Z", false,
                ),
            ),
        )
        repository.startWorkout(TEST_SCOPE, TEST_DELIVERY)

        var failed = false
        try {
            repository.downloadWorkout(TEST_SCOPE, "qa-workout")
        } catch (failure: io.healthtracker.companion.core.model.AppFailure) {
            failed = failure.code == io.healthtracker.companion.core.model.AppErrorCode.REVISION_CONFLICT
        }
        SyncScheduler.cancelAll()

        assertTrue(failed)
        assertEquals(TEST_PACKAGE, dao.packageForDelivery(TEST_SCOPE, TEST_DELIVERY)?.packageId)
        assertEquals("package_revision_conflict:revision", dao.planningConflict(TEST_SCOPE, "qa-workout")?.changedFields)
        assertEquals("conflict", dao.planned(TEST_SCOPE, "qa-workout")?.status)
    }

    @Test fun autosavePreservesPausedAndPendingSyncDraftStates() = runBlocking {
        val repository = repository()
        seedDownload(status = "acknowledged")
        repository.startWorkout(TEST_SCOPE, TEST_DELIVERY)
        val dao = database.companionDao()
        val set = dao.draftSet(TEST_SCOPE, TEST_DELIVERY, 1, 1)!!

        repository.pauseOrResume(TEST_SCOPE, TEST_DELIVERY, pause = true)
        repository.saveSet(set.copy(reps = 8))
        assertEquals("paused", dao.draft(TEST_SCOPE, TEST_DELIVERY)?.status)

        repository.pauseOrResume(TEST_SCOPE, TEST_DELIVERY, pause = false)
        repository.checkpointSet(TEST_SCOPE, TEST_DELIVERY, set.copy(reps = 8, completed = true))
        repository.saveSet(set.copy(reps = 9))
        assertEquals("pending_sync", dao.draft(TEST_SCOPE, TEST_DELIVERY)?.status)
    }

    @Test fun legacyStartedDraftWhoseSetsWereCascadeDeletedIsRecovered() = runBlocking {
        seedDownload(status = "started")
        val dao = database.companionDao()
        dao.upsertDraft(
            testDraft(
                status = "corrupt",
                payloadHash = "legacy-hash-calculated-before-cascade",
                corruptReason = "draft_payload_hash_mismatch",
            ),
        )

        val recovered = repository().observeActiveDraft(TEST_SCOPE).first()

        assertEquals("active", recovered?.status)
        assertNull(recovered?.corruptReasonCode)
        assertEquals(2, dao.draftSets(TEST_SCOPE, TEST_DELIVERY).size)
        assertNotNull(dao.packageForDelivery(TEST_SCOPE, TEST_DELIVERY))
    }

    @Test fun compatibleAlreadyStartedConflictReconcilesWithoutRepeatingStart() = runBlocking {
        val server = MockWebServer().also { it.start() }
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val preferences = PreferenceStore(context)
        val tokens = SecureTokenStore(context).also { it.clear(); it.setTokens("qa-access", "qa-refresh") }
        try {
            preferences.configureServer(server.url("/").toString().trimEnd('/'), true)
            preferences.setAccountScope(TEST_SCOPE)
            val deviceId = preferences.ensureDeviceId()
            seedDownload(status = "acknowledged")
            val repository = CompanionRepository(database, preferences, tokens, ApiClient(preferences, tokens))
            repository.startWorkout(TEST_SCOPE, TEST_DELIVERY)
            val dao = database.companionDao()
            val start = dao.readyPending(TEST_SCOPE, System.currentTimeMillis(), 10).single()
            dao.updatePending(start.localId, "conflict", "revision_conflict", Long.MAX_VALUE)
            dao.upsertSyncState(SyncStateEntity(TEST_SCOPE, deviceId, "qa-cursor", "2099-07-20T00:00:00Z", "2099-07-20T00:00:00Z", null))
            server.enqueue(jsonResponse(deliveriesEnvelope(deviceId)))
            server.enqueue(jsonResponse("""{"data":{"schema_version":"1.0","changes":[],"next_cursor":"qa-cursor","has_more":false,"server_time":"2099-07-20T00:00:00Z"},"meta":{"api_version":"1","request_id":"qa"}}"""))
            server.enqueue(jsonResponse("""{"data":{"schema_version":"1.0","device_id":"$deviceId","cursor":"qa-cursor","last_pull_at_sequence":1,"last_push_at":null,"server_sequence":1,"server_time":"2099-07-20T00:00:00Z"},"meta":{"api_version":"1","request_id":"qa"}}"""))

            repository.synchronize(TEST_SCOPE)

            assertEquals(0, dao.observePendingCount(TEST_SCOPE).first())
            assertEquals(0, dao.observeConflictCount(TEST_SCOPE).first())
            assertEquals("started", dao.delivery(TEST_SCOPE, TEST_DELIVERY)?.status)
            val deliveriesRequest = server.takeRequest()
            val pullRequest = server.takeRequest()
            val statusRequest = server.takeRequest()
            assertEquals("GET", deliveriesRequest.method)
            assertEquals("/api/v1/companion/deliveries", deliveriesRequest.path)
            assertEquals("GET", pullRequest.method)
            assertEquals("GET", statusRequest.method)
        } finally {
            tokens.clear()
            server.shutdown()
        }
    }

    @Test fun start200ThenImmediateAndRepeatedPullKeepsOneValidDraft() = runBlocking {
        val server = MockWebServer().also { it.start() }
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val preferences = PreferenceStore(context)
        val tokens = SecureTokenStore(context).also { it.clear(); it.setTokens("qa-access", "qa-refresh") }
        try {
            preferences.configureServer(server.url("/").toString().trimEnd('/'), true)
            preferences.setAccountScope(TEST_SCOPE)
            val deviceId = preferences.ensureDeviceId()
            seedDownload(status = "acknowledged")
            val repository = CompanionRepository(database, preferences, tokens, ApiClient(preferences, tokens))
            val original = repository.startWorkout(TEST_SCOPE, TEST_DELIVERY)
            SyncScheduler.cancelAll()
            database.companionDao().upsertSyncState(
                SyncStateEntity(TEST_SCOPE, deviceId, "qa-cursor", "2099-07-20T00:00:00Z", "2099-07-20T00:00:00Z", null),
            )
            server.enqueue(jsonResponse(deliveryEnvelope(deviceId)))
            enqueuePullAndStatus(server, deviceId)
            enqueuePullAndStatus(server, deviceId)

            repository.synchronize(TEST_SCOPE)
            repository.synchronize(TEST_SCOPE)

            val recovered = repository.observeActiveDraft(TEST_SCOPE).first()
            val dao = database.companionDao()
            assertEquals(original.clientSubmissionId, recovered?.clientSubmissionId)
            assertEquals("active", recovered?.status)
            assertEquals(2, dao.draftSets(TEST_SCOPE, TEST_DELIVERY).size)
            assertNotNull(dao.packageForDelivery(TEST_SCOPE, TEST_DELIVERY))
            assertEquals(0, dao.observePendingCount(TEST_SCOPE).first())
            assertEquals(0, dao.observeConflictCount(TEST_SCOPE).first())
            assertEquals(5, server.requestCount)
            assertEquals("POST", server.takeRequest().method)
        } finally {
            tokens.clear()
            server.shutdown()
        }
    }

    @Test fun start409ForSameAlreadyStartedDeliveryReconcilesWithoutConflict() = runBlocking {
        val server = MockWebServer().also { it.start() }
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val preferences = PreferenceStore(context)
        val tokens = SecureTokenStore(context).also { it.clear(); it.setTokens("qa-access", "qa-refresh") }
        try {
            preferences.configureServer(server.url("/").toString().trimEnd('/'), true)
            preferences.setAccountScope(TEST_SCOPE)
            val deviceId = preferences.ensureDeviceId()
            seedDownload(status = "acknowledged")
            val repository = CompanionRepository(database, preferences, tokens, ApiClient(preferences, tokens))
            val original = repository.startWorkout(TEST_SCOPE, TEST_DELIVERY)
            SyncScheduler.cancelAll()
            val dao = database.companionDao()
            dao.upsertSyncState(SyncStateEntity(TEST_SCOPE, deviceId, "qa-cursor", "2099-07-20T00:00:00Z", "2099-07-20T00:00:00Z", null))
            server.enqueue(
                MockResponse().setResponseCode(409).setHeader("Content-Type", "application/json")
                    .setBody("""{"error":{"code":"delivery_state_conflict","message":"QA","details":{}},"meta":{"api_version":"1","request_id":"qa"}}"""),
            )
            server.enqueue(jsonResponse(deliveriesEnvelope(deviceId)))
            enqueuePullAndStatus(server, deviceId)

            repository.synchronize(TEST_SCOPE)

            val recovered = repository.observeActiveDraft(TEST_SCOPE).first()
            assertEquals(original.clientSubmissionId, recovered?.clientSubmissionId)
            assertEquals("started", dao.delivery(TEST_SCOPE, TEST_DELIVERY)?.status)
            assertEquals(0, dao.observePendingCount(TEST_SCOPE).first())
            assertEquals(0, dao.observeConflictCount(TEST_SCOPE).first())
            assertEquals(4, server.requestCount)
            assertEquals("POST", server.takeRequest().method)
            assertEquals("/api/v1/companion/deliveries", server.takeRequest().path)
        } finally {
            tokens.clear()
            server.shutdown()
        }
    }

    @Test fun manualAndWorkerSyncAreSerializedWithoutInterleavingCursors() = runBlocking {
        val server = MockWebServer().also { it.start() }
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val preferences = PreferenceStore(context)
        val tokens = SecureTokenStore(context).also { it.clear(); it.setTokens("qa-access", "qa-refresh") }
        try {
            preferences.configureServer(server.url("/").toString().trimEnd('/'), true)
            preferences.setAccountScope(TEST_SCOPE)
            val deviceId = preferences.ensureDeviceId()
            database.companionDao().upsertSyncState(
                SyncStateEntity(TEST_SCOPE, deviceId, "qa-cursor", "2099-07-20T00:00:00Z", "2099-07-20T00:00:00Z", null),
            )
            val repository = CompanionRepository(database, preferences, tokens, ApiClient(preferences, tokens))
            server.enqueue(jsonResponse(pullEnvelope()).setBodyDelay(200, TimeUnit.MILLISECONDS))
            server.enqueue(jsonResponse(statusEnvelope(deviceId)))

            coroutineScope {
                listOf(async { repository.synchronize(TEST_SCOPE) }, async { repository.synchronize(TEST_SCOPE) }).awaitAll()
            }

            val paths = List(2) { server.takeRequest().path.orEmpty().substringBefore('?') }
            assertEquals(
                listOf("/api/v1/sync/pull", "/api/v1/sync/status"),
                paths,
            )
        } finally {
            tokens.clear()
            server.shutdown()
        }
    }

    @Test fun delayedStartBlocksProgressAndCompleteUntilQueueCanDrainInOrder() = runBlocking {
        val server = MockWebServer().also { it.start() }
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val preferences = PreferenceStore(context)
        val tokens = SecureTokenStore(context).also { it.clear(); it.setTokens("qa-access", "qa-refresh") }
        try {
            preferences.configureServer(server.url("/").toString().trimEnd('/'), true)
            preferences.setAccountScope(TEST_SCOPE)
            val deviceId = preferences.ensureDeviceId()
            val dao = database.companionDao()
            dao.upsertSyncState(
                SyncStateEntity(TEST_SCOPE, deviceId, "qa-cursor", "2099-07-20T00:00:00Z", "2099-07-20T00:00:00Z", null),
            )
            seedDownload(status = "acknowledged")
            val repository = CompanionRepository(database, preferences, tokens, ApiClient(preferences, tokens))
            repository.startWorkout(TEST_SCOPE, TEST_DELIVERY)
            SyncScheduler.cancelAll()
            val set = dao.draftSet(TEST_SCOPE, TEST_DELIVERY, 1, 1)!!
            repository.checkpointSet(TEST_SCOPE, TEST_DELIVERY, set.copy(reps = 5, completed = true))
            SyncScheduler.cancelAll()
            repository.completeWorkout(TEST_SCOPE, TEST_DELIVERY)
            SyncScheduler.cancelAll()
            val start = dao.queuedActions(TEST_SCOPE, 10).first()
            dao.updatePending(start.localId, "pending", "qa_backoff", System.currentTimeMillis() + 60_000)
            enqueuePullAndStatus(server, deviceId)

            repository.synchronize(TEST_SCOPE)

            assertEquals(3, dao.pendingCount(TEST_SCOPE))
            assertEquals(listOf("/api/v1/sync/pull", "/api/v1/sync/status"), List(2) {
                server.takeRequest().path.orEmpty().substringBefore('?')
            })

            dao.updatePending(start.localId, "pending", null, 0)
            server.enqueue(jsonResponse(deliveryEnvelope(deviceId)))
            server.enqueue(jsonResponse("""{"data":{},"meta":{"api_version":"1","request_id":"qa"}}"""))
            server.enqueue(jsonResponse(completionEnvelope(deviceId)))
            enqueuePullAndStatus(server, deviceId)

            repository.synchronize(TEST_SCOPE)

            assertEquals(
                listOf(
                    "/api/v1/companion/deliveries/$TEST_DELIVERY/start",
                    "/api/v1/companion/deliveries/$TEST_DELIVERY/progress",
                    "/api/v1/companion/deliveries/$TEST_DELIVERY/complete",
                    "/api/v1/sync/pull",
                    "/api/v1/sync/status",
                ),
                List(5) { server.takeRequest().path.orEmpty().substringBefore('?') },
            )
            assertEquals(0, dao.pendingCount(TEST_SCOPE))
            assertEquals(0, dao.conflictCount(TEST_SCOPE))
            assertNull(dao.draft(TEST_SCOPE, TEST_DELIVERY))
            assertEquals(1, dao.observeRecent(TEST_SCOPE, 10, 0).first().size)
        } finally {
            tokens.clear()
            server.shutdown()
        }
    }

    @Test fun genuinelyMissingPackageRemainsCorrupt() = runBlocking {
        database.companionDao().upsertDraft(testDraft(status = "active", payloadHash = "qa-hash"))

        val recovered = repository().observeActiveDraft(TEST_SCOPE).first()

        assertEquals("corrupt", recovered?.status)
        assertEquals("draft_package_missing", recovered?.corruptReasonCode)
    }

    @Test fun packageWithoutExercisesOrSetsDoesNotLeaveWorkoutLoadingForever() = runBlocking {
        val dao = database.companionDao()
        dao.upsertDelivery(listOf(testDelivery("started")))
        dao.upsertPackage(
            WorkoutPackageEntity(
                TEST_SCOPE, TEST_PACKAGE, TEST_DELIVERY, "qa-workout", "qa-plan", "qa-version", "QA empty",
                "2099-07-20", "UTC", 1, "2099-07-20T00:00:00Z", null, TEST_HASH, "2099-07-20T00:00:00Z",
            ),
        )
        dao.upsertDraft(testDraft(status = "active", payloadHash = "qa-hash"))

        val recovered = repository().observeActiveDraft(TEST_SCOPE).first()

        assertEquals("corrupt", recovered?.status)
        assertEquals("draft_package_content_missing", recovered?.corruptReasonCode)
    }

    private fun repository(): CompanionRepository {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val preferences = PreferenceStore(context)
        val tokens = SecureTokenStore(context)
        return CompanionRepository(database, preferences, tokens, ApiClient(preferences, tokens))
    }

    private fun history(scope: String, id: String, event: String, completedAt: String, status: String = "synced") =
        HistorySessionEntity(
            scope, id, event, null, null, null, "Sesión QA", completedAt, null, completedAt,
            "UTC", 1800, 1, 2, "500", false, "qa", status, null, false, completedAt,
        )

    private suspend fun seedDownload(status: String) {
        val dao = database.companionDao()
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val preferences = PreferenceStore(context)
        val existing = preferences.values.first()
        if (existing.serverUrl == null) preferences.configureServer("https://qa-companion.example.test", false)
        val deviceId = preferences.ensureDeviceId()
        preferences.setAccountScope(TEST_SCOPE)
        val configured = preferences.values.first()
        dao.upsertAccount(
            AccountEntity(
                TEST_SCOPE, configured.serverUrl ?: "https://qa-companion.example.test", "qa-user", "qa@example.test",
                deviceId, "UTC", "2099-07-20T00:00:00Z",
            ),
        )
        dao.upsertProfile(LocalProfileEntity(TEST_SCOPE, "qa-profile", "1.0", "1.0", "1.0", 1, "2099-07-20T00:00:00Z"))
        dao.upsertDelivery(listOf(testDelivery(status)))
        dao.replacePackage(
            WorkoutPackageEntity(
                TEST_SCOPE, TEST_PACKAGE, TEST_DELIVERY, "qa-workout", "qa-plan", "qa-version", "QA test1",
                "2099-07-20", "UTC", 1, "2099-07-20T00:00:00Z", null, TEST_HASH, "2099-07-20T00:00:00Z",
            ),
            listOf(PackageExerciseEntity(TEST_SCOPE, TEST_PACKAGE, 1, "QA Squat", null)),
            listOf(
                PackageSetEntity(TEST_SCOPE, TEST_PACKAGE, 1, 1, 5, null, null, null, null, 60, null),
                PackageSetEntity(TEST_SCOPE, TEST_PACKAGE, 1, 2, 5, null, null, null, null, 60, null),
            ),
        )
    }

    private fun testDelivery(status: String, revision: Int = 2) = DeliveryEntity(
        TEST_SCOPE, TEST_DELIVERY, "qa-workout", "qa-profile", TEST_HASH, status, revision, 0,
        null, null, "2099-07-20T00:00:00Z",
    )

    private fun testDraft(
        status: String,
        payloadHash: String,
        corruptReason: String? = null,
        packageHash: String = TEST_HASH,
    ) = WorkoutDraftEntity(
        TEST_SCOPE, TEST_DELIVERY, TEST_PACKAGE, "qa-submission", "qa-event", "1.0", packageHash,
        status, "2099-07-20T00:00:00Z", null, 0, null, null, null, 0, payloadHash,
        "2099-07-20T00:00:00Z", "2099-07-27T00:00:00Z", corruptReason,
    )

    private fun jsonResponse(body: String) = MockResponse()
        .setHeader("Content-Type", "application/json")
        .setBody(body)

    private fun deliveriesEnvelope(deviceId: String) =
        """{"data":[{"schema_version":"1.0","id":"$TEST_DELIVERY","device_id":"$deviceId","profile_id":"qa-profile","planned_workout_id":"qa-workout","package_schema_version":"1.0","package_hash":"$TEST_HASH","status":"started","revision":3,"last_client_sequence":0,"created_at":"2099-07-20T00:00:00Z","updated_at":"2099-07-20T00:00:00Z","expires_at":null,"failure_code":null,"training_session_id":null,"duplicate":false}],"meta":{"api_version":"1","request_id":"qa"}}"""

    private fun deliveryEnvelope(deviceId: String) =
        """{"data":{"schema_version":"1.0","id":"$TEST_DELIVERY","device_id":"$deviceId","profile_id":"qa-profile","planned_workout_id":"qa-workout","package_schema_version":"1.0","package_hash":"$TEST_HASH","status":"started","revision":3,"last_client_sequence":0,"created_at":"2099-07-20T00:00:00Z","updated_at":"2099-07-20T00:00:00Z","expires_at":null,"failure_code":null,"training_session_id":null,"duplicate":false},"meta":{"api_version":"1","request_id":"qa"}}"""

    private fun deliveryEnvelope(deviceId: String, packageHash: String, status: String, revision: Int) =
        """{"data":{"schema_version":"1.0","id":"$TEST_DELIVERY","device_id":"$deviceId","profile_id":"qa-profile","planned_workout_id":"qa-workout","package_schema_version":"1.0","package_hash":"$packageHash","status":"$status","revision":$revision,"last_client_sequence":0,"created_at":"2099-07-20T00:00:00Z","updated_at":"2099-07-20T00:00:00Z","expires_at":null,"failure_code":null,"training_session_id":null,"duplicate":false},"meta":{"api_version":"1","request_id":"qa"}}"""

    private fun verifiedPackageEnvelope(): Pair<String, String> {
        val withoutHash = """{"schema_version":"1.0","package_id":"$TEST_PACKAGE","planned_workout_id":"qa-workout","plan_id":"qa-plan","plan_version_id":"qa-version","title":"QA offline","scheduled_for_date":"2099-07-20","timezone":"UTC","revision":1,"generated_at":"2099-07-20T00:00:00Z","expires_at":null,"exercises":[{"exercise_order":1,"name":"QA Squat","notes":null,"sets":[{"set_number":1,"reps":5,"rest_seconds":60}]}],"supported_metrics":["reps","weight_kg"],"unsupported_fields":[],"server_capabilities":{"offline":true},"device_capabilities":{},"compatibility_warnings":[]}"""
        val hash = CanonicalJson.sha256(Json.parseToJsonElement(withoutHash))
        val packageJson = withoutHash.dropLast(1) + ",\"package_hash\":\"$hash\"}"
        return hash to """{"data":$packageJson,"meta":{"api_version":"1","request_id":"qa"}}"""
    }

    private fun completionEnvelope(deviceId: String) =
        """{"data":{"delivery":{"schema_version":"1.0","id":"$TEST_DELIVERY","device_id":"$deviceId","profile_id":"qa-profile","planned_workout_id":"qa-workout","package_schema_version":"1.0","package_hash":"$TEST_HASH","status":"completed","revision":5,"last_client_sequence":1,"created_at":"2099-07-20T00:00:00Z","updated_at":"2099-07-20T01:00:00Z","expires_at":null,"failure_code":null,"training_session_id":"qa-session","duplicate":false},"completed_workout":{"schema_version":"1.0","id":"qa-session","client_event_id":"qa-event","planned_workout_id":"qa-workout","started_at":"2099-07-20T00:00:00Z","completed_at":"2099-07-20T01:00:00Z","timezone":"UTC","exercises":[]},"duplicate":false},"meta":{"api_version":"1","request_id":"qa"}}"""

    private fun enqueuePullAndStatus(server: MockWebServer, deviceId: String) {
        server.enqueue(jsonResponse(pullEnvelope()))
        server.enqueue(jsonResponse(statusEnvelope(deviceId)))
    }

    private fun pullEnvelope() =
        """{"data":{"schema_version":"1.0","changes":[],"next_cursor":"qa-cursor","has_more":false,"server_time":"2099-07-20T00:00:00Z"},"meta":{"api_version":"1","request_id":"qa"}}"""

    private fun statusEnvelope(deviceId: String) =
        """{"data":{"schema_version":"1.0","device_id":"$deviceId","cursor":"qa-cursor","last_pull_at_sequence":1,"last_push_at":null,"server_sequence":1,"server_time":"2099-07-20T00:00:00Z"},"meta":{"api_version":"1","request_id":"qa"}}"""

    private companion object {
        const val TEST_SCOPE = "qa-scope"
        const val TEST_DELIVERY = "00000000-0000-4000-8000-000000000011"
        const val TEST_PACKAGE = "00000000-0000-4000-8000-000000000012"
        const val TEST_HASH = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    }
}
