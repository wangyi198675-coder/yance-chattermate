//! Current-user Windows DPAPI vault for SIWC OAuth. Native Rust only.
//! Phase2A1: NO browser, OAuth transport, backend IPC or renderer commands.
//! Synthetic caller tests; no production account/credential is accessed.
//! The existing runtime-secrets.dpapi four-line record is NEVER modified.

#![allow(dead_code)] // Interface is registered only for native tests until Phase2A2.

use std::{
    ffi::{c_void, OsStr},
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    os::windows::{ffi::OsStrExt, fs::OpenOptionsExt, io::AsRawHandle},
    path::{Path, PathBuf},
    ptr,
    thread,
    time::{Duration, Instant},
};
use uuid::Uuid;

const HOST_HEADER: &[u8] = b"YANCE-SIWC-HOST-V1\0";
const RECORD_HEADER: &[u8] = b"YANCE-SIWC-ACCOUNT-V1\0";
const INNER_VERSION: &[u8] = b"SIWC-RECORD-V1\0";
const MAX_FILE: u64 = 65536 + 64;
const MAX_STRING: usize = 16384;
const LOCK_EXCLUSIVE: u32 = 0x0002;
const FILE_SHARE_READ: u32 = 0x00000001;
const FILE_SHARE_WRITE: u32 = 0x00000002; // no FILE_SHARE_DELETE: locked path cannot be renamed
const LOCK_NO_WAIT: u32 = 0x0001;
const REPLACE_EXISTING: u32 = 0x0001;
const WRITE_THROUGH: u32 = 0x0008;

#[repr(C)]
struct Overlapped {
    internal: usize,
    internal_high: usize,
    offset: u32,
    offset_high: u32,
    event: *mut c_void,
}
impl Overlapped {
    fn empty() -> Self {
        Self { internal: 0, internal_high: 0, offset: 0, offset_high: 0, event: ptr::null_mut() }
    }
}
#[link(name = "Kernel32")]
extern "system" {
    fn LockFileEx(handle: *mut c_void, flags: u32, reserved: u32,
                  count_low: u32, count_high: u32, overlapped: *mut Overlapped) -> i32;
    fn UnlockFileEx(handle: *mut c_void, reserved: u32, count_low: u32,
                    count_high: u32, overlapped: *mut Overlapped) -> i32;
    fn MoveFileExW(source: *const u16, destination: *const u16, flags: u32) -> i32;
}
struct FileLock {
    file: File,
    overlap: Overlapped,
}
impl Drop for FileLock {
    fn drop(&mut self) {
        unsafe {
            UnlockFileEx(self.file.as_raw_handle(), 0, 1, 0, &mut self.overlap);
        }
    }
}
fn lock_root(root: &Path) -> Result<FileLock, &'static str> {
    let path = root.join("siwc.lock");
    crate::dpapi::inspect_siwc_path(&path)?;
    let file = OpenOptions::new().read(true).write(true).create(true)
        .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE) // blocks rename/delete while open
        .open(&path).map_err(|_| "SIWC_LOCK_UNAVAILABLE")?;
    crate::dpapi::restrict_siwc_file(&path)?;
    let mut overlap = Overlapped::empty();
    let deadline = Instant::now() + Duration::from_secs(8);
    loop {
        let locked = unsafe {
            LockFileEx(file.as_raw_handle(), LOCK_EXCLUSIVE | LOCK_NO_WAIT, 0, 1, 0, &mut overlap)
        };
        if locked != 0 { return Ok(FileLock { file, overlap }); }
        if Instant::now() >= deadline { return Err("SIWC_LOCK_TIMEOUT"); }
        thread::sleep(Duration::from_millis(12));
    }
}
fn wide(path: &Path) -> Vec<u16> {
    OsStr::new(path.as_os_str()).encode_wide().chain(Some(0)).collect()
}
fn atomic_replace(root: &Path, target: &Path, bytes: &[u8]) -> Result<(), &'static str> {
    if bytes.is_empty() || bytes.len() as u64 > MAX_FILE {
        return Err("SIWC_FILE_INVALID");
    }
    // Temp and destination share a volume/directory. Reject existing redirection.
    crate::dpapi::inspect_siwc_path(root)?;
    crate::dpapi::inspect_siwc_path(target)?;
    let temp = root.join(format!(".siwc-txn-{}.tmp", Uuid::new_v4()));
    let attempt = (|| {
        let mut file = OpenOptions::new().write(true).create_new(true).open(&temp)
            .map_err(|_| "SIWC_TEMP_CREATE_FAILED")?;
        file.write_all(bytes).and_then(|_| file.sync_all())
            .map_err(|_| "SIWC_TEMP_FLUSH_FAILED")?;
        crate::dpapi::restrict_siwc_file(&temp)?;
        drop(file);
        let src = wide(&temp);
        let dst = wide(target);
        if unsafe { MoveFileExW(src.as_ptr(), dst.as_ptr(), REPLACE_EXISTING | WRITE_THROUGH) } == 0 {
            return Err("SIWC_ATOMIC_REPLACE_FAILED");
        }
        Ok(())
    })();
    if attempt.is_err() { let _ = fs::remove_file(temp); }
    attempt
}
fn read_small(path: &Path) -> Result<Option<Vec<u8>>, &'static str> {
    crate::dpapi::inspect_siwc_path(path)?;
    if path.exists() { crate::dpapi::restrict_siwc_file(path)?; }
    let mut f = match File::open(path) {
        Ok(v) => v,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(_) => return Err("SIWC_FILE_READ_FAILED"),
    };
    if f.metadata().map_err(|_| "SIWC_FILE_METADATA_FAILED")?.len() > MAX_FILE {
        return Err("SIWC_FILE_OVERSIZED");
    }
    let mut bytes = Vec::new();
    f.read_to_end(&mut bytes).map_err(|_| "SIWC_FILE_READ_FAILED")?;
    if bytes.is_empty() || bytes.len() as u64 > MAX_FILE {
        return Err("SIWC_FILE_INVALID");
    }
    Ok(Some(bytes))
}
fn seal(header: &[u8], value: &mut [u8]) -> Result<Vec<u8>, &'static str> {
    let result = crate::dpapi::seal_siwc(value);
    value.fill(0);
    let ciphertext = result?;
    let mut binary = Vec::with_capacity(header.len() + ciphertext.len());
    binary.extend_from_slice(header);
    binary.extend_from_slice(&ciphertext);
    Ok(binary)
}
fn unseal(header: &[u8], binary: &[u8]) -> Result<Vec<u8>, &'static str> {
    if !binary.starts_with(header) || binary.len() <= header.len() {
        return Err("SIWC_FILE_FORMAT_INVALID");
    }
    crate::dpapi::unseal_siwc(&binary[header.len()..])
}
fn validated_uuid(id: &str) -> Result<String, &'static str> {
    let value = Uuid::parse_str(id).map_err(|_| "SIWC_ACCOUNT_REF_INVALID")?;
    if value.get_version_num() != 4 || value.hyphenated().to_string() != id {
        return Err("SIWC_ACCOUNT_REF_INVALID");
    }
    Ok(id.to_owned())
}
fn field(out: &mut Vec<u8>, value: &str) -> Result<(), &'static str> {
    if value.is_empty() || value.len() > MAX_STRING {
        return Err("SIWC_FIELD_INVALID");
    }
    let size = u32::try_from(value.len()).map_err(|_| "SIWC_FIELD_INVALID")?;
    out.extend_from_slice(&size.to_le_bytes());
    out.extend_from_slice(value.as_bytes());
    Ok(())
}
fn take(bytes: &[u8], at: &mut usize) -> Result<String, &'static str> {
    if bytes.len().saturating_sub(*at) < 4 { return Err("SIWC_RECORD_INVALID"); }
    let mut size = [0u8; 4];
    size.copy_from_slice(&bytes[*at..*at + 4]);
    *at += 4;
    let size = u32::from_le_bytes(size) as usize;
    if size == 0 || size > MAX_STRING || bytes.len().saturating_sub(*at) < size {
        return Err("SIWC_RECORD_INVALID");
    }
    let value = String::from_utf8(bytes[*at..*at + size].to_vec())
        .map_err(|_| "SIWC_RECORD_INVALID")?;
    *at += size;
    Ok(value)
}
fn sid() -> Result<String, &'static str> {
    crate::dpapi::current_user_sid()
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum RevocationState { Active, Pending, Revoked }
impl RevocationState {
    fn byte(self) -> u8 {
        match self { Self::Active => 1, Self::Pending => 2, Self::Revoked => 3 }
    }
    fn parse(value: u8) -> Result<Self, &'static str> {
        match value { 1 => Ok(Self::Active), 2 => Ok(Self::Pending), 3 => Ok(Self::Revoked),
            _ => Err("SIWC_RECORD_INVALID") }
    }
}
#[derive(Clone)]
pub(crate) struct AccountIdentity {
    pub account_ref: String,   // randomly generated UUIDv4: filename only (not sub/email)
    pub org_ref: String,
    pub local_user_ref: String,
    pub subject: String,
    pub client_id: String,      // actual issued oaiapp_* client, never dynamic client
}
impl AccountIdentity {
    fn validate(&self) -> Result<(), &'static str> {
        validated_uuid(&self.account_ref)?;
        for val in [&self.org_ref, &self.local_user_ref, &self.subject, &self.client_id] {
            if val.is_empty() || val.len() > 255 || val.chars().any(char::is_control) {
                return Err("SIWC_ACCOUNT_IDENTITY_INVALID");
            }
        }
        if !self.client_id.starts_with("oaiapp_") {
            return Err("SIWC_ACCOUNT_IDENTITY_INVALID");
        }
        Ok(())
    }
}
// No Debug/Display/Serialize. Used only by native Rust code. Avoid logging/copying secrets.
pub(crate) struct SecretBundle {
    pub access_token: String,
    pub refresh_token: String,
    pub id_token: String,
}
impl SecretBundle {
    fn validate(&self) -> Result<(), &'static str> {
        for v in [&self.access_token, &self.refresh_token, &self.id_token] {
            if v.is_empty() || v.len() > 14000 { return Err("SIWC_TOKEN_INVALID"); }
        }
        Ok(())
    }
}
pub(crate) struct StoredAccount {
    pub identity: AccountIdentity,
    pub version: u64,
    pub status: RevocationState,
    pub tokens: Option<SecretBundle>,
}
pub(crate) struct Vault {
    root: PathBuf,
    host_id: String,
    owner_sid: String,
}
impl Vault {
    pub fn open(user_data_root: &Path) -> Result<Self, &'static str> {
        crate::dpapi::secure_root(user_data_root)?;
        let root = user_data_root.join("siwc");
        crate::dpapi::secure_root(&root)?;
        let _lock = lock_root(&root)?;
        let owner_sid = sid()?;
        let path = root.join("host-id.dpapi");
        let host_id = if let Some(binary) = read_small(&path)? {
            let mut raw = unseal(HOST_HEADER, &binary)?;
            let value = String::from_utf8(raw.clone()).map_err(|_| "SIWC_HOST_CORRUPT");
            raw.fill(0);
            let value = value?;
            validated_uuid(&value).map_err(|_| "SIWC_HOST_CORRUPT")?
        } else {
            let generated = Uuid::new_v4().hyphenated().to_string();
            let binary = seal(HOST_HEADER, &mut generated.as_bytes().to_vec())?;
            atomic_replace(&root, &path, &binary)?;
            generated
        };
        Ok(Self { root, host_id, owner_sid })
    }
    pub fn host_id(&self) -> &str { &self.host_id }
    pub fn new_account_ref() -> String {
        Uuid::new_v4().hyphenated().to_string()
    }
    fn check_context(&self) -> Result<(), &'static str> {
        if sid()? != self.owner_sid { return Err("SIWC_WINDOWS_USER_MISMATCH"); }
        Ok(())
    }
    fn account_path(&self, account_ref: &str) -> Result<PathBuf, &'static str> {
        let account_ref = validated_uuid(account_ref)?;
        Ok(self.root.join(format!("account-{account_ref}.dpapi")))
    }
    fn encode(&self, account: &StoredAccount) -> Result<Vec<u8>, &'static str> {
        account.identity.validate()?;
        if account.version == 0 { return Err("SIWC_RECORD_INVALID"); }
        if account.status == RevocationState::Revoked && account.tokens.is_some() {
            return Err("SIWC_REVOKED_HAS_TOKENS");
        }
        if account.status != RevocationState::Revoked &&
            account.tokens.as_ref().is_none_or(|tokens| tokens.validate().is_err()) {
            return Err("SIWC_TOKEN_INVALID");
        }
        let mut raw = INNER_VERSION.to_vec();
        raw.extend_from_slice(&account.version.to_le_bytes());
        raw.push(account.status.byte());
        for part in [
            &self.host_id, &self.owner_sid,
            &account.identity.account_ref, &account.identity.org_ref,
            &account.identity.local_user_ref, &account.identity.subject,
            &account.identity.client_id,
        ] {
            field(&mut raw, part)?;
        }
        if let Some(tokens) = &account.tokens {
            for part in [&tokens.access_token, &tokens.refresh_token, &tokens.id_token] {
                field(&mut raw, part)?;
            }
        }
        if raw.len() > 32768 { raw.fill(0); return Err("SIWC_RECORD_OVERSIZED"); }
        seal(RECORD_HEADER, &mut raw)
    }
    fn decode(&self, binary: &[u8], account_ref: &str) -> Result<StoredAccount, &'static str> {
        let mut raw = unseal(RECORD_HEADER, binary)?;
        let result = (|| {
            if !raw.starts_with(INNER_VERSION) { return Err("SIWC_RECORD_INVALID"); }
            let mut at = INNER_VERSION.len();
            if raw.len().saturating_sub(at) < 9 { return Err("SIWC_RECORD_INVALID"); }
            let mut ver = [0u8; 8];
            ver.copy_from_slice(&raw[at..at + 8]);
            at += 8;
            let version = u64::from_le_bytes(ver);
            if version == 0 { return Err("SIWC_RECORD_INVALID"); }
            let status = RevocationState::parse(raw[at])?;
            at += 1;
            let host = take(&raw, &mut at)?;
            let owner = take(&raw, &mut at)?;
            if host != self.host_id { return Err("SIWC_HOST_MISMATCH"); }
            if owner != self.owner_sid { return Err("SIWC_WINDOWS_USER_MISMATCH"); }
            let identity = AccountIdentity {
                account_ref: take(&raw, &mut at)?,
                org_ref: take(&raw, &mut at)?,
                local_user_ref: take(&raw, &mut at)?,
                subject: take(&raw, &mut at)?,
                client_id: take(&raw, &mut at)?,
            };
            identity.validate()?;
            if identity.account_ref != account_ref { return Err("SIWC_ACCOUNT_REF_MISMATCH"); }
            let tokens = if status == RevocationState::Revoked { None } else {
                Some(SecretBundle {
                    access_token: take(&raw, &mut at)?,
                    refresh_token: take(&raw, &mut at)?,
                    id_token: take(&raw, &mut at)?,
                })
            };
            if at != raw.len() { return Err("SIWC_RECORD_INVALID"); }
            if let Some(t) = &tokens { t.validate()?; }
            Ok(StoredAccount { identity, version, status, tokens })
        })();
        raw.fill(0);
        result
    }
    fn read_locked(&self, identity: &AccountIdentity) -> Result<StoredAccount, &'static str> {
        self.check_context()?;
        identity.validate()?;
        let path = self.account_path(&identity.account_ref)?;
        let binary = read_small(&path)?.ok_or("SIWC_ACCOUNT_NOT_FOUND")?;
        let record = self.decode(&binary, &identity.account_ref)?;
        let original = &record.identity;
        if original.org_ref != identity.org_ref ||
           original.local_user_ref != identity.local_user_ref ||
           original.subject != identity.subject ||
           original.client_id != identity.client_id {
            return Err("SIWC_ACCOUNT_IDENTITY_MISMATCH");
        }
        Ok(record)
    }
    /// Normal inference/refresh credential access: strictly Active-only.
    pub fn read(&self, identity: &AccountIdentity) -> Result<StoredAccount, &'static str> {
        let _lock = lock_root(&self.root)?;
        let record = self.read_locked(identity)?;
        if record.status != RevocationState::Active { return Err("SIWC_REAUTH_REQUIRED"); }
        Ok(record)
    }
    /// State inspection never yields token fields, including Pending and Revoked.
    pub fn status(&self, identity: &AccountIdentity) -> Result<(RevocationState, u64), &'static str> {
        let _lock = lock_root(&self.root)?;
        let record = self.read_locked(identity)?;
        Ok((record.status, record.version))
    }
    /// Native-only, single-purpose remote revocation input; never for inference.
    /// The caller must separately authorize the real revocation operation in Phase2A2.
    pub fn pending_refresh_for_revoke(&self, identity: &AccountIdentity) -> Result<String, &'static str> {
        let _lock = lock_root(&self.root)?;
        let mut record = self.read_locked(identity)?;
        if record.status != RevocationState::Pending { return Err("SIWC_REVOKE_NOT_PENDING"); }
        let mut bundle = record.tokens.take().ok_or("SIWC_REVOKE_TOKEN_MISSING")?;
        let refresh = std::mem::take(&mut bundle.refresh_token);
        Ok(refresh)
    }
    pub fn insert(&self, identity: AccountIdentity, tokens: SecretBundle) -> Result<(), &'static str> {
        let _lock = lock_root(&self.root)?;
        self.check_context()?;
        identity.validate()?;
        tokens.validate()?;
        let path = self.account_path(&identity.account_ref)?;
        if read_small(&path)?.is_some() {
            return Err("SIWC_ACCOUNT_ALREADY_EXISTS"); // Cannot overwrite/rebind account.
        }
        let record = StoredAccount { identity, version: 1, status: RevocationState::Active, tokens: Some(tokens) };
        atomic_replace(&self.root, &path, &self.encode(&record)?)
    }
    // Cross-process LockFileEx + version-CAS protects against concurrent refresh
    // and stale overwrite. No refresh is performed in Phase2A1 itself.
    pub fn rotate_if_version(
        &self, identity: &AccountIdentity, expected_version: u64,
        tokens: SecretBundle,
    ) -> Result<u64, &'static str> {
        let _lock = lock_root(&self.root)?;
        let mut record = self.read_locked(identity)?;
        if record.version != expected_version { return Err("SIWC_STALE_ROTATION"); }
        if record.status != RevocationState::Active { return Err("SIWC_REAUTH_REQUIRED"); }
        tokens.validate()?;
        record.tokens = Some(tokens);
        record.version = record.version.checked_add(1).ok_or("SIWC_VERSION_OVERFLOW")?;
        let path = self.account_path(&identity.account_ref)?;
        atomic_replace(&self.root, &path, &self.encode(&record)?)?;
        Ok(record.version)
    }
    pub fn mark_revoke_pending(
        &self, identity: &AccountIdentity, expected_version: u64,
    ) -> Result<u64, &'static str> {
        let _lock = lock_root(&self.root)?;
        let mut record = self.read_locked(identity)?;
        if record.version != expected_version { return Err("SIWC_STALE_ROTATION"); }
        if record.status != RevocationState::Active { return Err("SIWC_REVOKE_NOT_ACTIVE"); }
        record.status = RevocationState::Pending;
        record.version = record.version.checked_add(1).ok_or("SIWC_VERSION_OVERFLOW")?;
        atomic_replace(&self.root, &self.account_path(&identity.account_ref)?, &self.encode(&record)?)?;
        Ok(record.version)
    }
    // Revoke acknowledgment (or explicitly approved local credential destruction)
    // is Phase2A2's responsibility. Revoked record permanently removes secret
    // fields, preventing accidental reactivation of a disconnected identity.
    pub fn finalize_revoked(
        &self, identity: &AccountIdentity, expected_version: u64,
    ) -> Result<u64, &'static str> {
        let _lock = lock_root(&self.root)?;
        let mut record = self.read_locked(identity)?;
        if record.version != expected_version { return Err("SIWC_STALE_ROTATION"); }
        if record.status != RevocationState::Pending { return Err("SIWC_REVOKE_NOT_PENDING"); }
        record.tokens = None;
        record.status = RevocationState::Revoked;
        record.version = record.version.checked_add(1).ok_or("SIWC_VERSION_OVERFLOW")?;
        atomic_replace(&self.root, &self.account_path(&identity.account_ref)?, &self.encode(&record)?)?;
        Ok(record.version)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Arc, Barrier};
    fn qa_root() -> PathBuf {
        std::env::temp_dir().join(format!("yance-siwc-qa-{}", Uuid::new_v4()))
    }
    fn fake_identity(account_ref: String, sub: &str) -> AccountIdentity {
        AccountIdentity {
            account_ref, org_ref: "qa-org".into(), local_user_ref: "qa-native-user".into(),
            subject: sub.into(), client_id: "oaiapp_synthetic-only".into(),
        }
    }
    fn fake_tokens(suffix: &str) -> SecretBundle {
        SecretBundle {
            access_token: format!("SYNTHETIC-ACCESS-ONLY-{suffix}"),
            refresh_token: format!("SYNTHETIC-REFRESH-ONLY-{suffix}"),
            id_token: format!("SYNTHETIC-ID-ONLY-{suffix}"),
        }
    }
    #[test]
    fn current_user_dpapi_encryption_host_id_and_cold_reopen() {
        let root = qa_root();
        let vault = Vault::open(&root).unwrap();
        let stable = vault.host_id().to_string();
        let identity = fake_identity(Vault::new_account_ref(), "sub-1");
        vault.insert(identity.clone(), fake_tokens("alpha")).unwrap();
        let raw = fs::read(vault.account_path(&identity.account_ref).unwrap()).unwrap();
        assert!(raw.starts_with(RECORD_HEADER));
        assert!(!raw.windows(24).any(|s| s == b"SYNTHETIC-REFRESH-ONLY-"));
        drop(vault);
        let reopened = Vault::open(&root).unwrap();
        assert_eq!(reopened.host_id(), stable);
        let record = reopened.read(&identity).unwrap();
        assert_eq!(record.version, 1);
        assert_eq!(record.status.byte(), 1);
        assert_eq!(record.tokens.unwrap().refresh_token, "SYNTHETIC-REFRESH-ONLY-alpha");
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn different_accounts_and_subjects_cannot_cross_read_or_rebind() {
        let root = qa_root();
        let vault = Vault::open(&root).unwrap();
        let one = fake_identity(Vault::new_account_ref(), "sub-one");
        let two = fake_identity(Vault::new_account_ref(), "sub-two");
        vault.insert(one.clone(), fake_tokens("one")).unwrap();
        vault.insert(two.clone(), fake_tokens("two")).unwrap();
        assert_eq!(vault.read(&two).unwrap().tokens.unwrap().access_token, "SYNTHETIC-ACCESS-ONLY-two");
        let mut spoofed = one.clone();
        spoofed.subject = two.subject.clone();
        assert_eq!(vault.read(&spoofed).err(), Some("SIWC_ACCOUNT_IDENTITY_MISMATCH"));
        spoofed = one.clone();
        spoofed.org_ref = "other-org".into();
        assert_eq!(vault.read(&spoofed).err(), Some("SIWC_ACCOUNT_IDENTITY_MISMATCH"));
        spoofed = one.clone();
        spoofed.client_id = "oaiapp_other".into();
        assert_eq!(vault.read(&spoofed).err(), Some("SIWC_ACCOUNT_IDENTITY_MISMATCH"));
        assert_eq!(vault.insert(one, fake_tokens("hijack")).err(), Some("SIWC_ACCOUNT_ALREADY_EXISTS"));
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn simulated_different_windows_sid_is_denied_before_decryption() {
        let root = qa_root();
        let vault = Vault::open(&root).unwrap();
        let identity = fake_identity(Vault::new_account_ref(), "sid-simulation");
        vault.insert(identity.clone(), fake_tokens("owner")).unwrap();
        // Real cross-Windows-user DPAPI QA requires a second OS test account.
        // This synthetic test proves the explicit SID binding gate independently.
        let other_sid = Vault {
            root: vault.root.clone(),
            host_id: vault.host_id.clone(),
            owner_sid: "S-1-5-21-99999999".into(),
        };
        assert_eq!(other_sid.read(&identity).err(), Some("SIWC_WINDOWS_USER_MISMATCH"));
        assert_eq!(vault.read(&identity).unwrap().version, 1);
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn compare_and_swap_refresh_only_one_winner_across_independent_handles() {
        let root = qa_root();
        let vault = Vault::open(&root).unwrap();
        let identity = fake_identity(Vault::new_account_ref(), "sub-1");
        vault.insert(identity.clone(), fake_tokens("initial")).unwrap();
        let barrier = Arc::new(Barrier::new(3));
        let mut handles = Vec::new();
        for index in 0..2 {
            let root = root.clone();
            let identity = identity.clone();
            let barrier = barrier.clone();
            handles.push(thread::spawn(move || {
                let parallel = Vault::open(&root).unwrap();
                barrier.wait();
                parallel.rotate_if_version(&identity, 1, fake_tokens(&index.to_string()))
            }));
        }
        barrier.wait();
        let mut results: Vec<_> = handles.into_iter().map(|h| h.join().unwrap()).collect();
        results.sort_by_key(|r| r.is_err());
        assert_eq!(results[0], Ok(2));
        assert_eq!(results[1], Err("SIWC_STALE_ROTATION"));
        assert_eq!(vault.read(&identity).unwrap().version, 2);
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn damage_and_partial_temp_never_reinitialize_or_reveal() {
        let root = qa_root();
        let vault = Vault::open(&root).unwrap();
        let identity = fake_identity(Vault::new_account_ref(), "sub-1");
        vault.insert(identity.clone(), fake_tokens("before")).unwrap();
        let original = vault.account_path(&identity.account_ref).unwrap();
        let mut ct = fs::read(&original).unwrap();
        let last = ct.len() - 1;
        ct[last] ^= 0x55;
        fs::write(&original, ct).unwrap();
        assert!(vault.read(&identity).is_err());
        // Only an isolated uncommitted transaction must be ignored on reopen.
        fs::write(vault.root.join(".siwc-txn-fake.tmp"), b"SIMULATED-INTERRUPTION").unwrap();
        assert!(Vault::open(&root).is_ok()); // stable host id remains sealed.
        assert!(vault.read(&identity).is_err()); // no silent replacement.
        let host = vault.root.join("host-id.dpapi");
        fs::write(&host, b"corrupt").unwrap();
        assert!(Vault::open(&root).is_err()); // corrupt host must not rotate.
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn pending_and_final_revocation_have_durable_fail_closed_status() {
        let root = qa_root();
        let vault = Vault::open(&root).unwrap();
        let identity = fake_identity(Vault::new_account_ref(), "sub-1");
        vault.insert(identity.clone(), fake_tokens("revocable")).unwrap();
        assert_eq!(vault.mark_revoke_pending(&identity, 1), Ok(2));
        assert_eq!(vault.rotate_if_version(&identity, 2, fake_tokens("unsafe")), Err("SIWC_REAUTH_REQUIRED"));
        assert_eq!(Vault::open(&root).unwrap().read(&identity).err(), Some("SIWC_REAUTH_REQUIRED"));
        assert_eq!(vault.status(&identity).unwrap(), (RevocationState::Pending, 2));
        assert_eq!(vault.pending_refresh_for_revoke(&identity).unwrap(), "SYNTHETIC-REFRESH-ONLY-revocable");
        assert_eq!(vault.finalize_revoked(&identity, 2), Ok(3));
        assert_eq!(Vault::open(&root).unwrap().read(&identity).err(), Some("SIWC_REAUTH_REQUIRED"));
        assert_eq!(vault.status(&identity).unwrap(), (RevocationState::Revoked, 3));
        assert_eq!(vault.pending_refresh_for_revoke(&identity).err(), Some("SIWC_REVOKE_NOT_PENDING"));
        assert_eq!(vault.mark_revoke_pending(&identity, 3), Err("SIWC_REVOKE_NOT_ACTIVE"));
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn locked_filename_cannot_be_renamed_or_replaced() {
        let root = qa_root();
        let vault = Vault::open(&root).unwrap();
        let locked = lock_root(&vault.root).unwrap();
        let original = vault.root.join("siwc.lock");
        let moved = vault.root.join("siwc-replaced.lock");
        let rename = fs::rename(&original, &moved);
        assert!(rename.is_err(), "OS must deny rename of a locked file");
        assert!(original.exists());
        assert!(!moved.exists());
        assert!(fs::remove_file(&original).is_err(), "OS must deny delete while handle holds");
        assert!(OpenOptions::new().write(true).create_new(true).open(&original).is_err());
        drop(locked);
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn independent_process_cas_worker() {
        let root = match std::env::var_os("YANCE_SIWC_CAS_CHILD_ROOT") {
            Some(root) => PathBuf::from(root), None => return,
        };
        let identity = fake_identity(
            std::env::var("YANCE_SIWC_CAS_ACCOUNT_REF").unwrap(), "child-cas-sub"
        );
        let instance = std::env::var("YANCE_SIWC_CAS_CHILD_ID").unwrap();
        let vault = Vault::open(&root).unwrap();
        let result = vault.rotate_if_version(&identity, 1, fake_tokens(&instance));
        let label = match result {
            Ok(2) => "WIN", Err("SIWC_STALE_ROTATION") => "STALE",
            _ => panic!("unexpected child CAS result"),
        };
        fs::write(root.join(format!("cas-{instance}.out")), label).unwrap();
    }
    #[test]
    fn independent_os_process_cas_exactly_one_commits() {
        let root = qa_root();
        let vault = Vault::open(&root).unwrap();
        let identity = fake_identity(Vault::new_account_ref(), "child-cas-sub");
        vault.insert(identity.clone(), fake_tokens("before")).unwrap();
        let binary = std::env::current_exe().unwrap();
        let mut children = Vec::new();
        for number in 0..2 {
            let mut cmd = std::process::Command::new(&binary);
            cmd.arg("--exact").arg("siwc_secure_store::tests::independent_process_cas_worker")
                .arg("--nocapture")
                .env("YANCE_SIWC_CAS_CHILD_ROOT", &root)
                .env("YANCE_SIWC_CAS_ACCOUNT_REF", &identity.account_ref)
                .env("YANCE_SIWC_CAS_CHILD_ID", number.to_string());
            children.push(cmd.spawn().unwrap());
        }
        for mut child in children {
            assert!(child.wait().unwrap().success(), "child Windows process failed");
        }
        let counts = (0..2).map(|num|
            fs::read_to_string(root.join(format!("cas-{num}.out"))).unwrap()
        ).collect::<Vec<_>>();
        assert_eq!(counts.iter().filter(|x| x.as_str() == "WIN").count(), 1);
        assert_eq!(counts.iter().filter(|x| x.as_str() == "STALE").count(), 1);
        assert_eq!(vault.read(&identity).unwrap().version, 2);
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn unsafe_reparse_point_is_rejected() {
        let root = qa_root();
        fs::create_dir_all(&root).unwrap();
        let target = root.join("real-data");
        fs::create_dir_all(&target).unwrap();
        let junction = root.join("junction");
        let status = std::process::Command::new("cmd.exe")
            .args(["/C", "mklink", "/J"])
            .arg(&junction).arg(&target)
            .output().unwrap();
        assert!(status.status.success(), "isolated Windows junction creation needed for test");
        assert_eq!(Vault::open(&junction).err(), Some("DPAPI_REPARSE_PATH_REJECTED"));
        fs::remove_dir(&junction).unwrap(); // never recurse through a junction
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn legacy_four_line_runtime_secrets_remain_byte_compatible() {
        let root = qa_root();
        let legacy = (0..4).map(|_| "unit-test-only-runtime-secret-with-adequate-length")
            .collect::<Vec<_>>().join("\n");
        let first = crate::dpapi::load_or_create(&root, || legacy.clone()).unwrap();
        assert_eq!(first.lines().count(), 4);
        let original = fs::read(root.join("runtime-secrets.dpapi")).unwrap();
        let vault = Vault::open(&root).unwrap();
        let _ = vault.host_id();
        let after = fs::read(root.join("runtime-secrets.dpapi")).unwrap();
        assert_eq!(original, after);
        assert_eq!(crate::dpapi::load_or_create(&root, || unreachable!()).unwrap(), first);
        fs::remove_dir_all(root).unwrap();
    }
}
