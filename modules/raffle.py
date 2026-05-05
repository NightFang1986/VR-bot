import discord
from discord.ext import commands
import json
import os
import re
from datetime import datetime, timezone


class Raffle(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        self.RAFFLE_FILE = "raffle_data.json"
        self.TICKET_FILE = "raffle_tickets.json"
        self.GUILD_FILE = "guild_data.json"

    # =========================
    # JSON HELPERS
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

    def load_raffle(self):
        return self.load_json(self.RAFFLE_FILE, {"active": False})

    def save_raffle(self, data):
        self.save_json(self.RAFFLE_FILE, data)

    def load_tickets(self):
        return self.load_json(self.TICKET_FILE, {})

    def save_tickets(self, data):
        self.save_json(self.TICKET_FILE, data)

    def load_guild_data(self):
        return self.load_json(self.GUILD_FILE, [])

    # =========================
    # FORMAT HELPERS
    # =========================
    def parse_gw2_coins(self, value: str) -> int:
        value = value.lower().strip()
        total = 0

        gold = re.search(r"(\d+)\s*g", value)
        silver = re.search(r"(\d+)\s*s", value)
        copper = re.search(r"(\d+)\s*c", value)

        if gold:
            total += int(gold.group(1)) * 10000
        if silver:
            total += int(silver.group(1)) * 100
        if copper:
            total += int(copper.group(1))

        if total <= 0:
            raise ValueError("Invalid GW2 coin value.")

        return total

    def format_gold(self, coins: int) -> str:
        coins = int(coins or 0)
        return f"{coins // 10000}g {(coins % 10000) // 100}s {coins % 100}c"

    def get_remaining_time(self, end_time_str: str) -> str:
        end_time = datetime.fromisoformat(end_time_str)
        remaining = end_time - datetime.now(timezone.utc)

        if remaining.total_seconds() <= 0:
            return "Ended"

        hours, remainder = divmod(int(remaining.total_seconds()), 3600)
        minutes = remainder // 60
        return f"{hours}h {minutes}m"

    async def format_discord_user(self, discord_user_id: int, include_id: bool = False):
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

    # =========================
    # LOOKUPS
    # =========================
    def find_member_by_gw2_name(self, data, gw2_name: str):
        target = gw2_name.strip().lower()

        for member in data:
            if member.get("name", "").strip().lower() == target:
                return member

        return None

    def find_linked_member_by_discord_id(self, discord_user_id: int):
        for member in self.load_guild_data():
            if member.get("discord_user_id") == discord_user_id:
                return member

        return None

    async def gw2_name_autocomplete(self, interaction: discord.Interaction, current: str):
        query = current.lower().strip()
        choices = []

        for member in self.load_guild_data():
            name = member.get("name", "")

            if query in name.lower():
                choices.append(discord.app_commands.Choice(name=name, value=name))

        return choices[:25]

    # =========================
    # RAFFLE HELPERS
    # =========================
    def calculate_ticket_count(self, donation_total: int, ticket_price: int, multiple_tickets: bool) -> int:
        if ticket_price <= 0:
            return 0

        if donation_total < ticket_price:
            return 0

        if multiple_tickets:
            return donation_total // ticket_price

        return 1

    def recalculate_all_tickets(self, raffle: dict, tickets: dict) -> dict:
        ticket_price = int(raffle.get("ticket_price", 0))
        multiple_tickets = bool(raffle.get("multiple_tickets", False))

        for entry in tickets.values():
            donation_total = int(entry.get("raffle_donation_total", 0))
            entry["ticket_count"] = int(
                self.calculate_ticket_count(
                    donation_total=donation_total,
                    ticket_price=ticket_price,
                    multiple_tickets=multiple_tickets
                )
            )

        return tickets

    def build_weighted_pool(self, tickets: dict):
        pool = []

        for discord_id, entry in tickets.items():
            ticket_count = int(entry.get("ticket_count", 0))

            if ticket_count > 0:
                pool.extend([discord_id] * ticket_count)

        return pool

    def get_total_tickets(self, tickets: dict) -> int:
        return sum(
            int(entry.get("ticket_count", 0))
            for entry in tickets.values()
        )

    def get_raffle_pot_total(self, tickets: dict) -> int:
        return sum(
            int(entry.get("raffle_donation_total", 0))
            for entry in tickets.values()
        )

    def get_ticket_holders(self, tickets: dict, include_zero: bool = False):
        entries = []

        for discord_id, entry in tickets.items():
            ticket_count = int(entry.get("ticket_count", 0))
            donation_total = int(entry.get("raffle_donation_total", 0))

            if not include_zero and ticket_count <= 0:
                continue

            entries.append({
                "discord_id": discord_id,
                "gw2_account_name": entry.get("gw2_account_name", "Unknown"),
                "raffle_donation_total": donation_total,
                "ticket_count": ticket_count
            })

        entries.sort(
            key=lambda item: (
                item["ticket_count"],
                item["raffle_donation_total"],
                item["gw2_account_name"].lower()
            ),
            reverse=True
        )

        return entries

    # =========================
    # EMBED HELPERS
    # =========================
    def split_lines_for_embed_fields(self, lines, max_length=1000):
        chunks = []
        current = ""

        for line in lines:
            candidate = current + line + "\n"

            if len(candidate) > max_length:
                if current.strip():
                    chunks.append(current.strip())
                current = line + "\n"
            else:
                current = candidate

        if current.strip():
            chunks.append(current.strip())

        return chunks

    async def build_entries_embed(self, raffle: dict, entries: list, include_zero: bool):
        tickets = self.load_tickets()
        total_tickets = self.get_total_tickets(tickets)
        pot_total = self.get_raffle_pot_total(tickets)

        embed = discord.Embed(
            title=f"🎟️ Raffle Entries — {raffle.get('title', 'Unknown')}",
            color=0xC79C38,
            timestamp=datetime.now(timezone.utc)
        )

        header = (
            f"Tickets: **{total_tickets}** | "
            f"Pot: **{self.format_gold(pot_total)}** | "
            f"Showing: **{'All tracked donors' if include_zero else 'Ticket holders'}**"
        )

        lines = []

        for index, entry in enumerate(entries, 1):
            discord_display = await self.format_discord_user(
                int(entry["discord_id"]),
                include_id=False
            )

            lines.append(
                f"**{index}.** **{entry['gw2_account_name']}** — "
                f"{discord_display} — "
                f"🎫 **{entry['ticket_count']}** — "
                f"💰 **{self.format_gold(entry['raffle_donation_total'])}**"
            )

        full_description = header + "\n\n" + "\n".join(lines)

        # Prefer one clean description when it fits.
        if len(full_description) <= 3900:
            embed.description = full_description
        else:
            embed.description = header

            chunks = self.split_lines_for_embed_fields(lines, max_length=1000)

            for index, chunk in enumerate(chunks[:25], 1):
                field_name = "Entries" if index == 1 else f"Entries ({index})"

                embed.add_field(
                    name=field_name,
                    value=chunk,
                    inline=False
                )

            if len(chunks) > 25:
                embed.add_field(
                    name="Output truncated",
                    value="Some entries were hidden because Discord embeds have field limits.",
                    inline=False
                )

        embed.set_footer(text="Only linked guild members are included.")

        return embed

    # =========================
    # SLASH COMMANDS REMOVED
    # =========================
    # Slash command exposure was removed. This cog now only provides
    # raffle storage/format/helper methods used by modules/vr_bot_panels.py
    # and modules/raffle_panel.py.


async def setup(bot: commands.Bot):
    await bot.add_cog(Raffle(bot))