"""Simple health-check plugin."""


@bot.command("ping", aliases=("p",), help="Check whether the bot is alive.")
async def ping(ctx):
    await ctx.reply("pong")
