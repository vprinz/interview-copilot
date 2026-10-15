// Окно панели копайлота: узкое, поверх остальных окон (и поверх полноэкранного Meet),
// показывает страницу панели. Горячая клавиша ⌃⌥H из любого приложения — обновить подсказку сейчас.
//
//   bin/panel-window http://127.0.0.1:8765/
//
// Собирается сам и запускается scripts/copilot.py (src/copilot/native.py).

import AppKit
import Carbon.HIToolbox
import WebKit

let address = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "http://127.0.0.1:8765/"
let base = URL(string: address)!

func post(_ path: String) {
    var request = URLRequest(url: base.appendingPathComponent(path))
    request.httpMethod = "POST"
    URLSession.shared.dataTask(with: request).resume()
}

final class Delegate: NSObject, NSApplicationDelegate, WKUIDelegate {
    var window: NSPanel!

    func applicationDidFinishLaunching(_ notification: Notification) {
        let screen = NSScreen.main!.visibleFrame
        let size = NSSize(width: 380, height: min(820, screen.height))
        let frame = NSRect(x: screen.maxX - size.width, y: screen.maxY - size.height, width: size.width, height: size.height)
        window = NSPanel(contentRect: frame, styleMask: [.titled, .closable, .resizable, .nonactivatingPanel],
                         backing: .buffered, defer: false)
        window.title = "Копайлот"
        window.level = .floating
        window.hidesOnDeactivate = false
        window.isFloatingPanel = true
        window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        window.setFrameAutosaveName("copilot-panel")

        let web = WKWebView(frame: .zero)
        web.uiDelegate = self
        window.contentView = web
        web.load(URLRequest(url: base))
        window.orderFrontRegardless()
        print("window \(window.windowNumber)")
        fflush(stdout)

        // ⌃⌥H — глобальная горячая клавиша; отдельных разрешений macOS для неё не нужно.
        var handler = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetApplicationEventTarget(), { _, _, _ in
            post("refresh")
            return noErr
        }, 1, &handler, nil, nil)
        var hotKey: EventHotKeyRef?
        let status = RegisterEventHotKey(UInt32(kVK_ANSI_H), UInt32(controlKey | optionKey),
                                         EventHotKeyID(signature: OSType(0x434F5049), id: 1), GetApplicationEventTarget(), 0, &hotKey)
        if status != noErr {
            FileHandle.standardError.write("горячая клавиша ⌃⌥H занята другим приложением — обновляй кнопкой в панели\n".data(using: .utf8)!)
        }
    }

    // Страница спрашивает подтверждение перед сбросом таймера.
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.addButton(withTitle: "Да")
        alert.addButton(withTitle: "Нет")
        completionHandler(alert.runModal() == .alertFirstButtonReturn)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

let app = NSApplication.shared
let delegate = Delegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
