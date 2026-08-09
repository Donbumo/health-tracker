package io.healthtracker.companion.core.database

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import java.util.UUID
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ExternalSourcesProcessRecreationTest {
    @Test fun bleAssociationSurvivesDatabaseRecreation() {
        runBlocking {
            val context = ApplicationProvider.getApplicationContext<android.content.Context>()
            val databaseName = "alpha16-process-recreation-${UUID.randomUUID()}.db"
            try {
                val database = Room.databaseBuilder(context, CompanionDatabase::class.java, databaseName).build()
                try {
                    database.companionDao().upsertBleDeviceAssociation(fictionalAssociation())
                } finally {
                    database.close()
                }

                val reopened = Room.databaseBuilder(context, CompanionDatabase::class.java, databaseName).build()
                try {
                    val restored = reopened.companionDao().bleDeviceAssociationByFingerprint("qa-scope", "f1c710a1f1c710a1f1c710a1")
                    assertEquals("QA ficticio", restored?.sanitizedName)
                    assertEquals("xiaomi_s400_user_confirmed", restored?.userConfirmedModel)
                } finally {
                    reopened.close()
                }
            } finally {
                context.deleteDatabase(databaseName)
            }
        }
    }

    private fun fictionalAssociation() = BleDeviceAssociationEntity(
        accountScope = "qa-scope",
        associationKey = "qa-association",
        systemAssociationId = null,
        sanitizedName = "QA ficticio",
        alias = null,
        deviceFingerprint = "f1c710a1f1c710a1f1c710a1",
        serviceUuids = "00000000-0000-4000-8000-000000000001",
        manufacturerFingerprint = "f1c710a1f1c7",
        firstSeenAt = "2026-07-28T00:00:00Z",
        lastSeenAt = "2026-07-28T00:00:00Z",
        state = "associated_explicit_scan",
        userConfirmedModel = "xiaomi_s400_user_confirmed",
    )
}
