"""HappyBot: a compact plugin-based WhatsApp bot framework.

The transport is intentionally abstract so a WhatsApp adapter can feed incoming
messages into :class:`HappyBot` while plugins stay independent of the client.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import inspect
import json
import logging
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Awaitable, Callable

import config

Handler = Callable[["Context"], Any | Awaitable[Any]]

# ----------------------------------------------------------------------
# Debug logger setup — call this early so every module can use `log`.
# ----------------------------------------------------------------------
log = logging.getLogger("happybot")


# ----------------------------------------------------------------------
# ID helpers
# ----------------------------------------------------------------------
def normalize_whatsapp_id(value: Any) -> str:
    """Normalize WhatsApp IDs so owner checks work with phone numbers or JIDs."""
    text = str(value).strip().lower()
    if not text:
        return ""
    if "@" in text:
        text = text.split("@", 1)[0]
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits or text


def npm_command() -> str:
    """Return an npm executable that works on the current platform."""
    return shutil.which("npm.cmd") or shutil.which("npm") or "npm"


# ----------------------------------------------------------------------
# Events
# ----------------------------------------------------------------------
@dataclass
class Event:
    """Transport-neutral message/event passed in by a WhatsApp adapter.

    We keep `media_base64` as an explicit field so the adapter can stream
    media bytes without forcing the dataclass to accept arbitrary kwargs.
    """
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
    media_base64: str | None = None


@dataclass
class PluginInfo:
    """Runtime information kept for each loaded plugin."""
    name: str
    module: ModuleType
    commands: list[tuple[dict[str, Any], Handler]] = field(default_factory=list)
    listeners: list[tuple[str, Handler]] = field(default_factory=list)
    tasks: list[tuple[int, Handler]] = field(default_factory=list)
    enabled: bool = True


# ----------------------------------------------------------------------
# Storage
# ----------------------------------------------------------------------
class JsonDatabase:
    """Tiny JSON key/value store available to plugins through ctx.db."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.data: dict[str, Any] = {}
        self.load()
        log.debug("JsonDatabase initialised at %s with %d keys", self.path, len(self.data))

    def load(self) -> None:
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8") or "{}")
            except Exception:
                log.exception("Corrupt JSON in %s — starting fresh", self.path)
                self.data = {}
        else:
            self.save()

    def save(self) -> None:
        self.path.write_text(
            json.dumps(self.data, indent=2, sort_keys=True), encoding="utf-8"
        )

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.save()
        log.debug("db.set %s = %r", key, value)


# ----------------------------------------------------------------------
# Plugin context
# ----------------------------------------------------------------------
class Context:
    """Unified object plugins use instead of a raw WhatsApp client."""

    def __init__(self, bot: "HappyBot", event: Event, command: str = "",
                 args: list[str] | None = None) -> None:
        self.bot = bot
        self.event = event
        self.message = event.text
        self.sender = normalize_whatsapp_id(event.sender_id)
        self.chat = event.chat_id
        self.command = command
        self.args = args or []
        self.quoted = event.quoted
        self.db = bot.db

        log.debug(
            "Context built: sender=%s chat=%s cmd=%r args=%r is_owner=%s",
            self.sender, self.chat, self.command, self.args, self.is_owner,
        )

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


# ----------------------------------------------------------------------
# Plugin API exposed to plugin modules
# ----------------------------------------------------------------------
class PluginAPI:
    """Decorator API exposed inside each plugin as ``bot``."""

    def __init__(self) -> None:
        self.commands: list[tuple[dict[str, Any], Handler]] = []
        self.listeners: list[tuple[str, Handler]] = []
        self.tasks: list[tuple[int, Handler]] = []
        log.debug("PluginAPI initialised")

    def command(self, name: str, *, aliases: tuple[str, ...] = (),
                owner_only: bool = False, admin_only: bool = False, help: str = ""):
        def decorator(func: Handler) -> Handler:
            self.commands.append((
                {
                    "name": name.lower(),
                    "aliases": tuple(alias.lower() for alias in aliases),
                    "owner_only": owner_only,
                    "admin_only": admin_only,
                    "help": help,
                },
                func,
            ))
            log.debug("Registered command: %s (aliases=%s, owner_only=%s, admin_only=%s)",
                      name, aliases, owner_only, admin_only)
            return func
        return decorator

    def on(self, event_type: str):
        def decorator(func: Handler) -> Handler:
            self.listeners.append((event_type, func))
            log.debug("Registered listener for %s: %s", event_type, func.__name__)
            return func
        return decorator

    def task(self, interval: int):
        def decorator(func: Handler) -> Handler:
            self.tasks.append((interval, func))
            log.debug("Registered task every %ds: %s", interval, func.__name__)
            return func
        return decorator


# ----------------------------------------------------------------------
# Core bot
# ----------------------------------------------------------------------
class HappyBot:
    """Async core optimized for both tiny installs and very busy WhatsApp accounts."""

    def __init__(self) -> None:
        self.prefixes = tuple(config.PREFIXES)
        self.owner_ids = {
            normalize_whatsapp_id(oid)
            for oid in config.OWNER_IDS
            if normalize_whatsapp_id(oid)
        }
        self.plugins_path = Path(config.PLUGINS_PATH)
        self.db = JsonDatabase(config.DATABASE_PATH)
        self.plugins: dict[str, PluginInfo] = {}
        self.command_handlers: dict[str, list[tuple[PluginInfo, dict[str, Any], Handler]]] = {}
        self.listener_handlers: dict[str, list[tuple[PluginInfo, Handler]]] = {}
        self.queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=config.MAX_QUEUE_SIZE)
        self.handler_slots = asyncio.Semaphore(config.MAX_CONCURRENT_HANDLERS)
        self.running_tasks: set[asyncio.Task[Any]] = set()
        self.log = logging.getLogger("happybot")
        self.started_at = time.monotonic()
        self.stats = {"received": 0, "processed": 0, "dropped": 0, "errors": 0}
        self.temp_dir = Path(tempfile.mkdtemp(prefix="happybot-"))

        self.log.debug(
            "HappyBot initialised: prefixes=%s owners=%s plugins_path=%s",
            self.prefixes, self.owner_ids, self.plugins_path,
        )

    # ---------------- plugin loading ----------------
    def load_plugins(self) -> None:
        self.log.debug("load_plugins() called")
        self.plugins.clear()
        self.command_handlers.clear()
        self.listener_handlers.clear()
        self.plugins_path.mkdir(exist_ok=True)
        for path in sorted(self.plugins_path.glob("*.py")):
            if path.name.startswith("_"):
                continue
            self.load_plugin(path)
        self._rebuild_indexes()
        self.log.debug("load_plugins() done — %d plugins loaded", len(self.plugins))

    def load_plugin(self, path: Path) -> None:
        self.log.debug("Loading plugin: %s", path)
        api = PluginAPI()
        spec = importlib.util.spec_from_file_location(f"plugins.{path.stem}", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot load plugin {path}")
        module = importlib.util.module_from_spec(spec)
        module.bot = api
        try:
            spec.loader.exec_module(module)
        except Exception:
            self.stats["errors"] += 1
            self.log.exception("Failed to load plugin %s", path.stem)
            return
        self.plugins[path.stem] = PluginInfo(
            path.stem, module, api.commands, api.listeners, api.tasks
        )
        self.log.info("Loaded plugin %s", path.stem)

    def _rebuild_indexes(self) -> None:
        for plugin in self.plugins.values():
            for meta, handler in plugin.commands:
                for name in {meta["name"], *meta["aliases"]}:
                    self.command_handlers.setdefault(name, []).append((plugin, meta, handler))
            for event_type, handler in plugin.listeners:
                self.listener_handlers.setdefault(event_type, []).append((plugin, handler))
        self.log.debug(
            "Rebuilt indexes: %d commands, %d listeners",
            sum(len(v) for v in self.command_handlers.values()),
            sum(len(v) for v in self.listener_handlers.values()),
        )

    # ---------------- event loop ----------------
    async def emit(self, event: Event) -> bool:
        self.stats["received"] += 1
        self.log.debug("emit() received event id=%s kind=%s text=%r",
                       event.message_id, event.kind, event.text[:60])
        try:
            self.queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            self.stats["dropped"] += 1
            self.log.warning("Dropping event %s because queue is full", event.message_id)
            return False

    async def serve(self) -> None:
        self.log.debug("serve() starting")
        self.load_plugins()
        self._start_background_tasks()
        self.log.info("HappyBot is now waiting for events.")
        while True:
            event = await self.queue.get()
            self.log.debug("Dequeued event id=%s kind=%s", event.message_id, event.kind)
            task = asyncio.create_task(self._dispatch(event))
            self.running_tasks.add(task)
            task.add_done_callback(self.running_tasks.discard)
            task.add_done_callback(lambda _t: self.queue.task_done())

    async def _dispatch(self, event: Event) -> None:
        self.log.debug("_dispatch: id=%s kind=%s text=%r",
                       event.message_id, event.kind, event.text[:80])
        command, args = self._parse_command(event.text)
        self.log.debug("Parsed: command=%r args=%r", command, args)

        calls: list[tuple[PluginInfo, Handler, Context]] = []

        for plugin, handler in self.listener_handlers.get(event.kind, []):
            if plugin.enabled:
                calls.append((plugin, handler, Context(self, event, command, args)))

        for plugin, handler in self.listener_handlers.get("*", []):
            if plugin.enabled:
                calls.append((plugin, handler, Context(self, event, command, args)))

        if command:
            matched = self.command_handlers.get(command, [])
            self.log.debug("Command %r matched %d handler(s)", command, len(matched))
            for plugin, meta, handler in matched:
                if not plugin.enabled:
                    self.log.debug("Plugin %s disabled — skipping", plugin.name)
                    continue
                ctx = Context(self, event, command, args)
                if meta["owner_only"] and not ctx.is_owner:
                    self.log.debug("Owner-only command denied for %s", ctx.sender)
                    await ctx.reply("Owner permission required.")
                elif meta["admin_only"] and not ctx.is_admin:
                    self.log.debug("Admin-only command denied for %s", ctx.sender)
                    await ctx.reply("Admin permission required.")
                else:
                    calls.append((plugin, handler, ctx))
        else:
            self.log.debug("No command in message — only listeners (if any) will run")

        if calls:
            self.log.debug("Dispatching %d handler(s)", len(calls))
            await asyncio.gather(
                *(self._safe_call(handler, ctx, plugin.name) for plugin, handler, ctx in calls)
            )
        else:
            self.log.debug("No handlers to call for this event")

        self.stats["processed"] += 1

    def _parse_command(self, text: str) -> tuple[str, list[str]]:
        for prefix in self.prefixes:
            if text.startswith(prefix):
                parts = text[len(prefix):].split()
                return (parts[0].lower(), parts[1:]) if parts else ("", [])
        return "", []

    async def _safe_call(self, handler: Handler, ctx: Context, plugin_name: str) -> None:
        async with self.handler_slots:
            started = time.monotonic()
            self.log.debug("→ calling %s.%s", plugin_name, handler.__name__)
            try:
                result = handler(ctx)
                if inspect.isawaitable(result):
                    await asyncio.wait_for(result, timeout=config.COMMAND_TIMEOUT)
            except Exception:
                self.stats["errors"] += 1
                self.log.exception("Plugin %s failed", plugin_name)
            finally:
                elapsed = time.monotonic() - started
                if elapsed >= config.SLOW_HANDLER_WARNING:
                    self.log.warning("Plugin %s handler took %.2fs", plugin_name, elapsed)

    def _start_background_tasks(self) -> None:
        for plugin in self.plugins.values():
            if plugin.enabled:
                for interval, handler in plugin.tasks:
                    task = asyncio.create_task(self._task_loop(interval, handler, plugin.name))
                    self.running_tasks.add(task)
                    task.add_done_callback(self.running_tasks.discard)

    async def _task_loop(self, interval: int, handler: Handler, plugin_name: str) -> None:
        while True:
            await asyncio.sleep(interval)
            await self._safe_call(
                handler, Context(self, Event("task", "system", "system")), plugin_name
            )

    # ---------------- runtime helpers ----------------
    def runtime(self) -> dict[str, Any]:
        return {
            "uptime_seconds": int(time.monotonic() - self.started_at),
            "queue_size": self.queue.qsize(),
            "queue_limit": config.MAX_QUEUE_SIZE,
            "active_tasks": len(self.running_tasks),
            "plugins": len(self.plugins),
            **self.stats,
        }

    # ---------------- default transport (logs only) ----------------
    async def send_message(self, chat_id: str, text: str, **kwargs: Any) -> None:
        self.log.info("send_message chat=%s text=%s kwargs=%s", chat_id, text, kwargs)

    async def react(self, chat_id: str, message_id: str, emoji: str) -> None:
        self.log.info("react chat=%s message=%s emoji=%s", chat_id, message_id, emoji)

    async def adapter_action(self, action: str, **kwargs: Any) -> None:
        self.log.info("adapter_action action=%s kwargs=%s", action, kwargs)

    async def download_media(self, event: Event | dict,
                             target_dir: str | Path | None = None) -> Path | None:
        """Save media that has already been supplied by the WhatsApp adapter."""
        import base64

        media = None
        message_id = "media"

        if isinstance(event, dict):
            media = event.get("media")
            if media is None and event.get("media_base64"):
                media = base64.b64decode(event["media_base64"])
            message_id = event.get("message_id", "media")
        else:
            media = event.media or (
                base64.b64decode(event.media_base64) if event.media_base64 else None
            )
            message_id = event.message_id

        if media is None:
            self.log.debug("download_media: nothing to save for event %s", message_id)
            return None

        directory = Path(target_dir) if target_dir else self.temp_dir
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{message_id}.bin"

        if isinstance(media, bytes):
            target.write_bytes(media)
        else:
            target.write_bytes(bytes(media))
        self.log.debug("download_media: wrote %d bytes to %s", len(target.read_bytes()), target)
        return target

    def help_text(self) -> str:
        lines = ["Available commands:"]
        for plugin in self.plugins.values():
            if plugin.enabled:
                for meta, _ in plugin.commands:
                    aliases = f" (aliases: {', '.join(meta['aliases'])})" if meta["aliases"] else ""
                    lines.append(f"{self.prefixes[0]}{meta['name']}{aliases} - {meta['help'] or 'No help'}")
        return "\n".join(lines)


# ----------------------------------------------------------------------
# Stdio bridge for the Node.js WhatsApp adapter
# ----------------------------------------------------------------------
class StdioHappyBot(HappyBot):
    """Bridge mode used by the Baileys Node.js WhatsApp adapter."""

    async def run_stdio(self) -> None:
        self.log.debug("run_stdio() starting")
        self.load_plugins()
        self._start_background_tasks()
        loop = asyncio.get_running_loop()
        self.log.info("StdioHappyBot is now reading JSON events from stdin.")
        while True:
            try:
                line = await loop.run_in_executor(None, input)
            except EOFError:
                self.log.info("stdin closed — exiting run_stdio()")
                break
            if not line.strip():
                continue

            self.log.debug("Stdio received line: %s", line[:200])

            try:
                payload = json.loads(line)
            except Exception:
                self.stats["errors"] += 1
                self.log.exception("Invalid JSON from adapter: %s", line)
                continue

            # media_base64 is now an explicit Event field, so we can pass it directly.
            # We still defensively filter unknown keys, just in case.
            valid_fields = set(Event.__dataclass_fields__.keys())
            event_kwargs = {k: v for k, v in payload.items() if k in valid_fields}

            try:
                event = Event(**event_kwargs)
            except Exception:
                self.stats["errors"] += 1
                self.log.exception("Invalid adapter event: %s", line)
                continue

            await self._dispatch(event)

    async def send_message(self, chat_id: str, text: str, **kwargs: Any) -> None:
        self._write_action({"action": "send_message", "chat_id": chat_id, "text": text, **kwargs})

    async def react(self, chat_id: str, message_id: str, emoji: str) -> None:
        self._write_action({"action": "react", "chat_id": chat_id, "message_id": message_id, "emoji": emoji})

    async def adapter_action(self, action: str, **kwargs: Any) -> None:
        self._write_action({"action": "adapter_action", "name": action, **kwargs})

    def _write_action(self, action: dict[str, Any]) -> None:
        print(json.dumps(action, ensure_ascii=False), flush=True)


# ----------------------------------------------------------------------
# Bootstrap
# ----------------------------------------------------------------------
def run_whatsapp_adapter() -> int:
    """Connect once with connect.js if needed, then start the WhatsApp bot."""
    if not Path("package.json").exists():
        print("package.json is missing; cannot start the Baileys WhatsApp adapter.", file=sys.stderr)
        return 1
    if not Path("node_modules").exists():
        print("Installing Baileys dependencies with npm install...")
        install = subprocess.run([npm_command(), "install"], check=False)
        if install.returncode != 0:
            print("npm install failed. Make sure Node.js and npm are installed, then run `npm install` in this folder.")
            return install.returncode
    if not Path("auth_info/creds.json").exists():
        print("No saved WhatsApp session found. Starting one-time connection setup...")
        setup = subprocess.run(["node", "connect.js"], check=False)
        if setup.returncode != 0:
            return setup.returncode
    return subprocess.call(["node", "whatsapp_adapter.js"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Run HappyBot WhatsApp bot.")
    parser.add_argument("--stdio", action="store_true", help="Internal mode: read adapter events as JSON lines and write bot actions as JSON lines.")
    parser.add_argument("--core", action="store_true", help="Developer mode: run only the Python plugin core without WhatsApp.")
    parser.add_argument("--debug", action="store_true", help="Verbose DEBUG-level logging.")
    args = parser.parse_args()

    level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log.debug("main() invoked with args=%r", args)

    if args.stdio:
        asyncio.run(StdioHappyBot().run_stdio())
    elif args.core:
        asyncio.run(HappyBot().serve())
    else:
        raise SystemExit(run_whatsapp_adapter())


if __name__ == "__main__":
    main()