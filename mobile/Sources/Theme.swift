import SwiftUI

/// Tactical / military, light mode. Restrained field palette — olive green, earth
/// brown, and black ink on light paper, used sparingly. Entities are distinguished
/// primarily by SHAPE; colour is a secondary military accent "as needed". Explicit
/// colours (not semantic) so the look is identical regardless of system appearance;
/// the app forces light mode.
enum Theme {
    // Surfaces
    static let paper = Color(red: 0.93, green: 0.92, blue: 0.87)   // light field tan
    static let panel = Color(red: 0.96, green: 0.95, blue: 0.91)
    static let hairline = Color(red: 0.72, green: 0.70, blue: 0.62)
    static let faint = Color(red: 0.82, green: 0.80, blue: 0.73)

    // Ink
    static let ink = Color.black
    static let inkSecondary = Color(red: 0.28, green: 0.27, blue: 0.22)

    // Military accents (used sparingly)
    static let olive = Color(red: 0.30, green: 0.37, blue: 0.16)   // friendly / soldier
    static let oliveDark = Color(red: 0.21, green: 0.27, blue: 0.12) // drone
    static let brown = Color(red: 0.40, green: 0.28, blue: 0.15)   // POI / terrain
    static let danger = Color(red: 0.50, green: 0.16, blue: 0.10)  // hazard (muted brick)

    static let mono = Font.system(.body, design: .monospaced)
    static func mono(_ size: CGFloat, weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .monospaced)
    }
}
