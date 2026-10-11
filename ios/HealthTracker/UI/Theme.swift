import HealthTrackerKit
import SwiftUI
import UIKit

/// Design tokens from the web redesign (`backend/app/static/css/app.css`): neutral surfaces,
/// sky-blue primary, square corners and hairline borders, in light and dark variants.
enum Theme {
    static let bg = dynamic(light: 0xF3F2F2, dark: 0x141719)
    static let surface = dynamic(light: 0xFFFFFF, dark: 0x1C2023)
    static let surfaceMuted = dynamic(light: 0xEAE9E9, dark: 0x262B2F)
    static let text = dynamic(light: 0x201E1D, dark: 0xF2F3F4)
    static let textMuted = dynamic(light: 0x605D5D, dark: 0xA3ABB1)
    static let border = dynamic(light: 0x201E1D, lightAlpha: 0.22, dark: 0xF2F3F4, darkAlpha: 0.18)
    static let primary = dynamic(light: 0x075985, dark: 0x38BDF8)
    static let onPrimary = dynamic(light: 0xFFFFFF, dark: 0x0D0F10)
    static let primarySoft = dynamic(light: 0xE3EEF4, dark: 0x10303F)
    static let primaryInk = dynamic(light: 0x043851, dark: 0xBAE6FD)
    static let successBg = dynamic(light: 0xD8ECDF, dark: 0x10301F)
    static let successText = dynamic(light: 0x14532D, dark: 0x86EFAC)
    static let warningBg = dynamic(light: 0xF6E7C3, dark: 0x3D3013)
    static let warningText = dynamic(light: 0x7C5300, dark: 0xF0C46A)
    static let dangerBg = dynamic(light: 0xFFE0D9, dark: 0x4D170E)
    static let dangerText = dynamic(light: 0xAE1800, dark: 0xFF9783)

    enum Space {
        static let s1: CGFloat = 4, s2: CGFloat = 8, s3: CGFloat = 12, s4: CGFloat = 16, s5: CGFloat = 24, s6: CGFloat = 32
    }

    static func colorScheme(_ preference: ThemePreference) -> ColorScheme? {
        switch preference {
        case .system: nil
        case .light: .light
        case .dark: .dark
        }
    }

    private static func dynamic(light: UInt32, lightAlpha: CGFloat = 1, dark: UInt32, darkAlpha: CGFloat = 1) -> Color {
        Color(UIColor { traits in
            traits.userInterfaceStyle == .dark ? UIColor(hex: dark, alpha: darkAlpha) : UIColor(hex: light, alpha: lightAlpha)
        })
    }
}

private extension UIColor {
    convenience init(hex: UInt32, alpha: CGFloat) {
        self.init(
            red: CGFloat((hex >> 16) & 0xFF) / 255,
            green: CGFloat((hex >> 8) & 0xFF) / 255,
            blue: CGFloat(hex & 0xFF) / 255,
            alpha: alpha
        )
    }
}

// MARK: Components

struct Card<Content: View>: View {
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Space.s2) { content }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(Theme.Space.s4)
            .background(Theme.surface)
            .overlay(Rectangle().strokeBorder(Theme.border, lineWidth: 1))
    }
}

struct PrimaryButtonStyle: ButtonStyle {
    var destructive = false
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.body.weight(.semibold))
            .frame(maxWidth: .infinity, minHeight: 50)
            .foregroundStyle(Theme.onPrimary)
            .background((destructive ? Theme.dangerText : Theme.primary).opacity(isEnabled ? 1 : 0.45))
            .opacity(configuration.isPressed ? 0.85 : 1)
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
            .animation(.easeOut(duration: 0.16), value: configuration.isPressed)
    }
}

struct SecondaryButtonStyle: ButtonStyle {
    var destructive = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.body.weight(.medium))
            .frame(maxWidth: .infinity, minHeight: 48)
            .foregroundStyle(destructive ? Theme.dangerText : Theme.primary)
            .background(configuration.isPressed ? Theme.surfaceMuted : Theme.surface)
            .overlay(Rectangle().strokeBorder(destructive ? Theme.dangerText.opacity(0.6) : Theme.border, lineWidth: 1))
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
            .animation(.easeOut(duration: 0.16), value: configuration.isPressed)
    }
}

struct FieldStyle: ViewModifier {
    func body(content: Content) -> some View {
        content
            .padding(.horizontal, Theme.Space.s3)
            .frame(minHeight: 48)
            .background(Theme.surface)
            .overlay(Rectangle().strokeBorder(Theme.border, lineWidth: 1))
    }
}

struct StatusPill: View {
    enum Tone { case success, warning, danger, info }
    let text: String
    let tone: Tone

    var body: some View {
        Text(text)
            .font(.caption.weight(.semibold))
            .padding(.horizontal, Theme.Space.s2)
            .padding(.vertical, Theme.Space.s1)
            .foregroundStyle(foreground)
            .background(background)
    }

    private var foreground: Color {
        switch tone {
        case .success: Theme.successText
        case .warning: Theme.warningText
        case .danger: Theme.dangerText
        case .info: Theme.primaryInk
        }
    }

    private var background: Color {
        switch tone {
        case .success: Theme.successBg
        case .warning: Theme.warningBg
        case .danger: Theme.dangerBg
        case .info: Theme.primarySoft
        }
    }
}
