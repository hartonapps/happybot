# HappyBot

HappyBot is a lightweight, modular, plugin-based WhatsApp bot framework for Python. The core stays compact while features live in `plugins/`.

## Structure

```text
HappyBot/
├── main.py
├── config.py
├── database.json
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
