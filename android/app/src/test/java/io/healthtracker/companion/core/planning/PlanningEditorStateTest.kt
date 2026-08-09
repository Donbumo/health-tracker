package io.healthtracker.companion.core.planning

import androidx.lifecycle.SavedStateHandle
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class PlanningEditorStateTest {
    @Test
    fun processRecreationRestoresTheExactPlanAndWorkoutEditor() {
        val restored = PlanningEditorState(
            SavedStateHandle(
                mapOf(
                    PlanningEditorState.PLAN_KEY to "qa-plan-uuid",
                    PlanningEditorState.WORKOUT_KEY to "qa-workout-uuid",
                ),
            ),
        )

        assertEquals("qa-plan-uuid", restored.planId.value)
        assertEquals("qa-workout-uuid", restored.workoutId.value)

        restored.selectPlan(null)
        assertNull(restored.planId.value)
        assertNull(restored.workoutId.value)
    }
}
