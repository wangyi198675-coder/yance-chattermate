'use strict';

// W397: isolated GramJS MTProto USER transport, ported from V21
// backend/services/telegramAdapter.js @ 5c31f8b. Native Python owns canonical
// routing/persistence; this process does not own CRM, delivery DB or credentials.
// Stdout is ONLY line-framed IPC. NEVER print session, OTP, QR token or password.
const readline = require('node:readline');
const { TelegramClient } = require('telegram');
const { StringSession } = require('telegram/sessions');
const { NewMessage } = require('telegram/events');
console.log = () => {};
console.warn = () => {};
const io = process.stdout;
let client = null;
let authorized = false;
let authGeneration = 0;
let waitingCode = null;
let waitingPassword = null;
let currentPhone = '';
let appCredentials = null;
const MAX_MEDIA = 16 * 1024 * 1024;
const MAX_LINE = 24 * 1024 * 1024;
function emit(event, payload = {}) {
  io.write(JSON.stringify({ event, ...payload }) + '\n');
}
function response(id, result) {
  io.write(JSON.stringify({ id, ok: true, result: result || {} }) + '\n');
}
function failure(id, code) {
  io.write(JSON.stringify({ id, ok: false, error_code: code }) + '\n');
}
function rejectDeferred(deferred, code) {
  if (deferred) deferred.reject(Object.assign(new Error(code), {code}));
}
function deferredChallenge(step, generation) {
  return new Promise((resolve, reject) => {
    if (generation !== authGeneration) {
      reject(new Error('STALE_LOGIN')); return;
    }
    const handle = {resolve, reject};
    if (step === 'code') waitingCode = handle;
    if (step === 'password') waitingPassword = handle;
    emit('challenge', {step});
    const timer = setTimeout(() => {
      if (step === 'code' && waitingCode === handle) waitingCode = null;
      if (step === 'password' && waitingPassword === handle) waitingPassword = null;
      reject(Object.assign(new Error('LOGIN_CHALLENGE_EXPIRED'), {code:'LOGIN_CHALLENGE_EXPIRED'}));
    }, 300000);
    timer.unref?.();
    // Ensure timer does not keep process open beyond a disconnected client.
    const oldResolve = handle.resolve, oldReject = handle.reject;
    handle.resolve = value => {clearTimeout(timer); oldResolve(value);};
    handle.reject = err => {clearTimeout(timer); oldReject(err);};
  });
}
async function stopClient(logout = false) {
  authGeneration++;
  rejectDeferred(waitingCode, 'LOGIN_CANCELLED');
  rejectDeferred(waitingPassword, 'LOGIN_CANCELLED');
  waitingCode = null;
  waitingPassword = null;
  const old = client;
  client = null;
  authorized = false;
  currentPhone = '';
  if (old) {
    try {
      if (logout) await old.logOut();
      else await old.disconnect();
    } catch (_) { /* never leak provider error text */ }
  }
}
function ensureClient() {
  if (!client) throw Object.assign(new Error('NO_CLIENT'), {code:'NO_CLIENT'});
  return client;
}
function requireAuthorized() {
  if (!client || !authorized) throw Object.assign(new Error('NOT_AUTHORIZED'), {code:'NOT_AUTHORIZED'});
  return client;
}
function userIdentity(me) {
  return {
    id: String(me?.id || ''),
    username: String(me?.username || ''),
    name: [me?.firstName, me?.lastName].filter(Boolean).join(' ') || String(me?.username || '')
  };
}
function messagePayload(message, peerOverride = '') {
  const peer = String(peerOverride || message?.chatId || message?.peerId?.userId || message?.peerId?.channelId || '');
  const id = String(message?.id || '');
  return {
    external_conversation_id: peer,
    // ChatterMate's provider identity unique index lacks peer_id; use composite.
    external_message_id: peer + ':' + id,
    remote_message_id: id,
    external_account_id: '',
    direction: message?.out ? 'outbound' : 'inbound',
    text: String(message?.message || ''),
    sender_id: String(message?.senderId || ''),
    created_at: message?.date ? new Date(Number(message.date) * 1000).toISOString() : null,
    has_media: Boolean(message?.media),
    media_ref: message?.media ? peer + ':' + id : null,
    from_me: Boolean(message?.out),
  };
}
async function onAuthenticated(generation) {
  if (generation !== authGeneration || !client) return;
  const me = await client.getMe();
  if (!me?.id) throw Object.assign(new Error('IDENTITY_MISSING'), {code:'IDENTITY_MISSING'});
  const session = client.session.save();
  if (!session) throw Object.assign(new Error('SESSION_EXPORT_MISSING'), {code:'SESSION_EXPORT_MISSING'});
  authorized = true;
  emit('authenticated', {session, user: userIdentity(me)});
}
async function startQr() {
  const c = ensureClient();
  if (authorized) return {already_authorized: true};
  const generation = ++authGeneration;
  const {apiId, apiHash} = appCredentials;
  void c.signInUserWithQrCode(
    {apiId, apiHash},
    {
      qrCode: async ({token}) => {
        if (generation === authGeneration) {
          emit('challenge', {step:'qr', qr_uri:'tg://login?token=' + token.toString('base64url')});
        }
      },
      password: async hint => {
        if (generation !== authGeneration) throw new Error('STALE_LOGIN');
        emit('challenge', {step:'password', hint: String(hint || '').slice(0,100)});
        return deferredChallenge('password', generation);
      },
      onError: async err => {
        if (generation === authGeneration) {
          emit('error', {code: safeCode(err)});
        }
        return false;
      },
    }
  ).then(() => onAuthenticated(generation)).catch(err => {
    if (generation === authGeneration) emit('error', {code:safeCode(err)});
  });
  return {started:true, kind:'qr'};
}
async function startPhone(phone) {
  const c = ensureClient();
  if (authorized) return {already_authorized:true};
  const generation = ++authGeneration;
  currentPhone = phone;
  void c.start({
    phoneNumber: async () => phone,
    phoneCode: async () => deferredChallenge('code', generation),
    password: async hint => {
      emit('challenge', {step:'password', hint:String(hint || '').slice(0,100)});
      return deferredChallenge('password', generation);
    },
    onError: async err => {
      if (generation === authGeneration) emit('error', {code:safeCode(err)});
      return false;
    }
  }).then(() => onAuthenticated(generation)).catch(err => {
    if (generation === authGeneration) emit('error', {code:safeCode(err)});
  });
  return {started:true,kind:'phone'};
}
function safeCode(e) {
  const code = String(e?.code || e?.errorMessage || 'TELEGRAM_PROVIDER_ERROR');
  // Restrict output to finite enum-ish error token; never echo sensitive values.
  return /^[A-Z0-9_]{3,80}$/.test(code) ? code : 'TELEGRAM_PROVIDER_ERROR';
}
async function operate(method, args) {
  if (method === 'connect') {
    if (client) throw Object.assign(new Error('ALREADY_ACTIVE'), {code:'ALREADY_ACTIVE'});
    const apiId = Number(args.api_id), apiHash = String(args.api_hash || '');
    if (!Number.isSafeInteger(apiId) || apiId <= 0 || !/^[a-f0-9]{32}$/i.test(apiHash)) {
      throw Object.assign(new Error('INVALID_API_CREDENTIALS'), {code:'INVALID_API_CREDENTIALS'});
    }
    appCredentials = {apiId, apiHash};
    client = new TelegramClient(new StringSession(String(args.session || '')),
      apiId, apiHash, {connectionRetries:5, autoReconnect:true});
    client.setLogLevel?.('error');
    client.addEventHandler(event => {
      try { emit('message', {message: messagePayload(event.message)}); } catch (_) {}
    }, new NewMessage({}));
    await client.connect();
    authorized = Boolean(await client.checkAuthorization());
    if (authorized) await onAuthenticated(authGeneration);
    return {authorized};
  }
  if (method === 'disconnect') {
    await stopClient(false); emit('disconnected'); return {disconnected:true};
  }
  if (method === 'logout') {
    requireAuthorized(); await stopClient(true); emit('disconnected'); return {logged_out:true};
  }
  if (method === 'status') {
    if (!client || !authorized) return {connected:false, authorized:false};
    try {
      const live = Boolean(await client.checkAuthorization());
      if (!live) authorized = false;
      return {connected:live, authorized:live};
    } catch (_) {
      return {connected:false, authorized:false};
    }
  }
  if (method === 'start_qr') return startQr();
  if (method === 'start_phone') {
    if (!/^\+[1-9][0-9]{6,14}$/.test(String(args.phone || ''))) {
      throw Object.assign(new Error('PHONE_FORMAT_INVALID'), {code:'PHONE_FORMAT_INVALID'});
    }
    return startPhone(String(args.phone));
  }
  if (method === 'submit_code') {
    if (!waitingCode) throw Object.assign(new Error('NO_CODE_CHALLENGE'), {code:'NO_CODE_CHALLENGE'});
    const challenge = waitingCode; waitingCode = null;
    challenge.resolve(String(args.code || '')); return {received:true};
  }
  if (method === 'submit_password') {
    if (!waitingPassword) throw Object.assign(new Error('NO_PASSWORD_CHALLENGE'), {code:'NO_PASSWORD_CHALLENGE'});
    const challenge = waitingPassword; waitingPassword = null;
    challenge.resolve(String(args.password || '')); return {received:true};
  }
  const c = requireAuthorized();
  if (method === 'send_text' || method === 'send_media') {
    const peer = String(args.peer || '');
    if (!peer || peer.startsWith('bot:')) {
      throw Object.assign(new Error('INVALID_PEER'), {code:'INVALID_PEER'});
    }
    let sent;
    if (method === 'send_text') {
      sent = await c.sendMessage(peer, {message:String(args.text || '')});
    } else {
      const raw = String(args.media_base64 || '');
      if (raw.length > MAX_MEDIA * 1.4) throw Object.assign(new Error('MEDIA_TOO_LARGE'), {code:'MEDIA_TOO_LARGE'});
      const binary = Buffer.from(raw, 'base64');
      if (!binary.length || binary.length > MAX_MEDIA) {
        throw Object.assign(new Error('MEDIA_INVALID'), {code:'MEDIA_INVALID'});
      }
      sent = await c.sendFile(peer, {file:binary, caption:String(args.caption || ''),
        forceDocument:true,
        fileName:String(args.filename || 'attachment').replace(/^.*[\\/]/, '').replace(/[\x00-\x1f]/g, '').slice(0,128)});
    }
    return {id: String(sent?.id || '')};
  }
  if (method === 'download_media') {
    const peer = String(args.peer || ''), id = Number(args.message_id);
    if (!peer || !Number.isSafeInteger(id) || id <= 0) throw Object.assign(new Error('MEDIA_REF_INVALID'), {code:'MEDIA_REF_INVALID'});
    const result = await c.getMessages(peer, {ids:[id]});
    const item = result?.[0];
    if (!item?.media) throw Object.assign(new Error('MEDIA_NOT_FOUND'), {code:'MEDIA_NOT_FOUND'});
    const bytes = await c.downloadMedia(item.media);
    if (!Buffer.isBuffer(bytes) || !bytes.length || bytes.length > MAX_MEDIA) {
      throw Object.assign(new Error('MEDIA_SIZE_INVALID'), {code:'MEDIA_SIZE_INVALID'});
    }
    return {base64:bytes.toString('base64')};
  }
  if (method === 'dialogs') {
    const limit = Math.max(1, Math.min(2000, Number(args.limit) || 100));
    const dialogs = await c.getDialogs({limit});
    return {dialogs: Array.from(dialogs || [], dialog => ({
      external_conversation_id: String(dialog.id || dialog.entity?.id || ''),
      title: String(dialog.title || dialog.entity?.username || '').slice(0,256),
      unread_count: Number(dialog.unreadCount || 0),
      conversation_kind: dialog.isGroup ? 'group' : dialog.isChannel ? 'channel' : 'private',
    })).filter(item => item.external_conversation_id)};
  }
  if (method === 'backfill') {
    const peer = String(args.peer || '');
    const offsetId = Number(args.offset_id || 0);
    const limit = Math.max(1, Math.min(100, Number(args.limit) || 100));
    if (!peer || !Number.isSafeInteger(offsetId) || offsetId < 0) {
      throw Object.assign(new Error('BACKFILL_CURSOR_INVALID'), {code:'BACKFILL_CURSOR_INVALID'});
    }
    const values = await c.getMessages(peer, {limit, ...(offsetId ? {offsetId} : {})});
    return {messages:Array.from(values || [], m => messagePayload(m, peer))};
  }
  throw Object.assign(new Error('OPERATION_UNSUPPORTED'), {code:'OPERATION_UNSUPPORTED'});
}
const rl = readline.createInterface({input:process.stdin, crlfDelay:Infinity, terminal:false});
rl.on('line', line => {
  if (line.length > MAX_LINE) return;
  let frame;
  try { frame = JSON.parse(line); } catch (_) { return; }
  if (!Number.isSafeInteger(frame?.id) || typeof frame?.method !== 'string') return;
  Promise.resolve(operate(frame.method, frame.params || {}))
    .then(value => response(frame.id, value))
    .catch(error => failure(frame.id, safeCode(error)));
});
rl.on('close', () => {void stopClient(false).then(() => process.exit(0));});
