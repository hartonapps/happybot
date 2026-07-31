"""Configuration defaults for HappyBot."""

# Put your WhatsApp number here in international format, with or without the
# `@s.whatsapp.net` suffix. Example: {"2348012345678"} or
# {"2348012345678@s.whatsapp.net"}.
OWNER_IDS = {"2348067871926", "2348067871926@s.whatsapp.net"}
PREFIXES = ("!", "/", ".")
DATABASE_PATH = "database.json"
PLUGINS_PATH = "plugins"
COMMAND_TIMEOUT = 30
MAX_QUEUE_SIZE = 10000
MAX_CONCURRENT_HANDLERS = 100
SLOW_HANDLER_WARNING = 5
