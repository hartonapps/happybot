"""HappyBot: a compact plugin-based WhatsApp bot framework.

The transport is intentionally abstract so a WhatsApp adapter can feed incoming
messages into :class:`HappyBot` while plugins stay independent of the client.
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Awaitable, Callable

import config

Handler = Callable[["Context"], Any | Awaitable[Any]]


@dataclass
class Event:
    """Transport-neutral message/event passed in by a WhatsApp adapter."""

    message_id: str
    chat_id: str
    sender_id: str
    text: str = ""
    kind: str = "message"
    media: Any = None
    quoted: Any = None
    is_group: bool = False
    is_admin: bool = False
    raw: Any = None


@dataclass
class PluginInfo:
    """Runtime information kept for each loaded plugin."""

    name: str
    module: ModuleType
    commands: list[tuple[dict[str, Any], Handler]] = field(default_factory=list)
    listeners: list[tuple[str, Handler]] = field(default_factory=list)
    tasks: list[tuple[int, Handler]] = field(default_factory=list)
    enabled: bool = True


class JsonDatabase:
    """Tiny JSON key/value store available to plugins through ctx.db."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.data: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        else:
            self.save()

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True), encoding="utf-8")

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.save()


class Context:
    """Unified object plugins use instead of a raw WhatsApp client."""

    def __init__(self, bot: "HappyBot", event: Event, command: str = "", args: list[str] | None = None) -> None:
        self.bot = bot
        self.event = event
        self.message = event.text
        self.sender = event.sender_id
        self.chat = event.chat_id
        self.command = command
        self.args = args or []
        self.quoted = event.quoted
        self.db = bot.db

    async def reply(self, text: str) -> Any:
        return await self.bot.send_message(self.chat, text, reply_to=self.event.message_id)

    async def send(self, text: str, chat_id: str | None = None) -> Any:
        return await self.bot.send_message(chat_id or self.chat, text)

    async def react(self, emoji: str) -> Any:
        return await self.bot.react(self.chat, self.event.message_id, emoji)

    async def download_media(self, target_dir: str | Path | None = None) -> Path | None:
        return await self.bot.download_media(self.event, target_dir)

    @property
    def is_owner(self) -> bool:
        return self.sender in self.bot.owner_ids

    @property
    def is_admin(self) -> bool:
        return self.event.is_admin or self.is_owner


class PluginAPI:
    """Decorator API exposed inside each plugin as ``bot``."""

    def __init__(self) -> None:
        self.commands: list[tuple[dict[str, Any], Handler]] = []
        self.listeners: list[tuple[str, Handler]] = []
        self.tasks: list[tuple[int, Handler]] = []

    def command(self, name: str, *, aliases: tuple[str, ...] = (), owner_only: bool = False, admin_only: bool = False, help: str = ""):
        def decorator(func: Handler) -> Handler:
            self.commands.append(({"name": name, "aliases": aliases, "owner_only": owner_only, "admin_only": admin_only, "help": help}, func))
            return func

        return decorator

    def on(self, event_type: str):
        def decorator(func: Handler) -> Handler:
            self.listeners.append((event_type, func))
            return func

        return decorator

    def task(self, interval: int):
        def decorator(func: Handler) -> Handler:
            self.tasks.append((interval, func))
            return func

        return decorator


class HappyBot:
    """Small async core that discovers plugins and isolates handler errors."""

    def __init__(self) -> None:
        self.prefixes = tuple(config.PREFIXES)
        self.owner_ids = set(config.OWNER_IDS)
        self.plugins_path = Path(config.PLUGINS_PATH)
        self.db = JsonDatabase(config.DATABASE_PATH)
        self.plugins: dict[str, PluginInfo] = {}
        self.queue: asyncio.Queue[Event] = asyncio.Queue()
        self.log = logging.getLogger("happybot")
        self.temp_dir = Path(tempfile.mkdtemp(prefix="happybot-"))

    def load_plugins(self) -> None:
        self.plugins_path.mkdir(exist_ok=True)
        for path in sorted(self.plugins_path.glob("*.py")):
            if path.name.startswith("_"):
                continue
            self.load_plugin(path)

    def load_plugin(self, path: Path) -> None:
        api = PluginAPI()
        spec = importlib.util.spec_from_file_location(f"plugins.{path.stem}", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot load plugin {path}")
        module = importlib.util.module_from_spec(spec)
        module.bot = api
        spec.loader.exec_module(module)
        self.plugins[path.stem] = PluginInfo(path.stem, module, api.commands, api.listeners, api.tasks)
        self.log.info("Loaded plugin %s", path.stem)

    async def emit(self, event: Event) -> None:
        await self.queue.put(event)

    async def serve(self) -> None:
        self.load_plugins()
        asyncio.create_task(self._run_tasks())
        while True:
            event = await self.queue.get()
            asyncio.create_task(self._dispatch(event))

    async def _dispatch(self, event: Event) -> None:
        command, args = self._parse_command(event.text)
        for plugin in self.plugins.values():
            if not plugin.enabled:
                continue
            for event_type, handler in plugin.listeners:
                if event_type in {event.kind, "*"}:
                    await self._safe_call(handler, Context(self, event, command, args), plugin.name)
            if command:
                for meta, handler in plugin.commands:
                    names = {meta["name"], *meta["aliases"]}
                    if command not in names:
                        continue
                    ctx = Context(self, event, command, args)
                    if meta["owner_only"] and not ctx.is_owner:
                        await ctx.reply("Owner permission required.")
                    elif meta["admin_only"] and not ctx.is_admin:
                        await ctx.reply("Admin permission required.")
                    else:
                        await self._safe_call(handler, ctx, plugin.name)

    def _parse_command(self, text: str) -> tuple[str, list[str]]:
        for prefix in self.prefixes:
            if text.startswith(prefix):
                parts = text[len(prefix) :].split()
                return (parts[0].lower(), parts[1:]) if parts else ("", [])
        return "", []

    async def _safe_call(self, handler: Handler, ctx: Context, plugin_name: str) -> None:
        try:
            result = handler(ctx)
            if inspect.isawaitable(result):
                await asyncio.wait_for(result, timeout=config.COMMAND_TIMEOUT)
        except Exception:
            self.log.exception("Plugin %s failed", plugin_name)

    async def _run_tasks(self) -> None:
        while True:
            for plugin in self.plugins.values():
                if plugin.enabled:
                    for interval, handler in plugin.tasks:
                        asyncio.create_task(self._task_loop(interval, handler, plugin.name))
            await asyncio.Event().wait()

    async def _task_loop(self, interval: int, handler: Handler, plugin_name: str) -> None:
        while True:
            await asyncio.sleep(interval)
            await self._safe_call(handler, Context(self, Event("task", "system", "system")), plugin_name)

    async def send_message(self, chat_id: str, text: str, **kwargs: Any) -> None:
        self.log.info("send_message chat=%s text=%s kwargs=%s", chat_id, text, kwargs)

    async def react(self, chat_id: str, message_id: str, emoji: str) -> None:
        self.log.info("react chat=%s message=%s emoji=%s", chat_id, message_id, emoji)

    async def download_media(self, event: Event, target_dir: str | Path | None = None) -> Path | None:
        if event.media is None:
            return None
        directory = Path(target_dir) if target_dir else self.temp_dir
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{event.message_id}.bin"
        target.write_bytes(event.media if isinstance(event.media, bytes) else bytes(event.media))
        return target

    def help_text(self) -> str:
        lines = ["Available commands:"]
        for plugin in self.plugins.values():
            if plugin.enabled:
                for meta, _ in plugin.commands:
                    aliases = f" (aliases: {', '.join(meta['aliases'])})" if meta["aliases"] else ""
                    lines.append(f"{self.prefixes[0]}{meta['name']}{aliases} - {meta['help'] or 'No help'}")
        return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(HappyBot().serve())
