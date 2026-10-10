const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const source = fs.readFileSync(path.join(__dirname, "..", "extension", "background.js"), "utf8");

test("only explicit toolbar action triggers extraction", () => {
  assert.match(source, /chrome\.action\.onClicked\.addListener/);
  for (const forbidden of [
    "tabs.onUpdated", "tabs.onCreated", "runtime.onMessage", "runtime.onConnect",
    "alarms.", "setInterval(", "setTimeout(", "webNavigation", "commands.onCommand"
  ]) {
    assert.equal(source.includes(forbidden), false, forbidden);
  }
});

test("one-shot current-tab path rechecks navigation before native messaging", () => {
  assert.match(source, /target:\s*\{\s*tabId\s*\}/);
  assert.match(source, /chrome\.tabs\.get\(tabId\)/);
  assert.match(source, /current\.url\s*!==\s*initialUrl/);
  assert.match(source, /chrome\.runtime\.sendNativeMessage\(NATIVE_HOST/);
  assert.equal(source.includes("connectNative"), false);
});


const vm = require("node:vm");

function loadBackground({currentUrl}) {
  let listener = null;
  const calls = {execute: [], native: [], badges: []};
  const context = {
    URL,
    extractVisibleMessengerProfile() {},
    importScripts() {},
    chrome: {
      action: {
        onClicked: {addListener(fn) { listener = fn; }},
        async setBadgeText(value) { calls.badges.push(value); },
      },
      scripting: {
        async executeScript(options) {
          calls.execute.push(options);
          return [{
            result: {
              ok: true,
              payload: {
                schema_version: 1,
                binding_mode: "DIRECT_PROVIDER_USER",
                page_account_id: "9",
                thread_id: "123",
                provider_user_id: "123",
                display_name: "A",
                avatar_url: null,
                origin: "https://www.facebook.com",
                page_kind: "facebook_messages",
              },
            },
          }];
        },
      },
      tabs: {
        async get(tabId) { return {id: tabId, url: currentUrl}; },
      },
      runtime: {
        async sendNativeMessage(host, payload) {
          calls.native.push({host, payload});
          return {ok: true};
        },
      },
    },
  };
  vm.runInNewContext(source, context, {filename: "background.js"});
  return {listener, calls};
}

test("navigation race suppresses the native boundary", async () => {
  const initial = "https://www.facebook.com/messages/t/123?page_id=9";
  const {listener, calls} = loadBackground({
    currentUrl: "https://www.facebook.com/messages/t/456?page_id=9",
  });
  await listener({id: 17, url: initial});
  assert.equal(calls.execute.length, 1);
  assert.equal(calls.execute[0].target.tabId, 17);
  assert.equal(calls.native.length, 0);
  assert.equal(calls.badges.at(-1).text, "HOLD");
});

test("same current tab and URL permits exactly one one-shot native send", async () => {
  const initial = "https://www.facebook.com/messages/t/123?page_id=9";
  const {listener, calls} = loadBackground({currentUrl: initial});
  await listener({id: 21, url: initial});
  assert.equal(calls.execute.length, 1);
  assert.equal(calls.execute[0].target.tabId, 21);
  assert.equal(calls.native.length, 1);
  assert.equal(calls.native[0].host, "com.yance.browser_profile_enrichment");
  assert.equal(calls.badges.at(-1).text, "OK");
});

test("disallowed initial origin never executes or crosses native messaging", async () => {
  const {listener, calls} = loadBackground({currentUrl: "https://example.com/"});
  await listener({id: 8, url: "https://example.com/"});
  assert.equal(calls.execute.length, 0);
  assert.equal(calls.native.length, 0);
  assert.equal(calls.badges.at(-1).text, "ERR");
});
