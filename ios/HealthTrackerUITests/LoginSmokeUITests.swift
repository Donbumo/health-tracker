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

    /// Stage 4: download today's workout, start it, complete a set and the workout; the queue drains
    /// and history shows the synced session. Requires QA_EXPECTED_TODAY_WORKOUT and QA_EXPECTED_EXERCISE.
    func testWorkoutCaptureCompletesAndSyncs() throws {
        let env = ProcessInfo.processInfo.environment
        guard let title = env["QA_EXPECTED_TODAY_WORKOUT"], let exercise = env["QA_EXPECTED_EXERCISE"] else {
            throw XCTSkip("QA workout data not configured")
        }
        let app = XCUIApplication()
        app.launch()
        try loginIfNeeded(app, env)
        XCTAssertTrue(app.staticTexts[title].firstMatch.waitForExistence(timeout: 20), "Today's workout missing")

        let download = app.buttons["download_workout_\(title)"].firstMatch
        if download.waitForExistence(timeout: 5) { download.tap() }
        let start = app.buttons["start_workout_\(title)"].firstMatch
        XCTAssertTrue(start.waitForExistence(timeout: 20), "Download did not finish")
        attach(app, "11-downloaded")
        start.tap()

        XCTAssertTrue(app.staticTexts[exercise].firstMatch.waitForExistence(timeout: 15), "Workout screen did not open")
        attach(app, "12-workout")
        let completeSet = app.buttons["complete_set_1_1"]
        XCTAssertTrue(completeSet.waitForExistence(timeout: 10))
        completeSet.tap()
        XCTAssertTrue(app.staticTexts["Completada"].firstMatch.waitForExistence(timeout: 10), "Set was not completed")
        attach(app, "13-set-completed")

        let finish = app.buttons["complete_workout"]
        for _ in 0..<12 where !finish.isHittable { app.swipeUp() }
        finish.tap()
        app.buttons["Completar"].firstMatch.tap()
        XCTAssertTrue(app.navigationBars["Hoy"].waitForExistence(timeout: 15))
        attach(app, "14-completed")

        app.tabBars.buttons["Historial"].tap()
        let synced = app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "Sincronizado")).firstMatch
        XCTAssertTrue(synced.waitForExistence(timeout: 30), "Completed session did not sync")
        attach(app, "15-history-synced")
    }

    /// Stage 5: create a routine and a workout offline-first, add a catalog exercise, schedule it for
    /// today and see the schedule synced in the agenda. Requires QA_EXPECTED_CATALOG_EXERCISE.
    func testPlanningEditorCreatesAndSchedulesAWorkout() throws {
        let env = ProcessInfo.processInfo.environment
        guard let catalogExercise = env["QA_EXPECTED_CATALOG_EXERCISE"] else { throw XCTSkip("QA catalog not configured") }
        let suffix = String(Int(Date().timeIntervalSince1970) % 100_000)
        let planName = "Plan UI QA \(suffix)"
        let workoutName = "Día UI QA \(suffix)"
        let app = XCUIApplication()
        app.launch()
        try loginIfNeeded(app, env)

        app.tabBars.buttons["Plan"].tap()
        app.buttons["create_plan"].tap()
        let planField = app.alerts.textFields.firstMatch
        XCTAssertTrue(planField.waitForExistence(timeout: 5))
        planField.typeText(planName)
        app.alerts.buttons["Crear"].tap()
        let planRow = app.staticTexts[planName].firstMatch
        XCTAssertTrue(planRow.waitForExistence(timeout: 10), "Created plan not listed")
        planRow.tap()

        let addWorkout = app.buttons["add_workout"]
        XCTAssertTrue(addWorkout.waitForExistence(timeout: 10))
        addWorkout.tap()
        let workoutField = app.alerts.textFields.firstMatch
        XCTAssertTrue(workoutField.waitForExistence(timeout: 5))
        workoutField.typeText(workoutName)
        app.alerts.buttons["Crear"].tap()
        let workoutRow = app.staticTexts[workoutName].firstMatch
        XCTAssertTrue(workoutRow.waitForExistence(timeout: 10), "Created workout not listed")
        attach(app, "16-plan-detail")
        workoutRow.tap()

        let search = app.textFields["catalog_search"]
        XCTAssertTrue(search.waitForExistence(timeout: 10))
        search.tap()
        search.typeText(String(catalogExercise.prefix(5)))
        let item = app.buttons.matching(identifier: "catalog_item").firstMatch
        XCTAssertTrue(item.waitForExistence(timeout: 15), "Catalog did not load")
        item.tap()
        app.buttons["add_selected"].tap()
        XCTAssertTrue(app.staticTexts["Ejercicios (1)"].waitForExistence(timeout: 5))
        attach(app, "17-workout-editor")
        app.buttons["schedule_workout"].tap()

        app.navigationBars["Editar entrenamiento"].buttons["Rutina"].tap()
        XCTAssertTrue(app.navigationBars["Rutina"].waitForExistence(timeout: 5))
        app.navigationBars["Rutina"].buttons["Plan"].tap()
        let agenda = app.segmentedControls.buttons["Agenda"]
        XCTAssertTrue(agenda.waitForExistence(timeout: 5))
        agenda.tap()
        XCTAssertTrue(app.staticTexts[workoutName].firstMatch.waitForExistence(timeout: 10), "Schedule missing from agenda")
        let synced = app.staticTexts.matching(NSPredicate(format: "label == %@", "Programado")).firstMatch
        XCTAssertTrue(synced.waitForExistence(timeout: 40), "Schedule did not sync")
        attach(app, "18-agenda-synced")
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
