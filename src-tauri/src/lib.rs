use serde::{Deserialize, Serialize};
use std::fs;
use std::io::Read;
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, State, WindowEvent,
};

#[derive(Clone, Serialize, Deserialize, Debug)]
pub struct ProxyStatus {
    pub running: bool,
    pub port: u16,
    pub model: String,
    pub effort: String,
    pub agy_version: String,
    pub pid: Option<u32>,
}

#[derive(Clone, Serialize, Deserialize, Debug)]
pub struct TestResult {
    pub content: String,
    pub total_tokens: u32,
}

pub struct ProxyManager {
    pub child: Arc<Mutex<Option<Child>>>,
    pub project_dir: PathBuf,
}

fn get_project_dir() -> PathBuf {
    // 1. 优先检查当前工作目录
    if let Ok(cur) = std::env::current_dir() {
        if cur.join("agy_proxy.py").exists() {
            return cur;
        }
    }
    // 2. 检查可执行文件同级或上级目录 (适应 macOS App 与 Windows 安装包)
    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(exe_dir) = exe_path.parent() {
            if exe_dir.join("agy_proxy.py").exists() {
                return exe_dir.to_path_buf();
            }
            if let Some(bundle_dir) = exe_dir.parent().and_then(|p| p.parent()).and_then(|p| p.parent()) {
                if bundle_dir.join("agy_proxy.py").exists() {
                    return bundle_dir.to_path_buf();
                }
            }
        }
    }
    // 3. 开发者本地路径回退
    let dev_path = PathBuf::from("/Users/wadeliu/Desktop/通用项目/antigravity-proxy");
    if dev_path.exists() {
        return dev_path;
    }
    std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}

fn get_python_command() -> &'static str {
    if cfg!(windows) {
        if Command::new("python").arg("--version").output().is_ok() {
            "python"
        } else if Command::new("py").arg("--version").output().is_ok() {
            "py"
        } else {
            "python3"
        }
    } else {
        if Command::new("python3").arg("--version").output().is_ok() {
            "python3"
        } else {
            "python"
        }
    }
}

fn check_health(port: u16) -> Option<serde_json::Value> {
    let url = format!("http://127.0.0.1:{}/health", port);
    let resp = ureq::get(&url)
        .timeout(Duration::from_millis(1500))
        .call()
        .ok()?;

    if resp.status() == 200 {
        resp.into_json::<serde_json::Value>().ok()
    } else {
        None
    }
}

mod commands {
    use super::*;

    #[tauri::command]
    pub fn get_proxy_status() -> ProxyStatus {
        let port = 8765;
        if let Some(health) = check_health(port) {
            ProxyStatus {
                running: true,
                port,
                model: health
                    .get("default_model")
                    .and_then(|v| v.as_str())
                    .unwrap_or("gemini-3.8-flash")
                    .to_string(),
                effort: health
                    .get("default_effort")
                    .and_then(|v| v.as_str())
                    .unwrap_or("high")
                    .to_string(),
                agy_version: health
                    .get("agy_version")
                    .and_then(|v| v.as_str())
                    .unwrap_or("已连接")
                    .to_string(),
                pid: None,
            }
        } else {
            ProxyStatus {
                running: false,
                port,
                model: "gemini-3.8-flash".to_string(),
                effort: "high".to_string(),
                agy_version: "未检测".to_string(),
                pid: None,
            }
        }
    }

    #[tauri::command]
    pub fn start_proxy(state: State<ProxyManager>) -> Result<String, String> {
        if check_health(8765).is_some() {
            return Ok("服务已经在运行中".to_string());
        }

        let script_path = state.project_dir.join("agy_proxy.py");
        let log_path = state.project_dir.join("proxy.log");

        let stdout_file = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&log_path)
            .map_err(|e| format!("打开日志文件失败: {}", e))?;

        let stderr_file = stdout_file.try_clone().map_err(|e| e.to_string())?;
        let py_cmd = get_python_command();

        let child = Command::new(py_cmd)
            .arg(&script_path)
            .arg("--port")
            .arg("8765")
            .arg("--model")
            .arg("gemini-3.8-flash")
            .arg("--effort")
            .arg("medium")
            .arg("--timeout")
            .arg("300")
            .arg("--max-concurrency")
            .arg("5")
            .current_dir(&state.project_dir)
            .stdout(stdout_file)
            .stderr(stderr_file)
            .spawn()
            .map_err(|e| format!("启动 python 代理进程失败 (尝试使用 {}): {}", py_cmd, e))?;

        let pid = child.id();
        *state.child.lock().unwrap() = Some(child);

        for _ in 0..15 {
            std::thread::sleep(Duration::from_millis(200));
            if check_health(8765).is_some() {
                return Ok(format!("启动成功 (PID: {})", pid));
            }
        }

        Ok(format!("已启动进程 (PID: {})，等待就绪中", pid))
    }

    #[tauri::command]
    pub fn stop_proxy(state: State<ProxyManager>) -> Result<String, String> {
        if let Some(mut child) = state.child.lock().unwrap().take() {
            let _ = child.kill();
        }

        #[cfg(unix)]
        {
            let stop_script = state.project_dir.join("stop.sh");
            if stop_script.exists() {
                let _ = Command::new("bash").arg(&stop_script).output();
            }
        }

        #[cfg(windows)]
        {
            let stop_script = state.project_dir.join("stop.bat");
            if stop_script.exists() {
                let _ = Command::new("cmd").arg("/C").arg(&stop_script).output();
            }
        }

        std::thread::sleep(Duration::from_millis(500));
        Ok("服务已停止".to_string())
    }

    #[tauri::command]
    pub fn restart_proxy(state: State<ProxyManager>) -> Result<String, String> {
        let _ = stop_proxy(state.clone());
        std::thread::sleep(Duration::from_millis(800));
        start_proxy(state)
    }

    #[tauri::command]
    pub async fn test_completion(prompt: String) -> Result<TestResult, String> {
        tauri::async_runtime::spawn_blocking(move || {
            let url = "http://127.0.0.1:8765/v1/chat/completions";
            let body = serde_json::json!({
                "model": "gemini-3.8-flash",
                "messages": [
                    {"role": "user", "content": prompt}
                ]
            });

            let resp = ureq::post(url)
                .timeout(Duration::from_secs(60))
                .set("Content-Type", "application/json")
                .send_json(body)
                .map_err(|e| format!("请求失败: {}", e))?;

            let json: serde_json::Value = resp
                .into_json()
                .map_err(|e| format!("解析响应失败: {}", e))?;

            let content = json["choices"][0]["message"]["content"]
                .as_str()
                .unwrap_or("无返回内容")
                .to_string();

            let total_tokens = json["usage"]["total_tokens"]
                .as_u64()
                .unwrap_or(0) as u32;

            Ok(TestResult {
                content,
                total_tokens,
            })
        })
        .await
        .map_err(|e| format!("异步任务失败: {}", e))?
    }

    #[tauri::command]
    pub fn get_proxy_logs(state: State<ProxyManager>) -> Result<String, String> {
        let log_path = state.project_dir.join("proxy.log");
        if !log_path.exists() {
            return Ok("暂无日志".to_string());
        }

        let mut content = String::new();
        let mut file = fs::File::open(&log_path).map_err(|e| e.to_string())?;
        file.read_to_string(&mut content).map_err(|e| e.to_string())?;

        let lines: Vec<&str> = content.lines().collect();
        let last_lines = if lines.len() > 100 {
            lines[lines.len() - 100..].join("\n")
        } else {
            lines.join("\n")
        };

        Ok(last_lines)
    }
}

impl Clone for ProxyManager {
    fn clone(&self) -> Self {
        Self {
            child: Arc::clone(&self.child),
            project_dir: self.project_dir.clone(),
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let project_dir = get_project_dir();
    let manager = ProxyManager {
        child: Arc::new(Mutex::new(None)),
        project_dir,
    };

    tauri::Builder::default()
        .manage(manager)
        .setup(|app| {
            let show_item = MenuItem::with_id(app, "show", "显示控制台", true, None::<&str>)?;
            let restart_item = MenuItem::with_id(app, "restart", "重启代理服务", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "退出应用", true, None::<&str>)?;

            let menu = Menu::with_items(app, &[&show_item, &restart_item, &quit_item])?;

            let _tray = TrayIconBuilder::new()
                .menu(&menu)
                .tooltip("Antigravity Proxy")
                .on_menu_event(|app, event| match event.id().as_ref() {
                    "show" => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                    "restart" => {
                        let state = app.state::<ProxyManager>();
                        let _ = commands::restart_proxy(state);
                    }
                    "quit" => {
                        let state = app.state::<ProxyManager>();
                        let _ = commands::stop_proxy(state);
                        app.exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(window) = app.get_webview_window("main") {
                            if window.is_visible().unwrap_or(false) {
                                let _ = window.hide();
                            } else {
                                let _ = window.show();
                                let _ = window.set_focus();
                            }
                        }
                    }
                })
                .build(app)?;

            // 启动时检查代理服务
            if check_health(8765).is_none() {
                let state = app.state::<ProxyManager>();
                let _ = commands::start_proxy(state);
            }

            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .invoke_handler(tauri::generate_handler![
            commands::get_proxy_status,
            commands::start_proxy,
            commands::stop_proxy,
            commands::restart_proxy,
            commands::test_completion,
            commands::get_proxy_logs
        ])
        .run(tauri::generate_context!())
        .expect("运行 Tauri 失败");
}
