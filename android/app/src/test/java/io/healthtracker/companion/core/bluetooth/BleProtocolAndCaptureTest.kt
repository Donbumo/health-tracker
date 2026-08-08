package io.healthtracker.companion.core.bluetooth

import java.util.Base64
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.async
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
class BleProtocolAndCaptureTest {
    private val codec = BleCaptureCodec()

    @Test fun fictionalCaptureRoundTripsWithoutAccountOrAbsoluteTime() {
        val capture = fictionalCapture()
        val serialized = codec.serialize(capture)
        val replayed = codec.parse(serialized)
        assertEquals(capture, replayed)
        val text = serialized.decodeToString()
        listOf("accountScope", "server", "user", "mac", "deviceApiId").forEach { assertFalse(text.contains(it, ignoreCase = true)) }
        assertTrue(text.contains("\"fixtureFictional\":true"))
    }

    @Test fun invalidFormatIsRejected() {
        val invalid = fictionalCapture().copy(formatVersion = "future")
        assertEquals("capture_version_unsupported", runCatching { codec.serialize(invalid) }.exceptionOrNull()?.message)
    }

    @Test fun absoluteSessionTimeIsRejected() {
        assertEquals("capture_absolute_time_forbidden", runCatching { codec.serialize(fictionalCapture().copy(sessionStart = 1)) }.exceptionOrNull()?.message)
    }

    @Test fun invalidBase64IsRejected() {
        val bad = fictionalCapture().copy(events = listOf(BleCaptureEvent(eventType = "notification", relativeTimestampMs = 0, payload = "not base64")))
        assertEquals("capture_payload_invalid", runCatching { codec.serialize(bad) }.exceptionOrNull()?.message)
    }

    @Test fun oversizedFixtureIsRejected() {
        val limited = BleCaptureCodec(limits = BleCaptureLimits(maximumBytes = 1_024))
        val payload = Base64.getEncoder().encodeToString(ByteArray(1_025))
        val bad = fictionalCapture().copy(events = listOf(BleCaptureEvent(eventType = "notification", relativeTimestampMs = 0, payload = payload)))
        assertEquals("capture_byte_limit", runCatching { limited.serialize(bad) }.exceptionOrNull()?.message)
    }

    @Test fun replayIsDeterministic() = runTest {
        val source = DeterministicBleReplaySource()
        assertEquals(source.replay(fictionalCapture()).toList(), source.replay(fictionalCapture()).toList())
    }

    @Test fun emptyFrameIsInvalid() {
        val adapter = XiaomiS400ProtocolAdapter()
        assertEquals(XiaomiS400ProtocolState.INVALID_FRAME, adapter.observe(DecodedBleFrame(0, "empty", byteArrayOf())).state)
    }

    @Test fun firstUnknownFrameStaysUnknown() {
        val adapter = XiaomiS400ProtocolAdapter()
        assertEquals(XiaomiS400ProtocolState.UNKNOWN_FRAME, adapter.observe(frame(1, 2, 3)).state)
    }

    @Test fun repeatedFictionalFramesBecomeStableButUnverified() {
        val adapter = XiaomiS400ProtocolAdapter()
        adapter.observe(frame(1, 2, 3))
        adapter.observe(frame(1, 2, 3))
        assertEquals(XiaomiS400ProtocolState.STABLE_MEASUREMENT_UNVERIFIED, adapter.observe(frame(1, 2, 3)).state)
    }

    @Test fun changingBytesAreReportedWithoutSemantics() {
        val adapter = XiaomiS400ProtocolAdapter()
        adapter.observe(frame(1, 2, 3))
        val observation = adapter.observe(frame(1, 9, 3))
        assertEquals(setOf(1), observation.changedBytePositions)
        assertEquals(XiaomiS400ProtocolState.CANDIDATE_FRAME, observation.state)
    }

    @Test fun s400MapperNeverPublishesWeight() {
        val mapper = DisabledXiaomiS400MeasurementMapper()
        assertNull(mapper.map(ScaleProtocolObservation("stable_measurement_unverified", "fixture", true)))
    }

    @Test fun s400MapperNeverPublishesComposition() {
        val mapper = DisabledXiaomiS400MeasurementMapper()
        assertNull(mapper.map(ScaleProtocolObservation("unsupported_composition", "fixture", true)))
    }

    @Test fun oneGroundTruthObservationCannotEnableWeight() {
        assertFalse(ProtocolEnablementEvidence(1, 1, 1, 1, 0, true, true, true).weightMayBeEnabled())
    }

    @Test fun documentedEvidenceGateCanEnableFutureImplementation() {
        assertTrue(ProtocolEnablementEvidence(5, 3, 1, 5, 0, true, true, true).weightMayBeEnabled())
    }

    @Test fun propertyDecoderDetectsNotifyAndIndicateWithoutWriting() {
        val properties = characteristicProperties(0x10 or 0x20 or 0x02)
        assertEquals(setOf("read", "notify", "indicate"), properties)
        assertFalse("write" in properties)
    }

    @Test fun scanTimeoutMustBeWithinBoundedRange() {
        assertTrue(runCatching { BleScanConfig(14) }.isFailure)
        assertEquals(15, BleScanConfig(15).timeoutSeconds)
        assertEquals(30, BleScanConfig(30).timeoutSeconds)
        assertTrue(runCatching { BleScanConfig(31) }.isFailure)
    }

    @Test fun captureStopsOnTimeoutAndClosesStream() = runTest {
        val stream = FakeBleNotificationStream()
        val pending = async { ExperimentalBleCaptureSession(stream, BleCaptureLimits(maximumDurationMs = 1_000)).capture("abcdef123456") }
        runCurrent()
        advanceTimeBy(1_001)
        val capture = pending.await()
        assertEquals("timeout", capture.events.last().connectionState)
        assertTrue(stream.closed)
    }

    @Test fun captureStopsBeforeByteLimitAndClosesStream() = runTest {
        val stream = FakeBleNotificationStream()
        val pending = async { ExperimentalBleCaptureSession(stream, BleCaptureLimits(maximumBytes = 1_024)).capture("abcdef123456") }
        runCurrent()
        stream.emit(BleNotification("service", "characteristic", 0, ByteArray(1_025)))
        runCurrent()
        assertEquals("byte_limit", pending.await().events.last().connectionState)
        assertTrue(stream.closed)
    }

    @Test fun cancelledCaptureClosesStream() = runTest {
        val stream = FakeBleNotificationStream()
        val pending = async { ExperimentalBleCaptureSession(stream).capture("abcdef123456") }
        runCurrent()
        pending.cancel()
        runCurrent()
        assertTrue(stream.closed)
    }

    private fun fictionalCapture() = BleCapture(
        captureId = "cap_fixture_0001",
        deviceFingerprint = "abcdef123456",
        fixtureFictional = true,
        events = listOf(
            BleCaptureEvent("00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002", "notification", 10, Base64.getEncoder().encodeToString(byteArrayOf(1, 2, 3))),
            BleCaptureEvent(eventType = "connection", relativeTimestampMs = 20, connectionState = "disconnected"),
        ),
        expectedResult = BleExpectedResult("stable_measurement_unverified"),
    )

    private fun frame(vararg values: Int): DecodedBleFrame {
        val bytes = values.map(Int::toByte).toByteArray()
        return Base64BleFrameDecoder().decode(BleCaptureEvent(eventType = "notification", relativeTimestampMs = 0, payload = Base64.getEncoder().encodeToString(bytes)))
    }
}
