import SwiftUI

struct LogsView: View {
    @EnvironmentObject var service: ProxyService
    @State private var searchText: String = ""
    @State private var autoScroll: Bool = true

    private var filteredLines: [String] {
        let q = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !q.isEmpty else { return service.logLines }
        return service.logLines.filter { $0.lowercased().contains(q) }
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                HStack(spacing: 6) {
                    Image(systemName: "magnifyingglass")
                        .foregroundStyle(.secondary)
                    TextField("搜索日志关键字...", text: $searchText)
                        .textFieldStyle(.plain)
                        .frame(width: 200)
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

                ForEach(["Hermes", "调用", "错误", "超时"], id: \.self) { tag in
                    Button(tag) {
                        searchText = (searchText == tag) ? "" : tag
                    }
                    .controlSize(.small)
                    .buttonStyle(.bordered)
                    .tint(searchText == tag ? .accentColor : .secondary)
                }

                Spacer()

                Toggle("自动滚底", isOn: $autoScroll)
                    .toggleStyle(.checkbox)

                Button {
                    service.refreshLogs()
                } label: {
                    Label("刷新", systemImage: "arrow.clockwise")
                }

                Button {
                    service.clearLogView()
                } label: {
                    Label("清空视图", systemImage: "trash")
                }
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 12)

            Divider()

            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 4) {
                        ForEach(Array(filteredLines.enumerated()), id: \.offset) { idx, line in
                            Text(line)
                                .font(.system(size: 12, design: .monospaced))
                                .foregroundStyle(colorForLogLine(line))
                                .textSelection(.enabled)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .id(idx)
                        }
                    }
                    .padding(16)
                }
                .background(Color.black.opacity(0.88))
                .onChange(of: filteredLines.count) { _, newCount in
                    if autoScroll && newCount > 0 {
                        proxy.scrollTo(newCount - 1, anchor: .bottom)
                    }
                }
            }
        }
        .navigationTitle("实时日志")
        .onAppear {
            service.refreshLogs()
        }
    }

    private func colorForLogLine(_ line: String) -> Color {
        if line.contains("!!") || line.contains("错误") || line.contains("超时") || line.contains("500") || line.contains("504") {
            return Color(red: 1.0, green: 0.45, blue: 0.45)
        }
        if line.contains("Hermes") {
            return Color(red: 0.55, green: 0.85, blue: 1.0)
        }
        if line.contains("<- ") || line.contains("成功") {
            return Color(red: 0.48, green: 0.92, blue: 0.62)
        }
        if line.contains("-> ") {
            return Color(red: 1.0, green: 0.85, blue: 0.45)
        }
        return Color.white.opacity(0.84)
    }
}
