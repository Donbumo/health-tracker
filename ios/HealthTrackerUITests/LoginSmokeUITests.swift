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
        if let expected = env["QA_EXPECTED_WORKOUT"] {
            XCTAssertTrue(app.staticTexts[expected].firstMatch.waitForExistence(timeout: 20), "Synced workout not shown")
            let synced = NSPredicate(format: "label == %@", "Sincronizado")
            expectation(for: synced, evaluatedWith: app.staticTexts["sync_status"])
            waitForExpectations(timeout: 20)
        }
        attach(app, "03-home")

        app.tabBars.buttons["Ajustes"].tap()
        XCTAssertTrue(app.navigationBars["Ajustes"].waitForExistence(timeout: 5))
        attach(app, "04-settings")

        app.terminate()
        app.launch()
        XCTAssertTrue(app.navigationBars["Hoy"].waitForExistence(timeout: 20), "Session was not restored on relaunch")
        attach(app, "05-restored")
    }

    /// Stage 3: plans, history detail and exercise progress from the seeded QA account.
    /// Requires QA_EXPECTED_SESSION (plan workout name) and QA_EXPECTED_EXERCISE (exercise name).
    func testPlansHistoryAndProgress() throws {
        let env = ProcessInfo.processInfo.environment
        guard let session = env["QA_EXPECTED_SESSION"], let exercise = env["QA_EXPECTED_EXERCISE"] else {
            throw XCTSkip("QA training data not configured")
        }
        let app = XCUIApplication()
        app.launch()
        try loginIfNeeded(app, env)

        app.tabBars.buttons["Plan"].tap()
        XCTAssertTrue(app.staticTexts[session].firstMatch.waitForExistence(timeout: 20), "Seeded plan not listed")
        app.staticTexts[session].firstMatch.tap()
        XCTAssertTrue(app.navigationBars["Rutina"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts[session].firstMatch.waitForExistence(timeout: 10))
        attach(app, "06-plan")

        app.tabBars.buttons["Historial"].tap()
        let row = app.descendants(matching: .any).matching(identifier: "history_row").firstMatch
        XCTAssertTrue(row.waitForExistence(timeout: 20), "History did not load")
        attach(app, "07-history")
        row.tap()
        XCTAssertTrue(app.navigationBars["Sesión"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts[exercise].firstMatch.waitForExistence(timeout: 20), "History detail missing exercise")
        attach(app, "08-history-detail")

        app.tabBars.buttons["Progreso"].tap()
        XCTAssertTrue(app.staticTexts[exercise].firstMatch.waitForExistence(timeout: 20), "Progress exercise missing")
        attach(app, "09-progress")
        app.staticTexts[exercise].firstMatch.tap()
        XCTAssertTrue(app.staticTexts["Mejor carga por fecha"].waitForExistence(timeout: 10))
        attach(app, "10-exercise")

        // The cached copy stays readable after relaunch.
        app.terminate()
        app.launch()
        XCTAssertTrue(app.navigationBars["Hoy"].waitForExistence(timeout: 20))
        app.tabBars.buttons["Historial"].tap()
        XCTAssertTrue(row.waitForExistence(timeout: 10))
    }

    private func loginIfNeeded(_ app: XCUIApplication, _ env: [String: String]) throws {
        if app.navigationBars["Hoy"].waitForExistence(timeout: 8) { return }
        guard let server = env["QA_SERVER_URL"], let username = env["QA_USERNAME"], let password = env["QA_PASSWORD"] else {
            throw XCTSkip("QA backend not configured")
        }
        let serverField = app.textFields["server_field"]
        XCTAssertTrue(serverField.waitForExistence(timeout: 10))
        serverField.tap()
        serverField.typeText(server)
        if server.hasPrefix("http://") {
            let toggle = app.switches["local_http_toggle"]
            if toggle.value as? String == "0" { toggle.coordinate(withNormalizedOffset: CGVector(dx: 0.95, dy: 0.5)).tap() }
        }
        app.textFields["email_field"].tap()
        app.textFields["email_field"].typeText(username)
        app.secureTextFields["password_field"].tap()
        app.secureTextFields["password_field"].typeText(password)
        app.buttons["login_button"].tap()
        XCTAssertTrue(app.navigationBars["Hoy"].waitForExistence(timeout: 20), "Home did not appear after login")
    }

    private func attach(_ app: XCUIApplication, _ name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
