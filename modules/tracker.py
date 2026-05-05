import discord
from discord.ext import commands, tasks
import json
import os
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from services.gw2_api import GW2API, GW2APIError, GW2ConfigError


# =========================
# LOAD CONFIG
# =========================
CONFIG_FILE = "config.json"

with open(CONFIG_FILE, "r") as f:
    CONFIG = json.load(f)


class Tracker(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # CONFIG
        self.CHANNEL_ID = CONFIG["CHANNEL_ID"]
        self.USER_ID = CONFIG.get("USER_ID")
        self.ALERT_MODE = CONFIG.get("ALERT_MODE", "channel")

        self.POLL_INTERVAL = int(CONFIG.get("POLL_INTERVAL", 180))

        # DISPLAY LIMITS
        self.DONATIONS_DISPLAY_LIMIT = 25
        self.TOP_DONORS_MAX_LIMIT = 25

        # FILES
        self.STATE_FILE = "state.json"
        self.GUILD_FILE = "guild_data.json"
        self.WEEK_STATE_FILE = "week_state.json"
        self.RAFFLE_FILE = "raffle_data.json"
        self.RAFFLE_TICKET_FILE = "raffle_tickets.json"

        self.api: Optional[GW2API] = None

        self.poll_logs.change_interval(seconds=self.POLL_INTERVAL)
        self.poll_logs.start()
        self.weekly_reset_check.start()

    # =========================
    # LIFECYCLE
    # =========================
    async def cog_load(self):
        self.api = GW2API()
        await self.api.ensure_session()

    async def cog_unload(self):
        self.poll_logs.cancel()
        self.weekly_reset_check.cancel()

        if self.api is not None:
            await self.api.close()

    async def get_api(self) -> GW2API:
        if self.api is None:
            self.api = GW2API()
            await self.api.ensure_session()

        return self.api

    # =========================
    # FILE HANDLING
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

    def load_last_id(self):
        return self.load_json(self.STATE_FILE, {}).get("last_id")

    def save_last_id(self, last_id):
        self.save_json(self.STATE_FILE, {"last_id": last_id})

    def load_raffle(self):
        return self.load_json(self.RAFFLE_FILE, {"active": False})

    def load_raffle_tickets(self):
        return self.load_json(self.RAFFLE_TICKET_FILE, {})

    def save_raffle_tickets(self, data):
        self.save_json(self.RAFFLE_TICKET_FILE, data)

    # =========================
    # SAFE VALUE HELPERS
    # =========================
    def safe_int(self, value, default: int = 0) -> int:
        try:
            return int(value or 0)
        except Exception:
            return default

    def gold_to_coins(self, gold_value: float) -> int:
        """
        Converts gold entered as a slash command number into GW2 coin units.

        1 gold = 10,000 copper.
        Examples:
            1      -> 10000
            1.5    -> 15000
            0.75   -> 7500
        """
        try:
            return int(round(float(gold_value) * 10000))
        except Exception:
            return 0

    # =========================
    # FORMAT HELPERS
    # =========================
    def format_gold(self, coins: int) -> str:
        coins = int(coins or 0)
        gold = coins // 10000
        silver = (coins % 10000) // 100
        copper = coins % 100
        return f"{gold}g {silver}s {copper}c"

    async def format_discord_user(self, discord_user_id: int, include_id: bool = False):
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

    async def format_link_status(self, gw2_name: str, include_id: bool = False):
        link_status = self.get_link_status(gw2_name)

        if not link_status["linked"]:
            return "Linked: ❌ No"

        discord_name = await self.format_discord_user(
            int(link_status["discord_user_id"]),
            include_id=include_id
        )

        return f"Linked: ✅ {discord_name}"

    # =========================
    # WEEK SYSTEM
    # =========================
    def get_week_id(self):
        now = datetime.now(timezone.utc)
        return f"{now.isocalendar().year}-W{now.isocalendar().week}"

    def load_week_state(self):
        return self.load_json(self.WEEK_STATE_FILE, {}).get("week")

    def save_week_state(self, week_id):
        self.save_json(self.WEEK_STATE_FILE, {"week": week_id})

    def reset_all_weekly(self):
        data = self.load_guild_data()

        for member in data:
            member["weekly_gold"] = 0
            member["lifetime_gold"] = self.safe_int(member.get("lifetime_gold", 0))

        self.save_guild_data(data)

    # =========================
    # GW2 LOGIC
    # =========================
    async def fetch_guild_log(self) -> List[Dict[str, Any]]:
        api = await self.get_api()
        return await api.get_guild_log()

    def is_gold_deposit(self, entry):
        return (
            entry.get("type") == "stash"
            and entry.get("operation") == "deposit"
            and int(entry.get("coins", 0)) > 0
        )

    def get_link_status(self, gw2_name: str):
        """
        Returns:
        {
            "linked": bool,
            "discord_user_id": int | None
        }
        """
        target = gw2_name.strip().lower()
        data = self.load_guild_data()

        for member in data:
            if member.get("name", "").strip().lower() == target:
                discord_user_id = member.get("discord_user_id")

                if discord_user_id is not None:
                    return {
                        "linked": True,
                        "discord_user_id": int(discord_user_id)
                    }

                return {
                    "linked": False,
                    "discord_user_id": None
                }

        return {
            "linked": False,
            "discord_user_id": None
        }

    def find_member_index(self, data, gw2_name: str):
        target = gw2_name.strip().lower()

        for index, member in enumerate(data):
            if member.get("name", "").strip().lower() == target:
                return index

        return None

    def normalize_member_donation_fields(self, member: dict):
        member["weekly_gold"] = self.safe_int(member.get("weekly_gold", 0))
        member["lifetime_gold"] = self.safe_int(member.get("lifetime_gold", 0))

        if "discord_user_id" not in member:
            member["discord_user_id"] = None

        if "rank" not in member:
            member["rank"] = "Unknown"

        if "joined" not in member:
            member["joined"] = None

        return member

    def add_weekly_gold(self, name: str, coins: int):
        """
        Called when the tracker sees a new GW2 guild-bank gold deposit.

        This is the source of truth for bot-tracked donation totals:
        - weekly_gold increments and resets weekly
        - lifetime_gold increments forever unless manually corrected
        """
        data = self.load_guild_data()
        target = name.strip().lower()

        for member in data:
            if member.get("name", "").strip().lower() == target:
                member = self.normalize_member_donation_fields(member)

                member["weekly_gold"] += coins
                member["lifetime_gold"] += coins

                self.save_guild_data(data)
                return member["weekly_gold"]

        data.append(
            {
                "name": name,
                "rank": "Unknown",
                "joined": None,
                "discord_user_id": None,
                "weekly_gold": coins,
                "lifetime_gold": coins
            }
        )

        self.save_guild_data(data)
        return coins

    def set_lifetime_gold(self, name: str, coins: int):
        data = self.load_guild_data()
        index = self.find_member_index(data, name)

        if index is None:
            return None

        member = self.normalize_member_donation_fields(data[index])
        old_value = member["lifetime_gold"]
        member["lifetime_gold"] = max(0, int(coins))

        data[index] = member
        self.save_guild_data(data)

        return {
            "member": member,
            "old_value": old_value,
            "new_value": member["lifetime_gold"]
        }

    def adjust_lifetime_gold(self, name: str, coins_delta: int):
        data = self.load_guild_data()
        index = self.find_member_index(data, name)

        if index is None:
            return None

        member = self.normalize_member_donation_fields(data[index])
        old_value = member["lifetime_gold"]
        member["lifetime_gold"] = max(0, old_value + int(coins_delta))

        data[index] = member
        self.save_guild_data(data)

        return {
            "member": member,
            "old_value": old_value,
            "new_value": member["lifetime_gold"],
            "delta": int(coins_delta)
        }

    # =========================
    # RAFFLE INTEGRATION
    # =========================
    async def update_raffle(self, entry):
        raffle = self.load_raffle()

        if not raffle.get("active"):
            return None

        gw2_name = entry.get("user")
        coins = int(entry.get("coins", 0))

        if not gw2_name:
            return {
                "active": True,
                "linked": False,
                "updated": False,
                "ticket_count": 0,
                "donation_total": 0,
                "tickets_gained": 0
            }

        guild_data = self.load_guild_data()
        target = gw2_name.strip().lower()

        linked_member = None

        for member in guild_data:
            if (
                member.get("name", "").strip().lower() == target
                and member.get("discord_user_id") is not None
            ):
                linked_member = member
                break

        if linked_member is None:
            return {
                "active": True,
                "linked": False,
                "updated": False,
                "ticket_count": 0,
                "donation_total": 0,
                "tickets_gained": 0
            }

        discord_id = str(linked_member["discord_user_id"])
        tickets = self.load_raffle_tickets()

        if discord_id not in tickets:
            tickets[discord_id] = {
                "gw2_account_name": gw2_name,
                "raffle_donation_total": 0,
                "ticket_count": 0
            }

        old_ticket_count = int(tickets[discord_id].get("ticket_count", 0))

        tickets[discord_id]["raffle_donation_total"] = (
            int(tickets[discord_id].get("raffle_donation_total", 0)) + coins
        )

        donation_total = int(tickets[discord_id]["raffle_donation_total"])
        ticket_price = int(raffle.get("ticket_price", 0))

        if ticket_price <= 0:
            ticket_count = 0
        elif raffle.get("multiple_tickets"):
            ticket_count = donation_total // ticket_price
        else:
            ticket_count = 1 if donation_total >= ticket_price else 0

        tickets[discord_id]["ticket_count"] = int(ticket_count)
        tickets[discord_id]["gw2_account_name"] = gw2_name

        self.save_raffle_tickets(tickets)

        return {
            "active": True,
            "linked": True,
            "updated": True,
            "old_ticket_count": old_ticket_count,
            "ticket_count": int(ticket_count),
            "tickets_gained": max(0, int(ticket_count) - old_ticket_count),
            "donation_total": donation_total
        }

    # =========================
    # ALERTS
    # =========================
    async def send_alert(self, entry):
        name = entry.get("user", "Unknown")
        coins = int(entry.get("coins", 0))

        weekly = self.add_weekly_gold(name, coins)
        raffle_result = await self.update_raffle(entry)

        link_status_text = await self.format_link_status(name, include_id=False)

        description = (
            f"GW2 account: **{name}**\n"
            f"Deposited: **{self.format_gold(coins)}**\n"
            f"Weekly total: **{self.format_gold(weekly)}**\n"
            f"{link_status_text}"
        )

        if raffle_result and raffle_result.get("active"):
            if raffle_result.get("linked"):
                description += (
                    f"\n\n🎟️ **Raffle**\n"
                    f"Tickets: **{raffle_result.get('ticket_count', 0)}**\n"
                    f"Raffle total: **{self.format_gold(raffle_result.get('donation_total', 0))}**"
                )

                if raffle_result.get("tickets_gained", 0) > 0:
                    description += f"\nNew tickets: **+{raffle_result['tickets_gained']}**"
            else:
                description += (
                    f"\n\n🎟️ **Raffle**\n"
                    f"Linked: ❌ No\n"
                    f"Not counted until the account is linked."
                )

        embed = discord.Embed(
            title="💰 Guild Deposit",
            description=description,
            color=0xFFD700,
            timestamp=datetime.now(timezone.utc)
        )

        if self.ALERT_MODE in ("channel", "both") and self.CHANNEL_ID:
            channel = self.bot.get_channel(int(self.CHANNEL_ID))

            if channel:
                await channel.send(embed=embed)

        if self.ALERT_MODE in ("dm", "both") and self.USER_ID:
            try:
                user = await self.bot.fetch_user(int(self.USER_ID))
                await user.send(embed=embed)
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
    # POLLING
    # =========================
    @tasks.loop(seconds=180)
    async def poll_logs(self):
        await self.bot.wait_until_ready()

        last_id = self.load_last_id()

        try:
            logs = await self.fetch_guild_log()
            logs.reverse()

            for entry in logs:
                entry_id = entry.get("id")

                if entry_id is None:
                    continue

                if last_id and int(entry_id) <= int(last_id):
                    continue

                if self.is_gold_deposit(entry):
                    await self.send_alert(entry)

                last_id = int(entry_id)
                self.save_last_id(last_id)

        except Exception as e:
            print(f"❌ Tracker polling error: {e}")

    @poll_logs.before_loop
    async def before_poll_logs(self):
        await self.bot.wait_until_ready()

    # =========================
    # WEEKLY RESET
    # =========================
    @tasks.loop(minutes=5)
    async def weekly_reset_check(self):
        await self.bot.wait_until_ready()

        current_week = self.get_week_id()
        last_week = self.load_week_state()

        if last_week == current_week:
            return

        self.reset_all_weekly()
        self.save_week_state(current_week)

        print("🔄 Weekly reset executed (UTC week system)")

    @weekly_reset_check.before_loop
    async def before_weekly_reset_check(self):
        await self.bot.wait_until_ready()

    # =========================
    # EMBED BUILDER
    # =========================
    async def build_donor_embed(
        self,
        title: str,
        data,
        amount_field: str,
        amount_label: str,
        limit: int = 10
    ):
        embed = discord.Embed(
            title=title,
            color=0xFFD700,
            timestamp=datetime.now(timezone.utc)
        )

        data = sorted(
            data,
            key=lambda member: int(member.get(amount_field, 0)),
            reverse=True
        )

        if not data:
            embed.description = "No data yet."
            return embed

        shown_data = data[:limit]

        lines = []

        for index, member in enumerate(shown_data, 1):
            link_status = await self.format_link_status(
                member.get("name", "Unknown"),
                include_id=False
            )

            amount = self.safe_int(member.get(amount_field, 0))

            lines.append(
                f"**{index}. {member.get('name', 'Unknown')}** — "
                f"{amount_label}: **{self.format_gold(amount)}** — "
                f"{link_status}"
            )

        if len(data) > limit:
            lines.append("")
            lines.append(f"...and **{len(data) - limit}** more.")

        embed.description = "\n".join(lines)

        return embed

    # =========================
    # AUTOCOMPLETE
    # =========================
    async def donor_name_autocomplete(self, interaction: discord.Interaction, current: str):
        data = self.load_guild_data()
        query = current.lower().strip()

        choices = [discord.app_commands.Choice(name="all", value="all")]
        seen = {"all"}

        for member in data:
            name = member.get("name", "")

            if not name:
                continue

            if query in name.lower() and name.lower() not in seen:
                seen.add(name.lower())
                choices.append(
                    discord.app_commands.Choice(
                        name=name,
                        value=name
                    )
                )

        return choices[:25]

    async def donor_only_autocomplete(self, interaction: discord.Interaction, current: str):
        data = self.load_guild_data()
        query = current.lower().strip()

        choices = []
        seen = set()

        for member in data:
            name = member.get("name", "")

            if not name:
                continue

            if query in name.lower() and name.lower() not in seen:
                seen.add(name.lower())
                choices.append(
                    discord.app_commands.Choice(
                        name=name,
                        value=name
                    )
                )

        return choices[:25]


async def setup(bot: commands.Bot):
    await bot.add_cog(Tracker(bot))
