"""Core HappyBot commands implemented as regular plugins."""


@bot.command("ping", aliases=("p",), help="Check whether the bot is alive.")
async def ping(ctx):
    await ctx.reply("pong")


@bot.command("help", aliases=("menu",), help="Show available commands.")
async def help_command(ctx):
    await ctx.reply(ctx.bot.help_text())


@bot.command("plugins", owner_only=True, help="List loaded plugins.")
async def plugins(ctx):
    names = ", ".join(sorted(ctx.bot.plugins)) or "none"
    await ctx.reply(f"Loaded plugins: {names}")
