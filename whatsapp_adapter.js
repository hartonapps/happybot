const readline = require('readline');
const { spawn } = require('child_process');
const fs = require('fs');
const makeWASocket = require('@whiskeysockets/baileys').default;
const { DisconnectReason, useMultiFileAuthState } = require('@whiskeysockets/baileys');
const P = require('pino');
const qrcode = require('qrcode-terminal');

const AUTH_DIR = 'auth_info';
const MAX_RECONNECTS = 5;
const RECONNECT_DELAY_MS = 5000;
const RESTART_REQUIRED = 515;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function question(prompt) {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  return new Promise((resolve) => {
    rl.question(prompt, (answer) => {
      rl.close();
      resolve(answer.trim());
    });
  });
}

function clearSession(reason) {
  if (fs.existsSync(AUTH_DIR)) {
    fs.rmSync(AUTH_DIR, { recursive: true, force: true });
    console.log(`Removed saved WhatsApp session (${reason}). Pair again on next start.`);
  }
}

async function chooseLoginMethod() {
  const answer = await question('Connect with QR or phone code? [1=QR, 2=Code]: ');
  if (answer === '2' || answer.toLowerCase().startsWith('c')) return 'code';
  return 'qr';
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

function startPythonCore(sock, messageCache) {
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
      const options = action.reply_to && messageCache.has(action.reply_to) ? { quoted: messageCache.get(action.reply_to) } : {};
      await sock.sendMessage(action.chat_id, { text: action.text }, options);
    }
    if (action.action === 'react') {
      await sock.sendMessage(action.chat_id, { react: { text: action.emoji, key: { id: action.message_id, remoteJid: action.chat_id } } });
    }
  });

  py.on('exit', (code) => {
    if (code !== 0) console.log(`Python core exited with code ${code}.`);
  });

  return py;
}

async function start(attempt = 1, preferredMethod = null) {
  let connected = false;
  let py = null;
  let pairingRequested = false;
  const messageCache = new Map();
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const needsLogin = !state.creds.registered;
  const loginMethod = needsLogin ? (preferredMethod || await chooseLoginMethod()) : null;
  const sock = makeWASocket({
    auth: state,
    logger: P({ level: 'silent' }),
    printQRInTerminal: false,
    markOnlineOnConnect: false,
    syncFullHistory: false
  });

  if (needsLogin && loginMethod === 'qr') {
    console.log('Waiting for WhatsApp QR code...');
  }
  if (needsLogin && loginMethod === 'code') {
    console.log('Waiting for WhatsApp to prepare a pairing code...');
  }

  sock.ev.on('creds.update', saveCreds);
  sock.ev.on('connection.update', async ({ connection, lastDisconnect, qr }) => {
    if (qr && needsLogin && loginMethod === 'qr') {
      console.log('Scan this QR in WhatsApp > Linked devices > Link a device:');
      qrcode.generate(qr, { small: true });
      console.log('If it expires, keep this terminal open and wait for the next QR, or restart with `python main.py`.');
    }
    if (qr && needsLogin && loginMethod === 'code' && !pairingRequested) {
      pairingRequested = true;
      const phoneNumber = await question('Enter WhatsApp mobile number with country code (example 2348012345678): ');
      const cleanNumber = phoneNumber.replace(/\D/g, '');
      if (!cleanNumber) {
        clearSession('empty phone number');
        console.log('No valid phone number entered. Start again with `python main.py`.');
        process.exit(1);
      }
      try {
        const code = await sock.requestPairingCode(cleanNumber);
        console.log(`Pair this bot in WhatsApp with code: ${code}`);
        console.log('Open WhatsApp > Linked devices > Link with phone number instead, then enter the code quickly.');
      } catch (error) {
        clearSession('pairing code request failed');
        console.log(`Could not request a pairing code: ${error.message}`);
        console.log('Check the phone number, internet connection, and WhatsApp availability, then run `python main.py` again.');
        process.exit(1);
      }
    }
    if (connection === 'open') {
      connected = true;
      console.log('HappyBot connected to WhatsApp. Loading plugins now...');
      py = startPythonCore(sock, messageCache);
      return;
    }
    if (connection === 'close') {
      const code = lastDisconnect?.error?.output?.statusCode;
      if (py) py.kill();
      if (code === RESTART_REQUIRED && attempt < MAX_RECONNECTS) {
        console.log('WhatsApp requested a connection restart after pairing. Retrying without deleting the session...');
        await sleep(RECONNECT_DELAY_MS);
        start(attempt + 1, loginMethod);
        return;
      }
      if (code === DisconnectReason.loggedOut || (!connected && code !== RESTART_REQUIRED)) {
        clearSession(`login did not complete; status ${code || 'unknown'}`);
        console.log('Start again with `python main.py` to request a fresh QR or pairing code.');
        process.exit(1);
      }
      if (attempt >= MAX_RECONNECTS) {
        console.log('Maximum reconnect attempts reached. Keeping auth_info for the next start.');
        process.exit(1);
      }
      console.log(`WhatsApp disconnected. Reconnecting in ${RECONNECT_DELAY_MS / 1000}s (${attempt}/${MAX_RECONNECTS})...`);
      await sleep(RECONNECT_DELAY_MS);
      start(attempt + 1, loginMethod);
    }
  });

  sock.ev.on('messages.upsert', ({ messages, type }) => {
    if (type !== 'notify' || !py || !py.stdin.writable) return;
    for (const msg of messages) {
      if (!msg.message || msg.key.fromMe) continue;
      messageCache.set(msg.key.id, msg);
      if (messageCache.size > 5000) messageCache.delete(messageCache.keys().next().value);
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
  });
}

start();
