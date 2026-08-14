use std::{
    env, fs,
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

fn is_packaged_backend_filename(name: &str) -> bool {
    let normalized = name.to_ascii_lowercase();
    if normalized == "agentbench-backend.exe" {
        return true;
    }
    let Some(version) = normalized
        .strip_prefix("agentbench-backend-")
        .and_then(|value| value.strip_suffix(".exe"))
    else {
        return false;
    };
    !version.is_empty()
        && version.chars().any(|character| character.is_ascii_digit())
        && version
            .chars()
            .all(|character| character.is_ascii_digit() || character == '.')
}

fn cleanup_obsolete_backends(resource_dir: &Path) {
    let Some(current) = packaged_backend(resource_dir) else {
        return;
    };
    let Some(backend_dir) = current.parent() else {
        return;
    };
    let Ok(entries) = fs::read_dir(backend_dir) else {
        return;
    };

    for entry in entries.flatten() {
        let path = entry.path();
        if path == current || !path.is_file() {
            continue;
        }
        let Some(name) = path.file_name().and_then(|value| value.to_str()) else {
            continue;
        };
        if is_packaged_backend_filename(name) {
            let _ = fs::remove_file(path);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{is_packaged_backend_filename, resolve_workspace_folder};
    use std::{
        env, fs,
        time::{SystemTime, UNIX_EPOCH},
    };

    #[test]
    fn recognizes_only_release_sidecar_names() {
        assert!(is_packaged_backend_filename("agentbench-backend.exe"));
        assert!(is_packaged_backend_filename("agentbench-backend-3.1.1.exe"));
        assert!(is_packaged_backend_filename("AgentBench-Backend-4.0.0.EXE"));
        assert!(!is_packaged_backend_filename(
            "agentbench-backend-backup.exe"
        ));
        assert!(!is_packaged_backend_filename("unrelated.exe"));
    }

    #[test]
    fn validates_workspace_folders_before_launching_explorer() {
        assert_eq!(
            resolve_workspace_folder("  ").unwrap_err(),
            "Workspace path is empty"
        );

        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock")
            .as_nanos();
        let root = env::temp_dir().join(format!("agentbench-open-folder-{unique}"));
        fs::create_dir(&root).expect("create test workspace");
        let resolved = resolve_workspace_folder(root.to_str().expect("utf-8 path"))
            .expect("existing directory should be accepted");
        assert!(resolved.is_absolute());
        assert!(resolved.is_dir());
        assert!(!resolved.to_string_lossy().starts_with(r"\\?\"));

        let file = root.join("artifact.txt");
        fs::write(&file, "test").expect("create test artifact");
        assert_eq!(
            resolve_workspace_folder(file.to_str().expect("utf-8 path")).unwrap_err(),
            "Workspace path is not a directory"
        );
        fs::remove_dir_all(root).expect("remove test workspace");
    }
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

fn terminate_confirmed_backend(expect_current_version: bool) -> Result<(), String> {
    let rejected_version_operator = if expect_current_version { "-ne" } else { "-eq" };
    let script = format!(
        concat!(
            "$ErrorActionPreference='Stop'; ",
            "$health=Invoke-RestMethod -Uri 'http://127.0.0.1:43765/api/v1/health' -TimeoutSec 2; ",
            "if ($health.name -ne 'AgentBench Desktop' -or $health.version {} '{}') ",
            "{{ throw 'Backend identity/version no longer matches' }}; ",
            "$owners=Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 43765 -State Listen ",
            "| Select-Object -ExpandProperty OwningProcess -Unique; ",
            "foreach ($owner in $owners) {{ $process=Get-Process -Id $owner -ErrorAction Stop; ",
            "if ($process.Path -notlike '*agentbench-backend*.exe') {{ throw 'Listener is not an AgentBench sidecar' }}; ",
            "Stop-Process -Id $owner -Force }}"
        ),
        rejected_version_operator,
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
    Err("The confirmed AgentBench sidecar is still listening on port 43765".into())
}

fn terminate_confirmed_old_backend() -> Result<(), String> {
    terminate_confirmed_backend(false)
}

fn terminate_confirmed_current_backend() -> Result<(), String> {
    terminate_confirmed_backend(true)
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
            // PyInstaller one-file executables can hand the listening server to an
            // extracted child process. Close the verified listener as well as the
            // original process handle so the port cannot outlive the desktop app.
            let _ = terminate_confirmed_current_backend();
            let _ = child.kill();
            let _ = child.wait();
        }
    };
}

fn resolve_workspace_folder(path: &str) -> Result<PathBuf, String> {
    let trimmed = path.trim();
    if trimmed.is_empty() {
        return Err("Workspace path is empty".into());
    }
    let resolved = PathBuf::from(trimmed)
        .canonicalize()
        .map_err(|error| format!("Workspace path does not exist or cannot be accessed: {error}"))?;
    if !resolved.is_dir() {
        return Err("Workspace path is not a directory".into());
    }
    // Windows canonicalization commonly adds an extended-length `\\?\` prefix.
    // Filesystem APIs accept it, but Explorer can reject that spelling for an
    // otherwise valid directory, so convert it back to a shell-friendly path.
    let display = resolved.to_string_lossy();
    if let Some(unc) = display.strip_prefix(r"\\?\UNC\") {
        return Ok(PathBuf::from(format!(r"\\{unc}")));
    }
    if let Some(local) = display.strip_prefix(r"\\?\") {
        return Ok(PathBuf::from(local));
    }
    Ok(resolved)
}

#[tauri::command]
fn open_workspace_folder(path: String) -> Result<(), String> {
    let resolved = resolve_workspace_folder(&path)?;
    Command::new("explorer.exe")
        .arg(resolved)
        .creation_flags(CREATE_NO_WINDOW)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|error| format!("Could not open workspace in Windows Explorer: {error}"))?;
    Ok(())
}

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![open_workspace_folder])
        .setup(|app| {
            let backend = ensure_backend(app).map_err(std::io::Error::other)?;
            if let Ok(resource_dir) = app.path().resource_dir() {
                cleanup_obsolete_backends(&resource_dir);
            }
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
