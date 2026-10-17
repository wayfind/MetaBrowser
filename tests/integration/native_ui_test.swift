import Foundation
import ApplicationServices
import AppKit
let pid = pid_t(CommandLine.arguments[1])!
let app = AXUIElementCreateApplication(pid)
func attr(_ e: AXUIElement, _ name: String) -> CFTypeRef? {
    var value: CFTypeRef?
    AXUIElementCopyAttributeValue(e, name as CFString, &value)
    return value
}
func elements() -> [AXUIElement] {
    var result: [AXUIElement] = []
    func walk(_ e: AXUIElement, _ depth: Int) {
        if depth > 25 { return }
        result.append(e)
        for child in attr(e, kAXChildrenAttribute) as? [AXUIElement] ?? [] { walk(child, depth+1) }
    }
    for window in attr(app, kAXWindowsAttribute) as? [AXUIElement] ?? [] { walk(window,0) }
    return result
}
func text() -> String {
    elements().filter { (attr($0,kAXRoleAttribute) as? String) == "AXStaticText" }
        .compactMap { attr($0,kAXValueAttribute) as? String }.joined(separator:"\n")
}
func control(_ role: String,_ title: String) -> AXUIElement {
    guard let e = elements().first(where: { attr($0,kAXRoleAttribute) as? String == role && attr($0,kAXTitleAttribute) as? String == title }) else { fatalError("Missing control \(title)") }
    return e
}
func press(_ title: String) {
    precondition(AXUIElementPerformAction(control("AXButton",title), kAXPressAction as CFString) == .success)
}
func wait(_ message:String,_ condition:()->Bool) {
    for _ in 0..<250 { if condition() { return }; Thread.sleep(forTimeInterval:0.04) }
    fatalError("Timed out: \(message)")
}
func ready() -> Bool { text().contains("Ready") || text().contains("就绪") }
func send(_ message:String) {
    let fields=elements().filter { attr($0,kAXRoleAttribute) as? String == "AXTextField" }
    guard let input=fields.last else { fatalError("Missing input") }
    precondition(AXUIElementSetAttributeValue(input,kAXValueAttribute as CFString,message as CFString) == .success)
    press("发送")
}
NSRunningApplication(processIdentifier:pid)?.activate(options:[])
wait("initial real stream") { text().contains("真实 MetaCodes AgentCore") && ready() }
send("second-native-ui-turn")
wait("second turn") { text().contains("second-native-ui-turn") && ready() }
send("cancel-check native UI")
wait("active stream") { text().contains("cancel-check stream") }
press("停止")
wait("cancelled") { text().contains("Cancelled") || text().contains("已停止") }
send("recovery-native-ui-turn")
wait("after abort recovery") { text().contains("recovery-native-ui-turn") && ready() }
press("新会话")
wait("new session") { text().contains("新会话已就绪") }
send("native-recreated-session")
wait("recreated session response") { text().contains("native-recreated-session") && ready() && text().contains("真实 MetaCodes AgentCore") }
send("cancel-check close sidebar")
wait("stream before close") { text().contains("cancel-check stream") }
press("关闭侧边栏")
precondition(AXUIElementPerformAction(control("AXCheckBox","MetaCodes"),kAXPressAction as CFString) == .success)
wait("hide cancellation") { text().contains("Cancelled") || text().contains("已停止") }
press("新会话")
send("原生 MetaCodes 会话集成验收已通过。")
wait("final visible demo") { ready() && text().contains("真实 MetaCodes AgentCore") }
print("PASS: native Views streaming, multi-turn, Stop, recovery, reset, hide cancellation and visible demo")
