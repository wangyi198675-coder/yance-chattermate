//! Windows-only thin lifecycle bridge. Process Compose is the *only* process supervisor.
//! This module stages its configuration, runs the official binary, gates readiness,
//! and requests shutdown. It does not replace PostgreSQL, Garnet or ChatterMate.
use base64::{engine::general_purpose::URL_SAFE, Engine as _};
use std::{
    fs,
    io::{Read, Write},
    net::{SocketAddr, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::{
        atomic::{AtomicBool, Ordering},
        Mutex, OnceLock,
    },
    thread,
    time::{Duration, Instant},
};
use tauri::Manager;
use uuid::Uuid;

const API_PORT: u16 = 8000; // The shipped frontend/dist/config.js binds this origin.
const PG_PORT: u16 = 55435;
const GARNET_PORT: u16 = 56355;
const PC_PORT: u16 = 58355;
const START_TIMEOUT: Duration = Duration::from_secs(150);
const LOCALHOST: &str = "127.0.0.1";

static ACTIVE: AtomicBool = AtomicBool::new(false);
static STOPPING: AtomicBool = AtomicBool::new(false);
static CHILD: OnceLock<Mutex<Option<Child>>> = OnceLock::new();
static PATHS: OnceLock<Mutex<Option<Paths>>> = OnceLock::new();

#[derive(Clone)]
struct Paths {
    bundle: PathBuf,
    state: PathBuf,
    backend: PathBuf,
    compose: PathBuf,
    supervisor: PathBuf,
}

impl Paths {
    fn resolve() -> Result<Self, &'static str> {
        // Never infer a user's data directory from a Velopack install directory.
        let bundle = std::env::current_exe()
            .map_err(|_| "EXE_PATH")?
            .parent().ok_or("EXE_PARENT")?.to_path_buf();
        let state = {
            #[cfg(debug_assertions)]
            {
                if let Some(qa) = std::env::var_os("YANCE_W355_QA_DATA_ROOT") {
                    let p = PathBuf::from(qa);
                    if !p.is_absolute() || p == bundle { return Err("BAD_QA_DATA_ROOT"); }
                    p
                } else { regular_state()? }
            }
            #[cfg(not(debug_assertions))]
            { regular_state()? }
        };
        let backend = bundle.join("backend");
        let runtime = bundle.join("private-runtime");
        let supervisor = runtime.join("process-compose").join("process-compose.exe");
        for relative in [
            Path::new("process-compose/process-compose.exe"),
            Path::new("postgresql/bin/postgres.exe"),
            Path::new("postgresql/bin/initdb.exe"),
            Path::new("postgresql/bin/createdb.exe"),
            Path::new("python/python.exe"),
            Path::new("garnet/GarnetServer.exe"),
        ] {
            if !runtime.join(relative).is_file() { return Err("MISSING_PRIVATE_COMPONENT"); }
        }
        if !backend.join("app").join("main.py").is_file() { return Err("MISSING_BACKEND"); }
        if state.starts_with(&bundle) { return Err("IMMUTABLE_BUNDLE_DATA_ROOT"); }
        // Legacy pre-rebuild user data is never silently copied or overwritten.
        // A separately authorized import must be completed before fresh release
        // initialization on machines with the historical Yance controller root.
        #[cfg(not(debug_assertions))]
        if !state.join("postgres-data").exists() {
            let legacy = Path::new(r"C:\YanceController\current-user-data");
            if legacy.is_dir() && legacy.read_dir().is_ok_and(|mut x| x.next().is_some()) {
                return Err("LEGACY_DATA_IMPORT_REQUIRES_APPROVAL");
            }
        }
        crate::dpapi::secure_root(&state)?;
        Ok(Self {
            bundle, state: state.clone(), backend,
            compose: state.join("runtime-process-compose.yaml"), supervisor,
        })
    }
    fn runtime(&self) -> PathBuf { self.bundle.join("private-runtime") }
    fn pg(&self) -> PathBuf { self.runtime().join("postgresql").join("bin") }
    fn python(&self) -> PathBuf { self.runtime().join("python").join("python.exe") }
}

fn regular_state() -> Result<PathBuf, &'static str> {
    let local = std::env::var_os("LOCALAPPDATA").ok_or("NO_LOCALAPPDATA")?;
    // Frozen Windows product authority: one durable per-user data root.
    Ok(PathBuf::from(local).join("Yance").join("data"))
}

struct Secrets { db: String, jwt: String, conversation: String, fernet: String }
fn new_uuid() -> String { Uuid::new_v4().simple().to_string() }

fn load_or_create_secrets(root: &Path) -> Result<Secrets, &'static str> {
    let value = crate::dpapi::load_or_create(root, || {
        // CSPRNG-backed OS UUIDs; plaintext exists only in process memory.
        let mut key = [0_u8; 32];
        key[..16].copy_from_slice(Uuid::new_v4().as_bytes());
        key[16..].copy_from_slice(Uuid::new_v4().as_bytes());
        let value = format!("{}\n{}{}\n{}{}\n{}",
            new_uuid(), new_uuid(), new_uuid(), new_uuid(), new_uuid(), URL_SAFE.encode(key));
        key.fill(0);
        value
    })?;
    let parts: Vec<&str> = value.lines().collect();
    if parts.len() != 4 || parts.iter().any(|s| s.len() < 30) {
        return Err("DPAPI_SECRET_LAYOUT_INVALID");
    }
    Ok(Secrets {
        db: parts[0].into(), jwt: parts[1].into(),
        conversation: parts[2].into(), fernet: parts[3].into(),
    })
}

fn free_port(port: u16) -> bool {
    std::net::TcpListener::bind((LOCALHOST, port)).is_ok()
}
fn connected(port: u16) -> bool {
    let a = SocketAddr::from(([127, 0, 0, 1], port));
    TcpStream::connect_timeout(&a, Duration::from_millis(600)).is_ok()
}
fn http_ok(path: &str) -> bool {
    let a = SocketAddr::from(([127, 0, 0, 1], API_PORT));
    if let Ok(mut stream) = TcpStream::connect_timeout(&a, Duration::from_millis(1000)) {
        let _ = stream.set_read_timeout(Some(Duration::from_millis(1000)));
        let req = format!("GET {} HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nConnection: close\r\n\r\n", path, API_PORT);
        if stream.write_all(req.as_bytes()).is_ok() {
            let mut data = [0u8; 1024];
            if let Ok(n) = stream.read(&mut data) {
                return String::from_utf8_lossy(&data[..n]).starts_with("HTTP/1.1 200")
                    || String::from_utf8_lossy(&data[..n]).starts_with("HTTP/1.0 200");
            }
        }
    }
    false
}

// YAML double-quoted string using Rust debug escaping; paths are absolute Windows paths.
fn yaml(v: impl AsRef<str>) -> String { format!("{:?}", v.as_ref().replace('\\', "/")) }

fn compose_yaml(p: &Paths) -> String {
    let pg = p.pg().join("postgres.exe");
    let pgdata = p.state.join("postgres-data");
    let garnet = p.runtime().join("garnet").join("GarnetServer.exe");
    let garconf = p.state.join("garnet.conf");
    let python = p.python();
    let entries = [
        ("postgres", vec![pg.to_string_lossy().into_owned(), "-D".into(), pgdata.to_string_lossy().into_owned(), "-h".into(), LOCALHOST.into(), "-p".into(), PG_PORT.to_string()], p.pg()),
        ("garnet", vec![garnet.to_string_lossy().into_owned(), "--config-import-path".into(), garconf.to_string_lossy().into_owned()], p.state.clone()),
        ("api", vec![python.to_string_lossy().into_owned(), "-m".into(), "uvicorn".into(), "app.main:app".into(), "--host".into(), LOCALHOST.into(), "--port".into(), API_PORT.to_string(), "--workers".into(), "1".into()], p.backend.clone()),
        ("knowledge", vec![python.to_string_lossy().into_owned(), "-m".into(), "app.workers.knowledge_processor".into()], p.backend.clone()),
    ];
    let mut result = String::from("version: \"0.5\"\nis_strict: true\nordered_shutdown: true\nprocesses:\n");
    for (name, args, workdir) in entries {
        result += &format!("  {name}:\n    entrypoint:\n");
        for arg in args { result += &format!("      - {}\n", yaml(&arg)); }
        result += &format!(
            "    working_dir: {}\n    availability:\n      restart: \"always\"\n      backoff_seconds: 2\n    shutdown:\n      signal: 2\n      timeout_seconds: 40\n",
            yaml(workdir.to_string_lossy()));
    }
    result
}

fn common_env(cmd: &mut Command, p: &Paths, s: &Secrets) {
    cmd.env("DATABASE_URL", format!("postgresql+psycopg://yance:{}@{}:{}/yance", s.db, LOCALHOST, PG_PORT))
        .env("PGPASSWORD", &s.db)
        .env("JWT_SECRET_KEY", &s.jwt)
        .env("CONVERSATION_SECRET_KEY", &s.conversation)
        .env("ENCRYPTION_KEY", &s.fernet)
        .env("YANCE_DATA_ROOT", &p.state)
        .env("REDIS_URL", format!("redis://{}:{}/0", LOCALHOST, GARNET_PORT))
        .env("REDIS_ENABLED", "true")
        .env("FRONTEND_URL", "http://tauri.localhost")
        .env("CORS_ORIGINS", r#"["http://tauri.localhost","tauri://localhost","http://localhost:1420","http://127.0.0.1:8000"]"#)
        .env("PYTHONUTF8", "1")
        .env("PYTHONUNBUFFERED", "1")
        .env("DOTNET_ROOT", p.runtime().join("dotnet"))
        .env("PYTHONPATH", p.backend.as_os_str())
        .env("PATH", format!("{};{};{}", p.pg().display(), p.runtime().join("dotnet").display(), std::env::var("PATH").unwrap_or_default()));
}

fn quiet(cmd: &mut Command) -> &mut Command {
    cmd.stdout(Stdio::null()).stderr(Stdio::null()).stdin(Stdio::null())
}
fn successful(mut cmd: Command) -> Result<(), &'static str> {
    let status = quiet(&mut cmd).status().map_err(|_| "CHILD_PROCESS_LAUNCH_FAILED")?;
    if !status.success() { return Err("CHILD_PROCESS_FAILED"); }
    Ok(())
}

fn init_postgres(p: &Paths, s: &Secrets) -> Result<bool, &'static str> {
    let data = p.state.join("postgres-data");
    if data.join("PG_VERSION").is_file() { return Ok(false); }
    if data.exists() { return Err("PARTIAL_PG_DATA_REQUIRES_SAFE_RECOVERY"); }
    // Upstream PostgreSQL accepts --pwfile from a Windows named pipe; use its
    // own initdb and an ephemeral unguessable first-instance OS pipe.
    // No plaintext password file or local trust authentication is introduced.
    let mut init = Command::new(p.pg().join("initdb.exe"));
    init.args(["-D", &data.to_string_lossy(), "-U", "yance",
        "--auth-host=scram-sha-256", "--auth-local=scram-sha-256",
        "--encoding=UTF8"]);
    common_env(&mut init, p, s);
    crate::pg_password_pipe::run(init, &s.db)?;
    Ok(true)
}

fn wait_pg(p: &Paths, s: &Secrets, until: Instant) -> Result<(), &'static str> {
    while Instant::now() < until && !STOPPING.load(Ordering::SeqCst) {
        if CHILD.get().and_then(|v| v.lock().ok()).and_then(|mut g| g.as_mut().and_then(|c| c.try_wait().ok().flatten())).is_some() {
            return Err("SUPERVISOR_EXITED");
        }
        let mut cmd = Command::new(p.pg().join("pg_isready.exe"));
        cmd.args(["-h", LOCALHOST, "-p", &PG_PORT.to_string(), "-U", "yance"]);
        common_env(&mut cmd, p, s);
        if quiet(&mut cmd).status().is_ok_and(|x| x.success()) { return Ok(()); }
        thread::sleep(Duration::from_millis(600));
    }
    Err("POSTGRES_NOT_READY")
}

fn migrate(p: &Paths, s: &Secrets, _new_db: bool) -> Result<(), &'static str> {
    // PG_VERSION alone does not prove the application database exists: a crash
    // between initdb and createdb must be safely recoverable on next launch.
    let mut probe = Command::new(p.pg().join("psql.exe"));
    probe.args(["-h", LOCALHOST, "-p", &PG_PORT.to_string(), "-U", "yance",
        "-d", "postgres", "-t", "-A", "-c", "SELECT 1 FROM pg_database WHERE datname = 'yance'"]);
    common_env(&mut probe, p, s);
    let output = probe.stdout(Stdio::piped()).stderr(Stdio::null()).stdin(Stdio::null())
        .output().map_err(|_| "PG_DATABASE_PROBE_FAILED")?;
    if !output.status.success() { return Err("PG_DATABASE_PROBE_FAILED"); }
    if String::from_utf8_lossy(&output.stdout).trim() != "1" {
        let mut create = Command::new(p.pg().join("createdb.exe"));
        create.args(["-h", LOCALHOST, "-p", &PG_PORT.to_string(), "-U", "yance", "yance"]);
        common_env(&mut create, p, s);
        successful(create).map_err(|_| "CREATE_DATABASE_FAILED")?;
    }
    let mut alembic = Command::new(p.python());
    alembic.current_dir(&p.backend).args(["-m", "alembic", "upgrade", "head"]);
    common_env(&mut alembic, p, s);
    let output = alembic.stdout(Stdio::null()).stderr(Stdio::piped()).output()
        .map_err(|_| "ALEMBIC_START_FAILED")?;
    if !output.status.success() {
        #[cfg(debug_assertions)] {
            // Never write raw stderr: connection URLs and secrets may be included.
            let diagnostic = String::from_utf8_lossy(&output.stderr);
            let kinds = ["ModuleNotFoundError", "ImportError", "OperationalError",
                "ProgrammingError", "ValueError", "UndefinedTable", "UndefinedColumn",
                "KeyError", "RuntimeError", "Error", "NoSuchModuleError",
                "password authentication failed", "database \"yance\" does not exist",
                "Connection refused", "could not connect", "server closed the connection",
                "connection to server", "No module named", "extension \"vector\"",
                "no such file or directory", "FATAL"];
            let matched: Vec<&str> = kinds.iter().copied()
                .filter(|name| diagnostic.contains(name)).collect();
            let clues = ["password authentication failed", "does not exist", "connection refused",
                "Connection refused", "system is starting up", "timeout expired", "could not connect",
                "could not translate host", "closed the connection", "no pg_hba.conf entry",
                "permission denied", "extension", "FATAL", "connection failed", "No module named",
                "5432", "55435", "localhost", "127.0.0.1", "actively refused", "password",
                "authentication", "no password supplied", "server at", "could not resolve",
                "invalid port", "network unreachable", "Error 10061"];
            let safe_clues: Vec<&str> = clues.iter().copied()
                .filter(|c| diagnostic.contains(c)).collect();
            let _ = fs::write(p.state.join("qa-alembic-class.txt"),
                format!("types={}; clues={}; pc={}; pg={}", matched.join(","), safe_clues.join(","),
                    connected(PC_PORT), connected(PG_PORT)));
        }
        return Err("ALEMBIC_MIGRATION_FAILED");
    }
    Ok(())
}

fn status(p: &Paths, label: &str) {
    let _ = fs::write(p.state.join("startup-status.txt"), label.as_bytes());
}

fn start() -> Result<(), &'static str> {
    let p = Paths::resolve()?;
    *PATHS.get_or_init(|| Mutex::new(None)).lock().map_err(|_| "PATH_STATE")? = Some(p.clone());
    status(&p, "PREPARING");
    // If another service owns any fixed port, fail closed rather than adopt its HTTP /health.
    for port in [API_PORT, PG_PORT, GARNET_PORT, PC_PORT] {
        if !free_port(port) { status(&p, "PORT_OCCUPIED"); return Err("PORT_OCCUPIED"); }
    }
    crate::dpapi::secure_root(&p.state)?;
    let s = load_or_create_secrets(&p.state)?;
    status(&p, "INITIALIZING_PRIVATE_POSTGRES");
    let new_pg = init_postgres(&p, &s)?;
    fs::write(p.state.join("garnet.conf"), format!(
        "{{\n  \"Port\": {},\n  \"Address\": \"{}\"\n}}\n", GARNET_PORT, LOCALHOST
    )).map_err(|_| "GARNET_CONFIG_WRITE")?;
    fs::write(&p.compose, compose_yaml(&p)).map_err(|_| "COMPOSE_CONFIG_WRITE")?;
    status(&p, "STARTING_OFFICIAL_PROCESS_COMPOSE");
    let mut pc = Command::new(&p.supervisor);
    pc.args(["up", "postgres", "garnet", "--disable-dotenv", "-t=false", "-f", &p.compose.to_string_lossy(),
             "-p", &PC_PORT.to_string(), "--address", LOCALHOST, "--ordered-shutdown"]);
    common_env(&mut pc, &p, &s);
    pc.env("PC_LOG_FILE", p.state.join("process-compose-runtime.log"));
    let child = quiet(&mut pc).spawn().map_err(|_| "COMPOSE_SPAWN")?;
    *CHILD.get_or_init(|| Mutex::new(None)).lock().map_err(|_| "CHILD_LOCK")? = Some(child);
    let until = Instant::now() + START_TIMEOUT;
    status(&p, "WAITING_POSTGRES");
    wait_pg(&p, &s, until)?;
    if STOPPING.load(Ordering::SeqCst) { return Err("CANCELLED"); }
    status(&p, "MIGRATING_CANONICAL_ALEMBIC");
    migrate(&p, &s, new_pg)?;
    status(&p, "STARTING_NATIVE_API_AND_KNOWLEDGE");
    for service in ["api", "knowledge"] {
        let mut start = Command::new(&p.supervisor);
        start.args(["process", "start", service, "-p", &PC_PORT.to_string(), "-a", LOCALHOST]);
        common_env(&mut start, &p, &s);
        successful(start).map_err(|_| "COMPOSE_NATIVE_SERVICE_START_FAILED")?;
    }
    status(&p, "WAITING_NATIVE_API_AND_SETUP");
    while Instant::now() < until && !STOPPING.load(Ordering::SeqCst) {
        if !connected(PC_PORT) { return Err("SUPERVISOR_EXITED"); }
        if http_ok("/health") && http_ok("/api/v1/organizations/setup-status") {
            status(&p, "READY");
            return Ok(());
        }
        thread::sleep(Duration::from_millis(850));
    }
    Err("BACKEND_OR_BOOTSTRAP_NOT_READY")
}

fn transition(app: &tauri::AppHandle, ready: bool) {
    if let Some(window) = app.get_webview_window("main") {
        if ready {
            // Vue's own route guard performs authorized private bootstrap.
            let _ = window.eval("window.location.replace('/yance')");
        } else {
            let _ = window.eval("window.location.replace('/yance/startup?state=BACKEND_UNAVAILABLE')");
        }
    }
}
pub fn launch(app: tauri::AppHandle) {
    if STOPPING.load(Ordering::SeqCst) ||
        ACTIVE.compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst).is_err() {
        return;
    }
    thread::spawn(move || {
        match start() {
            Ok(()) => transition(&app, true),
            Err(code) => {
                #[cfg(debug_assertions)]
                if let Some(root) = std::env::var_os("YANCE_W355_QA_DATA_ROOT") {
                    let root = PathBuf::from(root);
                    let _ = fs::create_dir_all(&root);
                    let _ = fs::write(root.join("qa-early-error.txt"), code);
                }
                if let Some(p) = PATHS.get().and_then(|v| v.lock().ok()).and_then(|v| v.clone()) {
                    status(&p, code);
                }
                cleanup();
                if !STOPPING.load(Ordering::SeqCst) { transition(&app, false); }
                ACTIVE.store(false, Ordering::SeqCst);
            }
        }
    });
}
fn cleanup() {
    let p = PATHS.get().and_then(|v| v.lock().ok()).and_then(|v| v.clone());
    if let Some(p) = p {
        // Official v1.122.0 Windows shutdown is known to force-kill children.
        // This is an explicit release HOLD, not a claim of graceful shutdown.
        if connected(PC_PORT) {
            let mut down = Command::new(&p.supervisor);
            down.args(["down", "-p", &PC_PORT.to_string(), "--address", LOCALHOST]);
            let _ = quiet(&mut down).status();
        }
    }
    if let Some(v) = CHILD.get() {
        if let Ok(mut guard) = v.lock() {
            if let Some(mut child) = guard.take() {
                if child.try_wait().ok().flatten().is_none() {
                    let _ = child.kill(); // Supervisor only; Process Compose owns children.
                }
                let _ = child.wait();
            }
        }
    }
}
pub fn stop() {
    STOPPING.store(true, Ordering::SeqCst);
    cleanup();
    if let Some(p) = PATHS.get().and_then(|v| v.lock().ok()).and_then(|v| v.clone()) {
        status(&p, "STOPPED_OFFICIAL_WINDOWS_GRACEFUL_STOP_HOLD");
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn yaml_does_not_contain_secrets_or_global_runtime_paths() {
        let p = Paths {
            bundle: PathBuf::from(r"C:\Program Files\Yance"),
            state: PathBuf::from(r"C:\Users\Test\AppData\Local\Yance\desktop-state"),
            backend: PathBuf::from(r"C:\Program Files\Yance\backend"),
            compose: PathBuf::new(),
            supervisor: PathBuf::new(),
        };
        let config = compose_yaml(&p);
        for expected in ["postgres:", "garnet:", "api:", "knowledge:",
            "127.0.0.1", "ordered_shutdown: true", "PG_VERSION"] {
            if expected == "PG_VERSION" { assert!(!config.contains(expected)); }
            else { assert!(config.contains(expected), "missing {expected}"); }
        }
        assert!(!config.contains("SECRET_KEY"));
        assert!(!config.contains("password"));
    }
    #[test] fn immutable_paths_are_separate() {
        let a = PathBuf::from(r"C:\Program Files\Yance");
        let b = PathBuf::from(r"C:\Users\Person\AppData\Local\Yance\desktop-state");
        assert!(!b.starts_with(a));
    }
}
