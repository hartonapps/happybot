
const readline = require('readline');
const { spawn } = require('child_process');
const fs = require('fs');
const makeWASocket = require('@whiskeysockets/baileys').default;
const { DisconnectReason, useMultiFileAuthState } = require('@whiskeysockets/baileys');
const P = require('pino');

const AUTH_DIR = 'auth_info';
const MAX_RECONNECTS = 5;
const RECONNECT_DELAY_MS = 5000;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function baseMessageId(id) {
  return String(id || '').replace(/-\d+$/, '');
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

function startPythonCore(sock, messageCache, botMessageIds) {
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
    if (action.action === 'send_message') {
      const options = action.reply_to && messageCache.has(baseMessageId(action.reply_to))
        ? { quoted: messageCache.get(baseMessageId(action.reply_to)) }
        : {};
      const result = await sock.sendMessage(action.chat_id, { text: action.text }, options);
      if (result?.key?.id) {
        botMessageIds.add(result.key.id);
        messageCache.set(baseMessageId(result.key.id), result);
      }
    }
    if (action.action === 'react') {
      await sock.sendMessage(action.chat_id, {
        react: {
          text: action.emoji,
          key: { id: action.message_id, remoteJid: action.chat_id }
        }
      });
    }
  });

  py.on('exit', (code) => {
    if (code !== 0) console.log(`Python core exited with code ${code}.`);
  });

  return py;
}

async function start(attempt = 1) {
  let py = null;
  const messageCache = new Map();
  const botMessageIds = new Set();

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
      py = startPythonCore(sock, messageCache, botMessageIds);
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

  sock.ev.on('messages.upsert', ({ messages, type }) => {
    if (!py || !py.stdin.writable) return;
    for (const msg of messages) {
      if (!msg.message) continue;
      if (msg.key.fromMe) {
        if (botMessageIds.has(msg.key.id)) {
          botMessageIds.delete(msg.key.id);
          continue;
        }
      }

      // Cache every message under its base id so reactions (which can reference the same id
      // with a `-N` suffix from Baileys) still resolve to the original.
      messageCache.set(baseMessageId(msg.key.id), msg);
      if (messageCache.size > 10000) {
        messageCache.delete(messageCache.keys().next().value);
      }

      if (type === 'notify') {
        py.stdin.write(JSON.stringify({
          message_id: msg.key.id || `${Date.now()}`,
          chat_id: msg.key.remoteJid,
          sender_id: msg.key.participant || msg.key.remoteJid,
          text: textFromMessage(msg.message),
          kind: 'message',
          is_group: Boolean(msg.key.participant),
          raw: msg
        }) + '\n');
      }
    }
  });

  sock.ev.on('messages.reaction', async (reactions) => {
    console.log('🔔 REACTION EVENT FIRED:', reactions.length, 'reactions');
    if (!py || !py.stdin.writable) {
      console.log('❌ Python not ready, skipping reaction');
      return;
    }

    for (const { key, reaction } of reactions) {
      const reactionText = reaction.text || reaction;
      console.log(`📍 Processing reaction: ${reactionText} on message ${key.id}`);

      const baseId = baseMessageId(key.id);
      const originalMessage = messageCache.get(baseId);
      let mediaBase64 = null;

      if (!originalMessage) {
        console.log(`❌ Message ${key.id} (base ${baseId}) not in cache. Cache size: ${messageCache.size}`);
        continue;
      }

      // Try to attach the media payload (image/video/audio/document/sticker) as base64.
      try {
        const inner = originalMessage.message || {};
        const mediaNode =
          inner.imageMessage ||
          inner.videoMessage ||
          inner.audioMessage ||
          inner.documentMessage ||
          inner.stickerMessage;
        const mediaKey = mediaNode ? Object.keys(mediaNode)[0] : null; // e.g. "imageMessage"

        if (mediaNode && mediaKey && typeof sock.downloadContentFromMessage === 'function') {
          const mediaType = mediaKey.replace(/Message$/, ''); // "image", "video", ...
          const stream = await sock.downloadContentFromMessage(mediaNode, mediaType);
          const chunks = [];
          for await (const chunk of stream) chunks.push(chunk);
          mediaBase64 = Buffer.concat(chunks).toString('base64');
        }
      } catch (err) {
        console.log('Download failed:', err);
      }

      console.log(`✅ Found message in cache! Sending to Python`);

      py.stdin.write(JSON.stringify({
        message_id: key.id,
        chat_id: key.remoteJid,
        sender_id: key.participant || key.remoteJid,
        text: reactionText,
        kind: 'reaction',
        is_group: Boolean(key.participant),
        raw: originalMessage,
        media_base64: mediaBase64
      }) + '\n');
    }
  });
}

start();
