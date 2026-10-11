import Charts
import HealthTrackerKit
import SwiftUI

/// Android `ProgressScreen` (training section): range, summary metrics, latest record and per-exercise list.
struct TrainingProgressView: View {
    @Environment(AppModel.self) private var model
    private var training: TrainingModel { model.training }

    var body: some View {
        Screen {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: Theme.Space.s2) {
                    ForEach(TrainingModel.progressRanges, id: \.self) { range in
                        Chip(title: Self.rangeLabel(range), selected: training.progressRange == range) {
                            Task { await training.setProgressRange(range) }
                        }
                    }
                }
            }
            Muted(model.connected ? "Datos locales con actualización automática." : "Sin conexión: se muestra la última actualización guardada.")
            if let error = training.progressError {
                Text("Actualización temporal fallida: \(error)").font(.footnote).foregroundStyle(Theme.dangerText)
            }
            if let summary = training.progressSummary {
                Grid(horizontalSpacing: Theme.Space.s2, verticalSpacing: Theme.Space.s2) {
                    GridRow {
                        MetricTile(label: "Sesiones", value: "\(summary.sessions)")
                        MetricTile(label: "Días", value: "\(summary.trainingDays)")
                    }
                    GridRow {
                        MetricTile(label: "Series", value: "\(summary.completedSets)")
                        MetricTile(label: "Duración", value: DisplayText.duration(summary.durationSeconds))
                    }
                    GridRow {
                        MetricTile(label: "Volumen", value: summary.volumeKg.map { "\($0) kg\(summary.volumePartial ? " · parcial" : "")" } ?? "No comparable")
                            .gridCellColumns(2)
                    }
                }
                if summary.hasComparison {
                    Muted("Comparación con el periodo anterior disponible; no se muestran porcentajes con base cero.")
                }
            } else {
                Text(training.progressRefreshing ? "Calculando resumen…" : "No hay resumen guardado para este periodo.").foregroundStyle(Theme.textMuted)
            }
            if let record = training.latestRecord {
                Card {
                    Text("Mejor marca reciente").font(.headline)
                    Text("\(DisplayText.recordType(record.type)) · \(record.value) \(record.unit)")
                    Muted(DisplayText.readableDate(record.date))
                }
            }
            SectionTitle("Ejercicios")
            if training.progressExercises.isEmpty {
                Text("Aún no hay datos suficientes para mostrar ejercicios.").foregroundStyle(Theme.textMuted)
            }
            ForEach(training.progressExercises) { exercise in
                LinkCard(value: ExerciseRoute(id: exercise.publicId)) {
                    Text(exercise.name).font(.headline)
                    Text("\(exercise.sessionCount) sesiones · \(exercise.setCount) series")
                    Text(exercise.bestLoadKg.map { "Mejor carga: \($0) kg" } ?? "Carga no comparable")
                    Text(exercise.volumeKg.map { "Volumen: \($0) kg\(exercise.volumePartial ? " (parcial)" : "")" } ?? "Volumen no disponible")
                    Muted(DisplayText.trend(exercise.trend))
                }
                .accessibilityIdentifier("progress_exercise_row")
            }
        }
        .accessibilityIdentifier("progress_screen")
        .navigationTitle("Progreso")
        .navigationDestination(for: ExerciseRoute.self) { ExerciseProgressView(publicId: $0.id) }
        .refreshable { await training.refreshProgress() }
        .task { await training.refreshProgress() }
    }

    static func rangeLabel(_ range: String) -> String { range == "all" ? "Todo" : "\(range) días" }
}

struct ExerciseRoute: Hashable { let id: String }

/// Android `ExerciseDetailScreen`: trend charts, records and recent sessions for one exercise.
struct ExerciseProgressView: View {
    @Environment(AppModel.self) private var model
    let publicId: String

    var body: some View {
        let training = model.training
        Screen {
            if let exercise = training.selectedExercise, exercise.publicId == publicId {
                Card {
                    Text(exercise.name).font(.title3.weight(.semibold)).accessibilityAddTraits(.isHeader)
                    Text(exercise.lastPerformedAt.map { DisplayText.readableInstant($0) } ?? "Sin sesiones en el periodo")
                    Text("\(exercise.sessionCount) sesiones · \(exercise.setCount) series")
                    Text(exercise.bestLoadKg.map { "Mejor carga: \($0) kg" } ?? "Mejor carga no comparable")
                    if let reps = exercise.bestReps {
                        Text("Mejor serie: \(reps) reps\(exercise.bestRepsWeightKg.map { " con \($0) kg" } ?? "")")
                    }
                    Text(exercise.volumeKg.map { "Volumen: \($0) kg\(exercise.volumePartial ? " (parcial)" : "")" } ?? "Volumen no disponible")
                    Muted(DisplayText.trend(exercise.trend))
                }
                TrendChart(title: "Mejor carga por fecha", points: training.progressPoints, value: { $0.bestLoadKg }, unit: "kg")
                TrendChart(title: "Volumen por sesión", points: training.progressPoints, value: { $0.volumeKg }, unit: "kg")
                if !training.personalRecords.isEmpty {
                    Card {
                        Text("Mejores marcas").font(.headline)
                        ForEach(training.personalRecords) { record in
                            Text("\(DisplayText.recordType(record.type)): \(record.value) \(record.unit) · \(DisplayText.readableDate(record.date))")
                        }
                    }
                }
                SectionTitle("Últimas sesiones")
                ForEach(training.progressPoints.reversed().prefix(10)) { point in
                    Card {
                        Text(DisplayText.readableInstant(point.performedAt))
                        Text("\(point.setCount) series · \(point.volumeKg.map { "\($0) kg" } ?? "volumen no comparable")")
                        Muted("RIR \(point.averageRir ?? "—") · RPE \(point.averageRpe ?? "—")")
                    }
                    .accessibilityElement(children: .combine)
                }
            } else {
                Text("Cargando progreso guardado…").foregroundStyle(Theme.textMuted)
            }
        }
        .navigationTitle("Ejercicio")
        .navigationBarTitleDisplayMode(.inline)
        .task { await training.openProgressExercise(publicId) }
    }
}

/// Line chart of one numeric series with a text summary for VoiceOver (Android `TrendChart`).
private struct TrendChart: View {
    let title: String
    let points: [ProgressPoint]
    let value: (ProgressPoint) -> String?
    let unit: String

    private var plotted: [(point: ProgressPoint, value: Double)] {
        points.compactMap { point in
            guard let text = value(point), let number = Double(text), number.isFinite else { return nil }
            return (point, number)
        }
    }

    var body: some View {
        Card {
            Text(title).font(.headline)
            let data = plotted
            if let scale = DisplayText.chartScale(data.map(\.value)), let first = data.first, let last = data.last {
                Chart(data, id: \.point.sessionPublicId) { item in
                    LineMark(x: .value("Fecha", item.point.performedAt), y: .value(unit, item.value))
                        .foregroundStyle(Theme.primary)
                    PointMark(x: .value("Fecha", item.point.performedAt), y: .value(unit, item.value))
                        .foregroundStyle(Theme.primary)
                }
                .chartXAxis(.hidden)
                .chartYScale(domain: (scale.minimum - scale.span * 0.1)...(scale.maximum + scale.span * 0.1))
                .frame(height: 170)
                .accessibilityLabel("\(title): \(data.count) puntos, de \(Self.number(scale.minimum)) a \(Self.number(scale.maximum)) \(unit)")
                HStack {
                    Muted(DisplayText.readableDate(first.point.date))
                    Spacer()
                    Muted(DisplayText.readableDate(last.point.date))
                }
                Muted("Resumen: \(data.count) \(data.count == 1 ? "punto" : "puntos"); mínimo \(Self.number(scale.minimum)) \(unit) y máximo \(Self.number(scale.maximum)) \(unit).")
            } else {
                Text("Datos insuficientes para esta gráfica.").foregroundStyle(Theme.textMuted)
            }
        }
    }

    static func number(_ value: Double) -> String {
        value.formatted(.number.precision(.fractionLength(0...2)).locale(Locale(identifier: "es_MX")))
    }
}
