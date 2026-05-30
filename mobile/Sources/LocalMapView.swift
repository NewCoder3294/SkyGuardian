import SwiftUI

/// Top-down tactical map of the local frame. Pure view: it draws whatever entities
/// it is given — no business logic, no networking. Military light-mode aesthetic;
/// entities are distinguished by SHAPE (NATO-style), colour is a secondary accent.
struct LocalMapView: View {
    let entities: [Entity]
    var projection: MapProjection

    var body: some View {
        Canvas { context, size in
            drawGrid(&context, size: size)
            drawOrigin(&context, size: size)
            for entity in entities {
                drawMarker(entity, in: &context, size: size)
            }
        }
        .background(Theme.paper)
    }

    private func drawGrid(_ context: inout GraphicsContext, size: CGSize) {
        let step = projection.scale(in: size)  // 1 metre
        guard step > 1 else { return }
        var path = Path()
        var x = size.width / 2
        while x <= size.width { path.move(to: CGPoint(x: x, y: 0)); path.addLine(to: CGPoint(x: x, y: size.height)); x += step }
        x = size.width / 2 - step
        while x >= 0 { path.move(to: CGPoint(x: x, y: 0)); path.addLine(to: CGPoint(x: x, y: size.height)); x -= step }
        var y = size.height / 2
        while y <= size.height { path.move(to: CGPoint(x: 0, y: y)); path.addLine(to: CGPoint(x: size.width, y: y)); y += step }
        y = size.height / 2 - step
        while y >= 0 { path.move(to: CGPoint(x: 0, y: y)); path.addLine(to: CGPoint(x: size.width, y: y)); y -= step }
        context.stroke(path, with: .color(Theme.hairline.opacity(0.6)), lineWidth: 0.5)
    }

    private func drawOrigin(_ context: inout GraphicsContext, size: CGSize) {
        let c = CGPoint(x: size.width / 2, y: size.height / 2)
        var cross = Path()
        cross.move(to: CGPoint(x: c.x - 9, y: c.y)); cross.addLine(to: CGPoint(x: c.x + 9, y: c.y))
        cross.move(to: CGPoint(x: c.x, y: c.y - 9)); cross.addLine(to: CGPoint(x: c.x, y: c.y + 9))
        context.stroke(cross, with: .color(Theme.inkSecondary), lineWidth: 1)
        context.draw(Text("LAUNCH").font(Theme.mono(8, weight: .semibold)).foregroundColor(Theme.inkSecondary),
                     at: CGPoint(x: c.x, y: c.y + 18))
    }

    private func drawMarker(_ entity: Entity, in context: inout GraphicsContext, size: CGSize) {
        let p = projection.point(for: entity.position, in: size)
        let tint = color(for: entity.type).opacity(opacity(for: entity.status))
        let r: CGFloat = (entity.type == .soldier || entity.type == .drone) ? 8 : 6

        switch entity.type {
        case .soldier:                       // filled circle = friendly
            context.fill(Path(ellipseIn: CGRect(x: p.x - r, y: p.y - r, width: 2 * r, height: 2 * r)), with: .color(tint))
        case .drone:                         // triangle = own air asset
            context.fill(trianglePath(at: p, r: r), with: .color(tint))
        case .poi:                           // hollow diamond = point of interest
            context.stroke(diamondPath(at: p, r: r), with: .color(tint), lineWidth: 1.6)
        case .hazard:                        // X = hazard
            context.stroke(crossPath(at: p, r: r), with: .color(tint), lineWidth: 2)
        case .object:                        // small filled dot = detected object
            context.fill(Path(ellipseIn: CGRect(x: p.x - 3, y: p.y - 3, width: 6, height: 6)), with: .color(tint))
        }

        if let label = entity.label {
            context.draw(Text(label.uppercased()).font(Theme.mono(8)).foregroundColor(tint),
                         at: CGPoint(x: p.x, y: p.y - r - 8))
        }
    }

    private func trianglePath(at p: CGPoint, r: CGFloat) -> Path {
        var path = Path()
        path.move(to: CGPoint(x: p.x, y: p.y - r))
        path.addLine(to: CGPoint(x: p.x - r, y: p.y + r * 0.8))
        path.addLine(to: CGPoint(x: p.x + r, y: p.y + r * 0.8))
        path.closeSubpath()
        return path
    }

    private func diamondPath(at p: CGPoint, r: CGFloat) -> Path {
        var path = Path()
        path.move(to: CGPoint(x: p.x, y: p.y - r))
        path.addLine(to: CGPoint(x: p.x + r, y: p.y))
        path.addLine(to: CGPoint(x: p.x, y: p.y + r))
        path.addLine(to: CGPoint(x: p.x - r, y: p.y))
        path.closeSubpath()
        return path
    }

    private func crossPath(at p: CGPoint, r: CGFloat) -> Path {
        var path = Path()
        path.move(to: CGPoint(x: p.x - r, y: p.y - r)); path.addLine(to: CGPoint(x: p.x + r, y: p.y + r))
        path.move(to: CGPoint(x: p.x + r, y: p.y - r)); path.addLine(to: CGPoint(x: p.x - r, y: p.y + r))
        return path
    }

    private func color(for type: EntityType) -> Color {
        switch type {
        case .soldier: return Theme.olive
        case .drone: return Theme.oliveDark
        case .poi: return Theme.brown
        case .hazard: return Theme.danger
        case .object: return Theme.inkSecondary
        }
    }

    private func opacity(for status: EntityStatus) -> Double {
        switch status {
        case .active: return 1.0
        case .stale: return 0.55
        case .lost: return 0.28
        }
    }
}
