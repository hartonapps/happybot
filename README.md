# HappyBot

HappyBot is a ready-to-run WhatsApp bot. Start it with Python, and it uses Baileys under the hood for WhatsApp login while keeping bot commands as small Python plugins.

## What changed about login

Baileys supports two first-login methods: a terminal QR code and a phone-number pairing code. HappyBot now lets you choose either one every time a new session is needed.

`python main.py` is still the command you run. It starts the Baileys connector, waits for WhatsApp to confirm the device is linked, and only then loads the Python plugins.

## Files

```text
HappyBot/
├── main.py                # Start this file to run the WhatsApp bot
├── whatsapp_adapter.js    # Baileys connection/session adapter used by main.py
├── config.py              # Bot limits and command prefixes
├── database.json          # Tiny JSON database for plugins
├── requirements.txt       # Python requirements; currently standard-library only
├── package.json           # Baileys/Node.js packages
└── plugins/               # Drop command plugins here
```

## First run

Install Python and Node.js, then run:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

If `node_modules/` is missing, HappyBot runs `npm install` for the Baileys packages automatically, then starts the WhatsApp connector.

## Choose QR or code

When no saved session exists, HappyBot asks:

```text
Connect with QR or phone code? [1=QR, 2=Code]:
```

### Option 1: QR

Choose `1`. HappyBot prints a QR code in the terminal using `qrcode-terminal`.

On your phone, open WhatsApp → **Linked devices** → **Link a device**, then scan the terminal QR. Keep the terminal visible; QR codes are temporary, and HappyBot will print a fresh QR when Baileys emits a new one.

### Option 2: phone code

Choose `2`. HappyBot waits until Baileys emits a login QR event, then requests a pairing code at the correct time. Enter your WhatsApp mobile number with country code, for example `2348012345678`.

On your phone, open WhatsApp → **Linked devices** → **Link with phone number instead**, then enter the code quickly. Pairing codes are short-lived; if one expires, restart with `python main.py` and request a new one.

## Session saving and failed pairing

The WhatsApp session is saved in `auth_info/` by Baileys. Do not delete that folder unless you want to log out. If `auth_info/` exists and is valid, HappyBot reconnects with the saved session and will not ask for QR or phone code again.

If pairing fails before a stable login, HappyBot removes the incomplete `auth_info/` session automatically and exits with instructions to run `python main.py` again.

WhatsApp may close once with status `515` after pairing. HappyBot now treats this as a restart request and retries without deleting the session.

## Does Termux need to stay open?

Yes, the bot process must keep running somewhere. WhatsApp stays linked in `auth_info/`, but the bot cannot receive or reply to messages if Android kills or suspends the Termux process.

For better uptime on Termux:

```bash
termux-wake-lock
source .venv/bin/activate
python main.py
```

You can also run it inside `tmux` or another process manager. If you leave Termux and Android keeps the process alive, the bot can keep working. If Android stops the process, start it again with `python main.py`; a valid saved session should reconnect without a new QR/code.

## Daily use

After the first successful pairing, start the bot with:

```bash
source .venv/bin/activate
python main.py
```

Useful developer commands:

```bash
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
