# HappyBot

HappyBot is a lightweight, modular, plugin-based WhatsApp bot framework for Python. The core stays compact while features live in `plugins/`.

## Structure

```text
HappyBot/
├── main.py
├── config.py
├── database.json
├── requirements.txt
└── plugins/
    ├── core.py
    ├── ping.py
    └── runtime.py
```

## Setup

HappyBot currently uses only the Python standard library, but the project includes `requirements.txt` so setup stays familiar and future dependencies have a single home.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

On mobile environments such as Termux or Pydroid, create/activate the environment using the platform's normal Python flow, then run the same install and start commands:

```bash
python -m pip install -r requirements.txt
python main.py
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

## WhatsApp adapter

A WhatsApp transport adapter can create `Event` objects and feed them to `HappyBot.emit()`. The framework keeps WhatsApp-specific details outside plugins so the plugin API remains stable if the underlying client changes.
