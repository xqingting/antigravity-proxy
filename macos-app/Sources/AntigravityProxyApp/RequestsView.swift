import SwiftUI

struct RequestsView: View {
    @EnvironmentObject var service: ProxyService
    @State private var filterStatus: String = "all"
    @State private var searchText: String = ""
    @State private var selectedRecord: RequestRecord?

    private var filteredRecords: [RequestRecord] {
        service.stats.recentHistory.filter { rec in
            let statusOK: Bool = {
                switch filterStatus {
                case "success": return rec.isSuccess
                case "failed": return !rec.isSuccess
                case "hermes": return rec.isHermes == true
                default: return true
                }
            }()
            let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            let searchOK = query.isEmpty
                || rec.model.lowercased().contains(query)
                || rec.displayDate.lowercased().contains(query)
                || rec.timestamp.lowercased().contains(query)
                || (rec.clientIp?.lowercased().contains(query) ?? false)
                || (rec.inputPreview?.lowercased().contains(query) ?? false)
                || (rec.error?.lowercased().contains(query) ?? false)
            return statusOK && searchOK
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                Picker("状态", selection: $filterStatus) {
                    Text("全部 (\(service.stats.recentHistory.count))").tag("all")
                    Text("成功").tag("success")
                    Text("异常/超时").tag("failed")
                    Text("Hermes").tag("hermes")
                }
                .pickerStyle(.segmented)
                .frame(width: 310)

                Spacer()

                HStack(spacing: 6) {
                    Image(systemName: "magnifyingglass")
                        .foregroundStyle(.secondary)
                    TextField("搜索输入内容、模型、IP 或错误...", text: $searchText)
                        .textFieldStyle(.plain)
                        .frame(width: 240)
                    if !searchText.isEmpty {
                        Button { searchText = "" } label: {
                            Image(systemName: "xmark.circle.fill")
                                .foregroundStyle(.secondary)
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(.horizontal, 10)
                .padding(.vertical, 6)
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            }
            .padding(.horizontal, 24)
            .padding(.vertical, 14)

            Divider()

            if filteredRecords.isEmpty {
                ContentUnavailableView(
                    "无匹配请求记录",
                    systemImage: "doc.text.magnifyingglass",
                    description: Text("请调整筛选条件或等待新的 API 请求。点击任意记录可查看完整输入、执行过程与输出。")
                )
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                List {
                    ForEach(filteredRecords) { rec in
                        RequestRowCard(record: rec)
                            .contentShape(Rectangle())
                            .onTapGesture {
                                selectedRecord = rec
                            }
                    }
                }
                .listStyle(.inset)
            }
        }
        .navigationTitle("请求明细")
        .sheet(item: $selectedRecord) { rec in
            RequestDetailSheet(record: rec)
                .environmentObject(service)
        }
    }
}

struct RequestRowCard: View {
    let record: RequestRecord

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 10) {
                VStack(alignment: .leading, spacing: 1) {
                    Text(record.displayDate)
                        .font(.caption2.monospacedDigit())
                        .foregroundStyle(.secondary)
                    Text(record.timestamp)
                        .font(.callout.weight(.semibold).monospacedDigit())
                }
                .frame(width: 82, alignment: .leading)

                if record.isHermes == true {
                    StatusPill(text: "Hermes", color: .indigo)
                } else if let ip = record.clientIp, !ip.isEmpty {
                    StatusPill(text: ip == "127.0.0.1" ? "本地" : ip, color: .secondary)
                }

                Text(record.model)
                    .font(.caption.monospaced())
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(Color.accentColor.opacity(0.12), in: Capsule())

                Text(record.isStream ? "SSE" : "阻塞")
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(record.isStream ? .teal : .secondary)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background((record.isStream ? Color.teal : Color.secondary).opacity(0.12), in: Capsule())

                if let toolCount = record.toolCallsCount, toolCount > 0 {
                    Label("\(toolCount)", systemImage: "wrench.and.screwdriver.fill")
                        .font(.caption2.weight(.semibold).monospacedDigit())
                        .foregroundStyle(.orange)
                        .padding(.horizontal, 7)
                        .padding(.vertical, 2)
                        .background(Color.orange.opacity(0.14), in: Capsule())
                }

                Spacer()

                Text("入 \(Formatters.compactNumber(record.promptTokens)) / 出 \(Formatters.compactNumber(record.completionTokens))")
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)

                Text(Formatters.duration(record.duration))
                    .font(.caption.weight(.medium).monospacedDigit())
                    .frame(width: 62, alignment: .trailing)

                Text(String(format: "%.1f tps", record.tps))
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)
                    .frame(width: 68, alignment: .trailing)

                StatusPill(
                    text: record.isSuccess ? "成功" : (record.isTimeout ? "超时" : "失败"),
                    color: record.isSuccess ? .green : (record.isTimeout ? .orange : .red)
                )
                .frame(width: 52, alignment: .trailing)

                Image(systemName: "chevron.right")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.tertiary)
            }

            if let preview = record.inputPreview, !preview.isEmpty {
                HStack(spacing: 6) {
                    Image(systemName: "text.quote")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                    Text(preview)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .truncationMode(.tail)
                }
                .padding(.leading, 92)
            } else if let err = record.error, !err.isEmpty {
                HStack(spacing: 6) {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .font(.caption2)
                        .foregroundStyle(.orange)
                    Text(err)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .lineLimit(1)
                }
                .padding(.leading, 92)
            }
        }
        .padding(.vertical, 6)
    }
}

enum DetailTab: String, CaseIterable, Identifiable {
    case input = "输入"
    case process = "执行过程"
    case output = "输出"

    var id: String { rawValue }
}

struct RequestDetailSheet: View {
    @EnvironmentObject var service: ProxyService
    @Environment(\.dismiss) private var dismiss

    let record: RequestRecord
    @State private var trace: RequestTrace?
    @State private var isLoading: Bool = true
    @State private var selectedTab: DetailTab = .process
    @State private var expandedSystemIndices: Set<Int> = []

    var body: some View {
        VStack(spacing: 0) {
            // 顶部摘要头
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 8) {
                        Text("请求全链路明细")
                            .font(.headline)
                        Text(record.id)
                            .font(.caption.monospaced())
                            .foregroundStyle(.secondary)
                        StatusPill(
                            text: record.isSuccess ? "成功" : (record.isTimeout ? "超时" : "失败"),
                            color: record.isSuccess ? .green : (record.isTimeout ? .orange : .red)
                        )
                        if record.isHermes == true {
                            StatusPill(text: "Hermes (\(record.clientIp ?? ""))", color: .indigo)
                        }
                    }
                    Text("\(record.displayDate) \(record.timestamp)  ·  \(record.model)  ·  耗时 \(Formatters.duration(record.duration))  ·  入 \(Formatters.compactNumber(record.promptTokens)) / 出 \(Formatters.compactNumber(record.completionTokens)) tok")
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                }

                Spacer()

                Button("关闭") { dismiss() }
                    .keyboardShortcut(.cancelAction)
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 14)

            Divider()

            // 三大分段切换：输入 / 执行过程 / 输出
            HStack {
                Picker("明细视图", selection: $selectedTab) {
                    Text("📥 输入 (\(trace?.inputMessages.count ?? 0))").tag(DetailTab.input)
                    Text("⚙️ 执行过程 (\(trace?.executionSteps.count ?? 0))").tag(DetailTab.process)
                    Text("📤 输出").tag(DetailTab.output)
                }
                .pickerStyle(.segmented)
                .frame(width: 420)

                Spacer()

                if let convId = trace?.conversationId, !convId.isEmpty {
                    Button {
                        service.copyToClipboard(convId, label: "AGY 会话 ID")
                    } label: {
                        Label("ID: \(convId.prefix(8))", systemImage: "doc.on.doc")
                            .font(.caption.monospaced())
                    }
                    .controlSize(.small)
                }
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 10)
            .background(Color.primary.opacity(0.03))

            Divider()

            if isLoading {
                VStack(spacing: 12) {
                    ProgressView()
                    Text("正在加载完整请求轨迹...")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let trace {
                Group {
                    switch selectedTab {
                    case .input:
                        inputTabView(trace)
                    case .process:
                        processTabView(trace)
                    case .output:
                        outputTabView(trace)
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                VStack(spacing: 12) {
                    ContentUnavailableView(
                        "该历史记录无详细轨迹",
                        systemImage: "clock.badge.questionmark",
                        description: Text("此条为升级明细追踪功能之前的旧记录。此后新发起的请求将完整保存输入、执行过程与输出。")
                    )
                    if let err = record.error, !err.isEmpty {
                        VStack(alignment: .leading, spacing: 6) {
                            Text("错误信息")
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(.red)
                            Text(err)
                                .font(.system(.caption, design: .monospaced))
                                .textSelection(.enabled)
                                .padding(10)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .background(Color.red.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
                        }
                        .padding(.horizontal, 24)
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .frame(width: 860, height: 640)
        .task {
            isLoading = true
            let loaded = await service.fetchRequestTrace(id: record.id)
            trace = loaded
            if let loaded {
                // 若有工具步骤默认展示执行过程，否则展示输出
                selectedTab = loaded.executionSteps.contains(where: { $0.type == "tool" || $0.type == "hermes_tool_call" })
                    ? .process
                    : .output
            }
            isLoading = false
        }
    }

    // MARK: - 输入视图
    @ViewBuilder
    private func inputTabView(_ trace: RequestTrace) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: 14) {
                    Label("来源 IP：\(trace.clientIp?.isEmpty == false ? trace.clientIp! : "本机")", systemImage: "network")
                    if let chars = trace.promptChars, chars > 0 {
                        Label("送入引擎总字符：\(chars)", systemImage: "textformat.size")
                    }
                    Spacer()
                }
                .font(.caption.monospaced())
                .foregroundStyle(.secondary)

                ForEach(Array(trace.inputMessages.enumerated()), id: \.offset) { idx, msg in
                    let isLongSystem = (msg.role == "system" || msg.role == "developer") && msg.content.count > 400
                    let isExpanded = expandedSystemIndices.contains(idx)

                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            StatusPill(
                                text: msg.role.uppercased(),
                                color: roleColor(msg.role)
                            )
                            Text("\(msg.content.count) 字符")
                                .font(.caption2.monospacedDigit())
                                .foregroundStyle(.secondary)
                            Spacer()
                            if isLongSystem {
                                Button(isExpanded ? "收起" : "展开全文") {
                                    if isExpanded {
                                        expandedSystemIndices.remove(idx)
                                    } else {
                                        expandedSystemIndices.insert(idx)
                                    }
                                }
                                .controlSize(.mini)
                            }
                            Button("复制") {
                                service.copyToClipboard(msg.content, label: "\(msg.role) 消息")
                            }
                            .controlSize(.mini)
                        }

                        Text(isLongSystem && !isExpanded ? String(msg.content.prefix(360)) + "…" : msg.content)
                            .font(.system(.callout, design: msg.role == "system" ? .monospaced : .default))
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .padding(14)
                    .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))
                }
            }
            .padding(20)
        }
    }

    // MARK: - 执行过程时间轴
    @ViewBuilder
    private func processTabView(_ trace: RequestTrace) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                if trace.executionSteps.isEmpty {
                    ContentUnavailableView(
                        "直通推理（无中间工具步骤）",
                        systemImage: "arrow.right.circle",
                        description: Text("本次请求未触发本地工具调用或外部工具分发，由模型直接完成推理回复。")
                    )
                    .frame(height: 240)
                } else {
                    ForEach(Array(trace.executionSteps.enumerated()), id: \.offset) { idx, step in
                        HStack(alignment: .top, spacing: 12) {
                            // 左侧序号与时间轴线
                            VStack(spacing: 4) {
                                ZStack {
                                    Circle()
                                        .fill(stepColor(step.type).opacity(0.16))
                                        .frame(width: 28, height: 28)
                                    Image(systemName: stepIcon(step.type))
                                        .font(.caption.weight(.semibold))
                                        .foregroundStyle(stepColor(step.type))
                                }
                                if idx < trace.executionSteps.count - 1 {
                                    Rectangle()
                                        .fill(Color.primary.opacity(0.12))
                                        .frame(width: 2)
                                        .frame(maxHeight: .infinity)
                                }
                            }

                            VStack(alignment: .leading, spacing: 8) {
                                HStack {
                                    Text("Step \(idx + 1) · \(step.title)")
                                        .font(.callout.weight(.semibold))
                                    if let st = step.state, !st.isEmpty {
                                        StatusPill(text: st, color: stepColor(step.type))
                                    }
                                    Spacer()
                                    if let dur = step.duration, dur > 0 {
                                        Text(Formatters.duration(dur))
                                            .font(.caption.monospacedDigit())
                                            .foregroundStyle(.secondary)
                                    }
                                }

                                if let params = step.parameters, !params.isEmpty {
                                    VStack(alignment: .leading, spacing: 4) {
                                        HStack {
                                            Text(step.type == "agent_response" ? "推理统计" : "调用参数")
                                                .font(.caption2.weight(.semibold))
                                                .foregroundStyle(.secondary)
                                            Spacer()
                                            if step.type != "agent_response" {
                                                Button("复制参数") {
                                                    service.copyToClipboard(params, label: "工具参数")
                                                }
                                                .controlSize(.mini)
                                            }
                                        }
                                        Text(params)
                                            .font(.system(.caption, design: .monospaced))
                                            .textSelection(.enabled)
                                            .padding(10)
                                            .frame(maxWidth: .infinity, alignment: .leading)
                                            .background(Color.primary.opacity(0.05), in: RoundedRectangle(cornerRadius: 8))
                                    }
                                }

                                if let out = step.output, !out.isEmpty {
                                    VStack(alignment: .leading, spacing: 4) {
                                        HStack {
                                            Text("执行结果输出")
                                                .font(.caption2.weight(.semibold))
                                                .foregroundStyle(.secondary)
                                            Spacer()
                                            Button("复制输出") {
                                                service.copyToClipboard(out, label: "工具输出")
                                            }
                                            .controlSize(.mini)
                                        }
                                        Text(out)
                                            .font(.system(.caption, design: .monospaced))
                                            .textSelection(.enabled)
                                            .padding(10)
                                            .frame(maxWidth: .infinity, alignment: .leading)
                                            .background(Color.black.opacity(0.84), in: RoundedRectangle(cornerRadius: 8))
                                            .foregroundStyle(Color.white.opacity(0.9))
                                    }
                                }
                            }
                            .padding(14)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                            .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))
                        }
                    }
                }
            }
            .padding(20)
        }
    }

    // MARK: - 输出视图
    @ViewBuilder
    private func outputTabView(_ trace: RequestTrace) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                // Token 四维拆解条
                HStack(spacing: 12) {
                    TokenBadge(title: "输入", value: trace.usage.promptTokens, color: .blue)
                    TokenBadge(title: "输出", value: trace.usage.completionTokens, color: .green)
                    TokenBadge(title: "思考", value: trace.usage.thinkingTokens ?? 0, color: .purple)
                    TokenBadge(title: "缓存命中", value: trace.usage.cachedTokens ?? 0, color: .teal)
                    Spacer()
                    if !trace.outputText.isEmpty {
                        Button {
                            service.copyToClipboard(trace.outputText, label: "完整回复")
                        } label: {
                            Label("复制回复", systemImage: "doc.on.doc")
                        }
                        .controlSize(.small)
                    }
                }

                if let err = trace.error, !err.isEmpty {
                    VStack(alignment: .leading, spacing: 6) {
                        Label("执行异常 / 超时信息", systemImage: "exclamationmark.triangle.fill")
                            .font(.callout.weight(.semibold))
                            .foregroundStyle(.red)
                        Text(err)
                            .font(.system(.callout, design: .monospaced))
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .padding(14)
                    .background(Color.red.opacity(0.1), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                }

                VStack(alignment: .leading, spacing: 8) {
                    Text("最终返回正文")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    if trace.outputText.isEmpty {
                        Text(trace.executionSteps.contains(where: { $0.type == "hermes_tool_call" })
                             ? "本次响应仅包含转交 Hermes 执行的 Tool Calls（请在“执行过程”标签页查看具体工具调用参数）。"
                             : "无正文输出。")
                            .font(.callout)
                            .foregroundStyle(.secondary)
                    } else {
                        Text(trace.outputText)
                            .font(.body)
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                .padding(16)
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))
            }
            .padding(20)
        }
    }

    private func roleColor(_ role: String) -> Color {
        switch role.lowercased() {
        case "system", "developer": return .purple
        case "user": return .blue
        case "assistant": return .green
        case "tool": return .orange
        default: return .secondary
        }
    }

    private func stepColor(_ type: String) -> Color {
        switch type {
        case "tool": return .orange
        case "hermes_tool_call": return .indigo
        case "agent_response": return .blue
        default: return .secondary
        }
    }

    private func stepIcon(_ type: String) -> String {
        switch type {
        case "tool": return "wrench.and.screwdriver.fill"
        case "hermes_tool_call": return "arrow.triangle.branch"
        case "agent_response": return "brain"
        default: return "circle.fill"
        }
    }
}

struct TokenBadge: View {
    let title: String
    let value: Int
    let color: Color

    var body: some View {
        HStack(spacing: 6) {
            Text(title)
                .font(.caption2)
                .foregroundStyle(.secondary)
            Text(Formatters.compactNumber(value))
                .font(.caption.weight(.semibold).monospacedDigit())
                .foregroundStyle(color)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
        .background(color.opacity(0.1), in: Capsule())
    }
}
