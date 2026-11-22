import Foundation

enum SidebarTab: String, CaseIterable, Identifiable {
    case overview = "概览"
    case requests = "请求明细"
    case connect = "快速接入"
    case playground = "联调测试"
    case logs = "实时日志"

    var id: String { rawValue }

    var systemImage: String {
        switch self {
        case .overview: return "gauge.with.dots.needle.67percent"
        case .requests: return "list.bullet.rectangle.portrait"
        case .connect: return "network"
        case .playground: return "terminal"
        case .logs: return "doc.text.magnifyingglass"
        }
    }
}

struct ModelOption: Identifiable, Hashable {
    let id: String
    let label: String
    let badge: String

    static let presets: [ModelOption] = [
        ModelOption(id: "gemini-4-hydrogen", label: "Gemini 4 Hydrogen", badge: "旗舰主力"),
        ModelOption(id: "gemini-4-neon", label: "Gemini 4 Neon", badge: "高速均衡"),
        ModelOption(id: "gemini-4-argon", label: "Gemini 4 Argon", badge: "轻量敏捷"),
        ModelOption(id: "gemini-3.8-flash", label: "Gemini 3.8 Flash", badge: "经典稳定"),
    ]
}

enum EffortLevel: String, CaseIterable, Identifiable {
    case low
    case medium
    case high
    case xhigh

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .low: return "Low · 极速"
        case .medium: return "Medium · 均衡"
        case .high: return "High · 深度思考"
        case .xhigh: return "XHigh · 极限思考"
        }
    }
}

struct HealthResponse: Decodable, Sendable {
    let status: String
    let service: String?
    let defaultModel: String?
    let defaultEffort: String?
    let hermesIps: [String]?
    let maxConcurrency: Int?
    let agyPath: String?
    let agyVersion: String?
    let time: String?

    enum CodingKeys: String, CodingKey {
        case status, service, time
        case defaultModel = "default_model"
        case defaultEffort = "default_effort"
        case hermesIps = "hermes_ips"
        case maxConcurrency = "max_concurrency"
        case agyPath = "agy_path"
        case agyVersion = "agy_version"
    }
}

struct RequestRecord: Decodable, Identifiable, Sendable {
    let id: String
    let timestamp: String
    let date: String?
    let datetime: String?
    let model: String
    let isStream: Bool
    let duration: Double
    let promptTokens: Int
    let completionTokens: Int
    let cachedTokens: Int?
    let totalTokens: Int
    let tps: Double
    let status: String
    let error: String?

    enum CodingKeys: String, CodingKey {
        case id, timestamp, date, datetime, model, duration, tps, status, error
        case isStream = "is_stream"
        case promptTokens = "prompt_tokens"
        case completionTokens = "completion_tokens"
        case cachedTokens = "cached_tokens"
        case totalTokens = "total_tokens"
    }

    var displayDate: String {
        if let date, !date.isEmpty { return date }
        if let datetime, datetime.count >= 10 { return String(datetime.prefix(10)) }
        return "--"
    }

    var isSuccess: Bool { status.lowercased() == "success" }
    var isTimeout: Bool { status.lowercased() == "timeout" }
}

struct StatsSnapshot: Decodable, Sendable {
    let totalRequests: Int
    let successfulRequests: Int
    let failedRequests: Int
    let successRate: Double
    let activeRequests: Int
    let maxConcurrency: Int
    let totalPromptTokens: Int
    let totalCompletionTokens: Int
    let totalTokens: Int
    let avgDuration: Double
    let avgTps: Double
    let recentHistory: [RequestRecord]

    enum CodingKeys: String, CodingKey {
        case totalRequests = "total_requests"
        case successfulRequests = "successful_requests"
        case failedRequests = "failed_requests"
        case successRate = "success_rate"
        case activeRequests = "active_requests"
        case maxConcurrency = "max_concurrency"
        case totalPromptTokens = "total_prompt_tokens"
        case totalCompletionTokens = "total_completion_tokens"
        case totalTokens = "total_tokens"
        case avgDuration = "avg_duration"
        case avgTps = "avg_tps"
        case recentHistory = "recent_history"
    }

    static let empty = StatsSnapshot(
        totalRequests: 0,
        successfulRequests: 0,
        failedRequests: 0,
        successRate: 100.0,
        activeRequests: 0,
        maxConcurrency: 5,
        totalPromptTokens: 0,
        totalCompletionTokens: 0,
        totalTokens: 0,
        avgDuration: 0,
        avgTps: 0,
        recentHistory: []
    )
}

enum Formatters {
    static func compactNumber(_ value: Int) -> String {
        if value >= 1_000_000 {
            return String(format: "%.2fM", Double(value) / 1_000_000.0)
        } else if value >= 1_000 {
            return String(format: "%.1fK", Double(value) / 1_000.0)
        }
        return "\(value)"
    }

    static func duration(_ seconds: Double) -> String {
        if seconds >= 60 {
            let mins = Int(seconds) / 60
            let secs = seconds - Double(mins * 60)
            return String(format: "%dm %.1fs", mins, secs)
        }
        return String(format: "%.2fs", seconds)
    }
}
