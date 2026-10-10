const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { extractVisibleMessengerProfile } = require(path.join(__dirname, "..", "extension", "extractor.js"));

function element(attrs = {}, text = "") {
  return {
    textContent: text,
    href: attrs.href || "",
    src: attrs.src || "",
    getAttribute(name) { return attrs[name] ?? null; },
    getBoundingClientRect() { return { width: 20, height: 20 }; },
  };
}

function run(url, {
  login = false,
  pageElements = [],
  providerAnchors = [],
  providerElements = [],
  messageAnchors = [],
  heading = null,
  avatar = null,
} = {}) {
  global.location = new URL(url);
  global.getComputedStyle = () => ({ display: "block", visibility: "visible" });
  global.document = {
    querySelector(selector) {
      if (selector.includes('input[type="password"]')) return login ? element() : null;
      if (selector.includes("img[src]")) return avatar;
      if (selector.includes("header h1") || selector.includes('[role="heading"]')) return heading;
      return null;
    },
    querySelectorAll(selector) {
      if (selector.includes("message_id=")) return messageAnchors;
      if (selector.includes("[data-page-id]")) return pageElements;
      if (selector.includes("[data-psid]")) return providerElements;
      if (selector.includes("a[href]")) return providerAnchors;
      return [];
    },
  };
  return extractVisibleMessengerProfile();
}

test("Window56 direct-provider-user shape remains deterministic", () => {
  const id = "61594960173176";
  const result = run(
    "https://www.facebook.com/messages/t/" + id + "?page_id=1203748086150141",
    {
      providerAnchors: [element({ href: "https://www.facebook.com/profile.php?id=" + id })],
      heading: element({}, " Visible Person "),
      avatar: element({ src: "https://scontent.example.net/avatar.jpg" }),
    }
  );
  assert.equal(result.ok, true);
  assert.equal(result.payload.binding_mode, "DIRECT_PROVIDER_USER");
  assert.equal(result.payload.page_account_id, "1203748086150141");
  assert.equal(result.payload.provider_user_id, id);
  assert.equal(result.payload.thread_id, id);
  assert.equal("provider_message_ids" in result.payload, false);
});

test("fresh ordinary Facebook Page route uses canonical provider-message mode", () => {
  const page = "1203748086150141";
  const mid = "mid.$cAA.live-1";
  const result = run(
    "https://www.facebook.com/messages/t/" + page + "/",
    {
      providerAnchors: [element({ href: "https://www.facebook.com/" + page + "/" })],
      messageAnchors: [
        element({ href: "https://www.facebook.com/messenger_media/?message_id=" +
          encodeURIComponent(mid) + "&thread_id=" + page }, "MESSAGE BODY MUST NOT CROSS"),
      ],
      heading: element({}, "Yeonhee Kim"),
    }
  );
  assert.equal(result.ok, true);
  assert.equal(result.payload.binding_mode, "CANONICAL_PROVIDER_MESSAGE");
  assert.equal(result.payload.page_account_id, page);
  assert.deepEqual(result.payload.provider_message_ids, [mid]);
  assert.equal("thread_id" in result.payload, false);
  assert.equal("provider_user_id" in result.payload, false);
  assert.equal(JSON.stringify(result.payload).includes("MESSAGE BODY MUST NOT CROSS"), false);
});

test("numeric /messages/t path is not treated as provider user in fresh Page shape", () => {
  const page = "1203748086150141";
  const result = run("https://www.facebook.com/messages/t/" + page + "/", {
    providerAnchors: [element({ href: "https://www.facebook.com/" + page + "/" })],
    heading: element({}, "Yeonhee Kim"),
  });
  assert.equal(result.ok, false);
  assert.equal(result.error, "MISSING_PROVIDER_MESSAGE_IDENTITY");
});

test("provider-message collection is bounded to five exact visible MIDs", () => {
  const page = "1203748086150141";
  const messageAnchors = Array.from({length: 9}, (_, index) =>
    element({href: "https://www.facebook.com/messenger_media/?message_id=mid." +
      index + "&thread_id=" + page})
  );
  const result = run("https://www.facebook.com/messages/t/" + page + "/", {
    messageAnchors,
    heading: element({}, "A"),
  });
  assert.equal(result.ok, true);
  assert.equal(result.payload.provider_message_ids.length, 5);
  assert.deepEqual(result.payload.provider_message_ids, ["mid.0", "mid.1", "mid.2", "mid.3", "mid.4"]);
});

test("message href for another thread cannot prove current Page identity", () => {
  const page = "1203748086150141";
  const result = run("https://www.facebook.com/messages/t/" + page + "/", {
    messageAnchors: [
      element({href: "https://www.facebook.com/messenger_media/?message_id=mid.live&thread_id=999"}),
    ],
    heading: element({}, "A"),
  });
  assert.equal(result.error, "MISSING_PROVIDER_MESSAGE_IDENTITY");
});

test("Business Suite and other origins fail closed", () => {
  assert.equal(run("https://business.facebook.com/messages/t/123?page_id=9").error, "DISALLOWED_ORIGIN");
  assert.equal(run("https://example.com/messages/t/123?page_id=9").error, "DISALLOWED_ORIGIN");
});

test("logged-out page fails closed", () => {
  assert.equal(run("https://www.facebook.com/messages/t/123?page_id=9", { login: true }).error, "LOGGED_OUT");
});

test("ambiguous explicit Page account identity fails closed", () => {
  const result = run("https://www.facebook.com/messages/t/123?page_id=9", {
    pageElements: [element({"data-page-id": "10"})],
    heading: element({}, "A"),
  });
  assert.equal(result.error, "AMBIGUOUS_ACCOUNT_IDENTITY");
});

test("non-canonical direct thread/user identity cannot fall back without MID proof", () => {
  const result = run("https://www.facebook.com/messages/t/123?page_id=9", {
    providerAnchors: [element({ href: "https://www.facebook.com/profile.php?id=456" })],
    heading: element({}, "A"),
  });
  assert.equal(result.error, "NON_CANONICAL_THREAD_IDENTITY");
});

test("avatar may be absent but invalid avatar is rejected", () => {
  const ok = run("https://www.messenger.com/t/123?page_id=9", {
    providerAnchors: [element({ href: "https://www.facebook.com/profile.php?id=123" })],
    heading: element({}, "A"),
  });
  assert.equal(ok.ok, true);
  assert.equal(ok.payload.avatar_url, null);

  const bad = run("https://www.messenger.com/t/123?page_id=9", {
    providerAnchors: [element({ href: "https://www.facebook.com/profile.php?id=123" })],
    heading: element({}, "A"),
    avatar: element({ src: "data:image/png;base64,abc" }),
  });
  assert.equal(bad.error, "INVALID_AVATAR_URL");
});

test("profile fields are still required after identity proof", () => {
  const id = "123";
  const result = run("https://www.facebook.com/messages/t/" + id + "?page_id=9", {
    providerAnchors: [element({href: "https://www.facebook.com/profile.php?id=" + id})],
  });
  assert.equal(result.error, "NO_VISIBLE_PROFILE_FIELDS");
});
