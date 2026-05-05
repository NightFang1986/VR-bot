import json
import os
from datetime import datetime, timezone
from typing import List

import discord
from discord.ext import commands


GUILD_DATA_FILE = "guild_data.json"
SYNC_STATE_FILE = "guild_sync_state.json"
BOT_SYNC_STATE_FILE = "bot_sync_state.json"


class AdminPanelView(discord.ui.View):
    def __init__(self, cog: "AdminPanel", owner_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "❌ This admin panel belongs to someone else.",
                ephemeral=True
            )
            return False

        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "❌ This can only be used inside the server.",
                ephemeral=True
            )
            return False

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ You need administrator permissions to use this panel.",
                ephemeral=True
            )
            return False

        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

    @discord.ui.button(
        label="Bot Status",
        style=discord.ButtonStyle.secondary,
        emoji="🤖"
    )
    async def bot_status_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await interaction.response.defer(ephemeral=True)

        message = self.cog.build_bot_status_message()
        chunks = self.cog.split_message(message)

        for index, chunk in enumerate(chunks):
            await interaction.followup.send(chunk, ephemeral=True)

    @discord.ui.button(
        label="Guild Sync Status",
        style=discord.ButtonStyle.secondary,
        emoji="🔄"
    )
    async def guild_sync_status_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await interaction.response.defer(ephemeral=True)

        message = self.cog.build_guild_sync_status_message()
        chunks = self.cog.split_message(message)

        for chunk in chunks:
            await interaction.followup.send(chunk, ephemeral=True)

    @discord.ui.button(
        label="Guild Sync Now",
        style=discord.ButtonStyle.primary,
        emoji="⚡"
    )
    async def guild_sync_now_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await interaction.response.defer(ephemeral=True)

        guild_sync_cog = self.cog.bot.get_cog("GuildSync")

        if guild_sync_cog is None:
            return await interaction.followup.send(
                "❌ GuildSync cog is not loaded.",
                ephemeral=True
            )

        try:
            result = await guild_sync_cog.sync_guild_data()
            report = await guild_sync_cog.build_sync_report(result, manual=True)

            if not report:
                report = "🔄 **Guild Changes**\n\nNo members joined or left."

            chunks = self.cog.split_message(report)

            for chunk in chunks:
                await interaction.followup.send(chunk, ephemeral=True)

        except Exception as error:
            await interaction.followup.send(
                f"⚠️ Guild sync failed:\n```text\n{error}\n```",
                ephemeral=True
            )

    @discord.ui.button(
        label="Donation Summary",
        style=discord.ButtonStyle.secondary,
        emoji="💰"
    )
    async def donation_summary_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await interaction.response.defer(ephemeral=True)

        message = self.cog.build_donation_summary_message()
        chunks = self.cog.split_message(message)

        for chunk in chunks:
            await interaction.followup.send(chunk, ephemeral=True)

    @discord.ui.button(
        label="Role Missing Help",
        style=discord.ButtonStyle.secondary,
        emoji="🔎"
    )
    async def role_missing_help_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await interaction.response.defer(ephemeral=True)

        await interaction.followup.send(
            (
                "🔎 **Role Missing Help**\n\n"
                "Use this command to find members who do **not** have a role:\n\n"
                "`/role_missing role:@Role include_bots:false`\n\n"
                "Examples:\n"
                "`/role_missing role:@Member include_bots:false`\n"
                "`/role_missing role:@Officer include_bots:false`"
            ),
            ephemeral=True
        )


class AdminPanel(commands.Cog):
    """
    Ephemeral admin control panel.

    Current buttons:
        - Bot Status
        - Guild Sync Status
        - Guild Sync Now
        - Donation Summary
        - Role Missing Help

    Safe first panel:
        - No destructive actions
        - No public spam
        - No GW2 API calls except Guild Sync Now through the existing GuildSync cog
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # =========================
    # FILE HELPERS
    # =========================
    def load_json(self, path, default):
        if not os.path.exists(path):
            return default

        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return default

    # =========================
    # FORMAT HELPERS
    # =========================
    def now_utc_text(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def safe_int(self, value, default: int = 0) -> int:
        try:
            return int(value or 0)
        except Exception:
            return default

    def format_gold(self, coins: int) -> str:
        coins = int(coins or 0)
        gold = coins // 10000
        silver = (coins % 10000) // 100
        copper = coins % 100

        return f"{gold}g {silver}s {copper}c"

    def split_message(self, message: str, max_length: int = 1900) -> List[str]:
        chunks = []
        current = ""

        for line in message.splitlines():
            candidate = current + line + "\n"

            if len(candidate) > max_length:
                if current.strip():
                    chunks.append(current.strip())
                current = line + "\n"
            else:
                current = candidate

        if current.strip():
            chunks.append(current.strip())

        return chunks or ["No output."]

    def loaded_extension_names(self) -> List[str]:
        return list(getattr(self.bot, "loaded_extensions", []))

    def failed_extension_data(self) -> List[dict]:
        return list(getattr(self.bot, "failed_extensions", []))

    def sync_startup_text(self) -> str:
        should_sync = False

        try:
            should_sync = bool(self.bot.should_sync_on_startup())
        except Exception:
            should_sync = False

        if should_sync:
            return "Enabled ⚠️ slower / temporary only"

        return "Disabled ✅ recommended"

    # =========================
    # MESSAGE BUILDERS
    # =========================
    def build_panel_embed(self, user: discord.abc.User) -> discord.Embed:
        embed = discord.Embed(
            title="🛠️ Admin Panel",
            description=(
                "Private admin controls.\n\n"
                "Use the buttons below to inspect bot/guild state or run a safe manual sync."
            ),
            color=0x5865F2,
            timestamp=datetime.now(timezone.utc)
        )

        embed.add_field(
            name="Current actions",
            value=(
                "🤖 Bot Status\n"
                "🔄 Guild Sync Status\n"
                "⚡ Guild Sync Now\n"
                "💰 Donation Summary\n"
                "🔎 Role Missing Help"
            ),
            inline=False
        )

        embed.set_footer(
            text=f"Opened by {user.display_name if hasattr(user, 'display_name') else user.name}"
        )

        return embed

    def build_bot_status_message(self) -> str:
        loaded = self.loaded_extension_names()
        failed = self.failed_extension_data()

        sync_state = self.load_json(
            BOT_SYNC_STATE_FILE,
            {
                "last_mode": None,
                "last_success": None,
                "last_count": None,
                "last_error": None,
                "last_attempt_at": None
            }
        )

        lines = [
            "🤖 **Bot Status**",
            "",
            f"Loaded modules: ✅ **{len(loaded)}**",
            f"Failed modules: ❌ **{len(failed)}**",
            f"Slash sync on startup: **{self.sync_startup_text()}**",
            "",
            "**Command Sync State:**"
        ]

        if sync_state.get("last_attempt_at"):
            outcome = "✅ Success" if sync_state.get("last_success") else "❌ Failed"
            lines.append(f"Last sync: **{outcome}**")
            lines.append(f"Mode: **{sync_state.get('last_mode') or 'unknown'}**")
            lines.append(f"Attempted: **{sync_state.get('last_attempt_at')}**")

            if sync_state.get("last_count") is not None:
                lines.append(f"Command count: **{sync_state.get('last_count')}**")

            if sync_state.get("last_error"):
                lines.append(f"Error: `{sync_state.get('last_error')}`")
        else:
            lines.append("Last sync: **None recorded**")

        if loaded:
            lines.append("")
            lines.append("**Loaded:**")
            lines.extend(f"✅ `{extension}`" for extension in loaded)

        if failed:
            lines.append("")
            lines.append("**Failed:**")

            for item in failed:
                lines.append(
                    f"❌ `{item.get('extension', 'unknown')}` — `{item.get('error', 'unknown error')}`"
                )

        return "\n".join(lines)

    def build_guild_sync_status_message(self) -> str:
        state = self.load_json(SYNC_STATE_FILE, {})
        data = self.load_json(GUILD_DATA_FILE, [])

        linked_count = sum(
            1 for member in data
            if member.get("discord_user_id") is not None
        )

        unlinked_count = len(data) - linked_count

        total_weekly_gold = sum(
            self.safe_int(member.get("weekly_gold", 0))
            for member in data
        )

        total_lifetime_gold = sum(
            self.safe_int(member.get("lifetime_gold", 0))
            for member in data
        )

        last_sync = state.get("last_sync", "Never")

        return (
            "🔄 **Guild Sync Status**\n\n"
            f"Members tracked: **{len(data)}**\n"
            f"Linked: 🟢 **{linked_count}**\n"
            f"Unlinked: 🔴 **{unlinked_count}**\n"
            f"Weekly donated: **{self.format_gold(total_weekly_gold)}**\n"
            f"Bot-tracked lifetime donated: **{self.format_gold(total_lifetime_gold)}**\n"
            f"Last sync: **{last_sync}**\n\n"
            "🟢 Linked • 🔴 Unlinked"
        )

    def build_donation_summary_message(self) -> str:
        data = self.load_json(GUILD_DATA_FILE, [])

        weekly_donors = [
            member for member in data
            if self.safe_int(member.get("weekly_gold", 0)) > 0
        ]

        lifetime_donors = [
            member for member in data
            if self.safe_int(member.get("lifetime_gold", 0)) > 0
        ]

        total_weekly_gold = sum(
            self.safe_int(member.get("weekly_gold", 0))
            for member in data
        )

        total_lifetime_gold = sum(
            self.safe_int(member.get("lifetime_gold", 0))
            for member in data
        )

        top_weekly = sorted(
            weekly_donors,
            key=lambda member: self.safe_int(member.get("weekly_gold", 0)),
            reverse=True
        )[:5]

        top_lifetime = sorted(
            lifetime_donors,
            key=lambda member: self.safe_int(member.get("lifetime_gold", 0)),
            reverse=True
        )[:5]

        lines = [
            "💰 **Donation Summary**",
            "",
            f"Active weekly donors: **{len(weekly_donors)}**",
            f"Lifetime donors tracked: **{len(lifetime_donors)}**",
            f"Weekly total: **{self.format_gold(total_weekly_gold)}**",
            f"Bot-tracked lifetime total: **{self.format_gold(total_lifetime_gold)}**",
        ]

        if top_weekly:
            lines.append("")
            lines.append("**Top weekly donors:**")

            for index, member in enumerate(top_weekly, 1):
                lines.append(
                    f"**{index}.** {member.get('name', 'Unknown')} — "
                    f"{self.format_gold(self.safe_int(member.get('weekly_gold', 0)))}"
                )

        if top_lifetime:
            lines.append("")
            lines.append("**Top lifetime donors:**")

            for index, member in enumerate(top_lifetime, 1):
                lines.append(
                    f"**{index}.** {member.get('name', 'Unknown')} — "
                    f"{self.format_gold(self.safe_int(member.get('lifetime_gold', 0)))}"
                )

        return "\n".join(lines)

    # =========================
    # COMMANDS REMOVED
    # =========================
    # Slash command exposure was removed. This cog now only provides
    # helper methods used by modules/vr_bot_panels.py.


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminPanel(bot))