# HappyBot

HappyBot is a ready-to-run WhatsApp bot. Start it with Python, and it uses Baileys under the hood for WhatsApp login while keeping bot commands as small Python plugins.

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

`python main.py` is the normal startup command. If `node_modules/` is missing, it runs `npm install` for the Baileys packages, then starts the WhatsApp connector.

On first connection, the bot asks for your WhatsApp mobile number with country code, for example `2348012345678`. It then prints a pairing code. Open WhatsApp → **Linked devices** → **Link with phone number instead**, and enter the code.

HappyBot waits for WhatsApp to confirm the login before loading Python plugins. Seeing plugin logs means the WhatsApp connection has already opened.

## Session saving and failed pairing

The WhatsApp session is saved in `auth_info/` by Baileys. Do not delete that folder unless you want to log out. If `auth_info/` exists and is valid, HappyBot reconnects with the saved session and will not ask for your number again.

If pairing fails or WhatsApp closes before a stable login, HappyBot now removes the incomplete `auth_info/` session automatically and exits with instructions to run `python main.py` again. You should not have to manually delete a broken session after a failed link attempt.

By default HappyBot uses phone-number pairing only. QR output is hidden to avoid confusing two different pairing methods. If you specifically want QR output for debugging, run:

```bash
HAPPYBOT_SHOW_QR=1 python main.py
```

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
