import Foundation
import Network

/// Publishes de-duplicated reachability changes, like Android `ConnectivityObserver`.
public final class ConnectivityMonitor: @unchecked Sendable {
    private let monitor = NWPathMonitor()
    private let queue = DispatchQueue(label: "io.healthtracker.connectivity")
    private let lock = NSLock()
    private var continuations: [UUID: AsyncStream<Bool>.Continuation] = [:]
    private var last: Bool?

    public init() {
        monitor.pathUpdateHandler = { [weak self] path in
            self?.publish(path.status == .satisfied)
        }
        monitor.start(queue: queue)
    }

    deinit { monitor.cancel() }

    public var isConnected: Bool { lock.withLock { last ?? (monitor.currentPath.status == .satisfied) } }

    public func updates() -> AsyncStream<Bool> {
        AsyncStream { continuation in
            let id = UUID()
            let current: Bool? = lock.withLock {
                continuations[id] = continuation
                return last
            }
            if let current { continuation.yield(current) }
            continuation.onTermination = { [weak self] _ in
                _ = self?.lock.withLock { self?.continuations.removeValue(forKey: id) }
            }
        }
    }

    private func publish(_ connected: Bool) {
        let targets: [AsyncStream<Bool>.Continuation] = lock.withLock {
            guard last != connected else { return [] }
            last = connected
            return Array(continuations.values)
        }
        targets.forEach { $0.yield(connected) }
    }
}
