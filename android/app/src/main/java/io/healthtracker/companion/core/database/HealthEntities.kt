package io.healthtracker.companion.core.database

import androidx.room.Entity
import androidx.room.Index

@Entity(tableName = "daily_health_summaries", primaryKeys = ["accountScope", "date"])
data class DailyHealthSummaryEntity(
    val accountScope: String,
    val date: String,
    val timezone: String,
    val weightId: String?,
    val weightKg: String?,
    val weightIsExactDate: Boolean,
    val caloriesKcal: String?,
    val proteinG: String?,
    val carbohydrateG: String?,
    val fatG: String?,
    val fiberG: String?,
    val nutritionTargetKcal: String?,
    val stepsEntryId: String?,
    val steps: Long?,
    val stepsGoal: Long?,
    val scheduledWorkouts: Int,
    val completedWorkouts: Int,
    val syncStatus: String,
    val updatedAt: String?,
)

@Entity(
    tableName = "body_stats",
    primaryKeys = ["accountScope", "publicId"],
    indices = [Index(value = ["accountScope", "recordedAt"])],
)
data class BodyStatEntity(
    val accountScope: String,
    val publicId: String,
    val recordedAt: String,
    val weightKg: String,
    val bodyFatPercent: String?,
    val muscleMassKg: String?,
    val waterPercent: String?,
    val visceralFat: String?,
    val bmrKcal: String?,
    val bmi: String?,
    val notes: String?,
    val source: String,
    val revision: Int,
    val localRevision: Long,
    val syncStatus: String,
    val createdAt: String,
    val updatedAt: String,
)

@Entity(tableName = "nutrition_days", primaryKeys = ["accountScope", "date"])
data class NutritionDayEntity(
    val accountScope: String,
    val date: String,
    val caloriesKcal: String?,
    val proteinG: String?,
    val fatG: String?,
    val netCarbsG: String?,
    val totalCarbsG: String?,
    val fiberG: String?,
    val sugarG: String?,
    val sodiumMg: String?,
    val targetCaloriesKcal: String?,
    val updatedAt: String?,
)

@Entity(
    tableName = "nutrition_entries",
    primaryKeys = ["accountScope", "publicId"],
    indices = [Index(value = ["accountScope", "date", "mealType", "updatedAt"])],
)
data class NutritionEntryEntity(
    val accountScope: String,
    val publicId: String,
    val date: String,
    val mealType: String,
    val mealName: String?,
    val name: String,
    val quantity: String?,
    val unit: String?,
    val foodId: String?,
    val caloriesKcal: String?,
    val proteinG: String?,
    val fatG: String?,
    val netCarbsG: String?,
    val totalCarbsG: String?,
    val fiberG: String?,
    val sugarG: String?,
    val sodiumMg: String?,
    val notes: String?,
    val dataComplete: Boolean,
    val revision: Int,
    val localRevision: Long,
    val syncStatus: String,
    val createdAt: String,
    val updatedAt: String,
)

@Entity(
    tableName = "food_catalog",
    primaryKeys = ["accountScope", "publicId"],
    indices = [Index(value = ["accountScope", "normalizedName"])],
)
data class FoodCatalogEntity(
    val accountScope: String,
    val publicId: String,
    val name: String,
    val normalizedName: String,
    val brand: String?,
    val servingSizeG: String?,
    val servingLabel: String?,
    val caloriesPer100g: String?,
    val proteinGPer100g: String?,
    val fatGPer100g: String?,
    val carbsGPer100g: String?,
    val netCarbsGPer100g: String?,
    val fiberGPer100g: String?,
    val sodiumMgPer100g: String?,
    val notes: String?,
    val custom: Boolean,
    val archived: Boolean,
    val dataComplete: Boolean,
    val revision: Int,
    val syncStatus: String,
    val updatedAt: String,
)

@Entity(tableName = "food_catalog_state", primaryKeys = ["accountScope", "query"])
data class FoodCatalogStateEntity(
    val accountScope: String,
    val query: String,
    val nextCursor: String?,
    val hasMore: Boolean,
    val updatedAt: String,
)

@Entity(
    tableName = "daily_steps",
    primaryKeys = ["accountScope", "publicId"],
    indices = [Index(value = ["accountScope", "date", "source"], unique = true)],
)
data class DailyStepEntity(
    val accountScope: String,
    val publicId: String,
    val date: String,
    val steps: Long,
    val source: String,
    val goal: Long?,
    val revision: Int,
    val localRevision: Long,
    val syncStatus: String,
    val createdAt: String,
    val updatedAt: String,
)

@Entity(tableName = "health_conflicts", primaryKeys = ["accountScope", "entityId"])
data class HealthConflictEntity(
    val accountScope: String,
    val entityId: String,
    val entityType: String,
    val conflictType: String,
    val localRevision: Long,
    val serverRevision: Int?,
    val createdAt: String,
)

@Entity(tableName = "health_progress_points", primaryKeys = ["accountScope", "date"])
data class HealthProgressPointEntity(
    val accountScope: String,
    val date: String,
    val weightKg: String?,
    val steps: Long?,
    val caloriesKcal: String?,
    val proteinG: String?,
    val carbohydrateG: String?,
    val fatG: String?,
    val updatedAt: String,
)
