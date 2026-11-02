import AppKit
import Foundation

struct Runtime: Decodable {
    let url: String
    var browserURL: URL? {
        guard let u = URL(string: url), u.scheme == "http", u.host == "127.0.0.1", u.port != nil,
              let parts = URLComponents(url: u, resolvingAgainstBaseURL: false),
              parts.queryItems?.contains(where: { $0.name == "t" && !($0.value ?? "").isEmpty }) == true else { return nil }
        return u
    }
    func endpoint(_ path: String) -> URL? {
        guard let u = browserURL, var c = URLComponents(url: u, resolvingAgainstBaseURL: false) else { return nil }
        c.path = path; c.fragment = nil
        c.queryItems = c.queryItems?.filter { $0.name == "t" }
        return c.url
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    var project: URL!
    var child: Process?
    var log: FileHandle?
    var runtime: Runtime?
    var starting = false
    var quitting = false
    var awaitingQuitReply = false
    var startupTimer: Timer?
    var startupDeadline = Date()
    var statusWindow: NSWindow?
    var statusText: NSTextField?
    var stateURL: URL { project.appendingPathComponent(".app-runtime.json") }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let menu = NSMenu(); let item = NSMenuItem(); menu.addItem(item)
        let appMenu = NSMenu(); item.submenu = appMenu
        appMenu.addItem(withTitle: "Open Meeting Room", action: #selector(openRoom), keyEquivalent: "o").target = self
        appMenu.addItem(withTitle: "Show Project Folder", action: #selector(revealProject), keyEquivalent: "").target = self
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(withTitle: "Quit Meeting Room", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        NSApp.mainMenu = menu
        guard let url = Bundle.main.url(forResource: "project", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let config = try? JSONSerialization.jsonObject(with: data) as? [String: String],
              let path = config["directory"] else { fail("The launcher has no project folder. Rebuild it with tools/build_macos_app.py."); return }
        project = URL(fileURLWithPath: path, isDirectory: true)
        guard FileManager.default.fileExists(atPath: project.appendingPathComponent("run.sh").path) else {
            fail("The project folder has moved. Rebuild the launcher from its new location."); return
        }
        openRoom()
    }

    func readRuntime() -> Runtime? {
        guard let data = try? Data(contentsOf: stateURL), let r = try? JSONDecoder().decode(Runtime.self, from: data), r.browserURL != nil else { return nil }
        return r
    }

    func check(_ state: Runtime, completion: @escaping (Bool) -> Void) {
        guard let url = state.endpoint("/api/rooms") else { completion(false); return }
        var request = URLRequest(url: url); request.timeoutInterval = 2
        URLSession.shared.dataTask(with: request) { data, response, _ in
            let object = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
            let ok = (response as? HTTPURLResponse)?.statusCode == 200 && object?["rooms"] is [Any]
            DispatchQueue.main.async { completion(ok) }
        }.resume()
    }

    @objc func openRoom() {
        guard project != nil, !quitting else { return }
        if starting { statusWindow?.makeKeyAndOrderFront(nil); return }
        starting = true
        if let state = readRuntime() {
            check(state) { ok in
                if ok { self.ready(state) } else { self.startServer() }
            }
        } else { startServer() }
    }

    func showStarting() {
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 430, height: 130), styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.title = "Meeting Room"; window.center(); window.isReleasedWhenClosed = false
        let label = NSTextField(wrappingLabelWithString: "Starting Meeting Room…\nThe first launch may take a few minutes to prepare local speech tools.")
        label.frame = NSRect(x: 24, y: 25, width: 382, height: 78)
        window.contentView?.addSubview(label); statusText = label
        statusWindow = window; window.makeKeyAndOrderFront(nil)
    }

    func startServer() {
        if let child = child, child.isRunning { starting = false; fail("The server is still starting. Please wait and click the Dock icon again.", terminate: false); return }
        runtime = nil; showStarting()
        let process = Process(); process.executableURL = URL(fileURLWithPath: "/bin/bash")
        process.arguments = [project.appendingPathComponent("run.sh").path, "run", "--no-browser", "--launch-state", stateURL.path]
        process.currentDirectoryURL = project
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + NSHomeDirectory() + "/.local/bin:" + (env["PATH"] ?? "/usr/bin:/bin:/usr/sbin:/sbin")
        process.environment = env
        let logURL = project.appendingPathComponent(".app-launcher.log")
        do {
            // Logs may contain the local access token; only the current account can read them.
            let fm = FileManager.default
            if !fm.fileExists(atPath: logURL.path) { fm.createFile(atPath: logURL.path, contents: nil, attributes: [.posixPermissions: 0o600]) }
            try fm.setAttributes([.posixPermissions: 0o600], ofItemAtPath: logURL.path)
            log = try FileHandle(forWritingTo: logURL); try log?.truncate(atOffset: 0)
            process.standardOutput = log; process.standardError = log
            child = process
            process.terminationHandler = { p in
                DispatchQueue.main.async {
                    self.startupTimer?.invalidate(); self.startupTimer = nil; self.statusWindow?.close()
                    self.starting = false
                    if self.quitting { self.finishQuit(true) }
                    else if p.terminationStatus != 0 { self.fail("Meeting Room could not start. Another copy may be using port 8765. Check .app-launcher.log in the project folder.", terminate: false) }
                    else { self.runtime = nil; NSApp.terminate(nil) }
                }
            }
            try process.run()
            startupDeadline = Date().addingTimeInterval(600)
            startupTimer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { _ in self.pollReady() }
        } catch { starting = false; fail("Could not launch Meeting Room: \(error.localizedDescription)", terminate: false) }
    }

    func pollReady() {
        guard !quitting else { return }
        if Date() > startupDeadline {
            startupTimer?.invalidate(); startupTimer = nil; starting = false
            fail("Startup is taking longer than expected. Check .app-launcher.log; click the Dock icon again once setup has finished.", terminate: false); return
        }
        if let state = readRuntime() { check(state) { ok in if ok && self.starting { self.ready(state) } } }
    }

    func ready(_ state: Runtime) {
        startupTimer?.invalidate(); startupTimer = nil; starting = false; runtime = state
        statusWindow?.close()
        if let url = state.browserURL { NSWorkspace.shared.open(url) }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool { openRoom(); return true }
    @objc func revealProject() { if let project = project { NSWorkspace.shared.open(project) } }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if quitting { return .terminateLater }
        guard let state = runtime ?? (project == nil ? nil : readRuntime()), let url = state.endpoint("/api/quit") else {
            if child?.isRunning == true { child?.interrupt() }
            return .terminateNow
        }
        quitting = true; awaitingQuitReply = true
        check(state) { ok in
            if !ok && self.child?.isRunning != true { self.finishQuit(true); return }
            self.requestQuit(url)
        }
        return .terminateLater
    }

    func requestQuit(_ url: URL) {
        let alert = NSAlert(); alert.messageText = "Quit Meeting Room?"
        alert.informativeText = "All open meetings will be saved and closed."
        alert.addButton(withTitle: "Save and Quit"); alert.addButton(withTitle: "Cancel")
        if alert.runModal() != .alertFirstButtonReturn { quitting = false; finishQuit(false); return }
        startupTimer?.invalidate()
        var request = URLRequest(url: url); request.httpMethod = "POST"; request.timeoutInterval = 120
        var origin = URLComponents(url: url, resolvingAgainstBaseURL: false)!; origin.path = ""; origin.query = nil
        request.setValue(origin.string, forHTTPHeaderField: "Origin")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = Data("{\"save\":true}".utf8)
        URLSession.shared.dataTask(with: request) { _, response, error in
            DispatchQueue.main.async {
                let gone = !FileManager.default.fileExists(atPath: self.stateURL.path)
                if (response as? HTTPURLResponse)?.statusCode == 200 || (error != nil && (self.child?.isRunning == false || gone)) {
                    self.finishQuit(true)
                } else {
                    self.quitting = false; self.finishQuit(false)
                    self.fail("The meetings could not be saved and closed. The app will stay open; try quitting from its web interface.", terminate: false)
                }
            }
        }.resume()
    }

    func finishQuit(_ allow: Bool) {
        guard awaitingQuitReply else { return }
        awaitingQuitReply = false; NSApp.reply(toApplicationShouldTerminate: allow)
    }

    func fail(_ message: String, terminate: Bool = true) {
        statusWindow?.close(); let alert = NSAlert(); alert.messageText = "Meeting Room"; alert.informativeText = message
        alert.runModal()
        if terminate { if child?.isRunning == true { child?.interrupt() }; exit(1) }
    }
}

if CommandLine.arguments.contains("--self-test") {
    let state = Runtime(url: "http://127.0.0.1:8765/r/example/?t=test-token")
    precondition(state.endpoint("/api/quit")?.absoluteString == "http://127.0.0.1:8765/api/quit?t=test-token")
    precondition(Runtime(url: "https://example.com/?t=token").browserURL == nil)
    precondition(Runtime(url: "http://127.0.0.1:8765/").browserURL == nil)
    print("Launcher URL validation and endpoint routing passed.")
    exit(0)
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
