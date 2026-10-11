import Foundation

/// Debounced per-key persistence (android `DebouncedAutosave`): rapid edits persist only the latest
/// value after the delay; `flush()` persists everything pending immediately, in submission order.
public actor DebouncedAutosave<Value: Sendable> {
    private let delay: Duration
    private let persist: @Sendable (Value) async throws -> Void
    private let onSettled: @Sendable (Error?) async -> Void
    private var pending: [(key: String, value: Value)] = []
    private var timers: [String: Task<Void, Never>] = [:]
    private var persisting = false
    private var waiters: [CheckedContinuation<Void, Never>] = []

    public init(delay: Duration = .milliseconds(400),
                persist: @escaping @Sendable (Value) async throws -> Void,
                onSettled: @escaping @Sendable (Error?) async -> Void = { _ in }) {
        self.delay = delay
        self.persist = persist
        self.onSettled = onSettled
    }

    public func submit(key: String, value: Value) {
        pending.removeAll { $0.key == key }
        pending.append((key, value))
        timers[key]?.cancel()
        let delay = delay
        timers[key] = Task { [weak self] in
            try? await Task.sleep(for: delay)
            guard !Task.isCancelled else { return }
            await self?.persistKey(key)
        }
    }

    public func discard(key: String) {
        pending.removeAll { $0.key == key }
        timers.removeValue(forKey: key)?.cancel()
    }

    public var hasPending: Bool { !pending.isEmpty }

    /// Persists every pending value now. Errors are reported through `onSettled` and rethrown.
    public func flush() async throws {
        timers.values.forEach { $0.cancel() }
        timers.removeAll()
        var firstError: Error?
        while let key = pending.first?.key {
            if let error = await persistKey(key), firstError == nil { firstError = error }
        }
        if let firstError { throw firstError }
    }

    @discardableResult
    private func persistKey(_ key: String) async -> Error? {
        while persisting { await withCheckedContinuation { waiters.append($0) } }
        guard let index = pending.firstIndex(where: { $0.key == key }) else { return nil }
        let value = pending.remove(at: index).value
        timers.removeValue(forKey: key)
        persisting = true
        var failure: Error?
        do { try await persist(value) } catch { failure = error }
        persisting = false
        if !waiters.isEmpty { waiters.removeFirst().resume() }
        if failure != nil || pending.isEmpty { await onSettled(failure) }
        return failure
    }
}
