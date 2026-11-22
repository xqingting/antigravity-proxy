import SwiftUI
import AppKit

final class AppDelegate: NSObject, NSApplicationDelegate {
    weak var service: ProxyService?

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        // 点击窗口关闭按钮时隐藏至菜单栏常驻，不终止代理服务
        false
    }

    func applicationWillTerminate(_ notification: Notification) {
        MainActor.assumeIsolated {
            service?.terminateOnQuit()
        }
    }
}

@main
struct AntigravityProxyApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    @StateObject private var service = ProxyService()
    @State private var selectedTab: SidebarTab = .overview

    var body: some Scene {
        Window("Antigravity Proxy", id: "main") {
            MainContentView(selectedTab: $selectedTab)
                .environmentObject(service)
                .frame(minWidth: 920, minHeight: 620)
                .onAppear {
                    appDelegate.service = service
                    NSApp.setActivationPolicy(.regular)
                }
        }
        .defaultSize(width: 1080, height: 720)
        .windowToolbarStyle(.unified)

        MenuBarExtra {
            MenuBarContentView()
                .environmentObject(service)
        } label: {
            Image(systemName: service.isRunning ? "bolt.horizontal.circle.fill" : "bolt.horizontal.circle")
                .symbolRenderingMode(.hierarchical)
        }
    }
}

struct MainContentView: View {
    @EnvironmentObject var service: ProxyService
    @Binding var selectedTab: SidebarTab

    var body: some View {
        ZStack(alignment: .bottom) {
            NavigationSplitView {
                List(SidebarTab.allCases, selection: $selectedTab) { tab in
                    Label(tab.rawValue, systemImage: tab.systemImage)
                        .tag(tab)
                }
                .navigationSplitViewColumnWidth(min: 176, ideal: 196, max: 230)
                .safeAreaInset(edge: .bottom) {
                    VStack(alignment: .leading, spacing: 8) {
                        Divider()
                        HStack(spacing: 8) {
                            Circle()
                                .fill(service.isRunning ? Color.green : Color.red)
                                .frame(width: 8, height: 8)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(service.isRunning ? "服务运行中" : "服务已停止")
                                    .font(.caption.weight(.semibold))
                                Text("端口 \(service.port) · AGY \(service.agyVersion)")
                                    .font(.caption2)
                                    .foregroundStyle(.secondary)
                                    .monospacedDigit()
                            }
                            Spacer()
                        }
                        .padding(.horizontal, 12)
                        .padding(.vertical, 8)
                    }
                    .background(.ultraThinMaterial)
                }
            } detail: {
                Group {
                    switch selectedTab {
                    case .overview:
                        OverviewView(onSelectTab: { selectedTab = $0 })
                    case .requests:
                        RequestsView()
                    case .connect:
                        ConnectView()
                    case .playground:
                        PlaygroundView()
                    case .logs:
                        LogsView()
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Color(nsColor: .windowBackgroundColor))
            }
            .toolbar {
                ToolbarItemGroup(placement: .primaryAction) {
                    if service.isRunning {
                        Button {
                            Task { await service.restartProxy() }
                        } label: {
                            Label("重启服务", systemImage: "arrow.clockwise")
                        }
                        .disabled(service.isBusy)

                        Button {
                            Task { await service.stopProxy() }
                        } label: {
                            Label("停止服务", systemImage: "stop.circle")
                        }
                        .disabled(service.isBusy)
                    } else {
                        Button {
                            Task { await service.startProxy() }
                        } label: {
                            Label("启动服务", systemImage: "play.circle.fill")
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(service.isBusy)
                    }
                }
            }

            if let toast = service.toastMessage {
                HStack(spacing: 8) {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                    Text(toast)
                        .font(.callout.weight(.medium))
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
                .background(.regularMaterial, in: Capsule())
                .overlay(Capsule().strokeBorder(Color.primary.opacity(0.1), lineWidth: 1))
                .shadow(color: .black.opacity(0.15), radius: 12, y: 4)
                .padding(.bottom, 20)
                .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .animation(.spring(response: 0.28, dampingFraction: 0.85), value: service.toastMessage)
    }
}

struct MenuBarContentView: View {
    @EnvironmentObject var service: ProxyService
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        VStack(alignment: .leading) {
            Text(service.isRunning ? "● 运行中 · \(service.activeModel)" : "○ 已停止")
            Text("端口 \(service.port) · 思考 \(service.activeEffort) · \(service.stats.totalRequests) 次请求")
                .font(.caption)
                .foregroundStyle(.secondary)

            Divider()

            Button("显示控制台") {
                NSApp.activate(ignoringOtherApps: true)
                openWindow(id: "main")
            }

            if service.isRunning {
                Button("重启代理服务") {
                    Task { await service.restartProxy() }
                }
                Button("停止代理服务") {
                    Task { await service.stopProxy() }
                }
            } else {
                Button("启动代理服务") {
                    Task { await service.startProxy() }
                }
            }

            Divider()

            Button("复制本机 Base URL") {
                service.copyToClipboard(service.localBaseURL, label: "本机 Base URL")
            }
            Button("复制局域网 Base URL") {
                service.copyToClipboard(service.lanBaseURL, label: "局域网 Base URL")
            }

            Divider()

            Button("退出 Antigravity Proxy") {
                service.terminateOnQuit()
                NSApp.terminate(nil)
            }
            .keyboardShortcut("q")
        }
    }
}
