package io.healthtracker.companion.core.sync

import kotlinx.coroutines.CancellationException

/** Preserve structured cancellation across retry/error mapping boundaries. */
internal fun Throwable.rethrowIfCancellation() {
    if (this is CancellationException) throw this
}
