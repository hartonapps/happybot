"""Runtime statistics plugin."""


@bot.command("runtime", aliases=("status", "stats"), owner_only=True, help="Show queue, uptime, and error statistics.")
async def runtime(ctx):
    stats = ctx.bot.runtime()
    await ctx.reply(
        "Runtime status\n"
        f"Uptime: {stats['uptime_seconds']}s\n"
        f"Queue: {stats['queue_size']}/{stats['queue_limit']}\n"
        f"Received: {stats['received']}\n"
        f"Processed: {stats['processed']}\n"
        f"Dropped: {stats['dropped']}\n"
        f"Errors: {stats['errors']}\n"
        f"Plugins: {stats['plugins']}\n"
        f"Active tasks: {stats['active_tasks']}"
    )
