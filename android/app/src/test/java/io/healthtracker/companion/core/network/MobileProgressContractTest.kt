package io.healthtracker.companion.core.network

import io.healthtracker.companion.core.model.ApiEnvelope
import io.healthtracker.companion.core.model.MobileHistoryPageDto
import io.healthtracker.companion.core.model.ProgressExerciseDetailDto
import io.healthtracker.companion.core.model.ProgressSummaryDto
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Test

class MobileProgressContractTest {
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false }

    @Test fun historyPageMapsNullableVolumeAndCursor() {
        val envelope = json.decodeFromString<ApiEnvelope<MobileHistoryPageDto>>(
            """{"data":{"schema_version":"1.0","items":[{"public_id":"11111111-1111-4111-8111-111111111111","performed_at":"2026-07-23T12:00:00Z","completed_at":"2026-07-23T12:00:00Z","name":"Sesión QA","duration_seconds":1800,"exercise_count":1,"set_count":2,"volume_kg":null,"volume_partial":true,"source":"device_sync","sync_status":"synced"}],"next_cursor":"cursor-qa","has_more":true}}""",
        )
        assertEquals("cursor-qa", envelope.data.nextCursor)
        assertNull(envelope.data.items.single().volumeKg)
    }

    @Test fun summaryDoesNotInventPercentageWhenPreviousIsZero() {
        val envelope = json.decodeFromString<ApiEnvelope<ProgressSummaryDto>>(
            """{"data":{"schema_version":"1.0","range":"7","generated_at":"2026-07-24T00:00:00Z","metrics":{"sessions":1,"training_days":1,"distinct_exercises":1,"completed_sets":2,"total_reps":10,"volume_kg":"500.00","volume_partial":false,"duration_seconds":1800},"comparison":{"sessions":{"change":"1.00","percent":null,"previous":"0.00"}},"comparable_load_modes":["direct_total"]}}""",
        )
        assertNull(envelope.data.comparison?.get("sessions")?.percent)
    }

    @Test fun exerciseDetailMapsTextFallbackDataAndRecords() {
        val envelope = json.decodeFromString<ApiEnvelope<ProgressExerciseDetailDto>>(
            """{"data":{"schema_version":"1.0","range":"30","exercise":{"public_id":"22222222-2222-4222-8222-222222222222","name":"Remo QA","last_performed_at":"2026-07-23T00:00:00Z","session_count":1,"set_count":1,"best_load_kg":"40.00","best_repetition_set":{"reps":8,"weight_kg":"40.00"},"volume_kg":"320.00","volume_partial":false,"load_comparable":true,"load_modes":["direct_total"],"trend":"insufficient_data"},"points":[{"date":"2026-07-23","performed_at":"2026-07-23T00:00:00Z","session_public_id":"33333333-3333-4333-8333-333333333333","best_load_kg":"40.00","best_reps":8,"volume_kg":"320.00","set_count":1,"average_rir":"2.00","average_rpe":"8.00","load_comparable":true}],"personal_records":[{"type":"highest_load","value":"40.00","unit":"kg","date":"2026-07-23","session_public_id":"33333333-3333-4333-8333-333333333333","set_index":1}],"recent_sessions":[]}}""",
        )
        assertEquals(1, envelope.data.points.size)
        assertFalse(envelope.data.personalRecords.isEmpty())
    }
}
