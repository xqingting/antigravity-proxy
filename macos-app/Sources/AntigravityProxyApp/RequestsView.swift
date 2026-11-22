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
                default: return true
                }
            }()
            let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            let searchOK = query.isEmpty
                || rec.model.lowercased().contains(query)
                || rec.displayDate.lowercased().contains(query)
                || rec.timestamp.lowercased().contains(query)
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
                }
                .pickerStyle(.segmented)
                .frame(width: 240)

                Spacer()

                HStack(spacing: 6) {
                    Image(systemName: "magnifyingglass")
                        .foregroundStyle(.secondary)
                    TextField("筛选模型、日期或错误信息...", text: $searchText)
                        .textFieldStyle(.plain)
                        .frame(width: 220)
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
                    description: Text("请调整筛选条件或等待新的 API 请求。")
                )
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                List {
                    HStack {
                        Text("日期 / 时间").frame(width: 110, alignment: .leading)
                        Text("模型").frame(width: 170, alignment: .leading)
                        Text("模式").frame(width: 60, alignment: .leading)
                        Text("输入 Token").frame(width: 90, alignment: .trailing)
                        Text("输出 Token").frame(width: 90, alignment: .trailing)
                        Text("耗时").frame(width: 75, alignment: .trailing)
                        Text("速率").frame(width: 85, alignment: .trailing)
                        Spacer()
                        Text("状态").frame(width: 64, alignment: .trailing)
                    }
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                    .padding(.vertical, 4)

                    ForEach(filteredRecords) { rec in
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(rec.displayDate)
                                    .font(.caption2.monospacedDigit())
                                    .foregroundStyle(.secondary)
                                Text(rec.timestamp)
                                    .font(.callout.weight(.medium).monospacedDigit())
                            }
                            .frame(width: 110, alignment: .leading)

                            Text(rec.model)
                                .font(.caption.monospaced())
                                .lineLimit(1)
                                .frame(width: 170, alignment: .leading)

                            Text(rec.isStream ? "流式" : "阻塞")
                                .font(.caption2.weight(.medium))
                                .foregroundStyle(rec.isStream ? .teal : .secondary)
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background((rec.isStream ? Color.teal : Color.secondary).opacity(0.12), in: Capsule())
                                .frame(width: 60, alignment: .leading)

                            Text(Formatters.compactNumber(rec.promptTokens))
                                .font(.callout.monospacedDigit())
                                .frame(width: 90, alignment: .trailing)

                            Text(Formatters.compactNumber(rec.completionTokens))
                                .font(.callout.monospacedDigit())
                                .frame(width: 90, alignment: .trailing)

                            Text(Formatters.duration(rec.duration))
                                .font(.callout.monospacedDigit())
                                .frame(width: 75, alignment: .trailing)

                            Text(String(format: "%.1f tps", rec.tps))
                                .font(.callout.monospacedDigit())
                                .foregroundStyle(.secondary)
                                .frame(width: 85, alignment: .trailing)

                            Spacer()

                            HStack(spacing: 6) {
                                StatusPill(
                                    text: rec.isSuccess ? "成功" : (rec.isTimeout ? "超时" : "失败"),
                                    color: rec.isSuccess ? .green : (rec.isTimeout ? .orange : .red)
                                )
                            }
                            .frame(width: 64, alignment: .trailing)
                        }
                        .padding(.vertical, 4)
                        .contentShape(Rectangle())
                        .onTapGesture {
                            if rec.error != nil {
                                selectedRecord = rec
                            }
                        }
                    }
                }
                .listStyle(.inset)
            }
        }
        .navigationTitle("请求明细")
        .sheet(item: $selectedRecord) { rec in
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Label("请求异常详情", systemImage: "exclamationmark.triangle.fill")
                        .font(.headline)
                        .foregroundStyle(.orange)
                    Spacer()
                    Button("关闭") { selectedRecord = nil }
                }
                Divider()
                Text("时间：\(rec.displayDate) \(rec.timestamp)  |  模型：\(rec.model)  |  耗时：\(Formatters.duration(rec.duration))")
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
                ScrollView {
                    Text(rec.error ?? "无详细错误信息")
                        .font(.system(.callout, design: .monospaced))
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .padding(12)
                .background(Color.primary.opacity(0.05), in: RoundedRectangle(cornerRadius: 10))
            }
            .padding(20)
            .frame(width: 560, height: 320)
        }
    }
}
