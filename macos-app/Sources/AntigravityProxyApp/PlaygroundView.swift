import SwiftUI

struct PlaygroundView: View {
    @EnvironmentObject var service: ProxyService

    var body: some View {
        VStack(spacing: 16) {
            HStack(spacing: 14) {
                Picker("测试模型", selection: $service.playgroundModel) {
                    ForEach(ModelOption.presets) { opt in
                        Text(opt.label).tag(opt.id)
                    }
                }
                .frame(width: 240)

                Toggle("SSE 流式打字机", isOn: $service.playgroundStream)
                    .toggleStyle(.switch)

                Spacer()

                if let latency = service.playgroundLatency {
                    Label(Formatters.duration(latency), systemImage: "timer")
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
                if let tokens = service.playgroundTokens {
                    Label("\(tokens) tok", systemImage: "number")
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
            }
            .padding(.horizontal, 24)
            .padding(.top, 18)

            VStack(alignment: .leading, spacing: 8) {
                Text("测试提示词")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                HStack(alignment: .bottom, spacing: 12) {
                    TextEditor(text: $service.playgroundPrompt)
                        .font(.body)
                        .frame(height: 82)
                        .padding(8)
                        .background(Color.primary.opacity(0.04), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                        .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).strokeBorder(Color.primary.opacity(0.1), lineWidth: 1))

                    VStack(spacing: 8) {
                        if service.playgroundIsRunning {
                            Button(role: .destructive) {
                                service.cancelPlaygroundTest()
                            } label: {
                                Label("中止", systemImage: "stop.fill")
                                    .frame(width: 88)
                            }
                            .buttonStyle(.borderedProminent)
                        } else {
                            Button {
                                service.runPlaygroundTest()
                            } label: {
                                Label("发送测试", systemImage: "paperplane.fill")
                                    .frame(width: 88)
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(!service.isRunning || service.playgroundPrompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        }
                    }
                }
            }
            .padding(.horizontal, 24)

            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text("模型响应输出")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    if service.playgroundIsRunning {
                        ProgressView()
                            .controlSize(.mini)
                    }
                    Spacer()
                    if !service.playgroundOutput.isEmpty {
                        Button("复制回复") {
                            service.copyToClipboard(service.playgroundOutput, label: "测试回复")
                        }
                        .controlSize(.small)
                    }
                }

                ScrollView {
                    VStack(alignment: .leading, spacing: 10) {
                        if let err = service.playgroundError {
                            Label(err, systemImage: "exclamationmark.triangle.fill")
                                .foregroundStyle(.red)
                                .font(.callout)
                        }
                        if service.playgroundOutput.isEmpty && service.playgroundError == nil {
                            Text(service.playgroundIsRunning ? "正在等待推理引擎首字返回..." : "点击“发送测试”验证代理通道、模型路由与实时流式推流。")
                                .foregroundStyle(.secondary)
                                .font(.callout)
                        } else {
                            Text(service.playgroundOutput)
                                .font(.body)
                                .textSelection(.enabled)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                    .padding(16)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(Color.primary.opacity(0.08), lineWidth: 1))
            }
            .padding(.horizontal, 24)
            .padding(.bottom, 24)
        }
        .navigationTitle("联调测试")
    }
}
