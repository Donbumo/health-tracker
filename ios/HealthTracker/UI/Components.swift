import SwiftUI

/// Filter chip (Android `FilterChip`).
struct Chip: View {
    let title: String
    let selected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.subheadline.weight(selected ? .semibold : .regular))
                .padding(.horizontal, Theme.Space.s3)
                .frame(minHeight: 36)
                .foregroundStyle(selected ? Theme.primaryInk : Theme.text)
                .background(selected ? Theme.primarySoft : Theme.surface)
                .overlay(Rectangle().strokeBorder(selected ? Theme.primary : Theme.border, lineWidth: 1))
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}

/// Scrollable screen body with the standard padding and background.
struct Screen<Content: View>: View {
    @ViewBuilder var content: Content

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Space.s3) { content }
                .padding(Theme.Space.s4)
        }
        .background(Theme.bg)
    }
}

struct SectionTitle: View {
    let text: String
    init(_ text: String) { self.text = text }

    var body: some View {
        Text(text).font(.title3.weight(.semibold)).accessibilityAddTraits(.isHeader).padding(.top, Theme.Space.s2)
    }
}

/// Muted secondary line.
struct Muted: View {
    let text: String
    init(_ text: String) { self.text = text }

    var body: some View {
        Text(text).font(.footnote).foregroundStyle(Theme.textMuted)
    }
}

/// Card that navigates to a value when tapped.
struct LinkCard<Value: Hashable, Content: View>: View {
    let value: Value
    @ViewBuilder var content: Content

    var body: some View {
        NavigationLink(value: value) {
            Card {
                HStack(alignment: .center) {
                    VStack(alignment: .leading, spacing: Theme.Space.s1) { content }
                    Spacer(minLength: Theme.Space.s2)
                    Image(systemName: "chevron.right").font(.footnote.weight(.semibold)).foregroundStyle(Theme.textMuted)
                }
            }
        }
        .buttonStyle(.plain)
    }
}

/// Small labelled metric tile.
struct MetricTile: View {
    let label: String
    let value: String

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(.caption).foregroundStyle(Theme.textMuted)
            Text(value).font(.title3.weight(.semibold)).lineLimit(1).minimumScaleFactor(0.7)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(Theme.Space.s3)
        .background(Theme.surface)
        .overlay(Rectangle().strokeBorder(Theme.border, lineWidth: 1))
        .accessibilityElement(children: .combine)
    }
}
