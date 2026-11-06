import AppKit
import Foundation
import Network
import WebKit

final class StageWindow: NSWindow {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
    override var isKeyWindow: Bool { true }
    override var occlusionState: NSWindow.OcclusionState { [.visible] }
}

final class StageHost {
    private let activity = ProcessInfo.processInfo.beginActivity(
        options: [.userInitiated, .latencyCritical],
        reason: "Stage recording"
    )
    private struct HTTPRequest {
        let method: String
        let path: String
        let headers: [String: String]
        let body: [String: Any]
    }

    private enum HTTPParseResult {
        case incomplete
        case request(HTTPRequest)
        case invalid(status: Int, message: String)
    }

    private let maximumBodyBytes = 900_000
    private let maximumRequestBytes = 1_000_000
    private let webView: WKWebView
    private let window: StageWindow
    private let listener: NWListener
    private let networkQueue = DispatchQueue(label: "org.oiloil.oilstudio.stage.network")
    private let sessionToken: String
    private var titleObservation: NSKeyValueObservation?

    init(sessionToken: String) throws {
        self.sessionToken = sessionToken
        let visible = NSScreen.screens.first?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1920, height: 1080)
        let scale = min(1, visible.width * 0.88 / 1920, visible.height * 0.88 / 1080)
        let units = max(1, floor(120 * scale))
        let contentSize = NSSize(width: units * 16, height: units * 9)
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        webView = WKWebView(frame: NSRect(origin: .zero, size: contentSize), configuration: configuration)
        window = StageWindow(contentRect: NSRect(origin: .zero, size: contentSize),
            styleMask: [.borderless], backing: .buffered, defer: false)

        let parameters = NWParameters.tcp
        parameters.requiredLocalEndpoint = .hostPort(host: .ipv4(IPv4Address("127.0.0.1")!), port: .any)
        listener = try NWListener(using: parameters)

        window.title = ""
        window.titleVisibility = .hidden
        window.isOpaque = true
        window.backgroundColor = .black
        window.hasShadow = false
        window.ignoresMouseEvents = true
        window.isReleasedWhenClosed = false
        window.level = .normal
        window.collectionBehavior = [.stationary]
        window.contentView = webView
        webView.setValue(false, forKey: "drawsBackground")

        titleObservation = webView.observe(\.title, options: [.new]) { [weak window] view, _ in
            DispatchQueue.main.async {
                if let title = view.title, !title.isEmpty { window?.title = title }
            }
        }

        listener.newConnectionHandler = { [weak self] connection in
            guard let self else { return }
            connection.start(queue: self.networkQueue)
            self.receive(connection, buffer: Data())
        }
        listener.stateUpdateHandler = { [weak self] state in
            guard let self else { return }
            if case .ready = state, let port = self.listener.port?.rawValue {
                print("STAGE_READY {\"port\":\(port)}")
                fflush(stdout)
            } else if case .failed(let error) = state {
                FileHandle.standardError.write(Data("stage listener failed: \(error)\n".utf8))
            }
        }
    }

    func start(url: URL) {
        NSApplication.shared.setActivationPolicy(.accessory)
        if let visible = NSScreen.screens.first?.visibleFrame {
            let size = window.frame.size
            window.setFrameOrigin(NSPoint(x: visible.midX - size.width / 2, y: visible.midY - size.height / 2))
        }
        window.orderFrontRegardless()
        webView.load(URLRequest(url: url))
        listener.start(queue: networkQueue)
    }

    private func receive(_ connection: NWConnection, buffer: Data) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 65536) { [weak self] data, _, complete, error in
            guard let self else { connection.cancel(); return }
            var collected = buffer
            if let data { collected.append(data) }
            if collected.count > self.maximumRequestBytes {
                self.send(["ok": false, "error": "request too large"], status: 413, connection: connection)
                return
            }
            switch self.parseRequest(collected) {
            case .request(let request):
                self.route(request, connection: connection)
            case .invalid(let status, let message):
                self.send(["ok": false, "error": message], status: status, connection: connection)
            case .incomplete:
                if complete || error != nil {
                    self.send(["ok": false, "error": "incomplete request"], status: 400, connection: connection)
                } else {
                    self.receive(connection, buffer: collected)
                }
            }
        }
    }

    private func parseRequest(_ data: Data) -> HTTPParseResult {
        guard let headerRange = data.range(of: Data("\r\n\r\n".utf8)) else { return .incomplete }
        guard let header = String(data: data[..<headerRange.lowerBound], encoding: .utf8) else {
            return .invalid(status: 400, message: "invalid request headers")
        }
        let lines = header.components(separatedBy: "\r\n")
        guard let first = lines.first else { return .invalid(status: 400, message: "missing request line") }
        let components = first.split(separator: " ")
        guard components.count == 3, components[2] == "HTTP/1.1" else {
            return .invalid(status: 400, message: "invalid request line")
        }
        var headers: [String: String] = [:]
        for line in lines.dropFirst() {
            let pair = line.split(separator: ":", maxSplits: 1, omittingEmptySubsequences: false)
            guard pair.count == 2 else { return .invalid(status: 400, message: "invalid request header") }
            let name = pair[0].trimmingCharacters(in: .whitespaces).lowercased()
            let value = pair[1].trimmingCharacters(in: .whitespaces)
            guard !name.isEmpty, headers[name] == nil else {
                return .invalid(status: 400, message: "duplicate or empty request header")
            }
            headers[name] = value
        }
        guard headers["transfer-encoding"] == nil else {
            return .invalid(status: 400, message: "transfer encoding is not supported")
        }
        let lengthText = headers["content-length"] ?? "0"
        guard !lengthText.isEmpty, lengthText.allSatisfy({ $0 >= "0" && $0 <= "9" }), let length = Int(lengthText) else {
            return .invalid(status: 400, message: "invalid content length")
        }
        guard length <= maximumBodyBytes else {
            return .invalid(status: 413, message: "request body too large")
        }
        let bodyStart = headerRange.upperBound
        guard data.count >= bodyStart + length else { return .incomplete }
        let bodyData = data.subdata(in: bodyStart..<bodyStart + length)
        let body: [String: Any]
        if bodyData.isEmpty {
            body = [:]
        } else if let object = (try? JSONSerialization.jsonObject(with: bodyData)) as? [String: Any] {
            body = object
        } else {
            return .invalid(status: 400, message: "request body must be a JSON object")
        }
        let path = String(components[1].split(separator: "?", maxSplits: 1).first ?? "")
        return .request(HTTPRequest(method: String(components[0]), path: path, headers: headers, body: body))
    }

    private func route(_ request: HTTPRequest, connection: NWConnection) {
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            guard request.headers["authorization"] == "Bearer \(self.sessionToken)" else {
                self.send(["ok": false, "error": "unauthorized"], status: 401, connection: connection)
                return
            }
            guard request.headers["origin"] == nil else {
                self.send(["ok": false, "error": "browser origins are not allowed"], status: 403, connection: connection)
                return
            }
            let allowedMethods = ["/state": "GET", "/goto": "POST", "/evaluate": "POST", "/selector": "POST", "/point": "POST"]
            guard let allowedMethod = allowedMethods[request.path] else {
                self.send(["ok": false, "error": "unknown endpoint"], status: 404, connection: connection)
                return
            }
            guard request.method == allowedMethod else {
                self.send(["ok": false, "error": "method not allowed"], status: 405, connection: connection)
                return
            }
            if request.method == "POST" {
                let mediaType = request.headers["content-type"]?.components(separatedBy: ";").first?
                    .trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
                guard mediaType == "application/json" else {
                    self.send(["ok": false, "error": "content type must be application/json"], status: 415, connection: connection)
                    return
                }
            }
            let body = request.body
            switch (request.method, request.path) {
            case ("GET", "/state"):
                self.evaluate("({title:document.title,url:location.href,readyState:document.readyState,innerWidth,innerHeight,outerWidth,outerHeight})", connection: connection)
            case ("POST", "/goto"):
                guard let value = body["url"] as? String, let url = URL(string: value) else {
                    self.send(["ok": false, "error": "missing url"], connection: connection)
                    return
                }
                self.webView.load(URLRequest(url: url))
                self.send(["ok": true, "result": true], connection: connection)
            case ("POST", "/evaluate"):
                guard let source = body["script"] as? String else {
                    self.send(["ok": false, "error": "missing script"], connection: connection)
                    return
                }
                let mode = body["mode"] as? String ?? "function"
                let argument = body["argument"] ?? NSNull()
                let javaScript: String
                if mode == "function" {
                    javaScript = "const __fn = (\(source)); return await __fn(argument);"
                } else if source.trimmingCharacters(in: .whitespacesAndNewlines).hasPrefix("() =>")
                    || source.trimmingCharacters(in: .whitespacesAndNewlines).hasPrefix("async () =>") {
                    javaScript = "const __fn = (\(source)); return await __fn();"
                } else {
                    javaScript = "return await (async () => { \(source) })();"
                }
                var replied = false
                let timeoutWork = DispatchWorkItem { [weak self] in
                    guard !replied else { return }
                    replied = true
                    self?.send(["ok": false, "error": "timeout"], connection: connection)
                }
                DispatchQueue.main.asyncAfter(deadline: .now() + 8.0, execute: timeoutWork)
                self.webView.callAsyncJavaScript(javaScript, arguments: ["argument": argument], in: nil, in: .page,
                    completionHandler: { result in
                    guard !replied else { return }
                    replied = true
                    timeoutWork.cancel()
                    switch result {
                    case .success(let value): self.send(["ok": true, "result": value], connection: connection)
                    case .failure(let error): self.send(["ok": false, "error": self.jsErrorMessage(error)], connection: connection)
                    }
                })
            case ("POST", "/selector"):
                let selector = body["selector"] as? String ?? ""
                let action = body["action"] as? String ?? "click"
                let payload: [String: Any] = ["selector": selector, "action": action]
                var replied = false
                let timeoutWork = DispatchWorkItem { [weak self] in
                    guard !replied else { return }
                    replied = true
                    self?.send(["ok": false, "error": "timeout"], connection: connection)
                }
                DispatchQueue.main.asyncAfter(deadline: .now() + 5.0, execute: timeoutWork)
                self.webView.callAsyncJavaScript("""
                    const node = document.querySelector(selector);
                    if (!node) throw new Error(`No element matches selector: ${selector}`);
                    let r = node.getBoundingClientRect();
                    let fixed = false;
                    for (let el = node; el; el = el.parentElement) {
                      if (["fixed", "sticky"].includes(getComputedStyle(el).position)) { fixed = true; break; }
                    }
                    if (!fixed && (r.top < 0 || r.bottom > innerHeight || r.left < 0 || r.right > innerWidth)) {
                      node.scrollIntoView({block:"center",inline:"center",behavior:"instant"});
                      r = node.getBoundingClientRect();
                    }
                    const x = r.left + r.width / 2, y = r.top + r.height / 2;
                    const options = {bubbles:true,cancelable:true,view:window,clientX:x,clientY:y,pointerId:1,isPrimary:true};
                    const types = action === "click" ? ["pointerdown","mousedown","pointerup","mouseup","click"] :
                      ["pointerover","pointerenter","mouseover","mouseenter","pointermove","mousemove"];
                    for (const type of types) {
                      const down = type === "pointerdown" || type === "mousedown";
                      const eventOptions = {...options, buttons:down ? 1 : 0};
                      node.dispatchEvent(type.startsWith("pointer") ? new PointerEvent(type, eventOptions) : new MouseEvent(type, eventOptions));
                    }
                    return true;
                    """, arguments: payload, in: nil, in: .page) { result in
                    guard !replied else { return }
                    replied = true
                    timeoutWork.cancel()
                    self.sendResult(result, connection: connection)
                }
            case ("POST", "/point"):
                let x = body["x"] as? Double ?? 0
                let y = body["y"] as? Double ?? 0
                let action = body["action"] as? String ?? "click"
                let payload: [String: Any] = ["x": x, "y": y, "action": action]
                self.webView.callAsyncJavaScript("""
                    const node = document.elementFromPoint(x,y);
                    if (!node) return false;
                    const options = {bubbles:true,cancelable:true,view:window,clientX:x,clientY:y,pointerId:1,isPrimary:true};
                    const types = action === "click" ? ["pointerdown","mousedown","pointerup","mouseup","click"] :
                      ["pointerover","pointerenter","mouseover","mouseenter","pointermove","mousemove"];
                    for (const type of types) {
                      const down = type === "pointerdown" || type === "mousedown";
                      const eventOptions = {...options, buttons:down ? 1 : 0};
                      node.dispatchEvent(type.startsWith("pointer") ? new PointerEvent(type, eventOptions) : new MouseEvent(type, eventOptions));
                    }
                    return true;
                    """, arguments: payload, in: nil, in: .page) { result in
                    self.sendResult(result, connection: connection)
                }
            default:
                self.send(["ok": false, "error": "method not allowed"], status: 405, connection: connection)
            }
        }
    }

    private func jsErrorMessage(_ error: Error) -> String {
        let nsError = error as NSError
        if let message = nsError.userInfo["WKJavaScriptExceptionMessage"] as? String, !message.isEmpty {
            return message
        }
        return error.localizedDescription
    }

    private func evaluate(_ script: String, connection: NWConnection) {
        webView.evaluateJavaScript(script) { result, error in
            if let error { self.send(["ok": false, "error": self.jsErrorMessage(error)], connection: connection) }
            else { self.send(["ok": true, "result": result ?? NSNull()], connection: connection) }
        }
    }

    private func sendResult(_ result: Result<Any, Error>, connection: NWConnection) {
        switch result {
        case .success(let value): send(["ok": true, "result": value], connection: connection)
        case .failure(let error): send(["ok": false, "error": jsErrorMessage(error)], connection: connection)
        }
    }

    private func send(_ value: [String: Any], status: Int = 200, connection: NWConnection) {
        let body = (try? JSONSerialization.data(withJSONObject: value, options: [.fragmentsAllowed, .sortedKeys])) ?? Data("{}".utf8)
        let reasons = [200: "OK", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found",
            405: "Method Not Allowed", 413: "Content Too Large", 415: "Unsupported Media Type"]
        let responseHead = "HTTP/1.1 \(status) \(reasons[status] ?? "Error")\r\nContent-Type: application/json; charset=utf-8\r\nCache-Control: no-store\r\nConnection: close\r\nContent-Length: \(body.count)\r\n\r\n"
        var response = Data(responseHead.utf8)
        response.append(body)
        connection.send(content: response, completion: .contentProcessed { _ in connection.cancel() })
    }
}

let arguments = CommandLine.arguments
guard arguments.count == 2, let url = URL(string: arguments[1]),
    let sessionToken = ProcessInfo.processInfo.environment["OILSTUDIO_PLAYBOOK_STAGE_TOKEN"], sessionToken.count >= 32 else {
    fputs("usage: OILSTUDIO_PLAYBOOK_STAGE_TOKEN=<token> record_playbook_stage <url>\n", stderr)
    exit(2)
}
let host = try StageHost(sessionToken: sessionToken)
host.start(url: url)
NSApplication.shared.run()
