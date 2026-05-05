import discord
from discord.ext import commands, tasks
import json
import os
from datetime import datetime, timezone
from typing import Optional

from services.gw2_api import GW2API, GW2APIError, GW2ConfigError


# =========================
# LOAD CONFIG
# =========================
CONFIG_FILE = "config.json"

with open(CONFIG_FILE, "r") as f:
    CONFIG = json.load(f)


class GuildSync(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        self.CHANNEL_ID = CONFIG["CHANNEL_ID"]
        self.USER_ID = CONFIG.get("USER_ID")
        self.ALERT_MODE = CONFIG.get("ALERT_MODE", "channel")

        self.SYNC_INTERVAL = int(CONFIG.get("GUILD_SYNC_INTERVAL", 300))

        self.GUILD_FILE = "guild_data.json"
        self.SYNC_STATE_FILE = "guild_sync_state.json"

        self.api: Optional[GW2API] = None

        self.guild_sync_check.change_interval(seconds=self.SYNC_INTERVAL)
        self.guild_sync_check.start()

    # =========================
    # LIFECYCLE
    # =========================
    async def cog_load(self):
        self.api = GW2API()
        await self.api.ensure_session()

    async def cog_unload(self):
        self.guild_sync_check.cancel()

        if self.api is not None:
            await self.api.close()

    async def get_api(self) -> GW2API:
        if self.api is None:
            self.api = GW2API()
            await self.api.ensure_session()

        return self.api

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

    def save_json(self, path, data):
        with open(path, "w") as f:
            json.dump(data, f, indent=4)

    def load_guild_data(self):
        return self.load_json(self.GUILD_FILE, [])

    def save_guild_data(self, data):
        self.save_json(self.GUILD_FILE, data)

    def load_sync_state(self):
        return self.load_json(self.SYNC_STATE_FILE, {})

    def save_sync_state(self, data):
        self.save_json(self.SYNC_STATE_FILE, data)

    # =========================
    # FORMAT HELPERS
    # =========================
    def now_iso(self):
        return datetime.now(timezone.utc).isoformat()

    def safe_int(self, value, default: int = 0) -> int:
        try:
            return int(value or 0)
        except Exception:
            return default

    async def format_discord_user(
        self,
        discord_user_id: int,
        include_id: bool = False
    ):
        """
        Prefer server nickname/display name.
        Fall back to Discord username.
        Fall back to unknown user.
        """
        for guild in self.bot.guilds:
            member = guild.get_member(int(discord_user_id))

            if member is not None:
                if include_id:
                    return f"{member.display_name} (`{discord_user_id}`)"
                return member.display_name

        try:
            user = await self.bot.fetch_user(int(discord_user_id))

            if user is not None:
                if include_id:
                    return f"{user.name} (`{discord_user_id}`)"
                return user.name
        except Exception:
            pass

        if include_id:
            return f"Unknown user (`{discord_user_id}`)"

        return "Unknown user"

    def is_member_linked(self, member: dict) -> bool:
        return member.get("discord_user_id") is not None

    def link_dot_for_member(self, member: dict) -> str:
        if self.is_member_linked(member):
            return "🟢"

        return "🔴"

    async def format_member_name_with_dot(self, member: dict) -> str:
        name = member.get("name", "Unknown")
        dot = self.link_dot_for_member(member)

        if self.is_member_linked(member):
            discord_name = await self.format_discord_user(
                int(member["discord_user_id"]),
                include_id=False
            )
            return f"{dot} **{name}** - {discord_name}"

        return f"{dot} **{name}**"

    def linked_legend(self) -> str:
        return "🟢 Linked • 🔴 Unlinked"

    def format_gold(self, coins: int) -> str:
        coins = int(coins or 0)
        gold = coins // 10000
        silver = (coins % 10000) // 100
        copper = coins % 100
        return f"{gold}g {silver}s {copper}c"

    # =========================
    # GW2 API
    # =========================
    async def fetch_guild_members(self):
        api = await self.get_api()
        return await api.get_guild_members()

    # =========================
    # DONATION FIELD PRESERVATION
    # =========================
    def normalize_saved_member(self, member: dict) -> dict:
        """
        Makes sure every saved guild member has the fields the rest of the bot expects.

        Preserved by guild sync:
        - discord_user_id
        - weekly_gold
        - lifetime_gold
        """
        normalized = dict(member or {})

        normalized["name"] = normalized.get("name")
        normalized["rank"] = normalized.get("rank", "Unknown")
        normalized["joined"] = normalized.get("joined")

        if "discord_user_id" not in normalized:
            normalized["discord_user_id"] = None

        normalized["weekly_gold"] = self.safe_int(
            normalized.get("weekly_gold", 0),
            default=0
        )

        normalized["lifetime_gold"] = self.safe_int(
            normalized.get("lifetime_gold", 0),
            default=0
        )

        return normalized

    def preserve_donation_fields(self, existing_member: Optional[dict]):
        existing_member = self.normalize_saved_member(existing_member or {})

        return {
            "discord_user_id": existing_member.get("discord_user_id"),
            "weekly_gold": self.safe_int(existing_member.get("weekly_gold", 0)),
            "lifetime_gold": self.safe_int(existing_member.get("lifetime_gold", 0)),
        }

    # =========================
    # SYNC LOGIC
    # =========================
    def index_by_name(self, data):
        indexed = {}

        for member in data:
            normalized = self.normalize_saved_member(member)
            name = normalized.get("name")

            if not name:
                continue

            indexed[name] = normalized

        return indexed

    def build_synced_member(self, api_member: dict, existing_member: Optional[dict]):
        preserved = self.preserve_donation_fields(existing_member)

        return {
            "name": api_member.get("name"),
            "rank": api_member.get("rank", "Unknown"),
            "joined": api_member.get("joined"),
            "discord_user_id": preserved["discord_user_id"],
            "weekly_gold": preserved["weekly_gold"],
            "lifetime_gold": preserved["lifetime_gold"],
        }

    def compare_members(self, old_data, new_api_data):
        old_by_name = self.index_by_name(old_data)
        new_by_name = self.index_by_name(new_api_data)

        old_names = set(old_by_name.keys())
        new_names = set(new_by_name.keys())

        joined_names = sorted(new_names - old_names)
        left_names = sorted(old_names - new_names)

        rank_changes = []

        for name in sorted(old_names & new_names):
            old_rank = old_by_name[name].get("rank", "Unknown")
            new_rank = new_by_name[name].get("rank", "Unknown")

            if old_rank != new_rank:
                rank_changes.append(
                    {
                        "name": name,
                        "old_rank": old_rank,
                        "new_rank": new_rank
                    }
                )

        return joined_names, left_names, rank_changes

    async def sync_guild_data(self):
        old_data = self.load_guild_data()
        api_data = await self.fetch_guild_members()

        old_by_name = self.index_by_name(old_data)

        joined_names, left_names, rank_changes = self.compare_members(
            old_data,
            api_data
        )

        synced_data = []

        for api_member in api_data:
            name = api_member.get("name")

            if not name:
                continue

            existing_member = old_by_name.get(name)

            synced_data.append(
                self.build_synced_member(api_member, existing_member)
            )

        synced_data.sort(
            key=lambda member: (
                member.get("rank", "").lower(),
                member.get("name", "").lower()
            )
        )

        self.save_guild_data(synced_data)

        state = self.load_sync_state()
        state["last_sync"] = self.now_iso()
        state["member_count"] = len(synced_data)
        state["last_joined_count"] = len(joined_names)
        state["last_left_count"] = len(left_names)
        state["last_rank_change_count"] = len(rank_changes)
        self.save_sync_state(state)

        return {
            "changed": bool(joined_names or left_names or rank_changes),
            "membership_changed": bool(joined_names or left_names),
            "members": synced_data,
            "joined_names": joined_names,
            "left_names": left_names,
            "rank_changes": rank_changes,
            "old_data": old_data,
            "new_data": synced_data
        }

    # =========================
    # MESSAGE BUILDERS
    # =========================
    async def build_member_line(self, member: dict):
        return await self.format_member_name_with_dot(member)

    async def build_sync_report(self, result: dict, manual: bool = False):
        """
        Compact membership-change report.

        Auto output intentionally excludes:
        - member totals
        - ranks
        - rank changes

        Uses standard linked-dot format:
        🟢 **GW2Account.1234** - Discord nickname
        🔴 **GW2Account.1234**
        """
        joined_names = result["joined_names"]
        left_names = result["left_names"]
        new_data = result["new_data"]
        old_data = result["old_data"]

        old_by_name = self.index_by_name(old_data)
        new_by_name = self.index_by_name(new_data)

        lines = ["🔄 **Guild Changes**"]

        has_output_members = False

        if joined_names:
            has_output_members = True
            lines.append("")
            lines.append("Joined")

            for name in joined_names[:20]:
                member = new_by_name.get(
                    name,
                    {"name": name, "discord_user_id": None}
                )
                lines.append(await self.build_member_line(member))

            if len(joined_names) > 20:
                lines.append(f"...and **{len(joined_names) - 20}** more.")

        if left_names:
            has_output_members = True
            lines.append("")
            lines.append("Left / Removed")

            for name in left_names[:20]:
                member = old_by_name.get(
                    name,
                    {"name": name, "discord_user_id": None}
                )
                lines.append(await self.build_member_line(member))

            if len(left_names) > 20:
                lines.append(f"...and **{len(left_names) - 20}** more.")

        if not joined_names and not left_names:
            if manual:
                lines.append("")
                lines.append("No members joined or left.")
            else:
                return ""

        if has_output_members:
            lines.append("")
            lines.append(self.linked_legend())

        return "\n".join(lines)

    async def build_member_list_message(self, data, title: str, limit: int = 25):
        if not data:
            return f"{title}\n\nNo members found."

        lines = [title, ""]

        for index, member in enumerate(data[:limit], 1):
            line = await self.build_member_line(member)
            lines.append(f"**{index}.** {line}")

        if len(data) > limit:
            lines.append("")
            lines.append(f"...and **{len(data) - limit}** more.")

        lines.append("")
        lines.append(self.linked_legend())

        return "\n".join(lines)

    def split_message(self, message: str, max_length: int = 1900):
        chunks = []
        current = ""

        for line in message.splitlines():
            candidate = current + line + "\n"

            if len(candidate) > max_length:
                if current.strip():
                    chunks.append(current)
                current = line + "\n"
            else:
                current = candidate

        if current.strip():
            chunks.append(current)

        return chunks

    # =========================
    # ALERTS
    # =========================
    async def send_alert(self, message: str):
        if not message:
            return

        if self.ALERT_MODE in ("channel", "both") and self.CHANNEL_ID:
            channel = self.bot.get_channel(int(self.CHANNEL_ID))

            if channel:
                await channel.send(message)

        if self.ALERT_MODE in ("dm", "both") and self.USER_ID:
            try:
                user = await self.bot.fetch_user(int(self.USER_ID))
                await user.send(message)
            except Exception:
                pass

    # =========================
    # ERROR HELPERS
    # =========================
    def friendly_error_message(self, error: Exception) -> str:
        if isinstance(error, GW2ConfigError):
            return f"❌ {error}"

        if isinstance(error, GW2APIError):
            if error.status == 403:
                return (
                    "❌ GW2 API permission error.\n"
                    "Make sure the API key has the required guild permissions."
                )

            if error.status == 404:
                return (
                    "❌ GW2 API returned 404.\n"
                    "Check that `GUILD_ID` is correct in `config.json`."
                )

            return (
                "❌ GW2 API request failed.\n"
                f"```text\n{error}\n```"
            )

        return f"⚠️ Error: {error}"

    # =========================
    # BACKGROUND SYNC
    # =========================
    @tasks.loop(seconds=300)
    async def guild_sync_check(self):
        await self.bot.wait_until_ready()

        try:
            result = await self.sync_guild_data()

            if result["membership_changed"]:
                report = await self.build_sync_report(result, manual=False)
                await self.send_alert(report)
                print("🔄 Guild sync check — membership changes detected")
            elif result["rank_changes"]:
                print(
                    f"🔄 Guild sync check — {len(result['rank_changes'])} rank change(s), no alert sent"
                )
            else:
                print("🔄 Guild sync check — no changes")

        except Exception as e:
            print(f"❌ Guild sync check error: {e}")

    @guild_sync_check.before_loop
    async def before_guild_sync_check(self):
        await self.bot.wait_until_ready()

    # =========================
    # AUTOCOMPLETE
    # =========================
    async def rank_autocomplete(self, interaction: discord.Interaction, current: str):
        query = current.lower().strip()
        ranks = sorted(
            {
                member.get("rank", "Unknown")
                for member in self.load_guild_data()
                if member.get("rank")
            }
        )

        choices = []

        for rank in ranks:
            if query in rank.lower():
                choices.append(
                    discord.app_commands.Choice(
                        name=rank,
                        value=rank
                    )
                )

        return choices[:25]


async def setup(bot: commands.Bot):
    await bot.add_cog(GuildSync(bot))
