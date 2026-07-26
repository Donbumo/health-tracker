package io.healthtracker.companion.core.planning

import androidx.lifecycle.SavedStateHandle
import kotlinx.coroutines.flow.StateFlow

internal class PlanningEditorState(private val savedStateHandle: SavedStateHandle) {
    val planId: StateFlow<String?> = savedStateHandle.getStateFlow(PLAN_KEY, null)
    val workoutId: StateFlow<String?> = savedStateHandle.getStateFlow(WORKOUT_KEY, null)

    fun selectPlan(id: String?) {
        savedStateHandle[PLAN_KEY] = id
        if (id == null) selectWorkout(null)
    }

    fun selectWorkout(id: String?) {
        savedStateHandle[WORKOUT_KEY] = id
    }

    internal companion object {
        const val PLAN_KEY = "selected_plan_id"
        const val WORKOUT_KEY = "selected_plan_workout_id"
    }
}
