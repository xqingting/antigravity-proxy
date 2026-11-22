import Foundation
import AppKit
import Combine
import Darwin

@MainActor
final class ProxyService: ObservableObject {
    // 服务状态
    @Published var isRunning: Bool = false
    @Published var isBusy: Bool = false
    @Published var port: Int = 8765
    @Published var selectedModel: String = "gemini-4-hydrogen"
    @Published var selectedEffort: EffortLevel = .high
    @Published var activeModel: String = "gemini-4-hydrogen"
    @Published var activeEffort: String = "high"
    @Published var agyVersion: String = "检测中..."
    @Published var hermesIps: [String] = ["192.168.6.192"]
    @Published var hasLocalHermesDirective: Bool = false
    @Published var localLanIP: String = "127.0.0.1"

    // 统计数据
    @Published var stats: StatsSnapshot = .empty

    // 日志
    @Published var logLines: [String] = []

    // Toast 提示
    @Published var toastMessage: String?

    // 联调测试台状态
    @Published var playgroundModel: String = "gemini-4-hydrogen"
    @Published var playgroundStream: Bool = true
    @Published var playgroundPrompt: String = "用一句话介绍一下你自己以及当前的模型能力。"
    @Published var playgroundOutput: String = ""
    @Published var playgroundIsRunning: Bool = false
    @Published var playgroundLatency: Double?
    @Published var playgroundTokens: Int?
    @Published var playgroundError: String?

    private var managedProcess: Process?
    private var pollTimer: Timer?
    private var toastTask: Task<Void, Never>?
    private var streamTask: Task<Void, Never>?

    private let session: URLSession = {
        let cfg = URLSessionConfiguration.default
        cfg.timeoutIntervalForRequest = 400
        cfg.timeoutIntervalForResource = 1800
        return URLSession(configuration: cfg)
    }()

    var resourceDir: URL {
        if let res = Bundle.main.resourceURL {
            let bundled = res.appendingPathComponent("agy_proxy.py")
            if FileManager.default.fileExists(atPath: bundled.path) {
                return res
            }
        }
        // 开发模式回退至项目根目录
        let cwd = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
        if FileManager.default.fileExists(atPath: cwd.appendingPathComponent("agy_proxy.py").path) {
            return cwd
        }
        let parent = cwd.deletingLastPathComponent()
        if FileManager.default.fileExists(atPath: parent.appendingPathComponent("agy_proxy.py").path) {
            return parent
        }
        return URL(fileURLWithPath: "/Applications/Antigravity Proxy.app/Contents/Resources")
    }

    var proxyScriptURL: URL { resourceDir.appendingPathComponent("agy_proxy.py") }
    var proxyLogURL: URL { resourceDir.appendingPathComponent("proxy.log") }
    var localDirectiveURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".config/antigravity-proxy/hermes_directive.local.txt")
    }

    var localBaseURL: String { "http://127.0.0.1:\(port)/v1" }
    var lanBaseURL: String { "http://\(localLanIP):\(port)/v1" }

    init() {
        self.localLanIP = Self.detectLanIP() ?? "127.0.0.1"
        self.refreshLocalDirectiveStatus()
        self.startPolling()

        Task {
            await self.refreshAll()
            if !self.isRunning {
                await self.startProxy()
            }
        }
    }

    func showToast(_ message: String) {
        toastTask?.cancel()
        toastMessage = message
        toastTask = Task {
            try? await Task.sleep(nanoseconds: 2_200_000_000)
            if !Task.isCancelled {
                self.toastMessage = nil
            }
        }
    }

    func copyToClipboard(_ text: String, label: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
        showToast("已复制\(label)")
    }

    func refreshLocalDirectiveStatus() {
        hasLocalHermesDirective = FileManager.default.fileExists(atPath: localDirectiveURL.path)
    }

    func startPolling() {
        pollTimer?.invalidate()
        pollTimer = Timer.scheduledTimer(withTimeInterval: 2.5, repeats: true) { [weak self] _ in
            guard let self else { return }
            Task { @MainActor in
                await self.refreshAll()
            }
        }
    }

    func refreshAll() async {
        refreshLocalDirectiveStatus()
        await fetchHealth()
        if isRunning {
            await fetchStats()
        }
    }

    func fetchHealth() async {
        guard let url = URL(string: "http://127.0.0.1:\(port)/health") else { return }
        var req = URLRequest(url: url)
        req.timeoutInterval = 2.0
        do {
            let (data, resp) = try await session.data(for: req)
            guard let http = resp as? HTTPURLResponse, http.statusCode == 200 else {
                isRunning = false
                return
            }
            let health = try JSONDecoder().decode(HealthResponse.self, from: data)
            isRunning = (health.status == "ok")
            if let m = health.defaultModel, !m.isEmpty {
                activeModel = m
                if !isBusy { selectedModel = m }
            }
            if let e = health.defaultEffort, !e.isEmpty {
                activeEffort = e
                if !isBusy, let parsed = EffortLevel(rawValue: e.lowercased()) {
                    selectedEffort = parsed
                }
            }
            if let v = health.agyVersion, !v.isEmpty {
                agyVersion = v
            }
            if let ips = health.hermesIps {
                hermesIps = ips
            }
        } catch {
            isRunning = false
        }
    }

    func fetchStats() async {
        guard let url = URL(string: "http://127.0.0.1:\(port)/v1/stats") else { return }
        var req = URLRequest(url: url)
        req.timeoutInterval = 2.5
        do {
            let (data, resp) = try await session.data(for: req)
            guard let http = resp as? HTTPURLResponse, http.statusCode == 200 else { return }
            let decoded = try JSONDecoder().decode(StatsSnapshot.self, from: data)
            stats = decoded
        } catch {
            // 忽略单次轮询抖动
        }
    }

    func resetStats() async {
        guard let url = URL(string: "http://127.0.0.1:\(port)/v1/stats/reset") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.timeoutInterval = 5.0
        do {
            let (_, resp) = try await session.data(for: req)
            if let http = resp as? HTTPURLResponse, http.statusCode == 200 {
                await fetchStats()
                showToast("统计数据已重置")
            }
        } catch {
            showToast("重置失败：\(error.localizedDescription)")
        }
    }

    func startProxy() async {
        guard !isBusy else { return }
        isBusy = true
        defer { isBusy = false }

        await fetchHealth()
        if isRunning {
            showToast("代理服务已在运行中")
            return
        }

        let scriptPath = proxyScriptURL.path
        guard FileManager.default.fileExists(atPath: scriptPath) else {
            showToast("未找到代理核心 agy_proxy.py")
            return
        }

        let pyBin = Self.findPythonBinary()
        let logURL = proxyLogURL
        if !FileManager.default.fileExists(atPath: logURL.path) {
            FileManager.default.createFile(atPath: logURL.path, contents: nil)
        }

        do {
            let logHandle = try FileHandle(forWritingTo: logURL)
            try logHandle.seekToEnd()

            let proc = Process()
            proc.executableURL = URL(fileURLWithPath: pyBin)
            proc.arguments = [
                scriptPath,
                "--port", "\(port)",
                "--model", selectedModel,
                "--effort", selectedEffort.rawValue,
                "--timeout", "300",
                "--max-concurrency", "5",
            ]
            proc.currentDirectoryURL = resourceDir
            var env = ProcessInfo.processInfo.environment
            let extraPath = "/opt/homebrew/bin:/usr/local/bin:\(FileManager.default.homeDirectoryForCurrentUser.path)/.local/bin:/usr/bin:/bin"
            env["PATH"] = extraPath + ":" + (env["PATH"] ?? "")
            env["PYTHONUNBUFFERED"] = "1"
            proc.environment = env
            proc.standardOutput = logHandle
            proc.standardError = logHandle

            try proc.run()
            managedProcess = proc

            for _ in 0..<20 {
                try? await Task.sleep(nanoseconds: 200_000_000)
                await fetchHealth()
                if isRunning {
                    await fetchStats()
                    refreshLogs()
                    showToast("已启动 \(selectedModel) (\(selectedEffort.rawValue))")
                    return
                }
            }
            showToast("进程已拉起，等待端口就绪...")
        } catch {
            showToast("启动失败：\(error.localizedDescription)")
        }
    }

    func stopProxy(silent: Bool = false) async {
        if !silent { isBusy = true }
        defer { if !silent { isBusy = false } }

        if let proc = managedProcess, proc.isRunning {
            proc.terminate()
            managedProcess = nil
        }

        // 同时清理可能由之前实例拉起的同端口 agy_proxy.py 进程
        let killProc = Process()
        killProc.executableURL = URL(fileURLWithPath: "/usr/bin/pkill")
        killProc.arguments = ["-f", "agy_proxy.py"]
        try? killProc.run()
        killProc.waitUntilExit()

        try? await Task.sleep(nanoseconds: 450_000_000)
        isRunning = false
        if !silent {
            showToast("代理服务已停止")
        }
    }

    func restartProxy(applySelection: Bool = true) async {
        guard !isBusy else { return }
        isBusy = true
        let targetModel = selectedModel
        let targetEffort = selectedEffort
        await stopProxy(silent: true)
        selectedModel = targetModel
        selectedEffort = targetEffort
        isBusy = false
        await startProxy()
        if applySelection {
            playgroundModel = targetModel
        }
    }

    func terminateOnQuit() {
        pollTimer?.invalidate()
        streamTask?.cancel()
        if let proc = managedProcess, proc.isRunning {
            proc.terminate()
        }
        let killProc = Process()
        killProc.executableURL = URL(fileURLWithPath: "/usr/bin/pkill")
        killProc.arguments = ["-f", "agy_proxy.py"]
        try? killProc.run()
    }

    func refreshLogs() {
        guard let data = try? Data(contentsOf: proxyLogURL),
              let content = String(data: data, encoding: .utf8) else {
            logLines = ["暂无日志文件 (\(proxyLogURL.path))"]
            return
        }
        let allLines = content.components(separatedBy: .newlines).filter { !$0.isEmpty }
        logLines = Array(allLines.suffix(300))
    }

    func clearLogView() {
        logLines = []
        showToast("已清空当前日志视图")
    }

    // MARK: - 联调测试台（支持 SSE 真流式与阻塞模式）

    func runPlaygroundTest() {
        let prompt = playgroundPrompt.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !prompt.isEmpty else { return }

        streamTask?.cancel()
        playgroundIsRunning = true
        playgroundOutput = ""
        playgroundError = nil
        playgroundLatency = nil
        playgroundTokens = nil

        let model = playgroundModel
        let useStream = playgroundStream
        let start = Date()

        streamTask = Task {
            defer {
                self.playgroundIsRunning = false
                self.playgroundLatency = Date().timeIntervalSince(start)
            }

            guard let url = URL(string: "http://127.0.0.1:\(port)/v1/chat/completions") else { return }
            var req = URLRequest(url: url)
            req.httpMethod = "POST"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            let body: [String: Any] = [
                "model": model,
                "stream": useStream,
                "messages": [
                    ["role": "user", "content": prompt]
                ]
            ]
            req.httpBody = try? JSONSerialization.data(withJSONObject: body)

            do {
                if useStream {
                    let (bytes, resp) = try await session.bytes(for: req)
                    guard let http = resp as? HTTPURLResponse, http.statusCode == 200 else {
                        playgroundError = "HTTP 状态异常 (\((resp as? HTTPURLResponse)?.statusCode ?? -1))"
                        return
                    }
                    for try await line in bytes.lines {
                        if Task.isCancelled { break }
                        let trimmed = line.trimmingCharacters(in: .whitespaces)
                        guard trimmed.hasPrefix("data:") else { continue }
                        let payload = trimmed.dropFirst(5).trimmingCharacters(in: .whitespaces)
                        if payload == "[DONE]" { break }
                        guard let jsonData = payload.data(using: .utf8),
                              let obj = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any] else {
                            continue
                        }
                        if let err = obj["error"] as? [String: Any], let msg = err["message"] as? String {
                            playgroundError = msg
                            break
                        }
                        if let choices = obj["choices"] as? [[String: Any]],
                           let delta = choices.first?["delta"] as? [String: Any],
                           let content = delta["content"] as? String {
                            playgroundOutput += content
                        }
                        if let usage = obj["usage"] as? [String: Any],
                           let total = usage["total_tokens"] as? Int {
                            playgroundTokens = total
                        }
                    }
                } else {
                    let (data, resp) = try await session.data(for: req)
                    guard let http = resp as? HTTPURLResponse, http.statusCode == 200 else {
                        playgroundError = String(data: data, encoding: .utf8) ?? "请求失败"
                        return
                    }
                    if let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                        if let choices = obj["choices"] as? [[String: Any]],
                           let message = choices.first?["message"] as? [String: Any],
                           let content = message["content"] as? String {
                            playgroundOutput = content
                        }
                        if let usage = obj["usage"] as? [String: Any],
                           let total = usage["total_tokens"] as? Int {
                            playgroundTokens = total
                        }
                    }
                }
                await fetchStats()
            } catch {
                if !Task.isCancelled {
                    playgroundError = error.localizedDescription
                }
            }
        }
    }

    func cancelPlaygroundTest() {
        streamTask?.cancel()
        playgroundIsRunning = false
    }

    // MARK: - 辅助工具

    nonisolated static func findPythonBinary() -> String {
        let candidates = [
            "/opt/homebrew/bin/python3",
            "/usr/local/bin/python3",
            "/usr/bin/python3",
        ]
        for path in candidates where FileManager.default.isExecutableFile(atPath: path) {
            return path
        }
        return "/usr/bin/python3"
    }

    nonisolated static func detectLanIP() -> String? {
        var address: String?
        var ifaddr: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&ifaddr) == 0, let firstAddr = ifaddr else { return nil }
        defer { freeifaddrs(ifaddr) }

        for ptr in sequence(first: firstAddr, next: { $0.pointee.ifa_next }) {
            let interface = ptr.pointee
            let addrFamily = interface.ifa_addr.pointee.sa_family
            if addrFamily == UInt8(AF_INET) {
                let name = String(cString: interface.ifa_name)
                if name == "en0" || name == "en1" || name.hasPrefix("en") {
                    var hostname = [CChar](repeating: 0, count: Int(NI_MAXHOST))
                    if getnameinfo(
                        interface.ifa_addr,
                        socklen_t(interface.ifa_addr.pointee.sa_len),
                        &hostname,
                        socklen_t(hostname.count),
                        nil,
                        0,
                        NI_NUMERICHOST
                    ) == 0 {
                        let ip = String(cString: hostname)
                        if !ip.hasPrefix("127.") && !ip.hasPrefix("169.254.") {
                            address = ip
                            if name == "en0" { break }
                        }
                    }
                }
            }
        }
        return address
    }
}
