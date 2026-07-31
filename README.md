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
└── plugins/
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

## Running

```bash
python main.py
```

A WhatsApp transport adapter can create `Event` objects and feed them to `HappyBot.emit()`.
