// QA only. Enumerate/click a single explicit SDK-free fixture application's
// windows; never route events to the installed user browser or another app.
import Foundation
import AppKit
import ApplicationServices
import Vision

let command = CommandLine.arguments[1]
if command == "text-boxes" {
    let image = NSImage(contentsOfFile: CommandLine.arguments[2])!
    let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil)!
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    request.usesLanguageCorrection = false
    try VNImageRequestHandler(cgImage: cgImage).perform([request])
    let rows: [[String: Any]] = (request.results ?? []).compactMap { row in
        guard let text = row.topCandidates(1).first?.string else { return nil }
        let box = row.boundingBox
        return ["text": text, "x": box.minX, "y": box.minY,
                "width": box.width, "height": box.height]
    }
    print(String(data: try JSONSerialization.data(withJSONObject: rows), encoding: .utf8)!)
} else {
    let pid = pid_t(CommandLine.arguments[2])!
    guard let app = NSRunningApplication(processIdentifier: pid),
          let path = app.bundleURL?.path,
          path.contains("/out/mac-privacy-candidate/MetaBrowser.app")
    else { fatalError("Only the SDK-free candidate fixture is allowed") }
    let all = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements],
                                        kCGNullWindowID) as? [[String: Any]] ?? []
    let owned = all.filter { $0[kCGWindowOwnerPID as String] as? Int == Int(pid) }
    if command == "list" {
        let rows: [[String: Any]] = owned.compactMap { row in
            guard let id = row[kCGWindowNumber as String] as? Int,
                  let raw = row[kCGWindowBounds as String] as? NSDictionary,
                  let bounds = CGRect(dictionaryRepresentation: raw)
            else { return nil }
            return ["id": id, "x": bounds.minX, "y": bounds.minY,
                    "width": bounds.width, "height": bounds.height,
                    "layer": row[kCGWindowLayer as String] ?? 0]
        }
        print(String(data: try JSONSerialization.data(withJSONObject: rows), encoding: .utf8)!)
    } else if command == "click" {
        let id = Int(CommandLine.arguments[3])!
        guard let window = owned.first(where: { $0[kCGWindowNumber as String] as? Int == id }),
              let raw = window[kCGWindowBounds as String] as? NSDictionary,
              let bounds = CGRect(dictionaryRepresentation: raw)
        else {
            print("{\"clicked\":false,\"reason\":\"window_disappeared\"}")
            exit(0)
        }
        let point = CGPoint(x: Double(CommandLine.arguments[4])!,
                            y: Double(CommandLine.arguments[5])!)
        precondition(bounds.contains(point), "Click is outside the owned window")
        app.activate(options: [.activateAllWindows])
        RunLoop.current.run(until: Date().addingTimeInterval(0.3))
        // Window rectangles include transparent desktop-widget overlays. Query
        // the actual accessibility hit target rather than treating the whole
        // rectangle as an opaque cover. Never inspect a foreign element's text.
        var element: AXUIElement?
        let status = AXUIElementCopyElementAtPosition(AXUIElementCreateSystemWide(),
                                                      Float(point.x), Float(point.y), &element)
        if status == .success, let element = element {
            var owner: pid_t = 0
            AXUIElementGetPid(element, &owner)
            if owner == pid {
                func attribute(_ name: CFString) -> CFTypeRef? {
                    var value: CFTypeRef?
                    AXUIElementCopyAttributeValue(element, name, &value)
                    return value
                }
                let role = attribute(kAXRoleAttribute as CFString) as? String
                let title = attribute(kAXTitleAttribute as CFString) as? String
                if role == "AXButton" && ["确定", "好", "OK"].contains(title ?? "") {
                    let pressed = AXUIElementPerformAction(element, kAXPressAction as CFString)
                    print("{\"clicked\":\(pressed == .success),\"method\":\"owned_ax_hit_target\"}")
                    exit(0)
                }
            }
        }
        // Cocoa startup modals may ignore events posted directly to a PID.
        // Allow an OS click only after rechecking both foreground ownership and
        // the topmost window at this exact point. Abort on any competing app.
        guard NSWorkspace.shared.frontmostApplication?.processIdentifier == pid else {
            print("{\"clicked\":false,\"reason\":\"fixture_not_foreground\"}")
            exit(0)
        }
        func windowAtPoint() -> [String: Any]? {
          let current = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements],
                                                   kCGNullWindowID) as? [[String: Any]] ?? []
          return current.first { row in
            guard let raw = row[kCGWindowBounds as String] as? NSDictionary,
                  let rectangle = CGRect(dictionaryRepresentation: raw)
            else { return false }
            return rectangle.contains(point)
          }
        }
        var hit = windowAtPoint()
        if let overlayPID = hit?[kCGWindowOwnerPID as String] as? Int,
           let overlay = NSRunningApplication(processIdentifier: pid_t(overlayPID)),
           overlay.bundleURL?.path == "/System/Library/CoreServices/NotificationCenter.app" {
            // Dismiss only this verified, reversible system overlay. Do not
            // terminate it or touch its notification data. Recheck ownership
            // afterward; an overlay that remains still prohibits the click.
            for down in [true, false] {
                CGEvent(keyboardEventSource: nil, virtualKey: 53, keyDown: down)?.postToPid(pid_t(overlayPID))
                RunLoop.current.run(until: Date().addingTimeInterval(0.05))
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.3))
            hit = windowAtPoint()
        }
        guard hit?[kCGWindowOwnerPID as String] as? Int == Int(pid),
              hit?[kCGWindowNumber as String] as? Int == id else {
            // Activation can complete the earlier Return and dismiss the
            // alert. Do not click its old coordinates; let the caller inspect
            // the new UI and independently verify readiness/clean shutdown.
            let detail: [String: Any] = [
                "clicked": false, "reason": "window_changed_or_covered",
                "wanted_window": id, "wanted_pid": Int(pid),
                "hit_pid": hit?[kCGWindowOwnerPID as String] ?? -1,
                "hit_window": hit?[kCGWindowNumber as String] ?? -1,
                "hit_layer": hit?[kCGWindowLayer as String] ?? -1,
                "hit_alpha": hit?[kCGWindowAlpha as String] ?? -1]
            print(String(data: try JSONSerialization.data(withJSONObject: detail), encoding: .utf8)!)
            exit(0)
        }
        for type in [CGEventType.leftMouseDown, CGEventType.leftMouseUp] {
            let event = CGEvent(mouseEventSource: nil, mouseType: type,
                                mouseCursorPosition: point, mouseButton: .left)!
            event.setIntegerValueField(.mouseEventClickState, value: 1)
            event.post(tap: .cghidEventTap)
            RunLoop.current.run(until: Date().addingTimeInterval(0.05))
        }
        print("{\"clicked\":true}")
    } else { fatalError("Unknown fixture command") }
}
