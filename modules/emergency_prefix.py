import discord
from discord.ext import commands
import shlex


class EmergencyPrefix(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # =========================
    # HELPERS
    # =========================
    def is_admin_ctx(self, ctx: commands.Context) -> bool:
        return (
            isinstance(ctx.author, discord.Member)
            and ctx.author.guild_permissions.administrator
        )

    def bool_from_text(self, value: str) -> bool:
        return value.lower().strip() in ("true", "yes", "y", "1", "on", "all")

    def get_guild_link_cog(self):
        return self.bot.get_cog("GuildLink")

    def get_raffle_cog(self):
        return self.bot.get_cog("Raffle")

    async def require_admin(self, ctx: commands.Context) -> bool:
        if not self.is_admin_ctx(ctx):
            await ctx.reply("❌ No permission.")
            return False

        return True

    # =========================
    # !guildlink_force
    # =========================
    @commands.command(name="guildlink_force")
    @commands.has_permissions(administrator=True)
    async def guildlink_force_prefix(self, ctx: commands.Context, *, args: str):
        """
        Emergency prefix version of guildlink_force.

        Usage:
        !guildlink_force "Account.1234" @User
        !guildlink_force "Account.1234" DiscordNickname
        !guildlink_force "Account.1234" 123456789012345678
        """
        if not await self.require_admin(ctx):
            return

        guild_link = self.get_guild_link_cog()

        if guild_link is None:
            return await ctx.reply("❌ GuildLink module is not loaded.")

        try:
            parts = shlex.split(args)

            if len(parts) < 2:
                return await ctx.reply(
                    "❌ Usage: `!guildlink_force \"GW2Account.1234\" DiscordUser`\n"
                    "Examples:\n"
                    "`!guildlink_force \"Account.1234\" @User`\n"
                    "`!guildlink_force \"Account.1234\" Nickname`\n"
                    "`!guildlink_force \"Account.1234\" 123456789012345678`"
                )

            gw2_account_name = parts[0]
            discord_user_input = " ".join(parts[1:])

            data = guild_link.load_guild_data()

            member = guild_link.find_member_by_gw2_name(data, gw2_account_name)

            if member is None:
                return await ctx.reply("❌ Not a guild member.")

            fake_interaction = type(
                "FakeInteraction",
                (),
                {
                    "guild": ctx.guild,
                    "user": ctx.author
                }
            )()

            resolved = await guild_link.resolve_discord_user_input(
                fake_interaction,
                discord_user_input
            )

            if not resolved["ok"]:
                return await ctx.reply(resolved["error"])

            new_discord_id = resolved["discord_id"]
            resolved_display = resolved["display"]

            old_linked_member = guild_link.find_member_by_discord_id(data, new_discord_id)
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
                old_discord_display = await guild_link.format_discord_user(
                    int(old_discord_id),
                    include_id=True
                )

            member["discord_user_id"] = new_discord_id
            guild_link.save_guild_data(data)

            raffle_result = await guild_link.reconcile_active_raffle_for_member(member)

            if old_discord_id is None:
                response = (
                    f"✅ **Guild link force-created**\n\n"
                    f"GW2 account: **{member.get('name', 'Unknown')}**\n"
                    f"Linked: ✅ {resolved_display}"
                )

                log_message = (
                    f"🛠️ **Guild link force-created**\n"
                    f"Admin: **{ctx.author.display_name}**\n"
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
                    f"Admin: **{ctx.author.display_name}**\n"
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
                    f"Counted donation total: **{guild_link.format_gold(raffle_result['donation_total'])}**\n"
                    f"Tickets: **{raffle_result['ticket_count']}**"
                )

                log_message += (
                    f"\n🎟️ Active raffle updated: "
                    f"**{guild_link.format_gold(raffle_result['donation_total'])}** counted, "
                    f"**{raffle_result['ticket_count']}** ticket(s)."
                )

            await guild_link.send_link_update(log_message)
            await ctx.reply(response)

        except Exception as e:
            await ctx.reply(f"⚠️ Error: `{e}`")

    # =========================
    # !raffle_status
    # =========================
    @commands.command(name="raffle_status")
    async def raffle_status_prefix(self, ctx: commands.Context):
        raffle_cog = self.get_raffle_cog()

        if raffle_cog is None:
            return await ctx.reply("❌ Raffle module is not loaded.")

        try:
            raffle = raffle_cog.load_raffle()

            if not raffle.get("active"):
                return await ctx.reply("ℹ️ No active raffle.")

            tickets = raffle_cog.load_tickets()
            total_entries = raffle_cog.get_total_tickets(tickets)
            remaining = raffle_cog.get_remaining_time(raffle["end_time"])

            msg = (
                f"🎟️ **Raffle Status**\n\n"
                f"Raffle: **{raffle.get('title', 'Unknown')}**\n"
                f"Time remaining: **{remaining}**\n"
                f"Ticket price: **{raffle_cog.format_gold(raffle.get('ticket_price', 0))}**\n"
                f"Multiple tickets: **{'Yes' if raffle.get('multiple_tickets') else 'No'}**\n"
                f"Tickets: **{total_entries}**"
            )

            if raffle.get("winner_takes_all"):
                pot_total = raffle_cog.get_raffle_pot_total(tickets)
                msg += f"\nPot: **{raffle_cog.format_gold(pot_total)}**"

            await ctx.reply(msg)

        except Exception as e:
            await ctx.reply(f"⚠️ Error: `{e}`")

    # =========================
    # !raffle_entries
    # =========================
    @commands.command(name="raffle_entries")
    @commands.has_permissions(administrator=True)
    async def raffle_entries_prefix(self, ctx: commands.Context, include_zero: str = "false"):
        if not await self.require_admin(ctx):
            return

        raffle_cog = self.get_raffle_cog()

        if raffle_cog is None:
            return await ctx.reply("❌ Raffle module is not loaded.")

        try:
            raffle = raffle_cog.load_raffle()

            if not raffle.get("active"):
                return await ctx.reply("ℹ️ No active raffle.")

            show_zero = self.bool_from_text(include_zero)

            tickets = raffle_cog.load_tickets()
            entries = raffle_cog.get_ticket_holders(tickets, include_zero=show_zero)

            if not entries:
                return await ctx.reply("ℹ️ No raffle ticket holders yet.")

            embed = await raffle_cog.build_entries_embed(
                raffle=raffle,
                entries=entries,
                include_zero=show_zero
            )

            await ctx.reply(embed=embed)

        except Exception as e:
            await ctx.reply(f"⚠️ Error: `{e}`")

    # =========================
    # ERROR HANDLING
    # =========================
    @guildlink_force_prefix.error
    @raffle_entries_prefix.error
    async def admin_command_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingPermissions):
            return await ctx.reply("❌ No permission.")

        if isinstance(error, commands.MissingRequiredArgument):
            return await ctx.reply("❌ Missing required argument.")

        await ctx.reply(f"⚠️ Error: `{error}`")


async def setup(bot: commands.Bot):
    await bot.add_cog(EmergencyPrefix(bot))