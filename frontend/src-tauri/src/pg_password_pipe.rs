//! Windows native one-shot memory-only PostgreSQL initdb password transport.
//! Uses an unguessable first-instance named pipe accepted by upstream initdb
//! --pwfile; password never goes to the command line, a disk file or stdout.
use std::{
    ffi::c_void,
    iter,
    process::{Command, Stdio},
    ptr,
    thread,
    time::{Duration, Instant},
};
use uuid::Uuid;

type Handle = *mut c_void;
const PIPE_ACCESS_OUTBOUND: u32 = 0x0000_0002;
const FILE_FLAG_FIRST_PIPE_INSTANCE: u32 = 0x0008_0000;
const PIPE_NOWAIT: u32 = 0x0000_0001;
const ERROR_PIPE_CONNECTED: u32 = 535;
const ERROR_PIPE_LISTENING: u32 = 536;
const ERROR_PIPE_BUSY: u32 = 231;

#[link(name = "Kernel32")]
extern "system" {
    fn CreateNamedPipeW(
        name: *const u16, open_mode: u32, pipe_mode: u32, max_instances: u32,
        out_buffer: u32, in_buffer: u32, default_timeout: u32,
        security: *const c_void,
    ) -> Handle;
    fn ConnectNamedPipe(pipe: Handle, overlapped: *mut c_void) -> i32;
    fn WriteFile(
        file: Handle, buffer: *const c_void, bytes: u32,
        written: *mut u32, overlapped: *mut c_void,
    ) -> i32;
    fn FlushFileBuffers(handle: Handle) -> i32;
    fn DisconnectNamedPipe(pipe: Handle) -> i32;
    fn CloseHandle(handle: Handle) -> i32;
    fn GetLastError() -> u32;
}
struct PipeHandle(Handle);
impl Drop for PipeHandle {
    fn drop(&mut self) {
        if self.0 != (-1_isize) as Handle && !self.0.is_null() {
            unsafe { CloseHandle(self.0); }
        }
    }
}

pub fn run(mut initdb: Command, password: &str) -> Result<(), &'static str> {
    if password.is_empty() || password.contains('\n') || password.contains('\r') {
        return Err("INITDB_SECRET_FORMAT_INVALID");
    }
    let name = format!(r"\\.\pipe\Yance-pg-{}", Uuid::new_v4().simple());
    let wide: Vec<u16> = name.encode_utf16().chain(iter::once(0)).collect();
    let handle = unsafe {
        CreateNamedPipeW(wide.as_ptr(), PIPE_ACCESS_OUTBOUND | FILE_FLAG_FIRST_PIPE_INSTANCE,
            PIPE_NOWAIT, 1, 512, 0, 15_000, ptr::null())
    };
    let pipe = PipeHandle(handle);
    if handle == (-1_isize) as Handle || handle.is_null() {
        return Err("INITDB_PIPE_CREATION_FAILED");
    }

    initdb.arg(format!("--pwfile={name}"))
        .stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
    let mut child = initdb.spawn().map_err(|_| "INITDB_SPAWN_FAILED")?;
    let mut connected = false;
    let deadline = Instant::now() + Duration::from_secs(15);
    while Instant::now() < deadline {
        let result = unsafe { ConnectNamedPipe(pipe.0, ptr::null_mut()) };
        let err = if result == 0 { unsafe { GetLastError() } } else { 0 };
        if result != 0 || err == ERROR_PIPE_CONNECTED {
            connected = true;
            break;
        }
        if ![ERROR_PIPE_LISTENING, ERROR_PIPE_BUSY].contains(&err) {
            break;
        }
        if child.try_wait().map_err(|_| "INITDB_WAIT_FAILED")?.is_some() {
            break;
        }
        thread::sleep(Duration::from_millis(60));
    }
    if !connected {
        let _ = child.kill();
        let _ = child.wait();
        return Err("INITDB_PIPE_NOT_OPENED");
    }
    // Client opened the random first-instance OS pipe. Only an in-memory
    // newline-terminated password is transmitted; none of these bytes are logged.
    let mut payload = password.as_bytes().to_vec();
    payload.push(b'\n');
    let mut written = 0_u32;
    let ok = unsafe {
        WriteFile(pipe.0, payload.as_ptr().cast(), payload.len() as u32,
            &mut written, ptr::null_mut())
    };
    payload.fill(0);
    if ok != 0 { unsafe { FlushFileBuffers(pipe.0); } }
    unsafe { DisconnectNamedPipe(pipe.0); }
    if ok == 0 || written == 0 {
        let _ = child.kill();
        let _ = child.wait();
        return Err("INITDB_PIPE_WRITE_FAILED");
    }
    if !child.wait().map_err(|_| "INITDB_WAIT_FAILED")?.success() {
        return Err("INITDB_FAILED");
    }
    Ok(())
}
