"""Toggle reaction-based private media saving."""


@bot.command("reactsave", aliases=("rsave",), owner_only=True, help="Turn reaction media saving on or off: reactsave on/off.")
async def reactsave(ctx):
    if not ctx.args or ctx.args[0].lower() not in {"on", "off"}:
        prefix = ctx.bot.prefixes[0] if ctx.bot.prefixes else "!"
        await ctx.reply(f"Usage: {prefix}reactsave on or {prefix}reactsave off")
        return

    enabled = ctx.args[0].lower() == "on"
    ctx.db.set("reactsave_enabled", enabled)
    await ctx.bot.adapter_action("set_reactsave", enabled=enabled)
    await ctx.reply(f"Reaction media saving is now {'ON' if enabled else 'OFF'}.")
