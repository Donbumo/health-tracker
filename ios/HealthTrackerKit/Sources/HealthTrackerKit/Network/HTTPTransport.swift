import Foundation

public struct HTTPResult: Sendable {
    public let status: Int
    public let headers: [String: String]
    public let body: Data

    public init(status: Int, headers: [String: String] = [:], body: Data) {
        self.status = status
        self.headers = headers
        self.body = body
    }

    public func header(_ name: String) -> String? {
        headers.first { $0.key.caseInsensitiveCompare(name) == .orderedSame }?.value
    }
}

/// Seam between `APIClient` and the network so request policy is testable without a server.
public protocol HTTPTransport: Sendable {
    func send(_ request: URLRequest) async throws -> HTTPResult
}

public final class URLSessionTransport: NSObject, HTTPTransport, URLSessionTaskDelegate, @unchecked Sendable {
    private let session: URLSession

    public override init() {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 30
        configuration.timeoutIntervalForResource = 60
        configuration.waitsForConnectivity = false
        configuration.httpCookieAcceptPolicy = .never
        configuration.httpShouldSetCookies = false
        configuration.urlCache = nil
        configuration.requestCachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        session = URLSession(configuration: configuration)
        super.init()
    }

    public func send(_ request: URLRequest) async throws -> HTTPResult {
        let (data, response) = try await session.data(for: request, delegate: self)
        guard let http = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
        var headers: [String: String] = [:]
        for (key, value) in http.allHeaderFields {
            if let key = key as? String, let value = value as? String { headers[key] = value }
        }
        return HTTPResult(status: http.statusCode, headers: headers, body: data)
    }

    /// Redirects are never followed: a redirect could forward the bearer token to another origin.
    public func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        willPerformHTTPRedirection response: HTTPURLResponse,
        newRequest request: URLRequest
    ) async -> URLRequest? {
        nil
    }
}
