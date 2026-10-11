import Testing
@testable import HealthTrackerKit

/// Ported from android `ServerUrlValidatorTest`.
struct ServerURLValidatorTests {
    @Test func httpsIsNormalized() {
        let result = ServerURLValidator.validate(" https://Tracker.Example/ ", explicitLocalHTTP: false)
        #expect(result.valid, "\(result.error ?? "")")
        #expect(result.normalizedURL == "https://tracker.example")
    }

    @Test(arguments: [
        "javascript:alert(1)",
        "file:///tmp/app",
        "https://user:pass@example.test",
        "https://example.test/?debug=true",
        "https://example.test/#fragment",
    ])
    func arbitrarySchemesCredentialsQueriesAndFragmentsAreRejected(url: String) {
        #expect(!ServerURLValidator.validate(url, explicitLocalHTTP: false).valid)
    }

    @Test func portAndBasePathArePreservedWithOneCanonicalTrailingSlashPolicy() {
        let result = ServerURLValidator.validate("https://Tracker.Example:8443/health/tracker///", explicitLocalHTTP: false)
        #expect(result.normalizedURL == "https://tracker.example:8443/health/tracker")
    }

    @Test(arguments: [
        "https://example.test/a/../private",
        "https://example.test/a//private",
        "https://example.test/a/%2e%2e/private",
        "https://example.test/a%2fprivate",
        "https://example.test/a\\private",
        "https://example.test:0",
        "https://example.test/with space",
        "https://example.test\n/private",
    ])
    func relativeOrAmbiguousBasePathsAreRejected(url: String) {
        #expect(!ServerURLValidator.validate(url, explicitLocalHTTP: false).valid)
    }

    @Test func defaultPortsShareOneCanonicalServerIdentity() {
        #expect(ServerURLValidator.validate("https://example.test:443", explicitLocalHTTP: false).normalizedURL == "https://example.test")
        #expect(ServerURLValidator.validate("http://127.0.0.1:80", explicitLocalHTTP: true, buildAllowsLocalHTTP: true).normalizedURL == "http://127.0.0.1")
    }

    @Test func localHostPolicyRecognizesOnlyExplicitLocalRanges() {
        for host in ["localhost", "10.0.2.2", "192.168.1.20", "::1", "fd00::1", "fe80::1", "tracker.local"] {
            #expect(ServerURLValidator.isLocalDevelopmentHost(host), "\(host)")
        }
        for host in ["8.8.8.8", "private.example.test", "172.32.0.1", "fe80::1%en0"] {
            #expect(!ServerURLValidator.isLocalDevelopmentHost(host), "\(host)")
        }
    }

    @Test func localHTTPRequiresDebugCapabilityAndExplicitConfirmation() {
        let confirmedDebug = ServerURLValidator.validate("http://192.168.1.20:8000/base", explicitLocalHTTP: true, buildAllowsLocalHTTP: true)
        #expect(confirmedDebug.normalizedURL == "http://192.168.1.20:8000/base")
        #expect(!ServerURLValidator.validate("http://192.168.1.20:8000", explicitLocalHTTP: false, buildAllowsLocalHTTP: true).valid)
        #expect(!ServerURLValidator.validate("http://203.0.113.20:8000", explicitLocalHTTP: true, buildAllowsLocalHTTP: true).valid)
        #expect(!ServerURLValidator.validate("http://192.168.1.20:8000", explicitLocalHTTP: true, buildAllowsLocalHTTP: false).valid)
    }

    @Test func ipv6LiteralsKeepBrackets() {
        let result = ServerURLValidator.validate("http://[::1]:5000", explicitLocalHTTP: true, buildAllowsLocalHTTP: true)
        #expect(result.normalizedURL == "http://[::1]:5000")
    }
}
