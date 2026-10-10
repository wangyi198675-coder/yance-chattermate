/* Bundled/static extractor. No network calls, no storage, no arbitrary selectors. */
function extractVisibleMessengerProfile() {
  const DIRECT_PROVIDER_USER = "DIRECT_PROVIDER_USER";
  const CANONICAL_PROVIDER_MESSAGE = "CANONICAL_PROVIDER_MESSAGE";
  const allowedOrigins = new Map([
    ["https://facebook.com", "facebook_messages"],
    ["https://www.facebook.com", "facebook_messages"],
    ["https://messenger.com", "messenger_thread"],
    ["https://www.messenger.com", "messenger_thread"],
  ]);

  const fail = (code) => ({ ok: false, error: code });
  const origin = String(location.origin || "").toLowerCase();
  const pageKind = allowedOrigins.get(origin);
  if (!pageKind) return fail("DISALLOWED_ORIGIN");

  const host = String(location.hostname || "").toLowerCase();
  if (host === "business.facebook.com" || host.endsWith(".business.facebook.com")) {
    return fail("BUSINESS_SUITE_FORBIDDEN");
  }

  if (/\/login(?:\/|$)/i.test(location.pathname || "") ||
      document.querySelector('input[type="password"], form[action*="login"]')) {
    return fail("LOGGED_OUT");
  }

  const numeric = (value) => {
    const text = String(value || "").trim();
    return /^[0-9]{1,64}$/.test(text) ? text : null;
  };
  const messengerMid = (value) => {
    const text = String(value || "").trim();
    return /^mid\.[A-Za-z0-9_$.:=-]{1,511}$/.test(text) ? text : null;
  };
  const uniqueOne = (values) => {
    const set = [...new Set(values.filter(Boolean))];
    return set.length === 1 ? set[0] : null;
  };
  const visible = (el) => {
    if (!el) return false;
    if (typeof el.getBoundingClientRect !== "function") return true;
    const rect = el.getBoundingClientRect();
    const style = typeof getComputedStyle === "function" ? getComputedStyle(el) : null;
    return rect.width > 0 && rect.height > 0 &&
      (!style || (style.display !== "none" && style.visibility !== "hidden"));
  };
  const profileIdFromHref = (href) => {
    try {
      const u = new URL(href, location.href);
      if (!/(^|\.)facebook\.com$/i.test(u.hostname)) return null;
      const q = numeric(u.searchParams.get("id"));
      if (q) return q;
      const m = u.pathname.match(/^\/([0-9]{1,64})(?:\/|$)/);
      return m ? numeric(m[1]) : null;
    } catch (_) {
      return null;
    }
  };

  const url = new URL(location.href);
  const pathMatch = pageKind === "facebook_messages"
    ? (location.pathname || "").match(/^\/messages\/t\/([0-9]{1,64})(?:\/|$)/)
    : (location.pathname || "").match(/^\/(?:messages\/)?t\/([0-9]{1,64})(?:\/|$)/);
  const pathIdentity = pathMatch ? numeric(pathMatch[1]) : null;
  if (!pathIdentity) return fail("MISSING_THREAD_IDENTITY");

  const pageAccountCandidates = [];
  for (const key of ["page_id", "mailbox_id"]) {
    const value = numeric(url.searchParams.get(key));
    if (value) pageAccountCandidates.push(value);
  }
  for (const el of document.querySelectorAll("[data-page-id],[data-pageid],[data-owner-page-id]")) {
    if (!visible(el)) continue;
    for (const attr of ["data-page-id", "data-pageid", "data-owner-page-id"]) {
      const value = numeric(el.getAttribute(attr));
      if (value) pageAccountCandidates.push(value);
    }
  }
  const explicitPageAccountId = uniqueOne(pageAccountCandidates);
  if (pageAccountCandidates.length && !explicitPageAccountId) {
    return fail("AMBIGUOUS_ACCOUNT_IDENTITY");
  }

  const providerCandidates = [];
  for (const key of ["provider_user_id", "participant_id", "psid"]) {
    const value = numeric(url.searchParams.get(key));
    if (value) providerCandidates.push(value);
  }
  for (const el of document.querySelectorAll("[data-psid],[data-provider-user-id]")) {
    if (!visible(el)) continue;
    for (const attr of ["data-psid", "data-provider-user-id"]) {
      const value = numeric(el.getAttribute(attr));
      if (value) providerCandidates.push(value);
    }
  }

  const profileAnchors = document.querySelectorAll(
    'main header a[href], main [role="banner"] a[href], main [role="heading"] a[href], [role="main"] [role="heading"] a[href]'
  );
  for (const anchor of profileAnchors) {
    if (!visible(anchor)) continue;
    const value = profileIdFromHref(anchor.getAttribute("href") || anchor.href);
    if (value) providerCandidates.push(value);
  }
  const providerUserId = uniqueOne(providerCandidates);

  let bindingMode = null;
  let pageAccountId = null;
  let threadId = null;
  let directProviderUserId = null;
  let providerMessageIds = null;

  // Window56 direct-provider-user shape remains supported only when the page
  // account is independently visible and the path/profile identity converges.
  if (explicitPageAccountId && providerUserId && providerUserId === pathIdentity) {
    bindingMode = DIRECT_PROVIDER_USER;
    pageAccountId = explicitPageAccountId;
    threadId = pathIdentity;
    directProviderUserId = providerUserId;
  } else {
    // Fresh ordinary Facebook can expose /messages/t/<PageID>. In this mode the
    // numeric path is Page context, never a contact guess. Exact visible MIDs are
    // the identity bridge and the backend must re-validate the Page account.
    pageAccountId = explicitPageAccountId || pathIdentity;
    const mids = [];
    const messageAnchors = document.querySelectorAll(
      'main a[href*="message_id="], [role="main"] a[href*="message_id="]'
    );
    for (const anchor of messageAnchors) {
      if (mids.length >= 5) break;
      if (!visible(anchor)) continue;
      try {
        const href = String(anchor.getAttribute("href") || anchor.href || "");
        const u = new URL(href, location.href);
        const messageHost = String(u.hostname || "").toLowerCase();
        if (!allowedOrigins.has(u.origin.toLowerCase()) &&
            !/(^|\.)facebook\.com$/i.test(messageHost) &&
            !/(^|\.)messenger\.com$/i.test(messageHost)) {
          continue;
        }
        const messageId = messengerMid(u.searchParams.get("message_id"));
        const linkThreadId = numeric(u.searchParams.get("thread_id"));
        if (!messageId || linkThreadId !== pageAccountId) continue;
        if (!mids.includes(messageId)) mids.push(messageId);
      } catch (_) {
        continue;
      }
    }
    if (!mids.length) {
      if (!explicitPageAccountId && providerCandidates.length > 1) {
        return fail("AMBIGUOUS_PROVIDER_USER_IDENTITY");
      }
      if (!explicitPageAccountId && providerUserId === pathIdentity) {
        return fail("MISSING_PROVIDER_MESSAGE_IDENTITY");
      }
      return fail(providerCandidates.length
        ? "NON_CANONICAL_THREAD_IDENTITY"
        : "MISSING_PROVIDER_MESSAGE_IDENTITY");
    }
    bindingMode = CANONICAL_PROVIDER_MESSAGE;
    providerMessageIds = mids;
  }

  let displayName = null;
  const heading = document.querySelector(
    'main header h1, main header h2, main [role="banner"] h1, main [role="banner"] h2, main [role="heading"], [role="main"] [role="heading"]'
  );
  if (visible(heading)) {
    const text = String(heading.textContent || "").replace(/\s+/g, " ").trim();
    if (text && text.length <= 256) displayName = text;
  }

  let avatarUrl = null;
  const avatar = document.querySelector(
    'main header img[src], main [role="banner"] img[src], [role="main"] [role="heading"] img[src]'
  );
  if (visible(avatar)) {
    const raw = String(avatar.getAttribute("src") || avatar.src || "").trim();
    if (raw) {
      try {
        const parsed = new URL(raw, location.href);
        if (parsed.protocol !== "https:" || parsed.username !== "" || parsed.password !== "" ||
            parsed.href.length > 2048) {
          return fail("INVALID_AVATAR_URL");
        }
        avatarUrl = parsed.href;
      } catch (_) {
        return fail("INVALID_AVATAR_URL");
      }
    }
  }

  if (!displayName && !avatarUrl) return fail("NO_VISIBLE_PROFILE_FIELDS");

  const payload = {
    schema_version: 1,
    binding_mode: bindingMode,
    page_account_id: pageAccountId,
    display_name: displayName,
    avatar_url: avatarUrl,
    origin,
    page_kind: pageKind,
  };
  if (bindingMode === DIRECT_PROVIDER_USER) {
    payload.thread_id = threadId;
    payload.provider_user_id = directProviderUserId;
  } else {
    payload.provider_message_ids = providerMessageIds;
  }
  return { ok: true, payload };
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { extractVisibleMessengerProfile };
}
