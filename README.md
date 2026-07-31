# HappyBot

HappyBot is a ready-to-run WhatsApp bot. The connection step is now separated from the bot runtime so setup is easier to understand and debug.

## How it works now

- `connect.js` links WhatsApp once and saves the session in `auth_info/`.
- `main.py` starts the bot using the saved session.
- If `main.py` sees no saved session, it automatically runs `connect.js` first.
- Python plugins load only after WhatsApp is connected.

## Files

```text
HappyBot/
├── main.py                # Normal bot startup command
├── connect.js             # One-time WhatsApp QR/code setup
├── whatsapp_adapter.js    # Runtime WhatsApp adapter; uses saved auth_info/
├── config.py              # Bot limits and command prefixes
├── database.json          # Tiny JSON database for plugins
├── requirements.txt       # Python requirements; currently standard-library only
├── package.json           # Baileys/Node.js packages
└── plugins/               # Drop command plugins here
```

## First setup

Install Python and Node.js, then run:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

If `node_modules/` is missing, HappyBot runs `npm install` automatically. If `auth_info/` is missing, HappyBot runs `node connect.js` automatically.

You can also run connection setup manually:

```bash
node connect.js
python main.py
```

## Choose QR or phone code

When no saved session exists, `connect.js` asks:

```text
Connect with QR or phone code? [1=QR, 2=Code]:
```

### Option 1: QR

Choose `1`. HappyBot prints a QR code in the terminal using `qrcode-terminal`.

On your phone, open WhatsApp → **Linked devices** → **Link a device**, then scan the terminal QR. QR codes are temporary, so keep the terminal open until WhatsApp confirms linking.

### Option 2: phone code

Choose `2`. HappyBot waits until Baileys is ready, then asks for your WhatsApp mobile number with country code, for example `2348012345678`.

On your phone, open WhatsApp → **Linked devices** → **Link with phone number instead**, then enter the code quickly. Pairing codes are short-lived; if one expires, run `node connect.js` again for a fresh code.

## Session saving

A successful connection saves the WhatsApp session in `auth_info/`. After that, `python main.py` should reconnect without asking for QR or phone code again.

Do not delete `auth_info/` unless you want to log out or force a new pairing. If pairing fails before a stable login, `connect.js` removes the incomplete session automatically and tells you to try again.

WhatsApp may close once with status `515` during login. HappyBot treats that as a restart request and retries without deleting the session.

## Does Termux need to stay open?

Yes, the bot process must keep running somewhere. WhatsApp stays linked in `auth_info/`, but the bot cannot receive or reply to messages if Android kills or suspends Termux.

For better uptime on Termux:

```bash
termux-wake-lock
source .venv/bin/activate
python main.py
```

You can also run it inside `tmux` or another process manager. If Android stops the process, start it again with `python main.py`; a valid saved session should reconnect without a new QR/code.

## Daily use

After the first successful pairing, start the bot with:

```bash
source .venv/bin/activate
python main.py
```

Useful commands:

```bash
node connect.js          # link WhatsApp and save auth_info/ only
python main.py           # start the bot using saved auth_info/
python main.py --core    # run only the Python plugin core, no WhatsApp connection
python main.py --stdio   # internal bridge mode used by whatsapp_adapter.js
npm install              # manually install/update Baileys packages if needed
```

## Requirements

`requirements.txt` is intentionally small because the Python side uses only the standard library. WhatsApp connectivity is not a Python package; it comes from Baileys in `package.json` and is installed with npm.

## Included commands

- `!ping` or `/ping` replies with `pong`.
- `!help` or `/help` shows commands.
- `!runtime`, `!status`, or `!stats` shows uptime, queue size, dropped events, errors, plugin count, and active tasks. This command is owner-only.
- `!plugins` lists loaded plugins. This command is owner-only.

Set your WhatsApp ID in `OWNER_IDS` inside `config.py` before relying on owner-only commands.

## Adding a plugin

Create a new `.py` file in `plugins/`:

```python
@bot.command("hello", aliases=("hi",), help="Greet the sender.")
async def hello(ctx):
    await ctx.reply(f"Hello {ctx.sender}!")
```

Restart with `python main.py`.

## Reliability defaults

HappyBot is configured for both small personal accounts and busier WhatsApp accounts:

- Incoming messages use a bounded queue (`MAX_QUEUE_SIZE`).
- Handler concurrency is capped (`MAX_CONCURRENT_HANDLERS`).
- Slow or broken plugins are isolated and logged.
- Command/listener lookup is indexed so every message does not scan every plugin.
- Runtime stats expose received, processed, dropped, and error counts.
- WhatsApp reconnects automatically for normal disconnects and keeps the saved session unless login itself fails.

Tune these values in `config.py` for your phone or server.
