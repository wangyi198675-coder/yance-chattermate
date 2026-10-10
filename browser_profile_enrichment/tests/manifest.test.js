const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");

const extensionDir = path.join(__dirname, "..", "extension");
const manifest = JSON.parse(fs.readFileSync(path.join(extensionDir, "manifest.json"), "utf8"));

function extensionIdFromKey(base64Key) {
  const der = Buffer.from(base64Key, "base64");
  const first16 = crypto.createHash("sha256").update(der).digest().subarray(0, 16);
  const alphabet = "abcdefghijklmnop";
  let out = "";
  for (const byte of first16) out += alphabet[byte >> 4] + alphabet[byte & 15];
  return out;
}

test("manifest uses only the admitted MV3 permissions", () => {
  assert.equal(manifest.manifest_version, 3);
  assert.deepEqual([...manifest.permissions].sort(), ["activeTab", "nativeMessaging", "scripting"].sort());
  assert.equal("host_permissions" in manifest, false);
  assert.equal("content_scripts" in manifest, false);
  for (const forbidden of ["cookies", "debugger", "webRequest", "tabs", "storage", "<all_urls>"]) {
    assert.equal(JSON.stringify(manifest).includes(forbidden), false, forbidden);
  }
});

test("manifest key pins the exact native-host allowed extension id", () => {
  assert.equal(extensionIdFromKey(manifest.key), "hfcmihknnigilcafmalchjopmhhkihjf");
  assert.equal(manifest.background.service_worker, "background.js");
});
