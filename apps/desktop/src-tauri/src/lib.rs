use std::fs;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::{Manager, RunEvent, State};

struct Backend {
    port: u16,
    token: String,
    data_dir: String,
    error: Option<String>,
    owned: bool,
    child: Option<Child>,
}

struct BackendState {
    inner: Mutex<Backend>,
}

#[derive(Serialize)]
struct SessionDto {
    port: u16,
    token: String,
    #[serde(rename = "dataDir")]
    data_dir: String,
}

fn backend_command() -> Command {
    if let Ok(binary) = std::env::var("AGENTSHELF_BIN") {
        return Command::new(binary);
    }
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let launcher = if cfg!(windows) {
        root.join(".venv/Scripts/agentshelf.exe")
    } else {
        root.join(".venv/bin/agentshelf")
    };
    if launcher.exists() {
        return Command::new(launcher);
    }
    let python = if cfg!(windows) {
        root.join(".venv/Scripts/python.exe")
    } else {
        root.join(".venv/bin/python")
    };
    let program = if python.exists() {
        python
    } else if cfg!(windows) {
        PathBuf::from("python")
    } else {
        PathBuf::from("python3")
    };
    let mut command = Command::new(program);
    command.arg("-m").arg("agentshelf");
    command
}

fn start_backend() -> Result<Backend, String> {
    let mut command = backend_command();
    command.arg("serve").stdout(Stdio::piped()).stderr(Stdio::inherit());
    let mut child = command.spawn().map_err(|error| format!("无法启动本地服务：{error}"))?;
    let stdout = child.stdout.take().ok_or("本地服务没有输出")?;
    let mut reader = BufReader::new(stdout);
    let started = Instant::now();
    let ready = loop {
        if started.elapsed() > Duration::from_secs(30) {
            let _ = child.kill();
            return Err("本地服务启动超时".into());
        }
        let mut line = String::new();
        let read = reader.read_line(&mut line).map_err(|error| error.to_string())?;
        if read == 0 {
            let status = child.wait().ok();
            return Err(format!("本地服务提前退出：{status:?}"));
        }
        if let Some(payload) = line.trim().strip_prefix("AGENTSHELF_READY ") {
            break serde_json::from_str::<serde_json::Value>(payload).map_err(|error| error.to_string())?;
        }
    };
    thread::spawn(move || {
        let mut rest = String::new();
        let _ = reader.read_to_string(&mut rest);
    });
    let port = ready.get("port").and_then(|value| value.as_u64()).unwrap_or(0) as u16;
    let data_dir = ready.get("data_dir").and_then(|value| value.as_str()).unwrap_or("").to_string();
    let adopted = ready.get("adopted").and_then(|value| value.as_bool()).unwrap_or(false);
    if port == 0 || data_dir.is_empty() {
        return Err("服务就绪信息不完整".into());
    }
    let token = fs::read_to_string(PathBuf::from(&data_dir).join("token"))
        .map_err(|error| format!("无法读取本地令牌：{error}"))?
        .trim()
        .to_string();
    if token.is_empty() {
        return Err("本地令牌为空".into());
    }
    Ok(Backend {
        port,
        token,
        data_dir,
        error: None,
        owned: !adopted,
        child: if adopted { None } else { Some(child) },
    })
}

fn failed(message: String) -> Backend {
    Backend {
        port: 0,
        token: String::new(),
        data_dir: String::new(),
        error: Some(message),
        owned: false,
        child: None,
    }
}

fn request_shutdown(port: u16, token: &str) {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_secs(2)) else {
        return;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    let body = b"{}";
    let header = format!(
        "POST /api/admin/shutdown HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer {token}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        body.len()
    );
    let _ = stream.write_all(header.as_bytes());
    let _ = stream.write_all(body);
    let mut buffer = [0_u8; 256];
    let _ = stream.read(&mut buffer);
}

fn terminate(child: &mut Child) {
    #[cfg(unix)]
    {
        let _ = Command::new("kill").args(["-TERM", &child.id().to_string()]).status();
        let started = Instant::now();
        while started.elapsed() < Duration::from_secs(3) {
            match child.try_wait() {
                Ok(Some(_)) => return,
                _ => thread::sleep(Duration::from_millis(80)),
            }
        }
    }
    let _ = child.kill();
    let _ = child.wait();
}

fn stop_owned(backend: &mut Backend) {
    if !backend.owned {
        return;
    }
    backend.owned = false;
    if backend.port > 0 && !backend.token.is_empty() {
        request_shutdown(backend.port, &backend.token);
    }
    if let Some(child) = backend.child.as_mut() {
        terminate(child);
    }
}

#[tauri::command]
fn backend_session(state: State<BackendState>) -> Result<SessionDto, String> {
    let guard = state.inner.lock().map_err(|_| "状态不可用".to_string())?;
    if let Some(error) = &guard.error {
        return Err(error.clone());
    }
    Ok(SessionDto {
        port: guard.port,
        token: guard.token.clone(),
        data_dir: guard.data_dir.clone(),
    })
}

#[tauri::command]
fn open_data_dir(state: State<BackendState>) -> Result<(), String> {
    let guard = state.inner.lock().map_err(|_| "状态不可用".to_string())?;
    if guard.data_dir.is_empty() {
        return Err("还没有数据目录".into());
    }
    let path = guard.data_dir.clone();
    drop(guard);
    let mut command = if cfg!(target_os = "macos") {
        let mut command = Command::new("open");
        command.arg(&path);
        command
    } else if cfg!(windows) {
        let mut command = Command::new("explorer");
        command.arg(&path);
        command
    } else {
        let mut command = Command::new("xdg-open");
        command.arg(&path);
        command
    };
    command.spawn().map_err(|error| format!("无法打开目录：{error}"))?;
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let backend = start_backend().unwrap_or_else(failed);
            app.manage(BackendState {
                inner: Mutex::new(backend),
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![backend_session, open_data_dir])
        .build(tauri::generate_context!())
        .expect("AgentShelf 桌面壳启动失败")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(state) = app.try_state::<BackendState>() {
                    if let Ok(mut guard) = state.inner.lock() {
                        stop_owned(&mut guard);
                    }
                }
            }
        });
}
