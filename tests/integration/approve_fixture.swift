// Test-only native authorization driver, scoped to one isolated browser PID.
import Foundation
import ApplicationServices
let app=AXUIElementCreateApplication(pid_t(CommandLine.arguments[1])!)
func attr(_ e:AXUIElement,_ key:String)->CFTypeRef?{var result:CFTypeRef?;AXUIElementCopyAttributeValue(e,key as CFString,&result);return result}
func elements()->[AXUIElement]{
    var result:[AXUIElement]=[]
    func walk(_ e:AXUIElement,_ depth:Int){if depth>30{return};result.append(e);for c in attr(e,kAXChildrenAttribute) as? [AXUIElement] ?? []{walk(c,depth+1)}}
    for w in attr(app,kAXWindowsAttribute) as? [AXUIElement] ?? []{walk(w,0)}
    return result
}
let deadline=Date().addingTimeInterval(180)
while Date()<deadline {
    let all=elements()
    if let button=all.first(where:{attr($0,kAXRoleAttribute) as? String == "AXButton" && attr($0,kAXTitleAttribute) as? String == "允许本次操作" && attr($0,kAXEnabledAttribute) as? Bool == true}){
        // Only used with the local fixture profile and loopback test services.
        AXUIElementPerformAction(button,kAXPressAction as CFString)
    }
    Thread.sleep(forTimeInterval:0.1)
}
