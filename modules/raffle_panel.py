import json
import os
import random
from datetime import datetime, timezone
from typing import List

import discord
from discord.ext import commands


RAFFLE_FILE = "raffle_data.json"
RAFFLE_TICKET_FILE = "raffle_tickets.json"
GUILD_FILE = "guild_data.json"


class RaffleConfirmView(discord.ui.View):
    def __init__(self, cog: "RafflePanel", owner_id: int, action: str):
        super().__init__(timeout=120)
        self.cog = cog
        self.owner_id = owner_id
        self.action = action

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "❌ This confirmation belongs to someone else.",
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
                "❌ You need administrator permissions to use this.",
                ephemeral=True
            )
            return False

        return True

    async def disable_buttons(self):
        for item in self.children:
            item.disabled = True

    @discord.ui.button(
        label="Confirm",
        style=discord.ButtonStyle.danger,
        emoji="✅"
    )
    async def confirm_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await interaction.response.defer(ephemeral=True)

        try:
            await self.disable_buttons()

            if self.action == "draw":
                message = await self.cog.draw_raffle_winner()
            elif self.action == "end":
                message = await self.cog.end_raffle_without_draw()
            else:
                message = "❌ Unknown raffle action."

            await interaction.followup.send(message, ephemeral=True)

        except Exception as error:
            await interaction.followup.send(
                f"⚠️ Raffle action failed:\n```text\n{error}\n```",
                ephemeral=True
            )

    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.secondary,
        emoji="↩️"
    )
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await interaction.response.defer(ephemeral=True)
        await self.disable_buttons()

        await interaction.followup.send(
            "✅ Cancelled. The raffle was not changed.",
            ephemeral=True
        )


class RafflePanelView(discord.ui.View):
    def __init__(self, cog: "RafflePanel", owner_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "❌ This raffle panel belongs to someone else.",
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
        label="Status",
        style=discord.ButtonStyle.secondary,
        emoji="🎟️"
    )
    async def status_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await interaction.response.defer(ephemeral=True)

        embed = self.cog.build_status_embed()
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(
        label="Entries",
        style=discord.ButtonStyle.secondary,
        emoji="👥"
    )
    async def entries_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await interaction.response.defer(ephemeral=True)

        embeds = await self.cog.build_entries_embeds(include_zero=False)

        for embed in embeds:
            await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(
        label="Draw Winner",
        style=discord.ButtonStyle.success,
        emoji="🏆"
    )
    async def draw_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        raffle = self.cog.load_raffle()

        if not raffle.get("active"):
            return await interaction.response.send_message(
                "ℹ️ No active raffle.",
                ephemeral=True
            )

        tickets = self.cog.load_tickets()
        total_tickets = self.cog.get_total_tickets(tickets)
        pot_total = self.cog.get_raffle_pot_total(tickets)

        view = RaffleConfirmView(
            cog=self.cog,
            owner_id=interaction.user.id,
            action="draw"
        )

        await interaction.response.send_message(
            (
                "⚠️ **Confirm Raffle Draw**\n\n"
                f"Raffle: **{raffle.get('title', 'Unknown raffle')}**\n"
                f"Tickets: **{total_tickets}**\n"
                f"Pot: **{self.cog.format_gold(pot_total)}**\n\n"
                "This will draw a winner and end the raffle.\n\n"
                "Are you sure?"
            ),
            view=view,
            ephemeral=True
        )

    @discord.ui.button(
        label="End Raffle",
        style=discord.ButtonStyle.danger,
        emoji="🛑"
    )
    async def end_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        raffle = self.cog.load_raffle()

        if not raffle.get("active"):
            return await interaction.response.send_message(
                "ℹ️ No active raffle.",
                ephemeral=True
            )

        tickets = self.cog.load_tickets()
        total_tickets = self.cog.get_total_tickets(tickets)
        pot_total = self.cog.get_raffle_pot_total(tickets)

        view = RaffleConfirmView(
            cog=self.cog,
            owner_id=interaction.user.id,
            action="end"
        )

        await interaction.response.send_message(
            (
                "⚠️ **Confirm End Raffle**\n\n"
                f"Raffle: **{raffle.get('title', 'Unknown raffle')}**\n"
                f"Tickets: **{total_tickets}**\n"
                f"Pot: **{self.cog.format_gold(pot_total)}**\n\n"
                "This will end the raffle without drawing a winner.\n\n"
                "Are you sure?"
            ),
            view=view,
            ephemeral=True
        )

    @discord.ui.button(
        label="Help",
        style=discord.ButtonStyle.secondary,
        emoji="📋"
    )
    async def help_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await interaction.response.defer(ephemeral=True)

        embed = self.cog.build_help_embed()
        await interaction.followup.send(embed=embed, ephemeral=True)


class RafflePanel(commands.Cog):
    """
    Ephemeral raffle admin panel.

    Buttons:
        - Status
        - Entries
        - Draw Winner
        - End Raffle
        - Help

    Destructive actions require confirmation.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # =========================
    # RAFFLE COG BRIDGE
    # =========================
    def raffle_cog(self):
        return self.bot.get_cog("Raffle")

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

    def load_raffle(self) -> dict:
        raffle_cog = self.raffle_cog()

        if raffle_cog is not None and hasattr(raffle_cog, "load_raffle"):
            return raffle_cog.load_raffle()

        return self.load_json(RAFFLE_FILE, {"active": False})

    def save_raffle(self, data: dict):
        raffle_cog = self.raffle_cog()

        if raffle_cog is not None and hasattr(raffle_cog, "save_raffle"):
            raffle_cog.save_raffle(data)
            return

        self.save_json(RAFFLE_FILE, data)

    def load_tickets(self) -> dict:
        raffle_cog = self.raffle_cog()

        if raffle_cog is not None and hasattr(raffle_cog, "load_tickets"):
            return raffle_cog.load_tickets()

        return self.load_json(RAFFLE_TICKET_FILE, {})

    def load_guild_data(self) -> list:
        raffle_cog = self.raffle_cog()

        if raffle_cog is not None and hasattr(raffle_cog, "load_guild_data"):
            return raffle_cog.load_guild_data()

        return self.load_json(GUILD_FILE, [])

    # =========================
    # FORMAT / RAFFLE HELPERS
    # =========================
    def safe_int(self, value, default: int = 0) -> int:
        try:
            return int(value or 0)
        except Exception:
            return default

    def format_gold(self, coins: int) -> str:
        raffle_cog = self.raffle_cog()

        if raffle_cog is not None and hasattr(raffle_cog, "format_gold"):
            return raffle_cog.format_gold(coins)

        coins = int(coins or 0)
        return f"{coins // 10000}g {(coins % 10000) // 100}s {coins % 100}c"

    def get_remaining_time(self, end_time_str: str) -> str:
        raffle_cog = self.raffle_cog()

        if raffle_cog is not None and hasattr(raffle_cog, "get_remaining_time"):
            return raffle_cog.get_remaining_time(end_time_str)

        try:
            end_time = datetime.fromisoformat(end_time_str)
            remaining = end_time - datetime.now(timezone.utc)

            if remaining.total_seconds() <= 0:
                return "Ended"

            hours, remainder = divmod(int(remaining.total_seconds()), 3600)
            minutes = remainder // 60
            return f"{hours}h {minutes}m"
        except Exception:
            return "Unknown"

    async def format_discord_user(self, discord_user_id: int, include_id: bool = False):
        raffle_cog = self.raffle_cog()

        if raffle_cog is not None and hasattr(raffle_cog, "format_discord_user"):
            return await raffle_cog.format_discord_user(discord_user_id, include_id=include_id)

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

    def get_total_tickets(self, tickets: dict) -> int:
        raffle_cog = self.raffle_cog()

        if raffle_cog is not None and hasattr(raffle_cog, "get_total_tickets"):
            return raffle_cog.get_total_tickets(tickets)

        return sum(
            self.safe_int(entry.get("ticket_count", 0))
            for entry in tickets.values()
            if isinstance(entry, dict)
        )

    def get_raffle_pot_total(self, tickets: dict) -> int:
        raffle_cog = self.raffle_cog()

        if raffle_cog is not None and hasattr(raffle_cog, "get_raffle_pot_total"):
            return raffle_cog.get_raffle_pot_total(tickets)

        return sum(
            self.safe_int(entry.get("raffle_donation_total", 0))
            for entry in tickets.values()
            if isinstance(entry, dict)
        )

    def build_weighted_pool(self, tickets: dict) -> list:
        raffle_cog = self.raffle_cog()

        if raffle_cog is not None and hasattr(raffle_cog, "build_weighted_pool"):
            return raffle_cog.build_weighted_pool(tickets)

        pool = []

        for discord_id, entry in tickets.items():
            ticket_count = self.safe_int(entry.get("ticket_count", 0))

            if ticket_count > 0:
                pool.extend([discord_id] * ticket_count)

        return pool

    def get_ticket_holders(self, tickets: dict, include_zero: bool = False) -> list:
        raffle_cog = self.raffle_cog()

        if raffle_cog is not None and hasattr(raffle_cog, "get_ticket_holders"):
            return raffle_cog.get_ticket_holders(tickets, include_zero=include_zero)

        entries = []

        for discord_id, entry in tickets.items():
            if not isinstance(entry, dict):
                continue

            ticket_count = self.safe_int(entry.get("ticket_count", 0))
            donation_total = self.safe_int(entry.get("raffle_donation_total", 0))

            if not include_zero and ticket_count <= 0:
                continue

            entries.append(
                {
                    "discord_id": discord_id,
                    "gw2_account_name": entry.get("gw2_account_name", "Unknown"),
                    "raffle_donation_total": donation_total,
                    "ticket_count": ticket_count,
                }
            )

        entries.sort(
            key=lambda item: (
                item["ticket_count"],
                item["raffle_donation_total"],
                item["gw2_account_name"].lower()
            ),
            reverse=True
        )

        return entries

    def split_lines(self, lines: List[str], max_length: int = 3900) -> List[str]:
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

        return chunks or ["No output."]

    # =========================
    # PANEL EMBEDS
    # =========================
    def build_panel_embed(self, user: discord.abc.User) -> discord.Embed:
        raffle = self.load_raffle()
        tickets = self.load_tickets()

        active = bool(raffle.get("active"))
        title = raffle.get("title", "Current Raffle")
        total_tickets = self.get_total_tickets(tickets)
        ticket_holders = len(
            [
                entry for entry in tickets.values()
                if isinstance(entry, dict) and self.safe_int(entry.get("ticket_count", 0)) > 0
            ]
        )

        embed = discord.Embed(
            title="🎟️ Raffle Panel",
            description="Private raffle controls.",
            color=0xE67E22 if active else 0x95A5A6,
            timestamp=datetime.now(timezone.utc)
        )

        embed.add_field(
            name="Current raffle",
            value=(
                f"Name: **{title}**\n"
                f"Status: **{'Active ✅' if active else 'Inactive'}**\n"
                f"Ticket holders: **{ticket_holders}**\n"
                f"Tickets: **{total_tickets}**"
            ),
            inline=False
        )

        embed.add_field(
            name="Actions",
            value=(
                "🎟️ Status\n"
                "👥 Entries\n"
                "🏆 Draw Winner\n"
                "🛑 End Raffle\n"
                "📋 Help"
            ),
            inline=False
        )

        embed.set_footer(
            text=f"Opened by {user.display_name if hasattr(user, 'display_name') else user.name}"
        )

        return embed

    def build_status_embed(self) -> discord.Embed:
        raffle = self.load_raffle()
        tickets = self.load_tickets()

        active = bool(raffle.get("active"))
        title = raffle.get("title", "Unknown raffle")
        ticket_price = self.safe_int(raffle.get("ticket_price", 0))
        total_tickets = self.get_total_tickets(tickets)
        pot_total = self.get_raffle_pot_total(tickets)

        if active:
            remaining = self.get_remaining_time(raffle.get("end_time", ""))
        else:
            remaining = "No active raffle"

        ticket_holders = len(
            [
                entry for entry in tickets.values()
                if isinstance(entry, dict) and self.safe_int(entry.get("ticket_count", 0)) > 0
            ]
        )

        embed = discord.Embed(
            title="🎟️ Raffle Status",
            color=0xE67E22 if active else 0x95A5A6,
            timestamp=datetime.now(timezone.utc)
        )

        embed.description = (
            f"Raffle: **{title}**\n"
            f"Status: **{'Active ✅' if active else 'Inactive'}**\n"
            f"Time remaining: **{remaining}**\n"
            f"Ticket price: **{self.format_gold(ticket_price)}**\n"
            f"Multiple tickets: **{'Yes' if raffle.get('multiple_tickets') else 'No'}**\n"
            f"Winner takes all: **{'Yes' if raffle.get('winner_takes_all') else 'No'}**\n\n"
            f"Ticket holders: **{ticket_holders}**\n"
            f"Tickets: **{total_tickets}**\n"
            f"Pot: **{self.format_gold(pot_total)}**"
        )

        if not active:
            winner = raffle.get("winner_gw2_account_name")
            final_pot = raffle.get("final_pot")

            if winner:
                embed.add_field(
                    name="Last winner",
                    value=f"**{winner}**",
                    inline=False
                )

            if final_pot is not None:
                embed.add_field(
                    name="Final pot",
                    value=f"**{self.format_gold(final_pot)}**",
                    inline=False
                )

        return embed

    async def build_entries_embeds(self, include_zero: bool = False) -> List[discord.Embed]:
        raffle = self.load_raffle()

        if not raffle.get("active"):
            embed = discord.Embed(
                title="👥 Raffle Entries",
                description="ℹ️ No active raffle.",
                color=0x95A5A6,
                timestamp=datetime.now(timezone.utc)
            )
            return [embed]

        tickets = self.load_tickets()
        entries = self.get_ticket_holders(tickets, include_zero=include_zero)

        if not entries:
            embed = discord.Embed(
                title=f"👥 Raffle Entries — {raffle.get('title', 'Unknown')}",
                description="No raffle ticket holders yet.",
                color=0xE67E22,
                timestamp=datetime.now(timezone.utc)
            )
            return [embed]

        raffle_cog = self.raffle_cog()

        if raffle_cog is not None and hasattr(raffle_cog, "build_entries_embed"):
            return [
                await raffle_cog.build_entries_embed(
                    raffle=raffle,
                    entries=entries,
                    include_zero=include_zero
                )
            ]

        total_tickets = self.get_total_tickets(tickets)
        pot_total = self.get_raffle_pot_total(tickets)

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

        chunks = self.split_lines(lines, max_length=3600)
        embeds = []

        for page, chunk in enumerate(chunks, 1):
            embed = discord.Embed(
                title=f"👥 Raffle Entries — {raffle.get('title', 'Unknown')}",
                description=header + "\n\n" + chunk,
                color=0xE67E22,
                timestamp=datetime.now(timezone.utc)
            )

            embed.set_footer(text=f"Page {page}/{len(chunks)} • Only linked guild members are included.")
            embeds.append(embed)

        return embeds

    def build_help_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="📋 Raffle Panel Help",
            color=0xE67E22,
            timestamp=datetime.now(timezone.utc)
        )

        embed.description = (
            "**Panel buttons:**\n"
            "🎟️ **Status** — show raffle state, ticket count, and pot.\n"
            "👥 **Entries** — show current ticket holders.\n"
            "🏆 **Draw Winner** — confirmation first, then draws and ends raffle.\n"
            "🛑 **End Raffle** — confirmation first, ends without drawing.\n\n"
            "**Full commands still available:**\n"
            "`/raffle status`\n"
            "`/raffle ticket_status`\n"
            "`/raffle_admin create`\n"
            "`/raffle_admin edit`\n"
            "`/raffle_admin entries`\n"
            "`/raffle_admin ticket_add`\n"
            "`/raffle_admin ticket_remove`\n"
            "`/raffle_admin draw`\n"
            "`/raffle_admin end`"
        )

        return embed

    # =========================
    # DESTRUCTIVE ACTIONS
    # =========================
    async def draw_raffle_winner(self) -> str:
        raffle = self.load_raffle()

        if not raffle.get("active"):
            return "❌ No active raffle."

        tickets = self.load_tickets()
        pool = self.build_weighted_pool(tickets)
        pot_total = self.get_raffle_pot_total(tickets)

        raffle["active"] = False
        raffle["ended_at"] = datetime.now(timezone.utc).isoformat()

        if not pool:
            raffle["final_pot"] = pot_total
            self.save_raffle(raffle)

            return "ℹ️ No valid raffle entries existed. The raffle has been ended."

        winner_discord_id = random.choice(pool)
        winner_entry = tickets[winner_discord_id]
        winner_ticket_count = self.safe_int(winner_entry.get("ticket_count", 0))
        winner_display = await self.format_discord_user(
            int(winner_discord_id),
            include_id=False
        )

        raffle["winner_discord_id"] = winner_discord_id
        raffle["winner_gw2_account_name"] = winner_entry.get("gw2_account_name", "Unknown")

        if raffle.get("winner_takes_all"):
            raffle["final_pot"] = pot_total

        self.save_raffle(raffle)

        msg = (
            f"🏆 **Raffle Winner Drawn**\n\n"
            f"Raffle: **{raffle.get('title', 'Unknown raffle')}**\n"
            f"GW2 account: **{winner_entry.get('gw2_account_name', 'Unknown')}**\n"
            f"Discord: **{winner_display}**\n"
            f"Tickets: **{winner_ticket_count}**"
        )

        if raffle.get("winner_takes_all"):
            msg += f"\nPot: **{self.format_gold(pot_total)}**"

        return msg

    async def end_raffle_without_draw(self) -> str:
        raffle = self.load_raffle()

        if not raffle.get("active"):
            return "ℹ️ No active raffle."

        tickets = self.load_tickets()
        pot_total = self.get_raffle_pot_total(tickets)
        title = raffle.get("title", "Unknown raffle")

        raffle["active"] = False
        raffle["ended_at"] = datetime.now(timezone.utc).isoformat()

        if raffle.get("winner_takes_all"):
            raffle["final_pot"] = pot_total

        self.save_raffle(raffle)

        msg = (
            f"🛑 **Raffle ended**\n\n"
            f"Raffle: **{title}**\n"
            f"Tickets: **{self.get_total_tickets(tickets)}**"
        )

        if raffle.get("winner_takes_all"):
            msg += f"\nFinal pot: **{self.format_gold(pot_total)}**"

        return msg

    # =========================
    # COMMANDS REMOVED
    # =========================
    # Slash command exposure was removed. This cog now only provides
    # helper methods used by modules/vr_bot_panels.py.


async def setup(bot: commands.Bot):
    await bot.add_cog(RafflePanel(bot))