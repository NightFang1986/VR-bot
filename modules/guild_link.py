import discord
from discord.ext import commands
import json
import os
from typing import Optional


class GuildLink(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        self.GUILD_FILE = "guild_data.json"
        self.RAFFLE_FILE = "raffle_data.json"
        self.RAFFLE_TICKET_FILE = "raffle_tickets.json"

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

    def load_guild_data(self):
        return self.load_json(self.GUILD_FILE, [])

    def save_guild_data(self, data):
        self.save_json(self.GUILD_FILE, data)

    def load_raffle(self):
        return self.load_json(self.RAFFLE_FILE, {"active": False})

    def load_raffle_tickets(self):
        return self.load_json(self.RAFFLE_TICKET_FILE, {})

    def save_raffle_tickets(self, data):
        self.save_json(self.RAFFLE_TICKET_FILE, data)

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

    async def format_link_status(self, member: dict, include_id: bool = False):
        discord_user_id = member.get("discord_user_id")

        if discord_user_id is None:
            return "Linked: ❌ No"

        discord_display = await self.format_discord_user(
            int(discord_user_id),
            include_id=include_id
        )

        return f"Linked: ✅ {discord_display}"

    # =========================
    # LOOKUPS
    # =========================
    def find_member_by_gw2_name(self, data, gw2_name: str):
        target = gw2_name.strip().lower()

        for member in data:
            if member.get("name", "").strip().lower() == target:
                return member

        return None

    def find_member_by_discord_id(self, data, discord_user_id: int):
        target = int(discord_user_id)

        for member in data:
            saved_id = member.get("discord_user_id")

            if saved_id is not None and int(saved_id) == target:
                return member

        return None

    def find_members_by_name_contains(self, data, query: str):
        query = query.lower().strip()

        return [
            member for member in data
            if query in member.get("name", "").lower()
        ]

    def get_member_display_name(self, member: discord.Member):
        return member.display_name if member else "Unknown"

    async def resolve_discord_user_input(self, interaction: discord.Interaction, value: str):
        """
        Resolve Discord user from:
        - mention
        - raw Discord ID
        - username
        - display name / nickname

        Returns:
        {
            "ok": bool,
            "discord_id": int | None,
            "display": str | None,
            "error": str | None
        }
        """
        value = str(value or "").strip()

        if not value:
            return {
                "ok": False,
                "discord_id": None,
                "display": None,
                "error": "❌ Discord user input was empty."
            }

        guild = interaction.guild

        # Mention format: <@123> or <@!123>
        cleaned = (
            value
            .replace("<@", "")
            .replace(">", "")
            .replace("!", "")
            .strip()
        )

        if cleaned.isdigit():
            discord_id = int(cleaned)

            if guild is not None:
                member = guild.get_member(discord_id)

                if member is not None:
                    return {
                        "ok": True,
                        "discord_id": discord_id,
                        "display": member.display_name,
                        "error": None
                    }

            try:
                user = await self.bot.fetch_user(discord_id)

                if user is not None:
                    return {
                        "ok": True,
                        "discord_id": discord_id,
                        "display": user.name,
                        "error": None
                    }
            except Exception:
                pass

            return {
                "ok": True,
                "discord_id": discord_id,
                "display": f"Unknown user (`{discord_id}`)",
                "error": None
            }

        if guild is None:
            return {
                "ok": False,
                "discord_id": None,
                "display": None,
                "error": "❌ Could not resolve Discord user outside a server."
            }

        query = value.lower()

        exact_matches = []
        partial_matches = []

        for member in guild.members:
            candidates = [
                member.display_name,
                member.name,
                str(member),
                member.global_name or ""
            ]

            if any(candidate.lower() == query for candidate in candidates if candidate):
                exact_matches.append(member)
            elif any(query in candidate.lower() for candidate in candidates if candidate):
                partial_matches.append(member)

        matches = exact_matches or partial_matches

        if not matches:
            return {
                "ok": False,
                "discord_id": None,
                "display": None,
                "error": f"❌ Could not find Discord user matching **{value}**."
            }

        if len(matches) > 1:
            preview = "\n".join(
                f"• {member.display_name} (`{member.id}`)"
                for member in matches[:10]
            )

            extra = ""
            if len(matches) > 10:
                extra = f"\n...and **{len(matches) - 10}** more."

            return {
                "ok": False,
                "discord_id": None,
                "display": None,
                "error": (
                    f"❌ Multiple Discord users matched **{value}**.\n\n"
                    f"{preview}{extra}\n\n"
                    f"Use the Discord ID or mention instead."
                )
            }

        member = matches[0]

        return {
            "ok": True,
            "discord_id": int(member.id),
            "display": member.display_name,
            "error": None
        }

    async def resolve_lookup_query(self, interaction: discord.Interaction, query: Optional[str]):
        """
        Resolve a guild_data member from:
        - None/current user
        - GW2 account name
        - Discord mention
        - Discord ID
        - Discord nickname/display name
        """
        data = self.load_guild_data()

        if query is None or str(query).strip() == "":
            return {
                "ok": True,
                "member": self.find_member_by_discord_id(data, interaction.user.id),
                "error": None
            }

        query = str(query).strip()

        gw2_member = self.find_member_by_gw2_name(data, query)

        if gw2_member is not None:
            return {
                "ok": True,
                "member": gw2_member,
                "error": None
            }

        resolved = await self.resolve_discord_user_input(interaction, query)

        if resolved["ok"]:
            member = self.find_member_by_discord_id(data, int(resolved["discord_id"]))

            if member is not None:
                return {
                    "ok": True,
                    "member": member,
                    "error": None
                }

            return {
                "ok": False,
                "member": None,
                "error": (
                    f"❌ Discord user **{resolved['display']}** was found, "
                    f"but is not linked to a GW2 account."
                )
            }

        name_matches = self.find_members_by_name_contains(data, query)

        if len(name_matches) == 1:
            return {
                "ok": True,
                "member": name_matches[0],
                "error": None
            }

        if len(name_matches) > 1:
            preview = "\n".join(
                f"• {member.get('name', 'Unknown')}"
                for member in name_matches[:10]
            )

            extra = ""
            if len(name_matches) > 10:
                extra = f"\n...and **{len(name_matches) - 10}** more."

            return {
                "ok": False,
                "member": None,
                "error": (
                    f"❌ Multiple GW2 accounts matched **{query}**.\n\n"
                    f"{preview}{extra}\n\n"
                    f"Use the exact GW2 account name."
                )
            }

        return {
            "ok": False,
            "member": None,
            "error": f"❌ No linked guild member found for **{query}**."
        }

    # =========================
    # AUTOCOMPLETE
    # =========================
    async def gw2_account_autocomplete(self, interaction: discord.Interaction, current: str):
        query = current.lower().strip()
        choices = []

        for member in self.load_guild_data():
            name = member.get("name", "")

            if not name:
                continue

            if query in name.lower():
                choices.append(
                    discord.app_commands.Choice(
                        name=name,
                        value=name
                    )
                )

        return choices[:25]

    async def linked_query_autocomplete(self, interaction: discord.Interaction, current: str):
        query = current.lower().strip()
        choices = []

        for member in self.load_guild_data():
            name = member.get("name", "")
            discord_user_id = member.get("discord_user_id")

            if not name:
                continue

            if query in name.lower():
                label = name

                if discord_user_id is not None:
                    label += " ✅"
                else:
                    label += " ❌"

                choices.append(
                    discord.app_commands.Choice(
                        name=label[:100],
                        value=name
                    )
                )

        return choices[:25]

    # =========================
    # RAFFLE RECONCILIATION
    # =========================
    def calculate_raffle_ticket_count(self, donation_total: int, ticket_price: int, multiple_tickets: bool) -> int:
        if ticket_price <= 0:
            return 0

        if donation_total < ticket_price:
            return 0

        if multiple_tickets:
            return donation_total // ticket_price

        return 1

    async def reconcile_active_raffle_for_member(self, member: dict):
        """
        If a member donated during an active raffle while unlinked,
        linking them later should count their tracked raffle donation total.

        This relies on raffle_tickets storing Discord IDs once linked.
        If the member already has tracked raffle tickets, this recalculates them.
        """
        raffle = self.load_raffle()

        if not raffle.get("active"):
            return {
                "active": False,
                "updated": False,
                "donation_total": 0,
                "ticket_count": 0
            }

        discord_user_id = member.get("discord_user_id")

        if discord_user_id is None:
            return {
                "active": True,
                "updated": False,
                "donation_total": 0,
                "ticket_count": 0
            }

        tickets = self.load_raffle_tickets()
        key = str(discord_user_id)

        # If there is no donation record yet, nothing to reconcile.
        if key not in tickets:
            return {
                "active": True,
                "updated": False,
                "donation_total": 0,
                "ticket_count": 0
            }

        entry = tickets[key]
        donation_total = int(entry.get("raffle_donation_total", 0))
        ticket_price = int(raffle.get("ticket_price", 0))
        multiple_tickets = bool(raffle.get("multiple_tickets", False))

        ticket_count = self.calculate_raffle_ticket_count(
            donation_total=donation_total,
            ticket_price=ticket_price,
            multiple_tickets=multiple_tickets
        )

        entry["gw2_account_name"] = member.get("name", entry.get("gw2_account_name", "Unknown"))
        entry["ticket_count"] = ticket_count

        tickets[key] = entry
        self.save_raffle_tickets(tickets)

        return {
            "active": True,
            "updated": True,
            "donation_total": donation_total,
            "ticket_count": ticket_count
        }

    # =========================
    # LOGGING
    # =========================
    async def send_link_update(self, message: str):
        """
        Send link updates to the same bot log channel used by bot.py when possible.
        """
        if not message:
            return

        send_bot_log = getattr(self.bot, "send_bot_log", None)

        if callable(send_bot_log):
            try:
                await send_bot_log(message)
                return
            except Exception:
                pass

        print(message)

    # =========================
    # MESSAGE BUILDERS
    # =========================
    async def build_status_message(self, member: Optional[dict], viewer_is_admin: bool = False):
        if member is None:
            return (
                "🔗 **Guild Link Status**\n\n"
                "Linked: ❌ No\n"
                "No linked GW2 account was found."
            )

        name = member.get("name", "Unknown")
        rank = member.get("rank", "Unknown")
        weekly_gold = int(member.get("weekly_gold", 0))
        lifetime_gold = int(member.get("lifetime_gold", 0))
        link_status = await self.format_link_status(member, include_id=viewer_is_admin)

        lines = [
            "🔗 **Guild Link Status**",
            "",
            f"GW2 account: **{name}**",
            link_status,
            f"Weekly donated: **{self.format_gold(weekly_gold)}**",
            f"Lifetime donated: **{self.format_gold(lifetime_gold)}**",
        ]

        if viewer_is_admin:
            lines.insert(4, f"Rank: **{rank}**")

        return "\n".join(lines)

    async def build_summary_message(self):
        data = self.load_guild_data()

        total = len(data)
        linked = sum(
            1 for member in data
            if member.get("discord_user_id") is not None
        )
        unlinked = total - linked

        return (
            "🔗 **Guild Link Summary**\n\n"
            f"Guild members tracked: **{total}**\n"
            f"Linked: ✅ **{linked}**\n"
            f"Unlinked: ❌ **{unlinked}**"
        )

    # =========================
    # PANEL-CALLABLE ACTIONS
    # =========================
    async def status_lookup_from_panel(self, interaction: discord.Interaction, query: str):
        """
        Used by vr_bot_panels.py.
        Looks up guild link status without exposing a separate slash command.
        """
        try:
            resolved = await self.resolve_lookup_query(interaction, query)

            if not resolved["ok"]:
                return resolved["error"]

            return await self.build_status_message(
                resolved["member"],
                viewer_is_admin=True
            )

        except Exception as error:
            return f"⚠️ Error: {error}"

    async def force_link_from_panel(
        self,
        interaction: discord.Interaction,
        gw2_account_name: str,
        discord_user: str,
    ):
        """
        Used by vr_bot_panels.py.
        Force-links a GW2 account to a Discord user.
        Mirrors the previous /guildlink_admin force workflow.
        """
        try:
            data = self.load_guild_data()
            member = self.find_member_by_gw2_name(data, gw2_account_name)

            if member is None:
                return "❌ Not a guild member."

            resolved = await self.resolve_discord_user_input(
                interaction,
                discord_user
            )

            if not resolved["ok"]:
                return resolved["error"]

            new_discord_id = int(resolved["discord_id"])
            resolved_display = resolved["display"]

            old_linked_member = self.find_member_by_discord_id(data, new_discord_id)
            unlinked_previous_account = None

            if (
                old_linked_member is not None
                and old_linked_member.get("name") != member.get("name")
            ):
                unlinked_previous_account = old_linked_member.get("name", "Unknown")
                old_linked_member["discord_user_id"] = None

            old_discord_id = member.get("discord_user_id")
            old_discord_display = None

            if old_discord_id is not None:
                old_discord_display = await self.format_discord_user(
                    int(old_discord_id),
                    include_id=True
                )

            member["discord_user_id"] = new_discord_id
            self.save_guild_data(data)

            raffle_result = await self.reconcile_active_raffle_for_member(member)

            admin_name = (
                interaction.user.display_name
                if isinstance(interaction.user, discord.Member)
                else interaction.user.name
            )

            if old_discord_id is None:
                response = (
                    f"✅ **Guild link force-created**\n\n"
                    f"GW2 account: **{member.get('name', 'Unknown')}**\n"
                    f"Linked: ✅ {resolved_display}"
                )

                log_message = (
                    f"🛠️ **Guild link force-created**\n"
                    f"Admin: **{admin_name}**\n"
                    f"GW2 account: **{member.get('name', 'Unknown')}**\n"
                    f"Linked: ✅ {resolved_display}"
                )
            else:
                response = (
                    f"✅ **Guild link force-updated**\n\n"
                    f"GW2 account: **{member.get('name', 'Unknown')}**\n"
                    f"Linked: ✅ {resolved_display}\n"
                    f"Previous Discord: {old_discord_display}"
                )

                log_message = (
                    f"🛠️ **Guild link force-updated**\n"
                    f"Admin: **{admin_name}**\n"
                    f"GW2 account: **{member.get('name', 'Unknown')}**\n"
                    f"Linked: ✅ {resolved_display}\n"
                    f"Previous Discord: {old_discord_display}"
                )

            if unlinked_previous_account is not None:
                response += (
                    f"\n\n⚠️ Discord user was previously linked to "
                    f"**{unlinked_previous_account}** and has been moved."
                )

                log_message += (
                    f"\n⚠️ Discord user was previously linked to "
                    f"**{unlinked_previous_account}** and has been moved."
                )

            if raffle_result.get("updated"):
                response += (
                    f"\n\n🎟️ **Active raffle updated**\n"
                    f"Counted donation total: **{self.format_gold(raffle_result['donation_total'])}**\n"
                    f"Tickets: **{raffle_result['ticket_count']}**"
                )

                log_message += (
                    f"\n🎟️ Active raffle updated: "
                    f"**{self.format_gold(raffle_result['donation_total'])}** counted, "
                    f"**{raffle_result['ticket_count']}** ticket(s)."
                )

            await self.send_link_update(log_message)
            return response

        except Exception as error:
            return f"⚠️ Error: {error}"

    async def unlink_from_panel(self, interaction: discord.Interaction, query: str):
        """
        Used by vr_bot_panels.py.
        Unlinks a GW2 account or Discord user.
        Mirrors the previous /guildlink_admin unlink workflow.
        """
        try:
            resolved = await self.resolve_lookup_query(interaction, query)

            if not resolved["ok"]:
                return resolved["error"]

            member = resolved["member"]

            if member.get("discord_user_id") is None:
                return (
                    f"ℹ️ **{member.get('name', 'Unknown')}** is already unlinked.\n"
                    f"Linked: ❌ No"
                )

            old_discord_display = await self.format_discord_user(
                int(member["discord_user_id"]),
                include_id=True
            )

            member["discord_user_id"] = None

            data = self.load_guild_data()

            for saved_member in data:
                if saved_member.get("name") == member.get("name"):
                    saved_member["discord_user_id"] = None
                    break

            self.save_guild_data(data)

            admin_name = (
                interaction.user.display_name
                if isinstance(interaction.user, discord.Member)
                else interaction.user.name
            )

            response = (
                f"✅ **Guild account unlinked**\n\n"
                f"GW2 account: **{member.get('name', 'Unknown')}**\n"
                f"Previous Discord: {old_discord_display}\n"
                f"Linked: ❌ No"
            )

            await self.send_link_update(
                f"🔗 **Guild account unlinked**\n"
                f"Admin: **{admin_name}**\n"
                f"GW2 account: **{member.get('name', 'Unknown')}**\n"
                f"Previous Discord: {old_discord_display}"
            )

            return response

        except Exception as error:
            return f"⚠️ Error: {error}"

    async def summary_from_panel(self):
        """
        Used by vr_bot_panels.py.
        Returns linked/unlinked counts.
        """
        try:
            return await self.build_summary_message()
        except Exception as error:
            return f"⚠️ Error: {error}"


async def setup(bot: commands.Bot):
    await bot.add_cog(GuildLink(bot))