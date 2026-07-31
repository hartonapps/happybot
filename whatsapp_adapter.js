const readline = require('readline');
const { spawn } = require('child_process');
const fs = require('fs');
const makeWASocket = require('@whiskeysockets/baileys').default;
const { DisconnectReason, downloadMediaMessage, useMultiFileAuthState } = require('@whiskeysockets/baileys');
const P = require('pino');

const AUTH_DIR = 'auth_info';
const MAX_RECONNECTS = 5;
const RECONNECT_DELAY_MS = 5000;
const COMMAND_PREFIXES = ['.', '!', '/'];

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function clearSession(reason) {
  if (fs.existsSync(AUTH_DIR)) {
    fs.rmSync(AUTH_DIR, { recursive: true, force: true });
    console.log(`Removed saved WhatsApp session (${reason}). Run \`node connect.js\` to pair again.`);
  }
}

function textFromMessage(message) {
  return (
    message.conversation ||
    message.extendedTextMessage?.text ||
    message.imageMessage?.caption ||
    message.videoMessage?.caption ||
    ''
  );
}

function actualMessage(message) {
  return message.viewOnceMessage?.message || message.viewOnceMessageV2?.message || message;
}

function mediaKind(message) {
  const content = actualMessage(message);
  if (content.imageMessage) return 'image';
  if (content.videoMessage) return 'video';
  if (content.audioMessage) return 'audio';
  if (content.documentMessage) return 'document';
  if (content.stickerMessage) return 'sticker';
  return null;
}

function isCommandText(text) {
  return COMMAND_PREFIXES.some((prefix) => text.startsWith(prefix));
}

function botJid(sock) {
  return `${sock.user.id.split(':')[0]}@s.whatsapp.net`;
}

function startPythonCore(sock, messageCache, adapterState) {
  const py = spawn(process.env.PYTHON || 'python', ['main.py', '--stdio'], {
    cwd: process.cwd(),
    stdio: ['pipe', 'pipe', 'inherit']
  });

  const pyLines = readline.createInterface({ input: py.stdout });
  pyLines.on('line', async (line) => {
    if (!line.trim().startsWith('{')) {
      console.log(line);
      return;
    }
    const action = JSON.parse(line);
    console.log(`[action] ${action.action}`);
    if (action.action === 'send_message') {
      const options = action.reply_to && messageCache.has(action.reply_to) ? { quoted: messageCache.get(action.reply_to) } : {};
      await sock.sendMessage(action.chat_id, { text: action.text }, options);
    }
    if (action.action === 'react') {
      await sock.sendMessage(action.chat_id, { react: { text: action.emoji, key: { id: action.message_id, remoteJid: action.chat_id } } });
    }
    if (action.action === 'set_reactsave') {
      adapterState.reactsave = Boolean(action.enabled);
      console.log(`[reactsave] ${adapterState.reactsave ? 'ON' : 'OFF'}`);
    }
  });

  py.on('exit', (code) => {
    if (code !== 0) console.log(`Python core exited with code ${code}.`);
  });

  return py;
}

async function saveReactedMedia(sock, reactionMessage, messageCache) {
  const targetKey = reactionMessage.key;
  const target = messageCache.get(targetKey.id);
  if (!target?.message) {
    console.log(`[reactsave] Could not find reacted message ${targetKey.id} in cache.`);
    return;
  }

  const kind = mediaKind(target.message);
  if (!kind) {
    console.log(`[reactsave] Reacted message ${targetKey.id} has no downloadable media.`);
    return;
  }

  const buffer = await downloadMediaMessage(target, 'buffer', {}, { logger: P({ level: 'silent' }) });
  const owner = botJid(sock);
  const payload = { caption: `Saved by HappyBot from ${target.key.remoteJid}` };
  payload[kind] = buffer;
  if (kind === 'sticker') {
    delete payload.caption;
  }
  await sock.sendMessage(owner, payload);
  console.log(`[reactsave] Sent ${kind} from ${target.key.remoteJid} to ${owner}.`);
}

async function start(attempt = 1) {
  let py = null;
  const messageCache = new Map();
  const adapterState = { reactsave: false };
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  if (!state.creds.registered) {
    console.log('No saved WhatsApp session found. Run `node connect.js` first, or run `python main.py` to launch setup automatically.');
    process.exit(1);
  }

  const sock = makeWASocket({
    auth: state,
    logger: P({ level: 'silent' }),
    printQRInTerminal: false,
    markOnlineOnConnect: false,
    syncFullHistory: false
  });

  sock.ev.on('creds.update', saveCreds);
  sock.ev.on('connection.update', async ({ connection, lastDisconnect }) => {
    if (connection === 'open') {
      console.log('HappyBot connected to WhatsApp. Loading plugins now...');
      py = startPythonCore(sock, messageCache, adapterState);
      return;
    }
    if (connection === 'close') {
      const code = lastDisconnect?.error?.output?.statusCode;
      if (py) py.kill();
      if (code === DisconnectReason.loggedOut) {
        clearSession('WhatsApp logged out');
        process.exit(1);
      }
      if (attempt >= MAX_RECONNECTS) {
        console.log('Maximum reconnect attempts reached. Keeping auth_info for the next start.');
        process.exit(1);
      }
      console.log(`WhatsApp disconnected. Reconnecting in ${RECONNECT_DELAY_MS / 1000}s (${attempt}/${MAX_RECONNECTS})...`);
      await sleep(RECONNECT_DELAY_MS);
      start(attempt + 1);
    }
  });

  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify') return;
    for (const msg of messages) {
      if (!msg.message) continue;
      const text = textFromMessage(msg.message);
      const reaction = msg.message.reactionMessage;
      if (reaction) {
        console.log(`[reaction] ${msg.key.participant || msg.key.remoteJid} reacted ${reaction.text || ''} to ${reaction.key.id}`);
        if (adapterState.reactsave && msg.key.fromMe) {
          await saveReactedMedia(sock, reaction, messageCache);
        }
        continue;
      }
      messageCache.set(msg.key.id, msg);
      if (messageCache.size > 5000) messageCache.delete(messageCache.keys().next().value);
      if (msg.key.fromMe && !isCommandText(text)) continue;
      console.log(`[message] from=${msg.key.participant || msg.key.remoteJid} chat=${msg.key.remoteJid} text=${text || '[media/no text]'}`);
      if (!py || !py.stdin.writable) continue;
      py.stdin.write(JSON.stringify({
        message_id: msg.key.id || `${Date.now()}`,
        chat_id: msg.key.remoteJid,
        sender_id: msg.key.fromMe ? 'owner' : (msg.key.participant || msg.key.remoteJid),
        text,
        kind: 'message',
        is_group: Boolean(msg.key.participant),
        raw: msg
      }) + '\n');
    }
  });
}

start();
