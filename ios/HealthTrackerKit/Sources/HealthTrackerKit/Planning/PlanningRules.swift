import Foundation

/// Planning helpers (android `PlanningRules.kt`). Dates are local calendar days ("yyyy-MM-dd")
/// so a stored day never shifts when the device time zone changes.
public enum PlanningRules {
    private static var calendar: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        calendar.firstWeekday = 2
        return calendar
    }

    /// Moves `id` by `delta` positions; nil when the id is missing or the move leaves the list.
    public static func reorderedIds(_ ids: [String], id: String, delta: Int) -> [String]? {
        guard let from = ids.firstIndex(of: id) else { return nil }
        let to = from + delta
        guard ids.indices.contains(to) else { return nil }
        var values = ids
        values.insert(values.remove(at: from), at: to)
        return values
    }

    /// Monday–Sunday week or the calendar month containing `anchor`.
    public static func dateRange(anchor: String, month: Bool) -> ClosedRange<String>? {
        guard let date = parse(anchor) else { return nil }
        let first: Date
        let last: Date
        if month {
            let components = calendar.dateComponents([.year, .month], from: date)
            first = calendar.date(from: components)!
            last = calendar.date(byAdding: DateComponents(month: 1, day: -1), to: first)!
        } else {
            first = monday(of: date)
            last = calendar.date(byAdding: .day, value: 6, to: first)!
        }
        return format(first)...format(last)
    }

    /// Full weeks (Monday first) covering the month of `anchor`.
    public static func monthGrid(anchor: String) -> [String] {
        guard let range = dateRange(anchor: anchor, month: true), let start = parse(range.lowerBound), let end = parse(range.upperBound) else { return [] }
        let first = monday(of: start)
        let lastMonday = monday(of: end)
        let last = calendar.date(byAdding: .day, value: 6, to: lastMonday)!
        var days: [String] = []
        var cursor = first
        while cursor <= last {
            days.append(format(cursor))
            cursor = calendar.date(byAdding: .day, value: 1, to: cursor)!
        }
        return days
    }

    /// Next/previous week or month, keeping a valid day of month (Jan 31 + 1 month = Feb 28).
    public static func shiftedAnchor(_ anchor: String, month: Bool, delta: Int) -> String {
        guard let date = parse(anchor) else { return anchor }
        let shifted = month
            ? calendar.date(byAdding: .month, value: delta, to: date)!
            : calendar.date(byAdding: .day, value: 7 * delta, to: date)!
        return format(shifted)
    }

    /// Local prescription limits used before autosaving a planned set.
    public static func validPrescription(reps: String, load: String, rir: String, rpe: String, rest: String) -> Bool {
        (reps.isEmpty || Int(reps).map { $0 > 0 } == true) &&
            (load.isEmpty || LoadCalculator.parse(load) != nil) &&
            (rir.isEmpty || LoadCalculator.parse(rir).map { $0 <= 20 } == true) &&
            (rpe.isEmpty || LoadCalculator.parse(rpe).map { $0 <= 10 } == true) &&
            (rest.isEmpty || Int(rest).map { (0...86_400).contains($0) } == true)
    }

    public static func parse(_ day: String) -> Date? {
        guard day.count == 10 else { return nil }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(identifier: "UTC")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.date(from: day)
    }

    public static func format(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(identifier: "UTC")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: date)
    }

    private static func monday(of date: Date) -> Date {
        let weekday = calendar.component(.weekday, from: date) // 1 = Sunday
        let offset = (weekday + 5) % 7
        return calendar.date(byAdding: .day, value: -offset, to: date)!
    }
}
