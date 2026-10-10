importScripts("extractor.js");

const NATIVE_HOST = "com.yance.browser_profile_enrichment";
const ALLOWED_ORIGINS = new Set([
  "https://facebook.com",
  "https://www.facebook.com",
  "https://messenger.com",
  "https://www.messenger.com",
]);

function originOf(rawUrl) {
  try {
    return new URL(rawUrl).origin.toLowerCase();
  } catch (_) {
    return "";
  }
}

async function badge(tabId, text) {
  try {
    await chrome.action.setBadgeText({ tabId, text });
  } catch (_) {}
}

chrome.action.onClicked.addListener(async (tab) => {
  const tabId = tab && tab.id;
  const initialUrl = tab && tab.url;
  if (typeof tabId !== "number" || !initialUrl || !ALLOWED_ORIGINS.has(originOf(initialUrl))) {
    if (typeof tabId === "number") await badge(tabId, "ERR");
    return;
  }

  try {
    const injection = await chrome.scripting.executeScript({
      target: { tabId },
      func: extractVisibleMessengerProfile,
    });
    const result = injection && injection[0] && injection[0].result;
    if (!result || result.ok !== true || !result.payload) {
      await badge(tabId, "HOLD");
      return;
    }

    // activeTab is tied to the user gesture and current navigation. Re-read the
    // tab immediately before crossing the native boundary; navigation or an
    // origin change invalidates this one-shot request.
    const current = await chrome.tabs.get(tabId);
    if (!current || current.url !== initialUrl ||
        !ALLOWED_ORIGINS.has(originOf(current.url)) ||
        result.payload.origin !== originOf(current.url)) {
      await badge(tabId, "HOLD");
      return;
    }

    const response = await chrome.runtime.sendNativeMessage(NATIVE_HOST, result.payload);
    await badge(tabId, response && response.ok ? "OK" : "HOLD");
  } catch (_) {
    await badge(tabId, "HOLD");
  }
});
