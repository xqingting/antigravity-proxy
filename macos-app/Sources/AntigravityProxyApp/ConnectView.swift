import SwiftUI

struct ConnectView: View {
    @EnvironmentObject var service: ProxyService

    private var curlExample: String {
        """
        curl \(service.localBaseURL)/chat/completions \\
          -H "Content-Type: application/json" \\
          -H "Authorization: Bearer sk-antigravity-local" \\
          -d '{
            "model": "\(service.activeModel)",
            "stream": true,
            "messages": [{"role": "user", "content": "你好，请介绍一下你自己"}]
          }'
        """
    }

    private var allConfigText: String {
        """
        本机 Base URL: \(service.localBaseURL)
        局域网 Base URL: \(service.lanBaseURL)
        API Key: sk-antigravity-local
        Model: \(service.activeModel)
        """
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 14) {
                    HStack {
                        Label("标准 OpenAI 兼容端点", systemImage: "link")
                            .font(.headline)
                        Spacer()
                        Button {
                            service.copyToClipboard(allConfigText, label: "完整接入配置")
                        } label: {
                            Label("复制全部配置", systemImage: "doc.on.doc")
                        }
                        .buttonStyle(.borderedProminent)
                    }

                    ConfigRow(
                        title: "本机调用地址 (Cursor / ChatBox / 本机客户端)",
                        value: service.localBaseURL,
                        onCopy: { service.copyToClipboard(service.localBaseURL, label: "本机 Base URL") }
                    )
                    ConfigRow(
                        title: "局域网调用地址 (NAS / 手机 / 其他设备)",
                        value: service.lanBaseURL,
                        onCopy: { service.copyToClipboard(service.lanBaseURL, label: "局域网 Base URL") }
                    )
                    ConfigRow(
                        title: "API Key (本地代理校验占位符)",
                        value: "sk-antigravity-local",
                        onCopy: { service.copyToClipboard("sk-antigravity-local", label: "API Key") }
                    )
                    ConfigRow(
                        title: "默认模型名称",
                        value: service.activeModel,
                        onCopy: { service.copyToClipboard(service.activeModel, label: "模型名称") }
                    )
                }
                .padding(18)
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))

                VStack(alignment: .leading, spacing: 12) {
                    HStack {
                        Label("支持透传的模型列表", systemImage: "sparkles")
                            .font(.headline)
                        Spacer()
                    }
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 210), spacing: 10)], spacing: 10) {
                        ForEach(ModelOption.presets) { opt in
                            HStack {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(opt.label)
                                        .font(.callout.weight(.semibold))
                                    Text(opt.id)
                                        .font(.caption.monospaced())
                                        .foregroundStyle(.secondary)
                                }
                                Spacer()
                                Button {
                                    service.copyToClipboard(opt.id, label: opt.label)
                                } label: {
                                    Image(systemName: "doc.on.doc")
                                }
                                .buttonStyle(.borderless)
                            }
                            .padding(12)
                            .background(Color.primary.opacity(0.04), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                        }
                    }
                }
                .padding(18)
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))

                VStack(alignment: .leading, spacing: 12) {
                    HStack {
                        Label("终端 cURL 快速测试", systemImage: "apple.terminal")
                            .font(.headline)
                        Spacer()
                        Button {
                            service.copyToClipboard(curlExample, label: "cURL 测试命令")
                        } label: {
                            Label("复制命令", systemImage: "doc.on.doc")
                        }
                    }
                    Text(curlExample)
                        .font(.system(.caption, design: .monospaced))
                        .textSelection(.enabled)
                        .padding(14)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color.black.opacity(0.82), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                        .foregroundStyle(Color.white.opacity(0.92))
                }
                .padding(18)
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))
            }
            .padding(24)
        }
        .navigationTitle("快速接入")
    }
}

struct ConfigRow: View {
    let title: String
    let value: String
    let onCopy: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
            HStack {
                Text(value)
                    .font(.system(.callout, design: .monospaced))
                    .textSelection(.enabled)
                Spacer()
                Button("复制", action: onCopy)
                    .controlSize(.small)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(Color.primary.opacity(0.04), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        }
    }
}
