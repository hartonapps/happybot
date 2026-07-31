const readline = require('readline');
const fs = require('fs');
const P = require('pino');
const qrcode = require('qrcode-terminal');

let makeWASocket;
let DisconnectReason;
let useMultiFileAuthState;

try {
  const baileys = require('@whiskeysockets/baileys');
  makeWASocket = baileys.default;
  DisconnectReason = baileys.DisconnectReason;
  useMultiFileAuthState = baileys.useMultiFileAuthState;
} catch (error) {
  console.error('Missing Node dependencies. Run `npm install` in this folder, then start again.');
  process.exit(1);
}

const AUTH_DIR = 'auth_info';
const MAX_RESTARTS = 5;
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
    console.log(`Removed incomplete WhatsApp session (${reason}).`);
  }
}

async function chooseLoginMethod() {
  const answer = await question('Connect with QR or phone code? [1=QR, 2=Code]: ');
  if (answer === '2' || answer.toLowerCase().startsWith('c')) return 'code';
  return 'qr';
}

async function connect(attempt = 1, preferredMethod = null) {
  let opened = false;
  let pairingRequested = false;
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

  if (needsLogin) {
    console.log(loginMethod === 'qr' ? 'Waiting for QR code...' : 'Waiting for WhatsApp to prepare a pairing code...');
  } else {
    console.log('Saved session found. Verifying it can connect to WhatsApp...');
  }
  sock.ev.on('creds.update', saveCreds);
  sock.ev.on('connection.update', async ({ connection, lastDisconnect, qr }) => {
    if (needsLogin && qr && loginMethod === 'qr') {
      console.log('Scan this QR in WhatsApp > Linked devices > Link a device:');
      qrcode.generate(qr, { small: true });
      console.log('QR codes expire. Keep this terminal open for a fresh QR if needed.');
    }

    if (needsLogin && qr && loginMethod === 'code' && !pairingRequested) {
      pairingRequested = true;
      const phoneNumber = await question('Enter WhatsApp mobile number with country code (example 2348012345678): ');
      const cleanNumber = phoneNumber.replace(/\D/g, '');
      if (!cleanNumber) {
        clearSession('empty phone number');
        console.log('No valid phone number entered. Run `node connect.js` again.');
        process.exit(1);
      }
      try {
        const code = await sock.requestPairingCode(cleanNumber);
        console.log(`Pair this bot in WhatsApp with code: ${code}`);
        console.log('Open WhatsApp > Linked devices > Link with phone number instead, then enter the code quickly.');
      } catch (error) {
        clearSession('pairing code request failed');
        console.log(`Could not request a pairing code: ${error.message}`);
        process.exit(1);
      }
    }

    if (connection === 'open') {
      opened = true;
      console.log('WhatsApp session verified and saved in auth_info/. Now run `python main.py` to start the bot.');
      await sleep(1000);
      process.exit(0);
    }

    if (connection === 'close') {
      const code = lastDisconnect?.error?.output?.statusCode;
      if (code === RESTART_REQUIRED && attempt < MAX_RESTARTS) {
        console.log('WhatsApp requested a login restart. Retrying without deleting auth_info/...');
        await sleep(3000);
        connect(attempt + 1, loginMethod);
        return;
      }
      if (code === DisconnectReason.loggedOut || !opened) {
        clearSession(`login closed before success; status ${code || 'unknown'}`);
        console.log('Pairing did not finish. Run `node connect.js` again and use a fresh QR/code.');
        process.exit(1);
      }
    }
  });
}

connect();
