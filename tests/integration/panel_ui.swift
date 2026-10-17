// QA only: inspect and operate the native sidebar of one explicit fixture PID.
import Foundation
import AppKit
import ApplicationServices
let pid=pid_t(CommandLine.arguments[1])!
let app=AXUIElementCreateApplication(pid)
func attr(_ e:AXUIElement,_ name:String)->CFTypeRef?{var v:CFTypeRef?;AXUIElementCopyAttributeValue(e,name as CFString,&v);return v}
func elements()->[AXUIElement]{
 var result:[AXUIElement]=[]
 func walk(_ e:AXUIElement,_ depth:Int){if depth>30{return};result.append(e);for c in attr(e,kAXChildrenAttribute) as? [AXUIElement] ?? []{walk(c,depth+1)}}
 for w in attr(app,kAXWindowsAttribute) as? [AXUIElement] ?? []{walk(w,0)};return result
}
// Global settings have a separate key window. Re-activating the application
// between a menu opening and its selection can dismiss that native menu.
let command=CommandLine.arguments.count>2 ? CommandLine.arguments[2] : "dump"
if command != "quit" && ProcessInfo.processInfo.environment["METABROWSER_UI_NO_ACTIVATE"] != "1" {
 NSRunningApplication(processIdentifier:pid)?.activate(options:[])
}
if command == "navigate" {
 // Activation is asynchronous, especially after a restored identity window.
 // Wait for actual focus before sending Return; AXSetValue alone only edits
 // the omnibox and cannot prove that a navigation was committed.
 let activationDeadline=Date().addingTimeInterval(3)
 while NSWorkspace.shared.frontmostApplication?.processIdentifier != pid && Date()<activationDeadline {
  RunLoop.current.run(until:Date().addingTimeInterval(0.05))
 }
 precondition(NSWorkspace.shared.frontmostApplication?.processIdentifier == pid,"Fixture application did not activate; target=\(pid), foreground=\(NSWorkspace.shared.frontmostApplication?.processIdentifier ?? -1)")
 guard let e=elements().first(where:{attr($0,kAXRoleAttribute) as? String == "AXTextField" && (["地址和搜索栏","Address and search bar"].contains(attr($0,kAXDescriptionAttribute) as? String ?? "") || ["地址和搜索栏","Address and search bar"].contains(attr($0,kAXTitleAttribute) as? String ?? ""))}) else{fatalError("No address field")}
 precondition(AXUIElementSetAttributeValue(e,kAXFocusedAttribute as CFString,kCFBooleanTrue) == .success)
 precondition(AXUIElementSetAttributeValue(e,kAXValueAttribute as CFString,CommandLine.arguments[3] as CFString) == .success)
 RunLoop.current.run(until:Date().addingTimeInterval(0.10))
 precondition(attr(e,kAXFocusedAttribute) as? Bool == true,"Fixture omnibox lost focus")
 precondition(attr(e,kAXValueAttribute) as? String == CommandLine.arguments[3],"Fixture omnibox edit was replaced")
 let down=CGEvent(keyboardEventSource:nil,virtualKey:36,keyDown:true)!
 let up=CGEvent(keyboardEventSource:nil,virtualKey:36,keyDown:false)!
 down.flags=[];up.flags=[];down.postToPid(pid)
 RunLoop.current.run(until:Date().addingTimeInterval(0.03))
 up.postToPid(pid)
} else if command == "quit" {
 precondition(NSRunningApplication(processIdentifier:pid)?.terminate() == true)
} else if command == "key" {
 let key:CGKeyCode=CommandLine.arguments[3] == "Escape" ? 53 : 36
 CGEvent(keyboardEventSource:nil,virtualKey:key,keyDown:true)?.postToPid(pid)
 CGEvent(keyboardEventSource:nil,virtualKey:key,keyDown:false)?.postToPid(pid)
} else if command == "inspect" {
 for e in elements(){let title=attr(e,kAXTitleAttribute) as? String ?? "",desc=attr(e,kAXDescriptionAttribute) as? String ?? "";if title.contains(CommandLine.arguments[3])||desc.contains(CommandLine.arguments[3]){var actions:CFArray?;AXUIElementCopyActionNames(e,&actions);let data=try! JSONSerialization.data(withJSONObject:["title":title,"description":desc,"help":attr(e,kAXHelpAttribute) as? String ?? "","actions":actions as? [String] ?? [],"value":attr(e,kAXValueAttribute) as? String ?? (attr(e,kAXValueAttribute) as? NSNumber)?.stringValue ?? ""]);print(String(data:data,encoding:.utf8)!)}}
} else if command == "press" {
 let title=CommandLine.arguments[3]
 guard let e=elements().first(where:{element in
 var actions:CFArray?;AXUIElementCopyActionNames(element,&actions)
 return ((actions as? [String]) ?? []).contains(kAXPressAction) && ((attr(element,kAXTitleAttribute) as? String == title)||(attr(element,kAXDescriptionAttribute) as? String == title)||(attr(element,kAXHelpAttribute) as? String == title))
 }) else{fatalError("Missing button \(title)")}
 var actions:CFArray?;AXUIElementCopyActionNames(e,&actions)
 let names=(actions as? [String]) ?? []
 let children=(attr(e,kAXChildrenAttribute) as? [AXUIElement]) ?? []
 let submenu=children.contains(where:{attr($0,kAXRoleAttribute) as? String == "AXMenu"})
 let action=(attr(e,kAXRoleAttribute) as? String == "AXMenuItem" && !submenu && names.contains("AXPick")) ? "AXPick" : kAXPressAction
 precondition(AXUIElementPerformAction(e,action as CFString) == .success)
 } else if command == "cancel-menu" {
 for e in elements(){var actions:CFArray?;AXUIElementCopyActionNames(e,&actions);if ((actions as? [String]) ?? []).contains("AXCancel"){_ = AXUIElementPerformAction(e,"AXCancel" as CFString);break}}
 } else if command == "set" {
 let name=CommandLine.arguments[3], value=CommandLine.arguments[4]
 guard let e=elements().first(where:{["AXTextField","AXTextArea"].contains(attr($0,kAXRoleAttribute) as? String ?? "") && ((attr($0,kAXTitleAttribute) as? String == name)||(attr($0,kAXDescriptionAttribute) as? String == name))}) else{fatalError("Missing text field")}
 precondition(AXUIElementSetAttributeValue(e,kAXValueAttribute as CFString,value as CFString) == .success)
} else if command == "resize" {
 guard let window=(attr(app,kAXWindowsAttribute) as? [AXUIElement])?.first else{fatalError("No window")}
 var size=CGSize(width:Double(CommandLine.arguments[3])!,height:Double(CommandLine.arguments[4])!)
 let value=AXValueCreate(.cgSize,&size)!
 precondition(AXUIElementSetAttributeValue(window,kAXSizeAttribute as CFString,value) == .success)
} else if command == "bounds" {
 let names=CommandLine.arguments[3].components(separatedBy:"|")
 var rows:[[String:Any]]=[]
 for e in elements(){
 let role=attr(e,kAXRoleAttribute) as? String ?? ""
 var name=attr(e,kAXTitleAttribute) as? String ?? ""
 if name.isEmpty{name=attr(e,kAXDescriptionAttribute) as? String ?? ""}
 if name.isEmpty && role == "AXStaticText"{name=attr(e,kAXValueAttribute) as? String ?? ""}
 guard name != "API key",names.contains(where:{name == $0 || role == $0}) else{continue}
 guard let position=attr(e,kAXPositionAttribute),let size=attr(e,kAXSizeAttribute) else{continue}
 var point=CGPoint.zero,extent=CGSize.zero
 AXValueGetValue(position as! AXValue,.cgPoint,&point);AXValueGetValue(size as! AXValue,.cgSize,&extent)
 rows.append(["role":role,"name":name,"x":point.x,"y":point.y,"width":extent.width,"height":extent.height,"enabled":attr(e,kAXEnabledAttribute) as? Bool ?? true])
 }
 let data=try! JSONSerialization.data(withJSONObject:rows,options:[.sortedKeys]);print(String(data:data,encoding:.utf8)!)
} else if command == "window" {
 let windows=CGWindowListCopyWindowInfo([.optionOnScreenOnly,.excludeDesktopElements],kCGNullWindowID) as? [[String:Any]] ?? []
 guard let w=windows.first(where:{$0[kCGWindowOwnerPID as String] as? Int == Int(pid) && $0[kCGWindowLayer as String] as? Int == 0}) else{fatalError("No fixture window")}
 print(w[kCGWindowNumber as String]!)
} else {
 for e in elements(){let role=attr(e,kAXRoleAttribute) as? String ?? "";if ["AXButton","AXTextField","AXTextArea","AXStaticText","AXRadioButton","AXTabGroup","AXLink","AXCheckBox","AXPopUpButton","AXMenuItem","AXHeading"].contains(role){var name=attr(e,kAXTitleAttribute) as? String ?? attr(e,kAXDescriptionAttribute) as? String ?? "";if name.isEmpty{name=attr(e,kAXHelpAttribute) as? String ?? ""};let value=attr(e,kAXValueAttribute) as? String ?? "";if name == "API key"{continue};print(role,name,String(value.prefix(240)))}}
}
