import SwiftUI

/// Top-down tactical map of the local frame — a relative range/bearing map (NOT a
/// geographic basemap: this system is offline + GPS-less, so everything is drawn
/// relative to the launch point at the centre). Concentric range rings + bearings
/// replace the grid; live movement trails show each unit's path; entities are
/// pill-style markers. Pure view — it draws whatever it is given.
struct LocalMapView: View {
    let entities: [Entity]
    let trails: [String: [Vec3]]
    var projection: MapProjection

    var body: some View {
        Canvas { context, size in
            drawRangeRings(&context, size: size)
            drawBearings(&context, size: size)
            drawTrails(&context, size: size)
            drawOrigin(&context, size: size)
            for entity in entities { drawMarker(entity, in: &context, size: size) }
            drawNorth(&context, size: size)
            drawScaleBar(&context, size: size)
        }
        .background(Theme.paper)
    }

    private func center(_ size: CGSize) -> CGPoint { CGPoint(x: size.width / 2, y: size.height / 2) }

    // Concentric distance rings every 5 m, faintly labelled.
    private func drawRangeRings(_ ctx: inout GraphicsContext, size: CGSize) {
        let c = center(size)
        let s = projection.scale(in: size)
        let maxR = hypot(size.width, size.height) / 2
        var m = 5
        while CGFloat(m) * s <= maxR {
            let r = CGFloat(m) * s
            ctx.stroke(Path(ellipseIn: CGRect(x: c.x - r, y: c.y - r, width: 2 * r, height: 2 * r)),
                       with: .color(Theme.hairline.opacity(0.55)), lineWidth: 0.6)
            ctx.draw(Text("\(m)M").font(Theme.mono(7)).foregroundColor(Theme.inkSecondary.opacity(0.6)),
                     at: CGPoint(x: c.x + r * 0.707 - 2, y: c.y - r * 0.707 - 2))
            m += 5
        }
    }

    // Faint radial bearings every 45°.
    private func drawBearings(_ ctx: inout GraphicsContext, size: CGSize) {
        let c = center(size)
        let len = hypot(size.width, size.height) / 2
        var path = Path()
        for deg in stride(from: 0, to: 360, by: 45) {
            let a = CGFloat(deg) * .pi / 180
            path.move(to: c)
            path.addLine(to: CGPoint(x: c.x + cos(a) * len, y: c.y + sin(a) * len))
        }
        ctx.stroke(path, with: .color(Theme.hairline.opacity(0.35)), lineWidth: 0.5)
    }

    // Movement trails — the "path" line for each soldier/drone. Drawn as a comet
    // tail: older segments fade out, the freshest segment is solid. The drone trace
    // is emphasised (thicker + a heading chevron at the head) since it's the unit the
    // operator is reading most.
    private func drawTrails(_ ctx: inout GraphicsContext, size: CGSize) {
        // Draw soldier trails first so the drone trace sits on top.
        func drawOrder(_ id: String) -> Int { entityType(forId: id) == .drone ? 1 : 0 }
        let ordered = trails.sorted { drawOrder($0.key) < drawOrder($1.key) }
        for (id, pts) in ordered where pts.count >= 2 {
            let isDrone = entityType(forId: id) == .drone
            let base = color(forId: id)
            let lineW: CGFloat = isDrone ? 2.6 : 1.8
            let screen = pts.map { projection.point(for: $0, in: size) }
            let n = screen.count
            for i in 1..<n {
                let t = Double(i) / Double(n - 1)           // 0 = oldest, 1 = head
                var seg = Path()
                seg.move(to: screen[i - 1]); seg.addLine(to: screen[i])
                ctx.stroke(seg, with: .color(base.opacity(0.12 + 0.78 * t)),
                           style: StrokeStyle(lineWidth: lineW, lineCap: .round, lineJoin: .round))
            }
            if isDrone {
                drawHeadingChevron(&ctx, from: screen[n - 2], to: screen[n - 1], color: base)
            }
        }
    }

    // Small chevron at the head of a trail pointing along the direction of travel.
    private func drawHeadingChevron(_ ctx: inout GraphicsContext, from a: CGPoint, to b: CGPoint, color: Color) {
        let dx = b.x - a.x, dy = b.y - a.y
        let len = hypot(dx, dy)
        guard len > 0.5 else { return }
        let ux = dx / len, uy = dy / len            // unit heading
        let px = -uy, py = ux                        // perpendicular
        let back: CGFloat = 7, half: CGFloat = 4
        let tail = CGPoint(x: b.x - ux * back, y: b.y - uy * back)
        var v = Path()
        v.move(to: CGPoint(x: tail.x + px * half, y: tail.y + py * half))
        v.addLine(to: b)
        v.addLine(to: CGPoint(x: tail.x - px * half, y: tail.y - py * half))
        ctx.stroke(v, with: .color(color), style: StrokeStyle(lineWidth: 1.8, lineCap: .round, lineJoin: .round))
    }

    private func drawOrigin(_ ctx: inout GraphicsContext, size: CGSize) {
        let c = center(size)
        let r: CGFloat = 5
        ctx.stroke(Path(CGRect(x: c.x - r, y: c.y - r, width: 2 * r, height: 2 * r)),
                   with: .color(Theme.inkSecondary), lineWidth: 1.4)
        ctx.draw(Text("LAUNCH").font(Theme.mono(7, weight: .semibold)).foregroundColor(Theme.inkSecondary),
                 at: CGPoint(x: c.x, y: c.y + 15))
    }

    private func drawNorth(_ ctx: inout GraphicsContext, size: CGSize) {
        let x = size.width - 22
        let y: CGFloat = 22
        var arrow = Path()
        arrow.move(to: CGPoint(x: x, y: y - 10)); arrow.addLine(to: CGPoint(x: x - 5, y: y + 6))
        arrow.addLine(to: CGPoint(x: x, y: y + 2)); arrow.addLine(to: CGPoint(x: x + 5, y: y + 6))
        arrow.closeSubpath()
        ctx.fill(arrow, with: .color(Theme.ink))
        ctx.draw(Text("N").font(Theme.mono(9, weight: .bold)).foregroundColor(Theme.ink),
                 at: CGPoint(x: x, y: y + 14))
    }

    private func drawScaleBar(_ ctx: inout GraphicsContext, size: CGSize) {
        let s = projection.scale(in: size)
        let y = size.height - 18
        let x0: CGFloat = 14
        let x1 = x0 + 5 * s   // 5 metres
        var bar = Path()
        bar.move(to: CGPoint(x: x0, y: y)); bar.addLine(to: CGPoint(x: x1, y: y))
        bar.move(to: CGPoint(x: x0, y: y - 4)); bar.addLine(to: CGPoint(x: x0, y: y + 4))
        bar.move(to: CGPoint(x: x1, y: y - 4)); bar.addLine(to: CGPoint(x: x1, y: y + 4))
        ctx.stroke(bar, with: .color(Theme.ink), lineWidth: 1.2)
        ctx.draw(Text("5 M").font(Theme.mono(8)).foregroundColor(Theme.inkSecondary),
                 at: CGPoint(x: (x0 + x1) / 2, y: y - 9))
    }

    private func drawMarker(_ entity: Entity, in ctx: inout GraphicsContext, size: CGSize) {
        let p = projection.point(for: entity.position, in: size)
        let tint = color(for: entity.type).opacity(opacity(for: entity.status))
        let r: CGFloat = (entity.type == .soldier || entity.type == .drone) ? 7 : 5

        switch entity.type {
        case .soldier:
            ctx.fill(Path(ellipseIn: CGRect(x: p.x - r, y: p.y - r, width: 2 * r, height: 2 * r)), with: .color(tint))
        case .drone:
            ctx.fill(triangle(at: p, r: r), with: .color(tint))
        case .poi:
            ctx.stroke(diamond(at: p, r: r), with: .color(tint), lineWidth: 1.6)
        case .hazard:
            ctx.stroke(cross(at: p, r: r), with: .color(tint), lineWidth: 2)
        case .object:
            ctx.fill(Path(ellipseIn: CGRect(x: p.x - 2.5, y: p.y - 2.5, width: 5, height: 5)), with: .color(tint))
        }

        // Positron-style label chip.
        if let label = entity.label {
            let text = label.uppercased()
            let fs: CGFloat = 8.5
            let w = CGFloat(text.count) * fs * 0.62 + 10
            let chip = CGRect(x: p.x + r + 4, y: p.y - 8, width: w, height: 15)
            ctx.fill(Path(roundedRect: chip, cornerRadius: 1.5), with: .color(Theme.panel.opacity(0.92)))
            ctx.stroke(Path(roundedRect: chip, cornerRadius: 1.5), with: .color(tint.opacity(0.8)), lineWidth: 0.75)
            ctx.draw(Text(text).font(Theme.mono(fs)).foregroundColor(Theme.ink),
                     at: CGPoint(x: chip.midX + 1, y: chip.midY))
        }

        // Live SLAM position readout for the moving units.
        if entity.type == .drone || entity.type == .soldier {
            drawUnitReadout(entity, at: p, in: &ctx)
        }
    }

    private func triangle(at p: CGPoint, r: CGFloat) -> Path {
        var path = Path()
        path.move(to: CGPoint(x: p.x, y: p.y - r))
        path.addLine(to: CGPoint(x: p.x - r, y: p.y + r * 0.8))
        path.addLine(to: CGPoint(x: p.x + r, y: p.y + r * 0.8))
        path.closeSubpath()
        return path
    }

    private func diamond(at p: CGPoint, r: CGFloat) -> Path {
        var path = Path()
        path.move(to: CGPoint(x: p.x, y: p.y - r)); path.addLine(to: CGPoint(x: p.x + r, y: p.y))
        path.addLine(to: CGPoint(x: p.x, y: p.y + r)); path.addLine(to: CGPoint(x: p.x - r, y: p.y))
        path.closeSubpath()
        return path
    }

    private func cross(at p: CGPoint, r: CGFloat) -> Path {
        var path = Path()
        path.move(to: CGPoint(x: p.x - r, y: p.y - r)); path.addLine(to: CGPoint(x: p.x + r, y: p.y + r))
        path.move(to: CGPoint(x: p.x + r, y: p.y - r)); path.addLine(to: CGPoint(x: p.x - r, y: p.y + r))
        return path
    }

    private func color(forId id: String) -> Color {
        if let e = entities.first(where: { $0.id == id }) { return color(for: e.type) }
        return Theme.inkSecondary
    }

    private func entityType(forId id: String) -> EntityType? {
        entities.first(where: { $0.id == id })?.type
    }

    // Range (m from launch) + bearing (° from north) read straight off the SLAM
    // local frame, drawn under the drone/operator markers.
    private func drawUnitReadout(_ entity: Entity, at p: CGPoint, in ctx: inout GraphicsContext) {
        let range = hypot(entity.position.x, entity.position.y)
        var brg = atan2(entity.position.x, entity.position.y) * 180 / .pi   // +y=N, +x=E
        if brg < 0 { brg += 360 }
        let text = String(format: "%.0fM · %03.0f°", range, brg)
        ctx.draw(Text(text).font(Theme.mono(7)).foregroundColor(Theme.inkSecondary),
                 at: CGPoint(x: p.x, y: p.y + 16))
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
