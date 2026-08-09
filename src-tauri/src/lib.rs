use std::{
    env,
    io::{Read, Write},
    net::{SocketAddr, TcpStream},
    os::windows::process::CommandExt,
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Mutex,
    thread,
    time::Duration,
};
use tauri::{Manager, RunEvent};

const BACKEND_ADDRESS: &str = "127.0.0.1:43765";
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

struct BackendProcess(Mutex<Option<Child>>);

#[derive(Debug, PartialEq)]
enum EndpointState {
    Absent,
    Current,
    Older(String),
    Foreign,
}

fn packaged_backend(resource_dir: &Path) -> Option<PathBuf> {
    let filename = format!("agentbench-backend-{}.exe", env!("CARGO_PKG_VERSION"));
    let candidate = resource_dir
        .join("resources")
        .join("backend")
        .join(filename);
    candidate.is_file().then_some(candidate)
}

fn development_python() -> Option<PathBuf> {
    if let Ok(configured) = env::var("AGENTBENCH_PYTHON") {
        let path = PathBuf::from(configured);
        if path.is_file() {
            return Some(path);
        }
    }
    let workspace = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..");
    let candidate = workspace.join(".venv").join("Scripts").join("python.exe");
    candidate.is_file().then_some(candidate)
}

fn json_string_field(body: &str, field: &str) -> Option<String> {
    let marker = format!("\"{field}\"");
    let tail = body.get(body.find(&marker)? + marker.len()..)?;
    let value = tail.get(tail.find(':')? + 1..)?.trim_start();
    let quoted = value.strip_prefix('"')?;
    Some(quoted.get(..quoted.find('"')?)?.to_string())
}

fn endpoint_state() -> EndpointState {
    let Ok(address) = BACKEND_ADDRESS.parse::<SocketAddr>() else {
        return EndpointState::Foreign;
    };
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(300)) else {
        return EndpointState::Absent;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(800)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(800)));
    if stream
        .write_all(b"GET /api/v1/health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        .is_err()
    {
        return EndpointState::Foreign;
    }
    let mut response = String::new();
    if stream.read_to_string(&mut response).is_err() || !response.starts_with("HTTP/1.1 200") {
        return EndpointState::Foreign;
    }
    let body = response.split_once("\r\n\r\n").map_or("", |(_, body)| body);
    if json_string_field(body, "name").as_deref() != Some("AgentBench Desktop") {
        return EndpointState::Foreign;
    }
    let version = json_string_field(body, "version").unwrap_or_default();
    if version == env!("CARGO_PKG_VERSION") {
        EndpointState::Current
    } else {
        EndpointState::Older(version)
    }
}

fn terminate_confirmed_old_backend() -> Result<(), String> {
    let script = format!(
        concat!(
            "$ErrorActionPreference='Stop'; ",
            "$health=Invoke-RestMethod -Uri 'http://127.0.0.1:43765/api/v1/health' -TimeoutSec 2; ",
            "if ($health.name -ne 'AgentBench Desktop' -or $health.version -eq '{}') ",
            "{{ throw 'Backend identity/version no longer matches' }}; ",
            "$owners=Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 43765 -State Listen ",
            "| Select-Object -ExpandProperty OwningProcess -Unique; ",
            "foreach ($owner in $owners) {{ $process=Get-Process -Id $owner -ErrorAction Stop; ",
            "if ($process.Path -notlike '*agentbench-backend*.exe') {{ throw 'Listener is not an AgentBench sidecar' }}; ",
            "Stop-Process -Id $owner -Force }}"
        ),
        env!("CARGO_PKG_VERSION")
    );
    let status = Command::new("powershell.exe")
        .args(["-NoProfile", "-NonInteractive", "-Command", &script])
        .creation_flags(CREATE_NO_WINDOW)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map_err(|error| format!("Could not inspect the old AgentBench sidecar: {error}"))?;
    if !status.success() {
        return Err(
            "The old AgentBench sidecar was confirmed but could not be stopped safely".into(),
        );
    }
    for _ in 0..30 {
        if endpoint_state() == EndpointState::Absent {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(100));
    }
    Err("The old AgentBench sidecar is still listening on port 43765".into())
}

fn backend_command(app: &tauri::App) -> Result<Command, String> {
    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|error| format!("Cannot resolve resource directory: {error}"))?;
    let mut command = if let Some(binary) = packaged_backend(&resource_dir) {
        Command::new(binary)
    } else if let Some(python) = development_python() {
        let mut development = Command::new(python);
        development.arg("-m").arg("agentbench");
        development
    } else {
        return Err(
            "AgentBench backend was not packaged and no development Python was found".to_string(),
        );
    };
    command
        .creation_flags(CREATE_NO_WINDOW)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    Ok(command)
}

fn ensure_backend(app: &tauri::App) -> Result<Option<Child>, String> {
    match endpoint_state() {
        EndpointState::Current => return Ok(None),
        EndpointState::Older(_) => terminate_confirmed_old_backend()?,
        EndpointState::Foreign => {
            return Err(
                "Port 43765 is occupied by a service that is not the current AgentBench backend"
                    .into(),
            )
        }
        EndpointState::Absent => {}
    }
    let mut child = backend_command(app)?
        .spawn()
        .map_err(|error| format!("Could not start AgentBench backend: {error}"))?;
    for _ in 0..150 {
        match endpoint_state() {
            EndpointState::Current => return Ok(Some(child)),
            EndpointState::Foreign | EndpointState::Older(_) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err("A different backend claimed port 43765 during startup".into());
            }
            EndpointState::Absent => {}
        }
        if let Ok(Some(status)) = child.try_wait() {
            return Err(format!(
                "AgentBench backend exited during startup: {status}"
            ));
        }
        thread::sleep(Duration::from_millis(100));
    }
    let _ = child.kill();
    let _ = child.wait();
    Err("AgentBench backend did not become healthy within 15 seconds".into())
}

fn stop_backend(app_handle: &tauri::AppHandle) {
    let state = app_handle.state::<BackendProcess>();
    if let Ok(mut guard) = state.0.lock() {
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    };
}

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            let backend = ensure_backend(app).map_err(std::io::Error::other)?;
            app.manage(BackendProcess(Mutex::new(backend)));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building AgentBench Desktop");

    app.run(|app_handle, event| {
        if matches!(event, RunEvent::Exit | RunEvent::ExitRequested { .. }) {
            stop_backend(app_handle);
        }
    });
}
