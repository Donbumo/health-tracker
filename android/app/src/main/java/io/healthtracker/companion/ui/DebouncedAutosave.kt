package io.healthtracker.companion.ui

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

internal class DebouncedAutosave<T>(
    private val scope: CoroutineScope,
    private val debounceMillis: Long = 400,
    private val persist: suspend (T) -> Unit,
    private val onSaving: () -> Unit = {},
    private val onSettled: (Throwable?) -> Unit = {},
) {
    private val lock = Any()
    private val persistMutex = Mutex()
    private val pending = linkedMapOf<String, T>()
    private val jobs = mutableMapOf<String, Job>()

    fun submit(key: String, value: T) {
        synchronized(lock) {
            pending[key] = value
            jobs.remove(key)?.cancel()
            jobs[key] = scope.launch {
                delay(debounceMillis)
                persistKey(key)
            }
        }
        onSaving()
    }

    fun discard(key: String) {
        synchronized(lock) {
            pending.remove(key)
            jobs.remove(key)?.cancel()
        }
    }

    fun hasPending(): Boolean = synchronized(lock) { pending.isNotEmpty() }

    suspend fun flush() {
        while (true) {
            val keys = synchronized(lock) {
                jobs.values.forEach(Job::cancel)
                jobs.clear()
                pending.keys.toList()
            }
            if (keys.isEmpty()) return
            keys.forEach { persistKey(it) }
        }
    }

    private suspend fun persistKey(key: String) = persistMutex.withLock {
        val value = synchronized(lock) {
            jobs.remove(key)
            pending.remove(key)
        } ?: return@withLock
        val failure = runCatching { persist(value) }.exceptionOrNull()
        if (failure != null || !hasPending()) onSettled(failure)
    }
}
