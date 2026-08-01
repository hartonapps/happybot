const readline = require('readline');
const { spawn } = require('child_process');
const fs = require('fs');
const makeWASocket = require('@whiskeysockets/baileys').default;
const { DisconnectReason, useMultiFileAuthState } = require('@whiskeysockets/baileys');
const P = require('pino');

const AUTH_DIR = 'auth_info';
const MAX_RECONNECTS = 5;
const RECONNECT_DELAY_MS = 5000;
const DEBUG = process.env.DEBUG_ADAPTER === '1';

function dbg(...args) {
  if (DEBUG) console.log('🪵', ...args);
}

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
  const py = spawn(process.env.PYTHON || 'python', ['main.py', '--stdio', '--debug'], {
    cwd: process.cwd(),
    stdio: ['pipe', 'pipe', 'inherit'],
    env: { ...process.env, PYTHONUNBUFFERED: '1' },   // <-- force flush on Python side
  });

  console.log(`🐍 Python core spawned, pid=${py.pid}`);

  // Watch Python's stderr explicitly even though we set 'inherit'.
  // Termux sometimes drops it; this guarantees we see crashes.
  py.stderr.on('data', (data) => {
    process.stderr.write(`🐍 PY-ERR: ${data}`);
  });

  py.on('exit', (code, signal) => {
    console.log(`🐍 Python core exited (code=${code}, signal=${signal})`);
  });

  py.on('error', (err) => {
    console.error('🐍 Python spawn error:', err);
  });

  const pyLines = readline.createInterface({ input: py.stdout });
  pyLines.on('line', async (line) => {
    if (!line.trim().startsWith('{')) {
      console.log(line);
      return;
    }
    let action;
    try {
      action = JSON.parse(line);
    } catch (err) {
      console.error('Bad JSON from python:', line, err);
      return;
    }
    if (action.action === 'send_message') {
      const replyId = action.reply_to ? baseMessageId(action.reply_to) : null;
      const options = replyId && messageCache.has(replyId)
        ? { quoted: messageCache.get(replyId) }
        : {};
      try {
        const result = await sock.sendMessage(
          action.chat_id, { text: action.text }, options
        );
        if (result?.key?.id) {
          botMessageIds.add(result.key.id);
          messageCache.set(baseMessageId(result.key.id), result);
        }
      } catch (err) {
        console.error('sendMessage failed:', err);
      }
    }
    if (action.action === 'react') {
      try {
        await sock.sendMessage(action.chat_id, {
          react: {
            text: action.emoji,
            key: { id: action.message_id, remoteJid: action.chat_id }
          }
        });
      } catch (err) {
        console.error('react failed:', err);
      }
    }
    if (action.action === 'adapter_action') {
      dbg('adapter_action from python:', action);
    }
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

  // ----------------------------------------------------------------
  // messages.upsert — every incoming message
  // ----------------------------------------------------------------
  sock.ev.on('messages.upsert', ({ messages, type }) => {
    dbg(`upsert: count=${messages.length} type=${type} py_alive=${!!(py && py.stdin.writable)}`);
    if (!py || !py.stdin.writable) return;

    for (const msg of messages) {
      if (!msg.message) {
        dbg(`  skip ${msg.key?.id}: no message body`);
        continue;
      }

      const text = textFromMessage(msg.message);
      const fromMe = !!msg.key.fromMe;
      const isBotEcho = botMessageIds.has(msg.key.id);

      dbg(`  msg id=${msg.key.id} fromMe=${fromMe} isBotEcho=${isBotEcho} remoteJid=${msg.key.remoteJid} participant=${msg.key.participant || '-'} text=${JSON.stringify(text.slice(0, 40))}`);

      // Drop ONLY the bot's own echo (a message we just sent via send_message).
      // Do NOT drop owner self-test messages — they need to reach Python so .ping works.
      if (fromMe && isBotEcho) {
        botMessageIds.delete(msg.key.id);
        dbg(`    → dropped bot echo`);
        continue;
      }

      // Always cache so reactions to this message can be looked up.
      messageCache.set(baseMessageId(msg.key.id), msg);
      if (messageCache.size > 10000) {
        messageCache.delete(messageCache.keys().next().value);
      }

      if (type !== 'notify') {
        dbg(`    → not forwarding (type=${type})`);
        continue;
      }

      const payload = JSON.stringify({
        message_id: msg.key.id || `${Date.now()}`,
        chat_id: msg.key.remoteJid,
        sender_id: msg.key.participant || msg.key.remoteJid,
        text,
        kind: 'message',
        is_group: Boolean(msg.key.participant),
        raw: msg
      }) + '\n';

      const ok = py.stdin.write(payload);
      dbg(`    → wrote ${payload.length} bytes to python, ok=${ok}`);

      // If the kernel buffer is full, wait for drain before the next write.
      if (ok === false) {
        dbg('    → py.stdin buffer full, waiting for drain');
        py.stdin.once('drain', () => dbg('    → py.stdin drained'));
      }
    }
  });

  // ----------------------------------------------------------------
  // messages.reaction — every reaction (including on stories)
  // ----------------------------------------------------------------
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
        console.log(`   Last cached ids: ${Array.from(messageCache.keys()).slice(-5).join(', ')}`);
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
        const mediaKey = mediaNode ? Object.keys(mediaNode)[0] : null;

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

      const payload = JSON.stringify({
        message_id: key.id,
        chat_id: key.remoteJid,
        sender_id: key.participant || key.remoteJid,
        text: reactionText,
        kind: 'reaction',
        is_group: Boolean(key.participant),
        raw: originalMessage,
        media_base64: mediaBase64
      }) + '\n';

      const ok = py.stdin.write(payload);
      console.log(`   → wrote ${payload.length} bytes, ok=${ok}`);
    }
  });

  // ----------------------------------------------------------------
  // Optional: surface ALL events for debugging
  // ----------------------------------------------------------------
  if (DEBUG) {
    for (const ev of ['messages.update', 'message-receipt.update', 'presence.update', 'chats.update', 'contacts.update']) {
      sock.ev.on(ev, (payload) => {
        const summary = Array.isArray(payload)
          ? `${payload.length} item(s)`
          : typeof payload === 'object'
            ? Object.keys(payload).join(',')
            : String(payload);
        dbg(`📡 ${ev}: ${summary.slice(0, 120)}`);
      });
    }
  }
}

start();