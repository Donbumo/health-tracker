import XCTest

/// End-to-end smoke test against a running backend. Skipped unless QA credentials are provided:
/// TEST_RUNNER_QA_SERVER_URL, TEST_RUNNER_QA_USERNAME, TEST_RUNNER_QA_PASSWORD (fictional QA user only).
@MainActor
final class LoginSmokeUITests: XCTestCase {
    override func setUp() async throws {
        continueAfterFailure = false
    }

    func testLoginShowsHomeAndSettings() throws {
        let env = ProcessInfo.processInfo.environment
        guard let server = env["QA_SERVER_URL"], let username = env["QA_USERNAME"], let password = env["QA_PASSWORD"] else {
            throw XCTSkip("QA backend not configured")
        }
        let app = XCUIApplication()
        app.launch()
        attach(app, "01-login")

        let serverField = app.textFields["server_field"]
        XCTAssertTrue(serverField.waitForExistence(timeout: 10))
        serverField.tap()
        serverField.typeText(server)
        if server.hasPrefix("http://") {
            let toggle = app.switches["local_http_toggle"]
            if toggle.value as? String == "0" { toggle.coordinate(withNormalizedOffset: CGVector(dx: 0.95, dy: 0.5)).tap() }
        }
        let email = app.textFields["email_field"]
        email.tap()
        email.typeText(username)
        let secure = app.secureTextFields["password_field"]
        secure.tap()
        secure.typeText(password)
        attach(app, "02-filled")
        app.buttons["login_button"].tap()

        XCTAssertTrue(app.navigationBars["Hoy"].waitForExistence(timeout: 20), "Home did not appear after login")
        attach(app, "03-home")

        app.tabBars.buttons["Ajustes"].tap()
        XCTAssertTrue(app.navigationBars["Ajustes"].waitForExistence(timeout: 5))
        attach(app, "04-settings")

        app.terminate()
        app.launch()
        XCTAssertTrue(app.navigationBars["Hoy"].waitForExistence(timeout: 20), "Session was not restored on relaunch")
        attach(app, "05-restored")
    }

    private func attach(_ app: XCUIApplication, _ name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
