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

fn protect_or_unprotect_limited(
    bytes: &[u8], protect: bool, max_input: usize, max_output: u32,
) -> Result<Vec<u8>, &'static str> {
    if bytes.is_empty() || bytes.len() > max_input { return Err("DPAPI_BAD_INPUT_LENGTH"); }
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
    if succeeded == 0 || output.data.is_null() || output.size == 0 || output.size > max_output {
        if !output.data.is_null() { unsafe { LocalFree(output.data.cast()); } }
        return Err("DPAPI_CURRENT_USER_UNAVAILABLE_OR_CIPHERTEXT_INVALID");
    }
    let copy = unsafe { std::slice::from_raw_parts(output.data, output.size as usize).to_vec() };
    unsafe { LocalFree(output.data.cast()); }
    Ok(copy)
}
// Keep the original runtime-secrets.dpapi four-line wire/layout and limits unchanged.
fn protect_or_unprotect(bytes: &[u8], protect: bool) -> Result<Vec<u8>, &'static str> {
    protect_or_unprotect_limited(bytes, protect, 4096, 8192)
}

// Restricted to native Rust crate code. Never a Tauri invoke command or frontend API.
pub(crate) fn seal_siwc(bytes: &[u8]) -> Result<Vec<u8>, &'static str> {
    protect_or_unprotect_limited(bytes, true, 32768, 65536)
}
pub(crate) fn unseal_siwc(bytes: &[u8]) -> Result<Vec<u8>, &'static str> {
    protect_or_unprotect_limited(bytes, false, 65536, 32768)
}
pub(crate) fn restrict_siwc_file(path: &Path) -> Result<(), &'static str> {
    restrict_access(path, false)
}

pub(crate) fn current_user_sid() -> Result<String, &'static str> {
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
// Windows ACL correction: replace the WHOLE DACL, not just named grants.
// The previous icacls /grant:r left unrelated explicit Everyone entries.
#[repr(C)]
struct AclSizeInformation { ace_count: u32, bytes_used: u32, bytes_free: u32 }
#[repr(C)]
struct AceHeader { ace_type: u8, ace_flags: u8, ace_size: u16 }
#[repr(C)]
struct AccessAllowedAce { header: AceHeader, mask: u32, sid_start: u32 }
const DACL_SECURITY_INFORMATION: u32 = 0x00000004;
const PROTECTED_DACL_SECURITY_INFORMATION: u32 = 0x80000000;
const SE_DACL_PROTECTED: u16 = 0x1000;
const ACL_SIZE_INFORMATION_CLASS: u32 = 2;
const FILE_ALL_ACCESS: u32 = 0x001f01ff;
const REPARSE_POINT: u32 = 0x400;
const OI_CI: u8 = 0x03;
#[link(name = "Advapi32")]
extern "system" {
    fn ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl: *const u16, revision: u32, descriptor: *mut *mut c_void, size: *mut u32,
    ) -> i32;
    fn GetSecurityDescriptorDacl(
        descriptor: *const c_void, present: *mut i32, dacl: *mut *mut c_void,
        defaulted: *mut i32,
    ) -> i32;
    fn GetSecurityDescriptorControl(
        descriptor: *const c_void, control: *mut u16, revision: *mut u32,
    ) -> i32;
    fn SetNamedSecurityInfoW(
        object: *mut u16, object_type: u32, security_info: u32,
        owner: *mut c_void, group: *mut c_void, dacl: *mut c_void,
        sacl: *mut c_void,
    ) -> u32;
    fn GetNamedSecurityInfoW(
        object: *mut u16, object_type: u32, security_info: u32,
        owner: *mut *mut c_void, group: *mut *mut c_void,
        dacl: *mut *mut c_void, sacl: *mut *mut c_void,
        descriptor: *mut *mut c_void,
    ) -> u32;
    fn ConvertStringSidToSidW(text: *const u16, sid: *mut *mut c_void) -> i32;
    fn EqualSid(left: *const c_void, right: *const c_void) -> i32;
    fn GetAclInformation(acl: *const c_void, output: *mut c_void,
                          len: u32, class: u32) -> i32;
    fn GetAce(acl: *const c_void, index: u32, ace: *mut *mut c_void) -> i32;
}
struct LocalSecurityMem(*mut c_void);
impl Drop for LocalSecurityMem {
    fn drop(&mut self) { if !self.0.is_null() { unsafe { LocalFree(self.0); } } }
}
fn wide_os(value: &std::ffi::OsStr) -> Vec<u16> {
    use std::os::windows::ffi::OsStrExt;
    value.encode_wide().chain(std::iter::once(0)).collect()
}
fn reject_reparse_ancestors(path: &Path) -> Result<(), &'static str> {
    use std::os::windows::fs::MetadataExt;
    // Check the final entry AND all existing parents; missing leaf is allowed for
    // a new atomic replacement. Reject junctions, symlinks and mount-point reparses.
    for entry in path.ancestors() {
        match fs::symlink_metadata(entry) {
            Ok(meta) if meta.file_attributes() & REPARSE_POINT != 0 =>
                return Err("DPAPI_REPARSE_PATH_REJECTED"),
            Ok(_) => (),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => (),
            Err(_) => return Err("DPAPI_PATH_INSPECTION_FAILED"),
        }
    }
    Ok(())
}
pub(crate) fn inspect_siwc_path(path: &Path) -> Result<(), &'static str> {
    reject_reparse_ancestors(path)
}
fn restrict_access(path: &Path, dir: bool) -> Result<(), &'static str> {
    reject_reparse_ancestors(path)?;
    let metadata = fs::symlink_metadata(path).map_err(|_| "DPAPI_ACL_OBJECT_MISSING")?;
    if metadata.is_dir() != dir { return Err("DPAPI_ACL_OBJECT_TYPE_MISMATCH"); }
    let current = current_user_sid()?;
    let flags = if dir { "OICI" } else { "" };
    let sddl = format!("D:P(A;{flags};FA;;;{current})(A;{flags};FA;;;SY)");
    let sddl_w = wide_os(std::ffi::OsStr::new(&sddl));
    let path_w = wide_os(path.as_os_str());
    let mut desired_ptr: *mut c_void = std::ptr::null_mut();
    if unsafe {
        ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl_w.as_ptr(), 1, &mut desired_ptr, std::ptr::null_mut())
    } == 0 { return Err("DPAPI_ACL_BUILD_FAILED"); }
    let desired = LocalSecurityMem(desired_ptr);
    let mut present = 0i32;
    let mut defaulted = 0i32;
    let mut dacl: *mut c_void = std::ptr::null_mut();
    if unsafe {
        GetSecurityDescriptorDacl(desired.0, &mut present, &mut dacl, &mut defaulted)
    } == 0 || present == 0 || dacl.is_null() {
        return Err("DPAPI_ACL_BUILD_FAILED");
    }
    let outcome = unsafe {
        SetNamedSecurityInfoW(
            path_w.as_ptr() as *mut u16, 1,
            DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
            std::ptr::null_mut(), std::ptr::null_mut(), dacl, std::ptr::null_mut(),
        )
    };
    if outcome != 0 { return Err("DPAPI_ACL_REPLACE_FAILED"); }
    verify_protected_acl(path, dir, &current)
}
fn verify_protected_acl(path: &Path, dir: bool, current: &str) -> Result<(), &'static str> {
    reject_reparse_ancestors(path)?;
    let mut path_w = wide_os(path.as_os_str());
    let mut actual_ptr: *mut c_void = std::ptr::null_mut();
    let mut actual_acl: *mut c_void = std::ptr::null_mut();
    let outcome = unsafe {
        GetNamedSecurityInfoW(
            path_w.as_mut_ptr(), 1, DACL_SECURITY_INFORMATION,
            std::ptr::null_mut(), std::ptr::null_mut(), &mut actual_acl,
            std::ptr::null_mut(), &mut actual_ptr,
        )
    };
    if outcome != 0 { return Err("DPAPI_ACL_VERIFY_READ_FAILED"); }
    let actual = LocalSecurityMem(actual_ptr);
    if actual.0.is_null() || actual_acl.is_null() { return Err("DPAPI_ACL_VERIFY_FAILED"); }
    let mut control: u16 = 0;
    let mut revision: u32 = 0;
    if unsafe { GetSecurityDescriptorControl(actual.0, &mut control, &mut revision) } == 0 ||
        control & SE_DACL_PROTECTED == 0 {
        return Err("DPAPI_ACL_VERIFY_UNPROTECTED");
    }
    let mut size = AclSizeInformation { ace_count: 0, bytes_used: 0, bytes_free: 0 };
    if unsafe {
        GetAclInformation(actual_acl, (&mut size as *mut AclSizeInformation).cast(),
                          std::mem::size_of::<AclSizeInformation>() as u32,
                          ACL_SIZE_INFORMATION_CLASS)
    } == 0 || size.ace_count != 2 { return Err("DPAPI_ACL_VERIFY_EXTRA_ACE"); }
    let user_w = wide_os(std::ffi::OsStr::new(current));
    let system_w = wide_os(std::ffi::OsStr::new("S-1-5-18"));
    let mut user_ptr: *mut c_void = std::ptr::null_mut();
    let mut system_ptr: *mut c_void = std::ptr::null_mut();
    if unsafe { ConvertStringSidToSidW(user_w.as_ptr(), &mut user_ptr) } == 0 {
        return Err("DPAPI_ACL_VERIFY_SID_FAILED");
    }
    let user_sid = LocalSecurityMem(user_ptr);
    if unsafe { ConvertStringSidToSidW(system_w.as_ptr(), &mut system_ptr) } == 0 {
        return Err("DPAPI_ACL_VERIFY_SID_FAILED");
    }
    let system_sid = LocalSecurityMem(system_ptr);
    let mut matched = [false; 2];
    for index in 0..2 {
        let mut ace_ptr: *mut c_void = std::ptr::null_mut();
        if unsafe { GetAce(actual_acl, index, &mut ace_ptr) } == 0 || ace_ptr.is_null() {
            return Err("DPAPI_ACL_VERIFY_FAILED");
        }
        let ace = unsafe { &*(ace_ptr as *const AccessAllowedAce) };
        if ace.header.ace_type != 0 ||
           ace.mask != FILE_ALL_ACCESS ||
           ace.header.ace_flags != if dir { OI_CI } else { 0 } {
            return Err("DPAPI_ACL_VERIFY_WRONG_ACE");
        }
        let sid_ptr = std::ptr::addr_of!(ace.sid_start).cast::<c_void>();
        let is_user = unsafe { EqualSid(sid_ptr, user_sid.0) } != 0;
        let is_system = unsafe { EqualSid(sid_ptr, system_sid.0) } != 0;
        if is_user && !matched[0] { matched[0] = true; }
        else if is_system && !matched[1] { matched[1] = true; }
        else { return Err("DPAPI_ACL_VERIFY_EXTRA_ACE"); }
    }
    if !matched.into_iter().all(|ok| ok) { return Err("DPAPI_ACL_VERIFY_MISSING_ACE"); }
    Ok(())
}
pub fn secure_root(root: &Path) -> Result<(), &'static str> {
    reject_reparse_ancestors(root)?;
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
        // Historical explicit ACLs must be removed before opening a sealed secret.
        restrict_access(&target, false)?;
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
    fn real_windows_explicit_everyone_acl_is_removed_and_verified() {
        let root = std::env::temp_dir()
            .join(format!("yance-siwc-acl-injection-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&root).unwrap();
        let grant = std::process::Command::new("icacls.exe")
            .arg(&root).args(["/grant", "*S-1-1-0:(OI)(CI)R"])
            .output().unwrap();
        assert!(grant.status.success(), "ACL pre-seed must succeed in disposable dir");
        let owner = current_user_sid().unwrap();
        assert!(verify_protected_acl(&root, true, &owner).is_err(),
                "preexisting Everyone ACE must be rejected");
        secure_root(&root).unwrap();
        verify_protected_acl(&root, true, &owner).unwrap();

        let secret = root.join("qa-account.dpapi");
        fs::write(&secret, b"synthetic sealed-binary-placeholder").unwrap();
        let seed_file = std::process::Command::new("icacls.exe")
            .arg(&secret).args(["/grant", "*S-1-1-0:R"])
            .output().unwrap();
        assert!(seed_file.status.success());
        assert!(verify_protected_acl(&secret, false, &owner).is_err());
        restrict_siwc_file(&secret).unwrap();
        verify_protected_acl(&secret, false, &owner).unwrap();
        fs::remove_dir_all(root).unwrap();
    }
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
        let target = root.join("runtime-secrets.dpapi");
        let bytes = fs::read(&target).unwrap();
        assert!(!bytes.windows(15).any(|segment| segment == b"unit-test-only-"));
        let injected = std::process::Command::new("icacls.exe")
            .arg(&target).args(["/grant", "*S-1-1-0:R"]).output().unwrap();
        assert!(injected.status.success());
        assert!(verify_protected_acl(&target, false, &current_user_sid().unwrap()).is_err());
        let second = load_or_create(&root, || panic!("existing identity must be reused")).unwrap();
        verify_protected_acl(&target, false, &current_user_sid().unwrap()).unwrap();
        assert_eq!(bytes, fs::read(&target).unwrap(), "legacy four-line bytes must not change");
        assert_eq!(first, second);
        let _ = fs::remove_file(root.join("runtime-secrets.dpapi"));
        let _ = fs::remove_dir(root);
    }
}
