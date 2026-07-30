package io.healthtracker.companion.core.bluetooth

import java.util.ArrayDeque

enum class XiaomiS400ProtocolState(val storageValue: String) {
    PROTOCOL_UNKNOWN("protocol_unknown"),
    AWAITING_EVIDENCE("awaiting_evidence"),
    CANDIDATE_FRAME("candidate_frame"),
    UNKNOWN_FRAME("unknown_frame"),
    INVALID_FRAME("invalid_frame"),
    UNSTABLE_MEASUREMENT("unstable_measurement"),
    STABLE_MEASUREMENT_UNVERIFIED("stable_measurement_unverified"),
    VERIFIED_WEIGHT("verified_weight"),
    UNSUPPORTED_COMPOSITION("unsupported_composition"),
}

data class XiaomiS400Observation(
    val state: XiaomiS400ProtocolState,
    val frameFingerprint: String,
    val frameLength: Int,
    val repetitionCount: Int,
    val changedBytePositions: Set<Int>,
)

class XiaomiS400ProtocolAdapter(private val historyLimit: Int = 16) : ScaleProtocolAdapter {
    private val history = ArrayDeque<DecodedBleFrame>()

    override fun accept(frame: DecodedBleFrame): ScaleProtocolObservation {
        val observation = observe(frame)
        return ScaleProtocolObservation(observation.state.storageValue, observation.frameFingerprint, observation.repetitionCount >= 3)
    }

    fun observe(frame: DecodedBleFrame): XiaomiS400Observation {
        if (frame.length == 0 || frame.bytes.size != frame.length) return XiaomiS400Observation(
            XiaomiS400ProtocolState.INVALID_FRAME,
            frame.fingerprint,
            frame.length,
            0,
            emptySet(),
        )
        val previousSameLength = history.filter { it.length == frame.length }
        val repeated = previousSameLength.count { it.fingerprint == frame.fingerprint } + 1
        val changed = previousSameLength.lastOrNull()?.bytes?.zip(frame.bytes)?.mapIndexedNotNull { index, pair ->
            index.takeIf { pair.first != pair.second }
        }?.toSet().orEmpty()
        val state = when {
            repeated >= 3 -> XiaomiS400ProtocolState.STABLE_MEASUREMENT_UNVERIFIED
            previousSameLength.isNotEmpty() -> XiaomiS400ProtocolState.CANDIDATE_FRAME
            else -> XiaomiS400ProtocolState.UNKNOWN_FRAME
        }
        history.addLast(frame)
        while (history.size > historyLimit) history.removeFirst()
        return XiaomiS400Observation(state, frame.fingerprint, frame.length, repeated, changed)
    }
}

class DisabledXiaomiS400MeasurementMapper : ScaleMeasurementMapper {
    override fun map(observation: ScaleProtocolObservation): CandidateScaleMeasurement? = null
}

data class ProtocolEnablementEvidence(
    val captureCount: Int,
    val distinctDisplayedValues: Int,
    val distinctUnits: Int,
    val exactDisplayMatches: Int,
    val collisionCount: Int,
    val repeatable: Boolean,
    val integrityVerified: Boolean,
    val manuallyReviewed: Boolean,
) {
    fun weightMayBeEnabled(): Boolean = captureCount >= 5 &&
        distinctDisplayedValues >= 3 &&
        distinctUnits >= 1 &&
        exactDisplayMatches == captureCount &&
        collisionCount == 0 &&
        repeatable && integrityVerified && manuallyReviewed
}
