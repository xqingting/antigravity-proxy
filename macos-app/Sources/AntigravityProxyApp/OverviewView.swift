import SwiftUI

struct OverviewView: View {
    @EnvironmentObject var service: ProxyService
    var onSelectTab: (SidebarTab) -> Void
    @State private var showResetConfirm: Bool = false

    private var hasUnsavedModelChange: Bool {
        service.selectedModel != service.activeModel || service.selectedEffort.rawValue != service.activeEffort.lowercased()
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                headerBanner
                modelControlCard
                metricsGrid
                concurrencyAndHermesRow
                recentPreviewCard
            }
            .padding(24)
        }
        .navigationTitle("控制台概览")
        .confirmationDialog(
            "确定重置全部统计数据吗？",
            isPresented: $showResetConfirm,
            titleVisibility: .visible
        ) {
            Button("确认重置", role: .destructive) {
                Task { await service.resetStats() }
            }
            Button("取消", role: .cancel) {}
        } message: {
            Text("该操作将清空历史请求计数与 Token 汇总记录，无法撤销。")
        }
    }

    private var headerBanner: some View {
        HStack(spacing: 16) {
            ZStack {
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .fill(service.isRunning ? Color.green.opacity(0.14) : Color.red.opacity(0.14))
                    .frame(width: 52, height: 52)
                Image(systemName: service.isRunning ? "bolt.shield.fill" : "bolt.slash.fill")
                    .font(.system(size: 24))
                    .foregroundStyle(service.isRunning ? .green : .red)
            }

            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    Text("Antigravity Proxy")
                        .font(.title2.bold())
                    StatusPill(
                        text: service.isRunning ? "在线运行" : "已停止",
                        color: service.isRunning ? .green : .red
                    )
                }
                Text("OpenAI 兼容本地网关 · 监听 0.0.0.0:\(service.port) · 引擎 AGY \(service.agyVersion)")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .monospacedDigit()
            }

            Spacer()

            Button {
                showResetConfirm = true
            } label: {
                Label("重置统计", systemImage: "arrow.counterclockwise")
            }
            .disabled(!service.isRunning)
        }
        .padding(18)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .strokeBorder(Color.primary.opacity(0.08), lineWidth: 1)
        )
    }

    private var modelControlCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Label("推理引擎与默认模型", systemImage: "cpu")
                    .font(.headline)
                Spacer()
                Text("当前生效：\(service.activeModel) · effort: \(service.activeEffort)")
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
            }

            HStack(spacing: 14) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("默认模型")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Picker("默认模型", selection: $service.selectedModel) {
                        ForEach(ModelOption.presets) { opt in
                            Text("\(opt.label) (\(opt.badge))").tag(opt.id)
                        }
                    }
                    .labelsHidden()
                    .frame(minWidth: 260)
                }

                VStack(alignment: .leading, spacing: 6) {
                    Text("思考深度 (Effort)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Picker("思考深度", selection: $service.selectedEffort) {
                        ForEach(EffortLevel.allCases) { level in
                            Text(level.displayName).tag(level)
                        }
                    }
                    .labelsHidden()
                    .frame(minWidth: 180)
                }

                Spacer()

                Button {
                    Task { await service.restartProxy(applySelection: true) }
                } label: {
                    if service.isBusy {
                        ProgressView()
                            .controlSize(.small)
                            .padding(.horizontal, 8)
                    } else {
                        Label(hasUnsavedModelChange ? "应用并重启" : "重新加载", systemImage: "arrow.triangle.2.circlepath")
                    }
                }
                .buttonStyle(.borderedProminent)
                .tint(hasUnsavedModelChange ? .accentColor : .secondary)
                .disabled(service.isBusy)
            }
        }
        .padding(18)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .strokeBorder(Color.primary.opacity(0.08), lineWidth: 1)
        )
    }

    private var metricsGrid: some View {
        LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 14), count: 4), spacing: 14) {
            MetricCard(
                title: "累计请求",
                value: "\(service.stats.totalRequests)",
                subtitle: "成功 \(service.stats.successfulRequests) · 失败 \(service.stats.failedRequests)",
                icon: "arrow.up.arrow.down.circle.fill",
                tint: .blue
            )
            MetricCard(
                title: "成功率",
                value: String(format: "%.1f%%", service.stats.successRate),
                subtitle: "平均耗时 \(Formatters.duration(service.stats.avgDuration))",
                icon: "checkmark.seal.fill",
                tint: service.stats.successRate >= 90 ? .green : .orange
            )
            MetricCard(
                title: "Token 总消耗",
                value: Formatters.compactNumber(service.stats.totalTokens),
                subtitle: "入 \(Formatters.compactNumber(service.stats.totalPromptTokens)) · 出 \(Formatters.compactNumber(service.stats.totalCompletionTokens))",
                icon: "chart.bar.fill",
                tint: .purple
            )
            MetricCard(
                title: "平均吞吐",
                value: String(format: "%.1f tps", service.stats.avgTps),
                subtitle: "流式实时打字机透传",
                icon: "speedometer",
                tint: .teal
            )
        }
    }

    private var concurrencyAndHermesRow: some View {
        HStack(spacing: 14) {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Label("实时并发通道", systemImage: "rectangle.3.group")
                        .font(.headline)
                    Spacer()
                    Text("\(service.stats.activeRequests) / \(service.stats.maxConcurrency)")
                        .font(.subheadline.weight(.semibold).monospacedDigit())
                        .foregroundStyle(service.stats.activeRequests > 0 ? .blue : .secondary)
                }
                ProgressView(
                    value: Double(min(service.stats.activeRequests, max(1, service.stats.maxConcurrency))),
                    total: Double(max(1, service.stats.maxConcurrency))
                )
                .tint(.blue)
                Text("支持最多 \(service.stats.maxConcurrency) 路并发推理，超额自动安全排队避免 429 限流。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))

            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Label("Hermes NAS 专属协作", systemImage: "server.rack")
                        .font(.headline)
                    Spacer()
                    StatusPill(
                        text: service.hasLocalHermesDirective ? "本机私有指令已启用" : "通用防护模式",
                        color: service.hasLocalHermesDirective ? .green : .blue
                    )
                }
                Text("目标来源 IP：\(service.hermesIps.joined(separator: ", "))")
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
                Text("仅匹配该来源时自动注入本机私有指令并支持工具调用转换，敏感配置仅保存在本机。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))
        }
    }

    private var recentPreviewCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("最近调用动态", systemImage: "clock.arrow.circlepath")
                    .font(.headline)
                Spacer()
                Button("查看全部明细 →") {
                    onSelectTab(.requests)
                }
                .buttonStyle(.link)
            }

            if service.stats.recentHistory.isEmpty {
                ContentUnavailableView(
                    "暂无请求记录",
                    systemImage: "tray",
                    description: Text("发起 API 调用或在“联调测试”中发送消息后，实时指标将展示在这里。")
                )
                .frame(height: 150)
            } else {
                VStack(spacing: 0) {
                    ForEach(Array(service.stats.recentHistory.prefix(6).enumerated()), id: \.element.id) { idx, item in
                        if idx > 0 { Divider() }
                        HStack(spacing: 12) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(item.displayDate)
                                    .font(.caption2.monospacedDigit())
                                    .foregroundStyle(.secondary)
                                Text(item.timestamp)
                                    .font(.callout.weight(.medium).monospacedDigit())
                            }
                            .frame(width: 82, alignment: .leading)

                            Text(item.model)
                                .font(.caption.monospaced())
                                .padding(.horizontal, 8)
                                .padding(.vertical, 3)
                                .background(Color.accentColor.opacity(0.12), in: Capsule())

                            if item.isStream {
                                Text("SSE")
                                    .font(.caption2.weight(.semibold))
                                    .foregroundStyle(.teal)
                                    .padding(.horizontal, 6)
                                    .padding(.vertical, 2)
                                    .background(Color.teal.opacity(0.12), in: Capsule())
                            }

                            Spacer()

                            Text("入 \(Formatters.compactNumber(item.promptTokens)) / 出 \(Formatters.compactNumber(item.completionTokens))")
                                .font(.caption.monospacedDigit())
                                .foregroundStyle(.secondary)

                            Text(Formatters.duration(item.duration))
                                .font(.caption.monospacedDigit())
                                .frame(width: 64, alignment: .trailing)

                            StatusPill(
                                text: item.isSuccess ? "成功" : (item.isTimeout ? "超时" : "失败"),
                                color: item.isSuccess ? .green : (item.isTimeout ? .orange : .red)
                            )
                        }
                        .padding(.vertical, 10)
                    }
                }
            }
        }
        .padding(18)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .strokeBorder(Color.primary.opacity(0.08), lineWidth: 1)
        )
    }
}

struct MetricCard: View {
    let title: String
    let value: String
    let subtitle: String
    let icon: String
    let tint: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(title)
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.secondary)
                Spacer()
                Image(systemName: icon)
                    .foregroundStyle(tint)
            }
            Text(value)
                .font(.title2.bold().monospacedDigit())
            Text(subtitle)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .strokeBorder(Color.primary.opacity(0.08), lineWidth: 1)
        )
    }
}

struct StatusPill: View {
    let text: String
    let color: Color

    var body: some View {
        Text(text)
            .font(.caption2.weight(.semibold))
            .foregroundStyle(color)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(color.opacity(0.14), in: Capsule())
    }
}
