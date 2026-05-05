import discord
from discord.ext import commands
import aiohttp
import asyncio
import json
import os
import traceback
from datetime import datetime, timezone


# =========================
# CONFIG
# =========================
CONFIG_FILE = "config.json"
SYNC_STATE_FILE = "bot_sync_state.json"

DEFAULT_CONFIG_VALUES = {
    # Keep this false for fast normal restarts.
    # Use /bot_sync or !bot_sync manually after changing slash commands.
    "SYNC_COMMANDS_ON_STARTUP": False
}


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_json_file(path, default):
    if not os.path.exists(path):
        return default

    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default


def save_json_file(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)


def load_config():
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError("config.json not found.")

    return load_json_file(CONFIG_FILE, {})


def save_config(config):
    save_json_file(CONFIG_FILE, config)


def ensure_config_defaults():
    config = load_config()
    changed = False

    for key, value in DEFAULT_CONFIG_VALUES.items():
        if key not in config:
            config[key] = value
            changed = True

    if changed:
        save_config(config)

    return config


CONFIG = ensure_config_defaults()

TOKEN = CONFIG["DISCORD_TOKEN"]
DISCORD_GUILD_ID = int(CONFIG["DISCORD_GUILD_ID"])
CHANNEL_ID = int(CONFIG["CHANNEL_ID"]) if CONFIG.get("CHANNEL_ID") else None


# =========================
# INTENTS
# =========================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True


# =========================
# MODULES
# =========================
EXTENSIONS = [
    "modules.tracker",
    "modules.guild_sync",
    "modules.guild_link",
    "modules.raffle",
    "modules.guild_upgrades",
    "modules.guildbank_duplicates",
    "modules.role_tools",
    "modules.admin_panel",
    "modules.raffle_panel",
    "modules.vr_bot_panels",
    "modules.emergency_prefix",
]


# =========================
# FRIENDLY DISCORD SYNC ERRORS
# =========================
class DiscordCommandCreateLimitError(Exception):
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


def is_discord_create_limit_error(error) -> bool:
    """
    Discord code 30034:
    Max number of daily application command creates has been reached.
    """
    if isinstance(error, DiscordCommandCreateLimitError):
        return True

    if isinstance(error, discord.HTTPException):
        if getattr(error, "code", None) == 30034:
            return True

        text = str(error).lower()
        if "max number of daily application command creates" in text:
            return True

    text = str(error).lower()

    return (
        "30034" in text
        or "max number of daily application command creates" in text
        or "daily application command creates" in text
    )


def friendly_sync_error_message(error, mode: str = "slash command sync") -> str:
    if is_discord_create_limit_error(error):
        retry_text = ""

        retry_after = getattr(error, "retry_after", None)

        if retry_after is not None:
            try:
                retry_text = f"\nShort retry-after window: **{round(float(retry_after), 1)}s**"
            except Exception:
                retry_text = ""

        return (
            "⚠️ **Discord command-create limit reached**\n\n"
            "Discord refused the sync because this bot has hit the daily application-command "
            "create limit.\n\n"
            "What to do now:\n"
            "• Do **not** run more sync commands today.\n"
            "• Keep `SYNC_COMMANDS_ON_STARTUP` set to `false`.\n"
            "• Try again after Discord’s daily quota resets.\n\n"
            "Technical detail: Discord error code `30034`."
            f"{retry_text}"
        )

    if isinstance(error, asyncio.TimeoutError):
        return (
            f"⚠️ **{mode} timed out**\n\n"
            "The bot is still running, but Discord did not answer the sync request in time.\n\n"
            "What to do:\n"
            "• Do not spam repeated sync attempts.\n"
            "• Try `!bot_rest_sync_core` to check whether Discord returns a clearer error.\n"
            "• If REST reports error `30034`, stop syncing until the daily limit resets."
        )

    return f"⚠️ {mode} failed: `{error}`"


def compact_traceback(error) -> str:
    tb = traceback.format_exception(type(error), error, error.__traceback__)
    return "".join(tb)[-1800:]


# =========================
# BOT CLASS
# =========================
class GW2Bot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents
        )

        self.loaded_extensions = []
        self.failed_extensions = []
        self.startup_log_sent = False

        sync_state = self.load_sync_state()

        self.last_sync_count = sync_state.get("last_count")
        self.last_sync_mode = sync_state.get("last_mode")
        self.last_sync_error = sync_state.get("last_error")
        self.last_sync_success = sync_state.get("last_success")
        self.last_sync_attempt_at = sync_state.get("last_attempt_at")

    # =========================
    # CONFIG HELPERS
    # =========================
    def get_config(self):
        return load_config()

    def update_config_value(self, key, value):
        config = load_config()
        config[key] = value
        save_config(config)

    def should_sync_on_startup(self):
        config = load_config()
        return bool(config.get("SYNC_COMMANDS_ON_STARTUP", False))

    # =========================
    # SYNC STATE HELPERS
    # =========================
    def load_sync_state(self):
        return load_json_file(SYNC_STATE_FILE, {
            "last_mode": None,
            "last_success": None,
            "last_count": None,
            "last_error": None,
            "last_attempt_at": None
        })

    def save_sync_state(
        self,
        mode: str,
        success: bool,
        count: int | None = None,
        error: str | None = None
    ):
        state = {
            "last_mode": mode,
            "last_success": success,
            "last_count": count,
            "last_error": error,
            "last_attempt_at": utc_now_iso()
        }

        save_json_file(SYNC_STATE_FILE, state)

        self.last_sync_mode = mode
        self.last_sync_success = success
        self.last_sync_count = count
        self.last_sync_error = error
        self.last_sync_attempt_at = state["last_attempt_at"]

    # =========================
    # BOT LOGGING
    # =========================
    async def get_bot_log_channel(self):
        if not CHANNEL_ID:
            return None

        channel = self.get_channel(CHANNEL_ID)

        if channel is not None:
            return channel

        try:
            return await self.fetch_channel(CHANNEL_ID)
        except Exception:
            return None

    async def send_bot_log(self, message: str):
        channel = await self.get_bot_log_channel()

        if channel is None:
            print(f"[BOT LOG CHANNEL NOT FOUND] {message}")
            return

        try:
            await channel.send(message)
        except Exception as e:
            print(f"[BOT LOG SEND FAILED] {e}")
            print(message)

    # =========================
    # SAFE MODULE LOADING
    # =========================
    async def safe_load_extension(self, extension_name: str):
        try:
            await self.load_extension(extension_name)

            self.loaded_extensions.append(extension_name)
            print(f"✅ Loaded extension: {extension_name}")

        except Exception as e:
            error_text = traceback.format_exc()

            self.failed_extensions.append({
                "extension": extension_name,
                "error": str(e),
                "traceback": error_text
            })

            print(f"❌ Failed to load extension: {extension_name}")
            print(error_text)

    async def load_all_extensions(self):
        for extension in EXTENSIONS:
            await self.safe_load_extension(extension)

    # =========================
    # SLASH COMMAND SYNC HELPERS
    # =========================
    def get_guild_object(self):
        return discord.Object(id=DISCORD_GUILD_ID)

    async def get_application_id(self):
        if self.application_id:
            return int(self.application_id)

        app_info = await self.application_info()
        return int(app_info.id)

    async def clear_guild_commands(self, timeout_seconds: int = 120):
        guild = self.get_guild_object()

        print("🧹 Preparing empty guild slash command tree...")

        self.tree.clear_commands(guild=guild)

        print("🧹 Sending guild slash command clear request to Discord...")

        try:
            cleared = await asyncio.wait_for(
                self.tree.sync(guild=guild),
                timeout=timeout_seconds
            )

            self.save_sync_state(
                mode="clear",
                success=True,
                count=len(cleared),
                error=None
            )

            print(
                f"✅ Cleared guild slash commands for {DISCORD_GUILD_ID}. "
                f"Remaining: {len(cleared)}"
            )

            return cleared

        except Exception as e:
            self.save_sync_state(
                mode="clear",
                success=False,
                count=None,
                error=str(e)
            )
            raise

    async def sync_core_commands(self, timeout_seconds: int = 120):
        guild = self.get_guild_object()

        print("🔄 Preparing CORE slash command tree only...")

        self.tree.clear_commands(guild=guild)

        self.tree.add_command(bot_status, guild=guild)
        self.tree.add_command(bot_restart, guild=guild)
        self.tree.add_command(bot_sync, guild=guild)
        self.tree.add_command(bot_sync_startup, guild=guild)

        print("🔄 Sending CORE slash command sync request to Discord...")

        try:
            synced = await asyncio.wait_for(
                self.tree.sync(guild=guild),
                timeout=timeout_seconds
            )

            self.save_sync_state(
                mode="core",
                success=True,
                count=len(synced),
                error=None
            )

            print(f"✅ Synced {len(synced)} CORE guild slash commands to {DISCORD_GUILD_ID}")

            return synced

        except Exception as e:
            self.save_sync_state(
                mode="core",
                success=False,
                count=None,
                error=str(e)
            )
            raise

    async def sync_guild_commands(self, timeout_seconds: int = 300):
        guild = self.get_guild_object()

        print("🔄 Preparing FULL guild slash command tree...")

        self.tree.clear_commands(guild=guild)
        self.tree.copy_global_to(guild=guild)

        print("🔄 Sending FULL guild slash command sync request to Discord...")

        try:
            synced = await asyncio.wait_for(
                self.tree.sync(guild=guild),
                timeout=timeout_seconds
            )

            self.save_sync_state(
                mode="full",
                success=True,
                count=len(synced),
                error=None
            )

            print(f"✅ Synced {len(synced)} FULL guild slash commands to {DISCORD_GUILD_ID}")

            return synced

        except Exception as e:
            self.save_sync_state(
                mode="full",
                success=False,
                count=None,
                error=str(e)
            )
            raise

    async def rest_sync_core_commands(self, timeout_seconds: int = 60):
        """
        Direct REST diagnostic sync.

        Replaces this guild's slash command list with only the 4 core bot commands.
        Useful when discord.py tree.sync() hides the real Discord error.
        """
        application_id = await self.get_application_id()

        url = (
            f"https://discord.com/api/v10/applications/"
            f"{application_id}/guilds/{DISCORD_GUILD_ID}/commands"
        )

        admin_permission = "8"

        payload = [
            {
                "name": "bot_status",
                "description": "Admin only: show bot module status",
                "type": 1,
                "default_member_permissions": admin_permission,
                "dm_permission": False
            },
            {
                "name": "bot_sync",
                "description": "Admin only: manually sync slash commands",
                "type": 1,
                "default_member_permissions": admin_permission,
                "dm_permission": False
            },
            {
                "name": "bot_sync_startup",
                "description": "Admin only: enable or disable slash command sync on startup",
                "type": 1,
                "default_member_permissions": admin_permission,
                "dm_permission": False,
                "options": [
                    {
                        "name": "enabled",
                        "description": "Enable or disable slash command sync during bot startup",
                        "type": 5,
                        "required": True
                    }
                ]
            },
            {
                "name": "bot_restart",
                "description": "Admin only: restart the bot service",
                "type": 1,
                "default_member_permissions": admin_permission,
                "dm_permission": False
            }
        ]

        headers = {
            "Authorization": f"Bot {TOKEN}",
            "Content-Type": "application/json"
        }

        timeout = aiohttp.ClientTimeout(total=timeout_seconds)

        print("🌐 Sending CORE slash command sync through direct Discord REST API...")

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.put(url, headers=headers, json=payload) as resp:
                    text = await resp.text()

                    try:
                        data = json.loads(text) if text else []
                    except Exception:
                        data = text

                    if resp.status == 429:
                        retry_after = None
                        code = None
                        message = text

                        if isinstance(data, dict):
                            retry_after = data.get("retry_after")
                            code = data.get("code")
                            message = data.get("message", text)

                        if code == 30034 or "daily application command creates" in str(message).lower():
                            raise DiscordCommandCreateLimitError(
                                message=str(message),
                                retry_after=retry_after
                            )

                    if resp.status < 200 or resp.status >= 300:
                        raise Exception(
                            f"Discord REST sync failed with HTTP {resp.status}: {text}"
                        )

            self.save_sync_state(
                mode="rest_core",
                success=True,
                count=len(data),
                error=None
            )

            print(
                f"✅ REST synced {len(data)} CORE guild slash commands "
                f"to {DISCORD_GUILD_ID}"
            )

            return data

        except Exception as e:
            self.save_sync_state(
                mode="rest_core",
                success=False,
                count=None,
                error=str(e)
            )
            raise

    # =========================
    # STATUS BUILDERS
    # =========================
    def sync_status_lines(self):
        lines = []

        if self.last_sync_attempt_at:
            outcome = "✅ Success" if self.last_sync_success else "❌ Failed"

            lines.append(f"Last sync: **{outcome}**")
            lines.append(f"Mode: **{self.last_sync_mode or 'unknown'}**")
            lines.append(f"Attempted: **{self.last_sync_attempt_at}**")

            if self.last_sync_count is not None:
                lines.append(f"Command count: **{self.last_sync_count}**")

            if self.last_sync_error:
                lines.append(f"Error: `{self.last_sync_error}`")
        else:
            lines.append("Last sync: **None recorded**")

        return lines

    def startup_sync_warning_line(self):
        if self.should_sync_on_startup():
            return "Slash sync on startup: **Enabled ⚠️ slower / temporary only**"

        return "Slash sync on startup: **Disabled ✅ recommended**"

    # =========================
    # SETUP HOOK
    # =========================
    async def setup_hook(self):
        await self.load_all_extensions()

        # Core bot admin slash commands.
        # These only reach Discord after a sync.
        self.tree.add_command(bot_status)
        self.tree.add_command(bot_restart)
        self.tree.add_command(bot_sync)
        self.tree.add_command(bot_sync_startup)

        if self.should_sync_on_startup():
            print("⚠️ Slash command sync on startup is enabled. This is slower and should be temporary.")
            try:
                await self.sync_guild_commands(timeout_seconds=300)
            except Exception as e:
                message = friendly_sync_error_message(e, "Startup slash command sync")
                print(message)
                await self.send_bot_log(message)
        else:
            print("⚡ Slash command sync on startup is disabled. Startup will be faster.")

    # =========================
    # STARTUP LOG
    # =========================
    async def send_startup_report(self):
        """
        Compact Discord startup message.

        Full details stay available through:
        - /bot_status
        - !bot_status
        """
        if self.startup_log_sent:
            return

        self.startup_log_sent = True

        loaded_count = len(self.loaded_extensions)
        failed_count = len(self.failed_extensions)

        lines = [
            "🤖 **GW2 Bot Started**",
            f"Loaded modules: ✅ **{loaded_count}**",
            f"Failed modules: ❌ **{failed_count}**",
            self.startup_sync_warning_line(),
        ]

        if self.failed_extensions:
            lines.append("")
            lines.append("**Failed modules:**")

            for failed in self.failed_extensions:
                lines.append(f"❌ `{failed['extension']}` — `{failed['error']}`")

            lines.append("")
            lines.append("Check logs with:")
            lines.append("`journalctl -u gw2bot -f -o cat`")

        await self.send_bot_log("\n".join(lines))


bot = GW2Bot()


# =========================
# PERMISSION HELPERS
# =========================
def is_admin(interaction: discord.Interaction) -> bool:
    return (
        isinstance(interaction.user, discord.Member)
        and interaction.user.guild_permissions.administrator
    )


def interaction_display_name(interaction: discord.Interaction) -> str:
    if isinstance(interaction.user, discord.Member):
        return interaction.user.display_name

    return interaction.user.name


def context_display_name(ctx: commands.Context) -> str:
    if isinstance(ctx.author, discord.Member):
        return ctx.author.display_name

    return ctx.author.name


def bot_status_message() -> str:
    loaded_count = len(bot.loaded_extensions)
    failed_count = len(bot.failed_extensions)

    lines = [
        "🤖 **Bot Status**",
        "",
        f"Loaded modules: ✅ **{loaded_count}**",
        f"Failed modules: ❌ **{failed_count}**",
        bot.startup_sync_warning_line(),
        "",
        "**Command Sync State:**",
    ]

    lines.extend(bot.sync_status_lines())

    if bot.loaded_extensions:
        lines.append("")
        lines.append("**Loaded:**")
        lines.extend(
            f"✅ `{extension}`"
            for extension in bot.loaded_extensions
        )

    if bot.failed_extensions:
        lines.append("")
        lines.append("**Failed:**")

        for failed in bot.failed_extensions:
            lines.append(f"❌ `{failed['extension']}` — `{failed['error']}`")

        lines.append("")
        lines.append("Check logs with:")
        lines.append("`journalctl -u gw2bot -f -o cat`")

    return "\n".join(lines)


def bot_sync_help_message() -> str:
    return (
        "🧭 **Bot Sync Help**\n\n"
        "**Normal workflow**\n"
        "Use `/bot_sync` or `!bot_sync` only after adding, removing, renaming, "
        "or restructuring slash commands.\n\n"
        "**Recommended config**\n"
        "`SYNC_COMMANDS_ON_STARTUP` should stay `false` for fast restarts.\n\n"
        "**Commands**\n"
        "`/bot_sync` / `!bot_sync` — sync the full slash command tree.\n"
        "`!bot_rest_sync_core` — emergency REST sync of only the 4 core bot commands.\n"
        "`!bot_sync_core` — diagnostic sync of only core commands through discord.py.\n"
        "`!bot_sync_clear` — emergency clear of guild slash commands. Use carefully.\n"
        "`!bot_sync_startup false` — disable startup sync from chat.\n\n"
        "**Important Discord limit**\n"
        "Discord has a daily application-command create limit. If you see error `30034`, "
        "stop syncing for the day and try again after the quota resets.\n\n"
        "**Safe rule**\n"
        "One intentional sync after command changes. No repeated clear/sync loops."
    )


# =========================
# CORE SLASH COMMANDS
# =========================
@discord.app_commands.command(
    name="bot_status",
    description="Admin only: show bot module status"
)
@discord.app_commands.default_permissions(administrator=True)
async def bot_status(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    if not is_admin(interaction):
        return await interaction.followup.send("❌ No permission.")

    await interaction.followup.send(bot_status_message())


@discord.app_commands.command(
    name="bot_sync",
    description="Admin only: manually sync slash commands"
)
@discord.app_commands.default_permissions(administrator=True)
async def bot_sync(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    if not is_admin(interaction):
        return await interaction.followup.send("❌ No permission.")

    try:
        await interaction.followup.send(
            "🔄 **Syncing full slash command tree...**\n"
            "Do not run repeated syncs if this fails."
        )

        synced = await bot.sync_guild_commands(timeout_seconds=300)

        await interaction.followup.send(
            f"✅ **Slash commands synced**\n\n"
            f"Mode: **full**\n"
            f"Guild commands: **{len(synced)}**\n"
            f"Started by: ✅ {interaction_display_name(interaction)}"
        )

        await bot.send_bot_log(
            f"🔄 **Slash commands synced**\n"
            f"Mode: **full**\n"
            f"Guild commands: **{len(synced)}**\n"
            f"Started by: ✅ {interaction_display_name(interaction)}"
        )

    except Exception as e:
        message = friendly_sync_error_message(e, "Full slash command sync")
        await interaction.followup.send(message)
        await bot.send_bot_log(
            f"{message}\n\nStarted by: ✅ {interaction_display_name(interaction)}"
        )


@discord.app_commands.command(
    name="bot_sync_startup",
    description="Admin only: enable or disable slash command sync on startup"
)
@discord.app_commands.default_permissions(administrator=True)
async def bot_sync_startup(interaction: discord.Interaction, enabled: bool):
    await interaction.response.defer(ephemeral=True)

    if not is_admin(interaction):
        return await interaction.followup.send("❌ No permission.")

    bot.update_config_value("SYNC_COMMANDS_ON_STARTUP", bool(enabled))

    if enabled:
        msg = (
            "⚠️ **Startup sync enabled**\n\n"
            "Slash commands will sync every time the bot starts. "
            "This is slower and should only be temporary."
        )
    else:
        msg = (
            "✅ **Startup sync disabled**\n\n"
            "This is the recommended setting for normal use."
        )

    await interaction.followup.send(msg)

    await bot.send_bot_log(
        f"⚙️ **Startup sync setting updated**\n"
        f"Slash sync on startup: **{'Enabled ⚠️' if enabled else 'Disabled ✅'}**\n"
        f"Changed by: ✅ {interaction_display_name(interaction)}"
    )


@discord.app_commands.command(
    name="bot_restart",
    description="Admin only: restart the bot service"
)
@discord.app_commands.default_permissions(administrator=True)
async def bot_restart(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    if not is_admin(interaction):
        return await interaction.followup.send("❌ No permission.")

    await interaction.followup.send("🔄 Restarting bot...")

    await bot.send_bot_log(
        f"🔄 **Bot restart requested**\n"
        f"Started by: ✅ {interaction_display_name(interaction)}"
    )

    await asyncio.sleep(1)

    os._exit(0)


# =========================
# EMERGENCY PREFIX COMMANDS
# These work even when slash commands are stale/broken.
# =========================
@bot.command(name="bot_sync_help")
@commands.has_permissions(administrator=True)
async def prefix_bot_sync_help(ctx: commands.Context):
    await ctx.reply(bot_sync_help_message())


@bot.command(name="bot_rest_sync_core")
@commands.has_permissions(administrator=True)
async def prefix_bot_rest_sync_core(ctx: commands.Context):
    try:
        await ctx.reply("🌐 REST syncing core slash commands only...")

        synced = await bot.rest_sync_core_commands(timeout_seconds=60)

        await ctx.reply(
            f"✅ **Core slash commands REST synced**\n"
            f"Guild commands: **{len(synced)}**"
        )

        await bot.send_bot_log(
            f"🌐 **Core slash commands REST synced via emergency prefix command**\n"
            f"Guild commands: **{len(synced)}**\n"
            f"Started by: ✅ {context_display_name(ctx)}"
        )

    except Exception as e:
        message = friendly_sync_error_message(e, "REST core slash command sync")
        await ctx.reply(message)
        await bot.send_bot_log(
            f"{message}\n\nStarted by: ✅ {context_display_name(ctx)}"
        )


@bot.command(name="bot_sync_core")
@commands.has_permissions(administrator=True)
async def prefix_bot_sync_core(ctx: commands.Context):
    try:
        await ctx.reply("🔄 Syncing core slash commands only via discord.py...")

        synced = await bot.sync_core_commands(timeout_seconds=120)

        await ctx.reply(
            f"✅ **Core slash commands synced**\n"
            f"Guild commands: **{len(synced)}**"
        )

        await bot.send_bot_log(
            f"🔄 **Core slash commands synced via emergency prefix command**\n"
            f"Guild commands: **{len(synced)}**\n"
            f"Started by: ✅ {context_display_name(ctx)}"
        )

    except Exception as e:
        message = friendly_sync_error_message(e, "Core slash command sync")
        await ctx.reply(message)
        await bot.send_bot_log(
            f"{message}\n\nStarted by: ✅ {context_display_name(ctx)}"
        )


@bot.command(name="bot_sync")
@commands.has_permissions(administrator=True)
async def prefix_bot_sync(ctx: commands.Context):
    try:
        await ctx.reply(
            "🔄 **Syncing full slash command tree...**\n"
            "Do not run repeated syncs if this fails."
        )

        synced = await bot.sync_guild_commands(timeout_seconds=300)

        await ctx.reply(
            f"✅ **Slash commands synced**\n"
            f"Mode: **full**\n"
            f"Guild commands: **{len(synced)}**"
        )

        await bot.send_bot_log(
            f"🔄 **Full slash commands synced via emergency prefix command**\n"
            f"Guild commands: **{len(synced)}**\n"
            f"Started by: ✅ {context_display_name(ctx)}"
        )

    except Exception as e:
        message = friendly_sync_error_message(e, "Full slash command sync")
        await ctx.reply(message)
        await bot.send_bot_log(
            f"{message}\n\nStarted by: ✅ {context_display_name(ctx)}"
        )


@bot.command(name="bot_sync_clear")
@commands.has_permissions(administrator=True)
async def prefix_bot_sync_clear(ctx: commands.Context):
    try:
        await ctx.reply(
            "🧹 **Clearing guild slash commands...**\n"
            "Use carefully. You will need a successful sync afterwards to restore slash commands."
        )

        cleared = await bot.clear_guild_commands(timeout_seconds=120)

        await ctx.reply(
            f"✅ **Guild slash commands cleared**\n"
            f"Remaining guild commands: **{len(cleared)}**"
        )

        await bot.send_bot_log(
            f"🧹 **Guild slash commands cleared via emergency prefix command**\n"
            f"Remaining guild commands: **{len(cleared)}**\n"
            f"Started by: ✅ {context_display_name(ctx)}"
        )

    except Exception as e:
        message = friendly_sync_error_message(e, "Guild slash command clear")
        await ctx.reply(message)
        await bot.send_bot_log(
            f"{message}\n\nStarted by: ✅ {context_display_name(ctx)}"
        )


@bot.command(name="bot_status")
@commands.has_permissions(administrator=True)
async def prefix_bot_status(ctx: commands.Context):
    await ctx.reply(bot_status_message())


@bot.command(name="bot_restart")
@commands.has_permissions(administrator=True)
async def prefix_bot_restart(ctx: commands.Context):
    await ctx.reply("🔄 Restarting bot...")

    await bot.send_bot_log(
        f"🔄 **Bot restart requested via emergency prefix command**\n"
        f"Started by: ✅ {context_display_name(ctx)}"
    )

    await asyncio.sleep(1)

    os._exit(0)


@bot.command(name="bot_sync_startup")
@commands.has_permissions(administrator=True)
async def prefix_bot_sync_startup(ctx: commands.Context, enabled: str):
    value = enabled.lower().strip()

    if value not in ("true", "false", "yes", "no", "on", "off", "1", "0"):
        return await ctx.reply(
            "❌ Use one of: `true`, `false`, `on`, `off`, `yes`, `no`, `1`, `0`."
        )

    enabled_bool = value in ("true", "yes", "on", "1")
    bot.update_config_value("SYNC_COMMANDS_ON_STARTUP", enabled_bool)

    if enabled_bool:
        msg = (
            "⚠️ **Startup sync enabled**\n"
            "This is slower and should only be temporary."
        )
    else:
        msg = (
            "✅ **Startup sync disabled**\n"
            "This is the recommended setting for normal use."
        )

    await ctx.reply(msg)

    await bot.send_bot_log(
        f"⚙️ **Startup sync setting updated via emergency prefix command**\n"
        f"Slash sync on startup: **{'Enabled ⚠️' if enabled_bool else 'Disabled ✅'}**\n"
        f"Changed by: ✅ {context_display_name(ctx)}"
    )


# =========================
# PREFIX COMMAND ERROR HANDLING
# =========================
@prefix_bot_sync_help.error
@prefix_bot_rest_sync_core.error
@prefix_bot_sync_core.error
@prefix_bot_sync.error
@prefix_bot_sync_clear.error
@prefix_bot_status.error
@prefix_bot_restart.error
@prefix_bot_sync_startup.error
async def prefix_admin_command_error(ctx: commands.Context, error):
    if isinstance(error, commands.MissingPermissions):
        return await ctx.reply("❌ No permission.")

    if isinstance(error, commands.MissingRequiredArgument):
        return await ctx.reply("❌ Missing required argument.")

    await ctx.reply(f"⚠️ Error: `{error}`")


# =========================
# READY EVENT
# =========================
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    await bot.send_startup_report()


# =========================
# MAIN START
# =========================
async def main():
    async with bot:
        await bot.start(TOKEN)


asyncio.run(main())