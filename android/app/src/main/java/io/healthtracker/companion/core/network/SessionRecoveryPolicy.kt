package io.healthtracker.companion.core.network

import io.healthtracker.companion.core.model.AppErrorCode
import io.healthtracker.companion.core.model.AppFailure

internal enum class RefreshFailureDisposition { PRESERVE_LOCAL_SESSION, CLEAR_LOCAL_SESSION }

internal fun refreshFailureDisposition(error: AppFailure): RefreshFailureDisposition = when (error.code) {
    AppErrorCode.REFRESH_FAILED,
    AppErrorCode.UNAUTHORIZED,
    AppErrorCode.DEVICE_REVOKED -> RefreshFailureDisposition.CLEAR_LOCAL_SESSION
    else -> RefreshFailureDisposition.PRESERVE_LOCAL_SESSION
}
