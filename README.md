# HappyBot

HappyBot is a lightweight, modular, plugin-based WhatsApp bot framework. Plugins are written in Python, while WhatsApp connectivity is handled by a Baileys adapter (`whatsapp_adapter.js`).

## Structure

```text
HappyBot/
├── main.py                # Python plugin framework core
├── whatsapp_adapter.js    # Baileys WhatsApp adapter
├── config.py
├── database.json
├── requirements.txt       # Python dependencies
├── package.json           # Baileys / Node.js dependencies
└── plugins/
    ├── core.py
    ├── ping.py
    └── runtime.py
```

## Setup for WhatsApp with Baileys

`python main.py` only starts the Python plugin core. It does **not** ask for a mobile number because it is not the WhatsApp client. To connect to WhatsApp, run the Baileys adapter with Node.js:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
npm install
npm start
```

On first run, `npm start` asks for your WhatsApp mobile number with country code, then prints a pairing code. In WhatsApp, open **Linked devices** and use that code to pair the bot.

After pairing, Baileys stores the session in `auth_info/`. Future starts should reconnect without asking for the number again. Delete `auth_info/` only if you want to log out and pair again.

## Why `requirements.txt` is small

HappyBot's Python core currently uses only the Python standard library, so `requirements.txt` intentionally contains no Python packages. The WhatsApp/Baileys dependencies are JavaScript packages and live in `package.json`, installed with `npm install`.

## Running core-only mode

Core-only mode is useful for plugin development or tests, but it does not connect to WhatsApp:

```bash
python main.py
```

The Baileys adapter runs the core in JSON-lines bridge mode with:

```bash
python main.py --stdio
```

## Plugin example

```python
@bot.command("hello", aliases=("hi",), help="Greet the sender.")
async def hello(ctx):
    await ctx.reply(f"Hello {ctx.sender}!")

@bot.on("message")
async def listen(ctx):
    if "thanks" in ctx.message.lower():
        await ctx.react("❤️")
```

Drop the file into `plugins/` and restart HappyBot. Plugins receive a unified `ctx` object instead of a raw WhatsApp client.

## Included plugins

- `plugins/core.py` provides `help` and owner-only plugin listing commands.
- `plugins/ping.py` provides `ping`/`p` for a quick health check.
- `plugins/runtime.py` provides owner-only `runtime`/`status`/`stats` with uptime, queue, dropped event, error, plugin, and active-task counts.

## Scaling and reliability

HappyBot is fortified for both small personal bots and very busy WhatsApp accounts with thousands of contacts or much larger contact lists:

- Incoming events enter a bounded queue (`MAX_QUEUE_SIZE`) instead of blocking the adapter forever.
- If the queue is full, new events are dropped with a warning and counted in runtime stats so the bot fails visibly instead of running out of memory.
- Command and listener lookups are indexed at startup, avoiding a full plugin scan for every message.
- Handler concurrency is capped by `MAX_CONCURRENT_HANDLERS`, preventing slow plugins from creating unlimited tasks.
- Each plugin call has a timeout (`COMMAND_TIMEOUT`) and exception isolation so one broken plugin does not crash the framework.
- Slow handlers are logged using `SLOW_HANDLER_WARNING`, helping identify plugins that would freeze the bot under heavy traffic.
- Runtime stats can be checked from chat with the owner-only `runtime` command.

Tune the values in `config.py` for the device: lower limits for phones with little memory, higher limits for servers.
