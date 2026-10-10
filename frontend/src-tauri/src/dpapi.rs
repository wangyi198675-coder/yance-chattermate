//! Per-Windows-user Data Protection API custody for the native private runtime.
//! No key material is persisted as plaintext. DPAPI is the sole credential owner.
use std::{
    ffi::c_void,
    fs::{self, OpenOptions},
    io::Write,
    path::Path,
    process::{Command, Stdio},
};
#[repr(C)]
struct DataBlob {
    size: u32,
    data: *mut u8,
}
#[link(name = "Crypt32")]
extern "system" {
    fn CryptProtectData(
        input: *const DataBlob, description: *const u16, entropy: *const DataBlob,
        reserved: *mut c_void, prompt: *mut c_void,
        flags: u32, output: *mut DataBlob,
    ) -> i32;
    fn CryptUnprotectData(
        input: *const DataBlob, description: *mut *mut u16, entropy: *const DataBlob,
        reserved: *mut c_void, prompt: *mut c_void,
        flags: u32, output: *mut DataBlob,
    ) -> i32;
}
#[link(name = "Kernel32")]
extern "system" {
    fn LocalFree(ptr: *mut c_void) -> *mut c_void;
}
const UI_FORBIDDEN: u32 = 1;
const DOMAIN: &[u8] = b"YANCE-DESKTOP-PER-USER-CREDENTIALS-V1";
const HEADER: &[u8] = b"YANCE-DPAPI-V1\0";

fn protect_or_unprotect(bytes: &[u8], protect: bool) -> Result<Vec<u8>, &'static str> {
    if bytes.is_empty() || bytes.len() > 4096 { return Err("DPAPI_BAD_INPUT_LENGTH"); }
    // CryptProtectData never stores an application master secret; it uses the
    // logged-in Windows user's OS-managed DPAPI master key.
    let mut input_data = bytes.to_vec();
    let mut entropy_data = DOMAIN.to_vec();
    let input = DataBlob { size: input_data.len() as u32, data: input_data.as_mut_ptr() };
    let entropy = DataBlob { size: entropy_data.len() as u32, data: entropy_data.as_mut_ptr() };
    let mut output = DataBlob { size: 0, data: std::ptr::null_mut() };
    let succeeded = unsafe {
        if protect {
            CryptProtectData(&input, std::ptr::null(), &entropy, std::ptr::null_mut(),
                std::ptr::null_mut(), UI_FORBIDDEN, &mut output)
        } else {
            CryptUnprotectData(&input, std::ptr::null_mut(), &entropy, std::ptr::null_mut(),
                std::ptr::null_mut(), UI_FORBIDDEN, &mut output)
        }
    };
    input_data.fill(0);
    if succeeded == 0 || output.data.is_null() || output.size == 0 || output.size > 8192 {
        if !output.data.is_null() { unsafe { LocalFree(output.data.cast()); } }
        return Err("DPAPI_CURRENT_USER_UNAVAILABLE_OR_CIPHERTEXT_INVALID");
    }
    let copy = unsafe { std::slice::from_raw_parts(output.data, output.size as usize).to_vec() };
    unsafe { LocalFree(output.data.cast()); }
    Ok(copy)
}
fn current_user_sid() -> Result<String, &'static str> {
    let out = Command::new("whoami.exe").args(["/user", "/fo", "csv", "/nh"])
        .stdout(Stdio::piped()).stderr(Stdio::null())
        .output().map_err(|_| "SID_QUERY_FAILED")?;
    if !out.status.success() { return Err("SID_QUERY_FAILED"); }
    let source = String::from_utf8_lossy(&out.stdout);
    let sid = source.trim().trim_end_matches('"').rsplit(',').next()
        .unwrap_or("").trim().trim_matches('"').to_owned();
    if !sid.starts_with("S-1-") || !sid[4..].chars().all(|ch| ch.is_ascii_digit() || ch == '-') {
        return Err("SID_FORMAT_INVALID");
    }
    Ok(sid)
}
fn restrict_access(path: &Path, dir: bool) -> Result<(), &'static str> {
    let user = current_user_sid()?;
    let grant = if dir { format!("*{user}:(OI)(CI)F") } else { format!("*{user}:F") };
    let system = if dir { "*S-1-5-18:(OI)(CI)F" } else { "*S-1-5-18:F" };
    let out = Command::new("icacls.exe").arg(path)
        // Removes inherited broad grants; restrict to the exact logged-in SID
        // and SYSTEM. No shell interpolation, no credential values in args.
        .args(["/inheritance:r", "/grant:r"]).arg(grant).arg(system)
        .stdout(Stdio::null()).stderr(Stdio::null())
        .status().map_err(|_| "DPAPI_ACL_COMMAND_UNAVAILABLE")?;
    if !out.success() { return Err("DPAPI_ACL_RESTRICTION_FAILED"); }
    Ok(())
}
pub fn secure_root(root: &Path) -> Result<(), &'static str> {
    fs::create_dir_all(root).map_err(|_| "USER_DATA_ROOT_UNWRITABLE")?;
    restrict_access(root, true)
}
pub fn load_or_create(
    root: &Path,
    generate: impl FnOnce() -> String,
) -> Result<String, &'static str> {
    secure_root(root)?;
    // Never silently import a former QA plaintext file. A deliberate
    // operator-reviewed migration is required to avoid leaving copies behind.
    if root.join("private-secrets.txt").exists() {
        return Err("PLAINTEXT_SECRETS_MANUAL_MIGRATION_REQUIRED");
    }
    let target = root.join("runtime-secrets.dpapi");
    if target.exists() {
        let binary = fs::read(&target).map_err(|_| "DPAPI_FILE_READ_FAILED")?;
        if !binary.starts_with(HEADER) { return Err("DPAPI_FILE_FORMAT_INVALID"); }
        let decrypted = protect_or_unprotect(&binary[HEADER.len()..], false)?;
        let value = String::from_utf8(decrypted).map_err(|_| "DPAPI_UTF8_INVALID")?;
        if value.lines().count() != 4 || value.lines().any(|s| s.len() < 30) {
            return Err("DPAPI_SECRET_LAYOUT_INVALID");
        }
        return Ok(value);
    }
    let generated = generate();
    let ciphertext = protect_or_unprotect(generated.as_bytes(), true)?;
    let mut file = OpenOptions::new().create_new(true).write(true).open(&target)
        .map_err(|_| "DPAPI_CREATE_NEW_FAILED")?;
    file.write_all(HEADER).and_then(|_| file.write_all(&ciphertext))
        .and_then(|_| file.sync_all()).map_err(|_| "DPAPI_WRITE_FAILED")?;
    drop(file);
    restrict_access(&target, false)?;
    Ok(generated)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn dpapi_user_round_trip_never_returns_plaintext_ciphertext() {
        let msg = b"windows-user-dpapi-opaque-contract-test-no-credential";
        let ct = protect_or_unprotect(msg, true).expect("user DPAPI should be available");
        assert!(!ct.windows(msg.len()).any(|w| w == msg));
        assert_eq!(protect_or_unprotect(&ct, false).unwrap(), msg);
        let mut tampered = ct;
        tampered[0] ^= 0x40;
        assert!(protect_or_unprotect(&tampered, false).is_err());
    }
    #[test]
    fn durable_reopen_never_rotates_stored_user_dpapi_identity() {
        let root = std::env::temp_dir()
            .join(format!("yance-dpapi-unit-{}", uuid::Uuid::new_v4().simple()));
        let fake = (0..4).map(|_| "unit-test-only-opaque-string-not-a-real-password")
            .collect::<Vec<_>>().join("\n");
        let first = load_or_create(&root, || fake.clone()).unwrap();
        let bytes = fs::read(root.join("runtime-secrets.dpapi")).unwrap();
        assert!(!bytes.windows(15).any(|segment| segment == b"unit-test-only-"));
        let second = load_or_create(&root, || panic!("existing identity must be reused")).unwrap();
        assert_eq!(first, second);
        let _ = fs::remove_file(root.join("runtime-secrets.dpapi"));
        let _ = fs::remove_dir(root);
    }
}
