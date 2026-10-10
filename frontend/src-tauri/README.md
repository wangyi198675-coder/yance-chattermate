# Windows private runtime bridge (W355)

Native shell: Tauri 2.12.0 + Velopack 1.2.161. Process supervision: **official Process Compose 1.122.0** only. Backend/database/worker owner: existing ChatterMate + PostgreSQL + Garnet. No separate supervisor, database, scheduler or registry.

## Frozen data authority and immutable package

* Installed binaries resolve relative to the Yance.exe directory: backend/ and private-runtime/{postgresql,garnet,python,dotnet,process-compose}. No binary writes to Program Files or Velopack staging.
* One durable installed-user root: %LOCALAPPDATA%\Yance\data. Native YANCE_DATA_ROOT is exactly this root, PostgreSQL storage is data/postgres-data; local Process Compose configuration also lives beneath it.
* C:\YanceController\current-user-data is legacy read-only provenance. First install with this populated legacy data tree but without a new PG root intentionally fails closed (LEGACY_DATA_IMPORT_REQUIRES_APPROVAL). Only separately approved import can transfer legacy user data; never overwrite or delete it silently.
* YANCE_W355_QA_DATA_ROOT is debug-only, compiled out of release builds. Windows private runtime needs no globally installed Python, PostgreSQL, .NET, Docker or WSL.

## CurrentUser DPAPI custody

* Only data/runtime-secrets.dpapi persists the DB password, JWT, conversation and Fernet keys; the file contains only versioned Windows CurrentUser DPAPI ciphertext. Current Windows user SID and SYSTEM are the only permitted DACL principals for the root and encrypted file.
* Generated once and reused on restart. Decryption failure never regenerates keys or wipes the DB. Recover as the same Windows user with an authorized backup of the Windows profile and DPAPI master keys; any change of ownership or rotation is a separately approved migration.
* A historic plaintext private-secrets.txt in the selected root is detected and fails closed. No automatic plaintext migration or deletion.
* Native initdb uses its upstream --pwfile interface backed by an unguessable one-shot Windows named pipe (first-instance). Password bytes stay in memory, are not written to disk or argv and are not added to the Process Compose YAML/log. Decrypted keys appear only in the private child process environment.

## Startup and shutdown

Loopback ports: backend 8000, PG 55435, Garnet 56355, official Process Compose 58355. Preflight rejects existing listeners so a foreign HTTP 200 can never count as Yance READY. The Tauri single-instance plugin is retained.

Order: protected user data -> DPAPI -> private PostgreSQL initialization -> official Process Compose PG/Garnet -> check/create yance DB -> canonical Alembic upgrade -> native API and knowledge worker -> /health and /api/v1/organizations/setup-status HTTP 200 -> navigation to /yance. The existing Vue router performs authorized private bootstrap. On failure, an error code (not credentials) is recorded, owned processes are stopped, and the native startup error/retry page is used.

**Vendor release HOLD:** Process Compose v1.122.0 on Windows can force-stop child processes without delivering graceful signals; W350's private patch is neither bundled nor qualified. Do not claim graceful PostgreSQL/worker shutdown or release GREEN until official upstream qualification. W351 packs only after Controller admits this desktop-only commit; W356 owns installed Setup.exe, 920x620 Composer, restart and uninstall UAT.
