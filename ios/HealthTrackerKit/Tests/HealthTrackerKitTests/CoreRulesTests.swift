import Foundation
import Testing
@testable import HealthTrackerKit

/// Ported from android `ErrorMapperTest`, `CanonicalJsonTest`, `AuthRecoveryTest`,
/// `RedactionTest` and `PrivateFileNamesTest`.
struct ErrorMapperTests {
    @Test func timeoutAndUnavailableServerRemainRetryableNotConflicts() {
        let timeout = ErrorMapper.network(URLError(.timedOut))
        let unavailable = ErrorMapper.network(URLError(.notConnectedToInternet))
        #expect(timeout.code == .timeout)
        #expect(unavailable.code == .networkUnavailable)
        #expect(timeout.retryable && unavailable.retryable)
    }

    @Test(arguments: [AppErrorCode.networkUnavailable, .timeout, .tlsError, .serverError, .rateLimited, .unauthorized])
    func temporaryRefreshFailuresPreserveOfflineSession(code: AppErrorCode) {
        #expect(refreshFailureDisposition(AppFailure(code, "QA temporal", retryable: true)) == .preserveLocalSession)
    }

    @Test func dnsRefusalAndTlsUseSanitizedStableCodes() {
        let dns = ErrorMapper.network(URLError(.cannotFindHost, userInfo: [NSLocalizedDescriptionKey: "internal.qa.invalid"]))
        let refused = ErrorMapper.network(URLError(.cannotConnectToHost, userInfo: [NSLocalizedDescriptionKey: "secret-host"]))
        let tls = ErrorMapper.network(URLError(.serverCertificateUntrusted, userInfo: [NSLocalizedDescriptionKey: "certificate details"]))
        #expect(dns.code == .networkUnavailable)
        #expect(refused.code == .networkUnavailable)
        #expect(tls.code == .tlsError)
        #expect(!dns.userMessage.contains("internal.qa.invalid"))
        #expect(!refused.userMessage.contains("secret-host"))
        #expect(!tls.userMessage.contains("certificate details"))
    }

    @Test func expectedHttpFailuresHaveStableNonRawClassification() {
        #expect(ErrorMapper.http(status: 401, error: nil, retryAfter: nil).code == .unauthorized)
        for status in [403, 404, 409] { #expect(ErrorMapper.http(status: status, error: nil, retryAfter: nil).code == .validationError) }
        #expect(ErrorMapper.http(status: 429, error: nil, retryAfter: 3).code == .rateLimited)
        for status in [500, 502, 503, 504] { #expect(ErrorMapper.http(status: status, error: nil, retryAfter: nil).code == .serverError) }
    }

    @Test(arguments: [AppErrorCode.refreshFailed, .deviceRevoked])
    func definitiveRefreshFailureOrRevocationClearsSession(code: AppErrorCode) {
        #expect(refreshFailureDisposition(AppFailure(code, "QA definitiva", retryable: false)) == .clearLocalSession)
    }

    @Test func retryAfterAcceptsSecondsAndHttpDatesWithinBounds() {
        #expect(APIClient.parseRetryAfter("5") == 5)
        #expect(APIClient.parseRetryAfter("999999") == APIClient.maxRetryAfterSeconds)
        let now = Date(timeIntervalSince1970: 1_700_000_000)
        // 1_700_000_000 is Tue, 14 Nov 2023 22:13:20 GMT.
        #expect(APIClient.parseRetryAfter("Tue, 14 Nov 2023 22:15:20 GMT", now: now) == 120)
        #expect(APIClient.parseRetryAfter("Tue, 14 Nov 2023 22:00:00 GMT", now: now) == 0)
        #expect(APIClient.parseRetryAfter("not a date") == nil)
    }
}

struct CanonicalJSONTests {
    @Test func keyOrderDoesNotChangeHash() throws {
        let first = try JSONValue.parse(#"{"b":2,"a":{"z":1,"x":0}}"#)
        let second = try JSONValue.parse(#"{"a":{"x":0,"z":1},"b":2}"#)
        #expect(CanonicalJSON.sha256(first) == CanonicalJSON.sha256(second))
        #expect(CanonicalJSON.sha256(first) == "dd509768f814cf066b8e7fe99aa527fd718e13d8718be4639ce07ae172590a59")
    }

    @Test func packageHashFieldCanBeExcluded() throws {
        let first = try JSONValue.parse(#"{"a":1,"package_hash":"old"}"#)
        let second = try JSONValue.parse(#"{"package_hash":"new","a":1}"#)
        #expect(CanonicalJSON.sha256(first) != CanonicalJSON.sha256(second))
        #expect(CanonicalJSON.sha256(first, excludingTopLevelKey: "package_hash") == CanonicalJSON.sha256(second, excludingTopLevelKey: "package_hash"))
    }

    @Test func numberLiteralsAndEscapesRoundTripLosslessly() throws {
        let text = #"{"weight":72.50,"reps":1.0,"big":12345678901234567890,"note":"a\"b\\c\nd/é","u":"\u0001"}"#
        let encoded = try JSONValue.parse(text).encoded()
        #expect(encoded == #"{"weight":72.50,"reps":1.0,"big":12345678901234567890,"note":"a\"b\\c\nd/é","u":"\u0001"}"#)
    }

    @Test func malformedJSONIsRejected() {
        for text in [#"{"a":}"#, "[1,]", "01", #"{"a":1} x"#, #""\x""#] {
            #expect(throws: (any Error).self) { try JSONValue.parse(text) }
        }
    }

    @Test func accountScopeIsDeterministicPerServerAndUser() {
        let a = CanonicalJSON.accountScope(serverURL: "https://tracker.example", userPublicId: "qa-user-1")
        #expect(a == CanonicalJSON.accountScope(serverURL: "https://tracker.example", userPublicId: "qa-user-1"))
        #expect(a != CanonicalJSON.accountScope(serverURL: "https://other.example", userPublicId: "qa-user-1"))
        #expect(a.count == 64)
    }
}

struct AuthRecoveryTests {
    @Test(arguments: [AppErrorCode.networkUnavailable, .timeout, .tlsError, .serverError, .rateLimited, .unauthorized])
    func temporaryFailuresAllowCachedOfflineResume(code: AppErrorCode) {
        let decision = classifyRestoreFailure(AppFailure(code, "QA temporal", retryable: true))
        #expect(decision.state == .authenticated)
        #expect(!decision.clearLocalSession)
    }

    @Test func revokedExpiredAndIncompatibleSessionsRemainBlocked() {
        let revoked = classifyRestoreFailure(AppFailure(.deviceRevoked, "QA revoked", retryable: false))
        #expect(revoked.state == .deviceRevoked && revoked.clearLocalSession)
        let expired = classifyRestoreFailure(AppFailure(.refreshFailed, "QA expired", retryable: false))
        #expect(expired.state == .tokenExpired && expired.clearLocalSession)
        #expect(classifyRestoreFailure(AppFailure(.schemaIncompatible, "QA schema", retryable: false)).state == .serverIncompatible)
    }
}

struct SecurityTests {
    @Test func secretsAreRemovedFromDiagnostics() {
        let output = Redaction.sanitize("Authorization: Bearer-secret password=hunter2 refresh_token=rt1.secret")
        #expect(!output.contains("hunter2"))
        #expect(!output.contains("rt1.secret"))
        #expect(output.contains("[REDACTED]"))
    }

    @Test func remoteIdentifiersNeverBecomePathSegments() throws {
        let malicious = "../../secure_session_v1\\..\\token"
        let value = try PrivateFileNames.opaque(label: "medical-document", remoteIdentifier: malicious, extension: "pdf")
        #expect(value.range(of: "^medical-document-[0-9a-f]{32}\\.pdf$", options: .regularExpression) != nil)
        #expect(!value.contains("/") && !value.contains("\\") && !value.contains(".."))
    }

    @Test func namesAreDeterministicAndPurposeSeparated() throws {
        let first = try PrivateFileNames.opaque(label: "activity-route", remoteIdentifier: "qa-remote-id", extension: "json")
        #expect(first == (try PrivateFileNames.opaque(label: "activity-route", remoteIdentifier: "qa-remote-id", extension: "json")))
        #expect(first != (try PrivateFileNames.opaque(label: "activity-series", remoteIdentifier: "qa-remote-id", extension: "json")))
    }

    @Test func callerControlledLabelsAndExtensionsAreRejected() {
        #expect(throws: PrivateFileNames.Failure.labelInvalid) { try PrivateFileNames.opaque(label: "../escape", remoteIdentifier: "qa", extension: "json") }
        #expect(throws: PrivateFileNames.Failure.extensionInvalid) { try PrivateFileNames.opaque(label: "safe", remoteIdentifier: "qa", extension: "../db") }
    }

    @Test func tokensAreBoundToServerIdentityAndVersioned() throws {
        let store = TokenStore(storage: InMemorySecureStorage())
        try store.setTokens(access: "qa-access", refresh: "qa-refresh", serverIdentity: "https://a.example")
        #expect(store.accessToken(serverIdentity: "https://a.example") == "qa-access")
        #expect(store.refreshToken(serverIdentity: "https://b.example") == nil)
        let version = store.mutationVersion
        store.clear()
        #expect(store.refreshToken() == nil)
        #expect(!(try store.replaceTokensIfVersion(version, access: "x", refresh: "y", serverIdentity: "https://a.example")))
        #expect(!store.clearIfVersion(version))
    }
}
