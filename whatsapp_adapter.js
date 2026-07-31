const readline = require('readline');
const { spawn } = require('child_process');
const makeWASocket = require('@whiskeysockets/baileys').default;
const { DisconnectReason, useMultiFileAuthState } = require('@whiskeysockets/baileys');
const P = require('pino');
const qrcode = require('qrcode-terminal');

function question(prompt) {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  return new Promise((resolve) => {
    rl.question(prompt, (answer) => {
      rl.close();
      resolve(answer.trim());
    });
  });
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

async function start() {
  const { state, saveCreds } = await useMultiFileAuthState('auth_info');
  const sock = makeWASocket({
    auth: state,
    logger: P({ level: 'silent' }),
    printQRInTerminal: false,
    markOnlineOnConnect: false,
    syncFullHistory: false
  });

  if (!sock.authState.creds.registered) {
    const phoneNumber = await question('Enter WhatsApp mobile number with country code (example 2348012345678): ');
    const code = await sock.requestPairingCode(phoneNumber.replace(/\D/g, ''));
    console.log(`Pair this bot in WhatsApp with code: ${code}`);
  }

  const messageCache = new Map();
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

  sock.ev.on('creds.update', saveCreds);
  sock.ev.on('connection.update', ({ connection, lastDisconnect, qr }) => {
    if (qr) qrcode.generate(qr, { small: true });
    if (connection === 'open') console.log('HappyBot connected to WhatsApp.');
    if (connection === 'close') {
      const code = lastDisconnect?.error?.output?.statusCode;
      if (code !== DisconnectReason.loggedOut) start();
      else console.log('WhatsApp logged out. Delete auth_info and pair again.');
    }
  });

  sock.ev.on('messages.upsert', ({ messages, type }) => {
    if (type !== 'notify') return;
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
