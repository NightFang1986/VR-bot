import asyncio
import difflib
import json
import os
import random
import subprocess
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import discord
from discord import app_commands
from discord.ext import commands


RAFFLE_FILE = "raffle_data.json"
RAFFLE_TICKET_FILE = "raffle_tickets.json"
GUILD_FILE = "guild_data.json"
GUILD_UPGRADE_STATE_FILE = "guild_upgrade_state.json"
BOT_SYNC_STATE_FILE = "bot_sync_state.json"


# ============================================================
# CONFIRMATION VIEWS
# ============================================================
class ConfirmActionView(discord.ui.View):
    def __init__(
        self,
        cog: "VRBotPanels",
        owner_id: int,
        action: str,
        title: str,
    ):
        super().__init__(timeout=120)
        self.cog = cog
        self.owner_id = owner_id
        self.action = action
        self.title = title

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self.cog.admin_interaction_check(interaction, self.owner_id)

    async def disable_buttons(self):
        for item in self.children:
            item.disabled = True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger, emoji="✅")
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await self.disable_buttons()

        try:
            if self.action == "bot_sync":
                message = await self.cog.run_bot_sync()
            elif self.action == "bot_restart":
                message = await self.cog.run_bot_restart()
            elif self.action == "raffle_draw":
                message = await self.cog.run_raffle_draw()
            elif self.action == "raffle_end":
                message = await self.cog.run_raffle_end()
            elif self.action == "upgrade_end":
                message = await self.cog.run_guild_upgrade_end()
            elif self.action == "donation_reset_weekly":
                message = await self.cog.reset_weekly_donations_from_panel()
            else:
                message = "❌ Unknown action."

            await interaction.followup.send(message, ephemeral=True)

        except Exception as error:
            await interaction.followup.send(
                f"⚠️ Action failed:\n```text\n{error}\n```",
                ephemeral=True,
            )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="↩️")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await self.disable_buttons()
        await interaction.followup.send("✅ Cancelled. Nothing was changed.", ephemeral=True)


# ============================================================
# RAFFLE MODALS
# ============================================================
class RaffleCreateModal(discord.ui.Modal, title="Create Raffle"):
    raffle_title = discord.ui.TextInput(
        label="Raffle title",
        placeholder="Example: Monthly Guild Raffle",
        max_length=100,
        required=True,
    )

    duration_hours = discord.ui.TextInput(
        label="Duration in hours",
        placeholder="Example: 168 for 7 days",
        max_length=8,
        required=True,
        default="168",
    )

    ticket_price_gold = discord.ui.TextInput(
        label="Ticket price in gold",
        placeholder="Example: 5",
        max_length=12,
        required=True,
        default="1",
    )

    multiple_tickets = discord.ui.TextInput(
        label="Multiple tickets? yes/no",
        placeholder="yes or no",
        max_length=5,
        required=True,
        default="yes",
    )

    winner_takes_all = discord.ui.TextInput(
        label="Winner takes all? yes/no",
        placeholder="yes or no",
        max_length=5,
        required=True,
        default="yes",
    )

    def __init__(self, cog: "VRBotPanels"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        message = await self.cog.create_raffle_from_panel(
            title=str(self.raffle_title.value).strip(),
            duration_hours_text=str(self.duration_hours.value).strip(),
            ticket_price_gold_text=str(self.ticket_price_gold.value).strip(),
            multiple_tickets_text=str(self.multiple_tickets.value).strip(),
            winner_takes_all_text=str(self.winner_takes_all.value).strip(),
        )

        await interaction.followup.send(message, ephemeral=True)


class RaffleEditModal(discord.ui.Modal, title="Edit Raffle"):
    raffle_title = discord.ui.TextInput(
        label="New title, blank keeps current",
        placeholder="Leave blank to keep current",
        max_length=100,
        required=False,
    )

    duration_hours = discord.ui.TextInput(
        label="Duration hours, blank keeps",
        placeholder="Example: 72",
        max_length=8,
        required=False,
    )

    ticket_price_gold = discord.ui.TextInput(
        label="New ticket price in gold, blank keeps",
        placeholder="Example: 5",
        max_length=12,
        required=False,
    )

    multiple_tickets = discord.ui.TextInput(
        label="Multiple tickets? yes/no/blank keeps",
        placeholder="yes / no / blank",
        max_length=5,
        required=False,
    )

    winner_takes_all = discord.ui.TextInput(
        label="Winner takes all? yes/no/blank keeps",
        placeholder="yes / no / blank",
        max_length=5,
        required=False,
    )

    def __init__(self, cog: "VRBotPanels"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        message = await self.cog.edit_raffle_from_panel(
            title=str(self.raffle_title.value).strip(),
            duration_hours_text=str(self.duration_hours.value).strip(),
            ticket_price_gold_text=str(self.ticket_price_gold.value).strip(),
            multiple_tickets_text=str(self.multiple_tickets.value).strip(),
            winner_takes_all_text=str(self.winner_takes_all.value).strip(),
        )

        await interaction.followup.send(message, ephemeral=True)


class RaffleTicketModifyModal(discord.ui.Modal):
    discord_user_id = discord.ui.TextInput(
        label="Discord user ID",
        placeholder="Right click user → Copy User ID",
        max_length=32,
        required=True,
    )

    ticket_count = discord.ui.TextInput(
        label="Ticket count",
        placeholder="Example: 1",
        max_length=8,
        required=True,
        default="1",
    )

    note = discord.ui.TextInput(
        label="Optional note",
        placeholder="Optional admin note",
        style=discord.TextStyle.paragraph,
        max_length=300,
        required=False,
    )

    def __init__(self, cog: "VRBotPanels", mode: str):
        self.cog = cog
        self.mode = mode
        super().__init__(
            title="Add Raffle Tickets" if mode == "add" else "Remove Raffle Tickets"
        )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        message = await self.cog.modify_raffle_tickets_from_panel(
            mode=self.mode,
            discord_user_id_text=str(self.discord_user_id.value).strip(),
            ticket_count_text=str(self.ticket_count.value).strip(),
            note=str(self.note.value).strip(),
        )

        await interaction.followup.send(message, ephemeral=True)


# ============================================================
# GUILD UPGRADE MODALS
# ============================================================
class GuildUpgradeSearchModal(discord.ui.Modal, title="Search/List Guild Upgrades"):
    search = discord.ui.TextInput(
        label="Search text",
        placeholder="Example: brawling",
        max_length=80,
        required=False,
    )

    show_all = discord.ui.TextInput(
        label="Show all? yes/no",
        placeholder="yes or no",
        max_length=5,
        required=True,
        default="yes",
    )

    def __init__(self, cog: "VRBotPanels"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        output = await self.cog.run_guild_upgrade_search_from_panel(
            search=str(self.search.value).strip(),
            show_all_text=str(self.show_all.value).strip(),
        )

        await self.cog.send_panel_output(interaction, output)


class GuildUpgradeNumberModal(discord.ui.Modal):
    number = discord.ui.TextInput(
        label="Upgrade number",
        placeholder="Number from the upgrade list",
        max_length=12,
        required=True,
    )

    def __init__(self, cog: "VRBotPanels", mode: str):
        self.cog = cog
        self.mode = mode
        super().__init__(
            title="Start Guild Upgrade" if mode == "start" else "Confirm Guild Upgrade"
        )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if self.mode == "start":
            output = await self.cog.run_guild_upgrade_start_from_panel(
                number_text=str(self.number.value).strip()
            )
        else:
            output = await self.cog.run_guild_upgrade_confirm_from_panel(
                number_text=str(self.number.value).strip()
            )

        await self.cog.send_panel_output(interaction, output)


class GuildUpgradeChannelModal(discord.ui.Modal, title="Set Upgrade Channel"):
    channel_id = discord.ui.TextInput(
        label="Channel ID",
        placeholder="Right click channel → Copy Channel ID",
        max_length=32,
        required=True,
    )

    def __init__(self, cog: "VRBotPanels"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        output = await self.cog.run_guild_upgrade_set_channel_from_panel(
            channel_id_text=str(self.channel_id.value).strip()
        )

        await self.cog.send_panel_output(interaction, output)


# ============================================================
# DONATION MODALS
# ============================================================
class DonationSetLifetimeModal(discord.ui.Modal, title="Set Lifetime Donation"):
    discord_user_id = discord.ui.TextInput(
        label="Discord user ID",
        placeholder="Right click user → Copy User ID",
        max_length=32,
        required=True,
    )

    lifetime_gold = discord.ui.TextInput(
        label="Lifetime gold total",
        placeholder="Example: 250",
        max_length=16,
        required=True,
    )

    def __init__(self, cog: "VRBotPanels"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        message = await self.cog.set_lifetime_donation_from_panel(
            discord_user_id_text=str(self.discord_user_id.value).strip(),
            lifetime_gold_text=str(self.lifetime_gold.value).strip(),
        )

        await interaction.followup.send(message, ephemeral=True)


class DonationAdjustLifetimeModal(discord.ui.Modal, title="Adjust Lifetime Donation"):
    discord_user_id = discord.ui.TextInput(
        label="Discord user ID",
        placeholder="Right click user → Copy User ID",
        max_length=32,
        required=True,
    )

    adjustment_gold = discord.ui.TextInput(
        label="Adjustment in gold",
        placeholder="Example: 25 or -10",
        max_length=16,
        required=True,
    )

    def __init__(self, cog: "VRBotPanels"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        message = await self.cog.adjust_lifetime_donation_from_panel(
            discord_user_id_text=str(self.discord_user_id.value).strip(),
            adjustment_gold_text=str(self.adjustment_gold.value).strip(),
        )

        await interaction.followup.send(message, ephemeral=True)


# ============================================================
# GUILD LINK USER MODAL
# ============================================================
class GuildSelfLinkModal(discord.ui.Modal, title="Link GW2 Account"):
    account_name = discord.ui.TextInput(
        label="GW2 account name or partial",
        placeholder="Example: Account.1234 or partial account name",
        max_length=80,
        required=True,
    )

    def __init__(self, cog: "VRBotPanels"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        message = await self.cog.self_link_account_from_panel(
            user=interaction.user,
            account_name=str(self.account_name.value).strip(),
        )

        await interaction.followup.send(message, ephemeral=True)


class GuildLinkStatusLookupModal(discord.ui.Modal, title="Guild Link Status Lookup"):
    query = discord.ui.TextInput(
        label="Lookup text",
        placeholder="Example: Account.1234, @User, or partial nickname",
        max_length=100,
        required=True,
    )

    def __init__(self, cog: "VRBotPanels"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        message = await self.cog.guild_link_status_lookup_from_panel(
            query=str(self.query.value).strip(),
        )

        await interaction.followup.send(message, ephemeral=True)


class GuildLinkForceModal(discord.ui.Modal, title="Force Guild Link"):
    account_name = discord.ui.TextInput(
        label="GW2 account name or partial",
        placeholder="Example: Account.1234 or partial account name",
        max_length=80,
        required=True,
    )

    discord_user = discord.ui.TextInput(
        label="Discord target",
        placeholder="Example: @User, 123456789012345678, or partial nickname",
        max_length=100,
        required=True,
    )

    def __init__(self, cog: "VRBotPanels"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        message = await self.cog.force_link_account_from_panel(
            admin_user=interaction.user,
            account_name=str(self.account_name.value).strip(),
            discord_user_text=str(self.discord_user.value).strip(),
        )

        await interaction.followup.send(message, ephemeral=True)


class GuildLinkUnlinkModal(discord.ui.Modal, title="Unlink Guild Account"):
    query = discord.ui.TextInput(
        label="Lookup text",
        placeholder="Example: Account.1234, @User, or partial nickname",
        max_length=100,
        required=True,
    )

    def __init__(self, cog: "VRBotPanels"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        message = await self.cog.unlink_account_from_panel(
            admin_user=interaction.user,
            query=str(self.query.value).strip(),
        )

        await interaction.followup.send(message, ephemeral=True)


# ============================================================
# STANDARD USER PANEL
# ============================================================
class VRBotUserPanelView(discord.ui.View):
    def __init__(self, cog: "VRBotPanels", owner_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "❌ This panel belongs to someone else.",
                ephemeral=True,
            )
            return False

        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

    @discord.ui.button(label="Raffle Status", style=discord.ButtonStyle.secondary, emoji="🎟️", row=0)
    async def raffle_status_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(embed=self.cog.build_public_raffle_status_embed(), ephemeral=True)

    @discord.ui.button(label="My Tickets", style=discord.ButtonStyle.secondary, emoji="🎫", row=0)
    async def my_tickets_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(embed=await self.cog.build_my_tickets_embed(interaction.user), ephemeral=True)

    @discord.ui.button(label="Guild Upgrade", style=discord.ButtonStyle.secondary, emoji="🏗️", row=0)
    async def guild_upgrade_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        embeds = await self.cog.build_user_guild_upgrade_output()

        for embed in embeds:
            await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="Link Status", style=discord.ButtonStyle.secondary, emoji="🔗", row=1)
    async def link_help_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(embed=await self.cog.build_link_status_embed(interaction.user), ephemeral=True)

    @discord.ui.button(label="Link Account", style=discord.ButtonStyle.primary, emoji="📝", row=1)
    async def link_account_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Respond immediately with the modal.
        # Discord modal interactions cannot be deferred first, so avoid doing file I/O
        # or guild_data checks before send_modal(), otherwise Discord may show
        # "application did not respond" even though the second click works.
        await self.cog.send_modal_safely(interaction, lambda: GuildSelfLinkModal(self.cog), "Link Account")

    @discord.ui.button(label="My Donations", style=discord.ButtonStyle.secondary, emoji="💰", row=2)
    async def my_donations_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(embed=await self.cog.build_my_donations_embed(interaction.user), ephemeral=True)

    @discord.ui.button(label="Guild Info", style=discord.ButtonStyle.secondary, emoji="👥", row=2)
    async def guild_info_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(embed=self.cog.build_guild_info_embed(), ephemeral=True)


# ============================================================
# ADMIN BASE VIEW
# ============================================================
class AdminOnlyBaseView(discord.ui.View):
    def __init__(self, cog: "VRBotPanels", owner_id: int, timeout: int = 300):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self.cog.admin_interaction_check(interaction, self.owner_id)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

    async def open_main_menu(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=self.cog.build_admin_panel_embed(interaction.user),
            view=VRBotAdminPanelView(self.cog, interaction.user.id),
            ephemeral=True,
        )


# ============================================================
# ADMIN MAIN PANEL
# ============================================================
class VRBotAdminPanelView(AdminOnlyBaseView):
    @discord.ui.button(label="Bot Controls", style=discord.ButtonStyle.primary, emoji="🤖", row=0)
    async def bot_controls_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=self.cog.build_bot_controls_embed(interaction.user),
            view=BotControlsView(self.cog, interaction.user.id),
            ephemeral=True,
        )

    @discord.ui.button(label="Guild Sync", style=discord.ButtonStyle.secondary, emoji="🔄", row=0)
    async def guild_sync_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=self.cog.build_guild_sync_panel_embed(interaction.user),
            view=GuildSyncPanelView(self.cog, interaction.user.id),
            ephemeral=True,
        )

    @discord.ui.button(label="Guild Link", style=discord.ButtonStyle.secondary, emoji="🔗", row=0)
    async def guild_link_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=self.cog.build_guild_link_panel_embed(interaction.user),
            view=GuildLinkPanelView(self.cog, interaction.user.id),
            ephemeral=True,
        )

    @discord.ui.button(label="Raffle", style=discord.ButtonStyle.secondary, emoji="🎟️", row=1)
    async def raffle_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=self.cog.build_raffle_admin_panel_embed(interaction.user),
            view=RaffleAdminPanelView(self.cog, interaction.user.id),
            ephemeral=True,
        )

    @discord.ui.button(label="Guild Upgrades", style=discord.ButtonStyle.secondary, emoji="🏗️", row=1)
    async def guild_upgrades_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=self.cog.build_guild_upgrade_admin_panel_embed(interaction.user),
            view=GuildUpgradeAdminPanelView(self.cog, interaction.user.id),
            ephemeral=True,
        )

    @discord.ui.button(label="Donations", style=discord.ButtonStyle.secondary, emoji="💰", row=1)
    async def donations_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=self.cog.build_donations_panel_embed(interaction.user),
            view=DonationsPanelView(self.cog, interaction.user.id),
            ephemeral=True,
        )

    @discord.ui.button(label="Role Tools", style=discord.ButtonStyle.secondary, emoji="🔎", row=2)
    async def role_tools_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=self.cog.build_role_tools_panel_embed(interaction.user),
            view=RoleToolsPanelView(self.cog, interaction.user.id),
            ephemeral=True,
        )

    @discord.ui.button(label="Guild Bank", style=discord.ButtonStyle.secondary, emoji="🧹", row=2)
    async def guild_bank_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            embed=self.cog.build_guild_bank_panel_embed(interaction.user),
            view=GuildBankPanelView(self.cog, interaction.user.id),
            ephemeral=True,
        )


# ============================================================
# ADMIN SUBPANELS
# ============================================================
class BotControlsView(AdminOnlyBaseView):
    @discord.ui.button(label="Main Menu", style=discord.ButtonStyle.secondary, emoji="🏠", row=0)
    async def main_menu_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.open_main_menu(interaction)

    @discord.ui.button(label="Status", style=discord.ButtonStyle.secondary, emoji="🤖", row=0)
    async def status_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await self.cog.send_text_chunks(interaction, self.cog.build_bot_status_message())

    @discord.ui.button(label="Sync Commands", style=discord.ButtonStyle.primary, emoji="🔁", row=0)
    async def sync_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "⚠️ **Confirm Command Sync**\n\n"
            "This will sync the current slash command tree with Discord.\n\n"
            "Use this only after command structure changes, because Discord has a daily create limit.",
            view=ConfirmActionView(self.cog, interaction.user.id, "bot_sync", "Sync Commands"),
            ephemeral=True,
        )

    @discord.ui.button(label="Restart Bot", style=discord.ButtonStyle.danger, emoji="♻️", row=1)
    async def restart_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "⚠️ **Confirm Bot Restart**\n\n"
            "This will restart the systemd service:\n"
            "`gw2bot`\n\n"
            "Only continue if you are sure.",
            view=ConfirmActionView(self.cog, interaction.user.id, "bot_restart", "Restart Bot"),
            ephemeral=True,
        )

    @discord.ui.button(label="Sync Startup Info", style=discord.ButtonStyle.secondary, emoji="⚙️", row=1)
    async def sync_startup_info_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(self.cog.build_sync_startup_info_message(), ephemeral=True)


class GuildSyncPanelView(AdminOnlyBaseView):
    @discord.ui.button(label="Main Menu", style=discord.ButtonStyle.secondary, emoji="🏠", row=0)
    async def main_menu_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.open_main_menu(interaction)

    @discord.ui.button(label="Status", style=discord.ButtonStyle.secondary, emoji="📊", row=0)
    async def status_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await self.cog.send_text_chunks(interaction, self.cog.build_guild_sync_status_message())

    @discord.ui.button(label="Sync Now", style=discord.ButtonStyle.primary, emoji="⚡", row=0)
    async def sync_now_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await self.cog.send_text_chunks(interaction, await self.cog.run_guild_sync_now())

    @discord.ui.button(label="Members Help", style=discord.ButtonStyle.secondary, emoji="👥", row=1)
    async def members_help_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(
            "👥 **Guild Members Help**\n\n"
            "Member lists are now mostly handled by the Guild Link panel.\n\n"
            "Current fallback commands:\n"
            "`/guild_members linked:all limit:25`\n"
            "`/guild_members linked:linked limit:25`\n"
            "`/guild_members linked:unlinked limit:25`",
            ephemeral=True,
        )


class GuildLinkPanelView(AdminOnlyBaseView):
    @discord.ui.button(label="Main Menu", style=discord.ButtonStyle.secondary, emoji="🏠", row=0)
    async def main_menu_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.open_main_menu(interaction)

    @discord.ui.button(label="Linked Members", style=discord.ButtonStyle.secondary, emoji="🟢", row=0)
    async def linked_members_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        embeds = await self.cog.build_guild_link_member_embeds("linked", "🟢 Linked Guild Members")
        for embed in embeds:
            await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="Unlinked Members", style=discord.ButtonStyle.secondary, emoji="🔴", row=0)
    async def unlinked_members_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        embeds = await self.cog.build_guild_link_member_embeds("unlinked", "🔴 Unlinked Guild Members")
        for embed in embeds:
            await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="Status Lookup", style=discord.ButtonStyle.secondary, emoji="🔎", row=1)
    async def status_lookup_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.send_modal_safely(interaction, lambda: GuildLinkStatusLookupModal(self.cog), "Status Lookup")

    @discord.ui.button(label="Force Link", style=discord.ButtonStyle.primary, emoji="🛠️", row=1)
    async def force_link_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.send_modal_safely(interaction, lambda: GuildLinkForceModal(self.cog), "Force Link")

    @discord.ui.button(label="Unlink", style=discord.ButtonStyle.danger, emoji="⛓️", row=1)
    async def unlink_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await self.cog.send_modal_safely(interaction, lambda: GuildLinkUnlinkModal(self.cog), "Unlink")
        except Exception as error:
            if interaction.response.is_done():
                await interaction.followup.send(
                    f"❌ Failed to open the unlink popup.\n```text\n{error}\n```",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    f"❌ Failed to open the unlink popup.\n```text\n{error}\n```",
                    ephemeral=True,
                )

    @discord.ui.button(label="Summary", style=discord.ButtonStyle.secondary, emoji="📊", row=2)
    async def summary_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(self.cog.build_guild_link_summary_message(), ephemeral=True)

    @discord.ui.button(label="Help", style=discord.ButtonStyle.secondary, emoji="📋", row=2)
    async def link_help_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(self.cog.build_guild_link_help_message(), ephemeral=True)


class RaffleAdminPanelView(AdminOnlyBaseView):
    @discord.ui.button(label="Main Menu", style=discord.ButtonStyle.secondary, emoji="🏠", row=0)
    async def main_menu_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.open_main_menu(interaction)

    @discord.ui.button(label="Status", style=discord.ButtonStyle.secondary, emoji="🎟️", row=0)
    async def status_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(embed=self.cog.build_raffle_status_embed(), ephemeral=True)

    @discord.ui.button(label="Entries", style=discord.ButtonStyle.secondary, emoji="👥", row=0)
    async def entries_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        embeds = await self.cog.build_raffle_entries_embeds(include_zero=False)
        for embed in embeds:
            await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="Create", style=discord.ButtonStyle.success, emoji="➕", row=1)
    async def create_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.send_modal_safely(interaction, lambda: RaffleCreateModal(self.cog), "Create Raffle")

    @discord.ui.button(label="Edit", style=discord.ButtonStyle.primary, emoji="✏️", row=1)
    async def edit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        raffle = self.cog.load_raffle()
        if not raffle.get("active"):
            await interaction.response.send_message("ℹ️ No active raffle to edit.", ephemeral=True)
            return
        await self.cog.send_modal_safely(interaction, lambda: RaffleEditModal(self.cog), "Edit Raffle")

    @discord.ui.button(label="Add Tickets", style=discord.ButtonStyle.primary, emoji="🎫", row=1)
    async def add_tickets_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        raffle = self.cog.load_raffle()
        if not raffle.get("active"):
            await interaction.response.send_message("ℹ️ No active raffle.", ephemeral=True)
            return
        await self.cog.send_modal_safely(interaction, lambda: RaffleTicketModifyModal(self.cog, mode="add"), "Add Tickets")

    @discord.ui.button(label="Remove Tickets", style=discord.ButtonStyle.secondary, emoji="➖", row=2)
    async def remove_tickets_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        raffle = self.cog.load_raffle()
        if not raffle.get("active"):
            await interaction.response.send_message("ℹ️ No active raffle.", ephemeral=True)
            return
        await self.cog.send_modal_safely(interaction, lambda: RaffleTicketModifyModal(self.cog, mode="remove"), "Remove Tickets")

    @discord.ui.button(label="Draw Winner", style=discord.ButtonStyle.success, emoji="🏆", row=2)
    async def draw_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        raffle = self.cog.load_raffle()

        if not raffle.get("active"):
            await interaction.response.send_message("ℹ️ No active raffle.", ephemeral=True)
            return

        tickets = self.cog.load_tickets()

        await interaction.response.send_message(
            "⚠️ **Confirm Raffle Draw**\n\n"
            f"Raffle: **{raffle.get('title', 'Unknown raffle')}**\n"
            f"Tickets: **{self.cog.get_total_tickets(tickets)}**\n"
            f"Pot: **{self.cog.format_gold(self.cog.get_raffle_pot_total(tickets))}**\n\n"
            "This will draw a winner and end the raffle.",
            view=ConfirmActionView(self.cog, interaction.user.id, "raffle_draw", "Draw Raffle Winner"),
            ephemeral=True,
        )

    @discord.ui.button(label="End Raffle", style=discord.ButtonStyle.danger, emoji="🛑", row=2)
    async def end_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        raffle = self.cog.load_raffle()

        if not raffle.get("active"):
            await interaction.response.send_message("ℹ️ No active raffle.", ephemeral=True)
            return

        tickets = self.cog.load_tickets()

        await interaction.response.send_message(
            "⚠️ **Confirm End Raffle**\n\n"
            f"Raffle: **{raffle.get('title', 'Unknown raffle')}**\n"
            f"Tickets: **{self.cog.get_total_tickets(tickets)}**\n"
            f"Pot: **{self.cog.format_gold(self.cog.get_raffle_pot_total(tickets))}**\n\n"
            "This will end the raffle without drawing a winner.",
            view=ConfirmActionView(self.cog, interaction.user.id, "raffle_end", "End Raffle"),
            ephemeral=True,
        )


class GuildUpgradeAdminPanelView(AdminOnlyBaseView):
    @discord.ui.button(label="Main Menu", style=discord.ButtonStyle.secondary, emoji="🏠", row=0)
    async def main_menu_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.open_main_menu(interaction)

    @discord.ui.button(label="Status", style=discord.ButtonStyle.secondary, emoji="📊", row=0)
    async def status_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        output = await self.cog.build_guild_upgrade_admin_status_output()
        await self.cog.send_panel_output(interaction, output)

    @discord.ui.button(label="Search/List", style=discord.ButtonStyle.secondary, emoji="🔍", row=0)
    async def search_list_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.send_modal_safely(interaction, lambda: GuildUpgradeSearchModal(self.cog), "Search/List Upgrades")

    @discord.ui.button(label="Start", style=discord.ButtonStyle.primary, emoji="▶️", row=1)
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.send_modal_safely(interaction, lambda: GuildUpgradeNumberModal(self.cog, mode="start"), "Start Upgrade")

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success, emoji="✅", row=1)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.send_modal_safely(interaction, lambda: GuildUpgradeNumberModal(self.cog, mode="confirm"), "Confirm Upgrade")

    @discord.ui.button(label="Set Channel", style=discord.ButtonStyle.secondary, emoji="📌", row=1)
    async def set_channel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.send_modal_safely(interaction, lambda: GuildUpgradeChannelModal(self.cog), "Set Upgrade Channel")

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.primary, emoji="🔄", row=2)
    async def refresh_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(await self.cog.run_guild_upgrade_refresh(), ephemeral=True)

    @discord.ui.button(label="End Tracker", style=discord.ButtonStyle.danger, emoji="🛑", row=2)
    async def end_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = self.cog.load_guild_upgrade_state()

        if not state.get("active"):
            await interaction.response.send_message("ℹ️ No active guild upgrade tracker.", ephemeral=True)
            return

        await interaction.response.send_message(
            "⚠️ **Confirm End Tracker**\n\n"
            f"This will stop tracking **{state.get('upgrade_name', 'Unknown')}** "
            "and delete the public upgrade post.\n\n"
            "Are you sure?",
            view=ConfirmActionView(self.cog, interaction.user.id, "upgrade_end", "End Upgrade Tracker"),
            ephemeral=True,
        )


class DonationsPanelView(AdminOnlyBaseView):
    @discord.ui.button(label="Main Menu", style=discord.ButtonStyle.secondary, emoji="🏠", row=0)
    async def main_menu_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.open_main_menu(interaction)

    @discord.ui.button(label="Summary", style=discord.ButtonStyle.secondary, emoji="📊", row=0)
    async def summary_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(embed=self.cog.build_donation_summary_embed(), ephemeral=True)

    @discord.ui.button(label="Weekly Donors", style=discord.ButtonStyle.secondary, emoji="🏆", row=0)
    async def weekly_donors_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        embeds = await self.cog.build_donor_list_embeds(
            "🏆 Weekly Donors",
            "weekly_gold",
            "No weekly donors recorded.",
        )
        for embed in embeds:
            await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="Lifetime Donors", style=discord.ButtonStyle.secondary, emoji="👑", row=1)
    async def lifetime_donors_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        embeds = await self.cog.build_donor_list_embeds(
            "👑 Lifetime Donors",
            "lifetime_gold",
            "No lifetime donors recorded.",
        )
        for embed in embeds:
            await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="Set Lifetime", style=discord.ButtonStyle.primary, emoji="📝", row=1)
    async def set_lifetime_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.send_modal_safely(interaction, lambda: DonationSetLifetimeModal(self.cog), "Set Lifetime")

    @discord.ui.button(label="Adjust Lifetime", style=discord.ButtonStyle.primary, emoji="➕", row=2)
    async def adjust_lifetime_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.send_modal_safely(interaction, lambda: DonationAdjustLifetimeModal(self.cog), "Adjust Lifetime")

    @discord.ui.button(label="Reset Weekly", style=discord.ButtonStyle.danger, emoji="🧹", row=2)
    async def reset_weekly_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "⚠️ **Confirm Weekly Donation Reset**\n\n"
            "This will set `weekly_gold` to `0` for all tracked guild members.\n\n"
            "Lifetime totals will not be changed.",
            view=ConfirmActionView(self.cog, interaction.user.id, "donation_reset_weekly", "Reset Weekly Donations"),
            ephemeral=True,
        )


class RoleMissingSelect(discord.ui.RoleSelect):
    def __init__(self, cog: "VRBotPanels"):
        super().__init__(
            placeholder="Choose a role to check...",
            min_values=1,
            max_values=1,
            row=1,
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        role = self.values[0]
        embeds = self.cog.build_missing_role_embeds(
            guild=interaction.guild,
            role=role,
            include_bots=False,
        )

        for embed in embeds:
            await interaction.followup.send(embed=embed, ephemeral=True)


class RoleToolsPanelView(AdminOnlyBaseView):
    def __init__(self, cog: "VRBotPanels", owner_id: int, timeout: int = 300):
        super().__init__(cog=cog, owner_id=owner_id, timeout=timeout)
        self.add_item(RoleMissingSelect(cog))

    @discord.ui.button(label="Main Menu", style=discord.ButtonStyle.secondary, emoji="🏠", row=0)
    async def main_menu_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.open_main_menu(interaction)

    @discord.ui.button(label="Help", style=discord.ButtonStyle.secondary, emoji="📋", row=0)
    async def help_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(
            "🔎 **Role Tools Help**\n\n"
            "Use the role dropdown in this panel to find members who do **not** have a selected role.\n\n"
            "Bots are excluded by default.",
            ephemeral=True,
        )


class GuildBankPanelView(AdminOnlyBaseView):
    @discord.ui.button(label="Main Menu", style=discord.ButtonStyle.secondary, emoji="🏠", row=0)
    async def main_menu_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.open_main_menu(interaction)

    @discord.ui.button(label="Duplicate Stacks", style=discord.ButtonStyle.primary, emoji="🧹", row=0)
    async def duplicate_stacks_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        output = await self.cog.run_guild_bank_duplicates_check()

        if isinstance(output, str):
            await interaction.followup.send(output, ephemeral=True)
            return

        for embed in output:
            await interaction.followup.send(embed=embed, ephemeral=True)


# ============================================================
# MAIN COG
# ============================================================
class VRBotPanels(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ========================================================
    # CHECKS / COMMON OUTPUT
    # ========================================================
    async def admin_interaction_check(self, interaction: discord.Interaction, owner_id: int) -> bool:
        if interaction.user.id != owner_id:
            await interaction.response.send_message("❌ This panel belongs to someone else.", ephemeral=True)
            return False

        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ This can only be used inside the server.", ephemeral=True)
            return False

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You need administrator permissions to use this.", ephemeral=True)
            return False

        return True

    async def send_panel_output(self, interaction: discord.Interaction, output):
        if isinstance(output, discord.Embed):
            await interaction.followup.send(embed=output, ephemeral=True)
            return

        if isinstance(output, list):
            if not output:
                await interaction.followup.send("No output.", ephemeral=True)
                return

            for item in output:
                if isinstance(item, discord.Embed):
                    await interaction.followup.send(embed=item, ephemeral=True)
                else:
                    await interaction.followup.send(str(item), ephemeral=True)
            return

        await self.send_text_chunks(interaction, str(output))


    async def send_modal_safely(self, interaction: discord.Interaction, modal_factory, action_name: str):
        """Open a modal immediately and return a clean ephemeral error if Discord rejects it."""
        try:
            modal = modal_factory()
            await interaction.response.send_modal(modal)
        except Exception as error:
            message = (
                f"❌ Could not open the **{action_name}** popup.\n"
                "This is usually caused by a Discord UI limit or a stale interaction. Try opening the panel again.\n"
                f"```text\n{error}\n```"
            )

            try:
                if interaction.response.is_done():
                    await interaction.followup.send(message, ephemeral=True)
                else:
                    await interaction.response.send_message(message, ephemeral=True)
            except Exception:
                pass

    # ========================================================
    # FILE HELPERS
    # ========================================================
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
        raffle_cog = self.bot.get_cog("Raffle")

        if raffle_cog is not None and hasattr(raffle_cog, "load_raffle"):
            return raffle_cog.load_raffle()

        return self.load_json(RAFFLE_FILE, {"active": False})

    def save_raffle(self, data):
        raffle_cog = self.bot.get_cog("Raffle")

        if raffle_cog is not None and hasattr(raffle_cog, "save_raffle"):
            raffle_cog.save_raffle(data)
            return

        self.save_json(RAFFLE_FILE, data)

    def load_tickets(self):
        raffle_cog = self.bot.get_cog("Raffle")

        if raffle_cog is not None and hasattr(raffle_cog, "load_tickets"):
            return raffle_cog.load_tickets()

        return self.load_json(RAFFLE_TICKET_FILE, {})

    def save_tickets(self, data):
        raffle_cog = self.bot.get_cog("Raffle")

        if raffle_cog is not None and hasattr(raffle_cog, "save_tickets"):
            raffle_cog.save_tickets(data)
            return

        self.save_json(RAFFLE_TICKET_FILE, data)

    def load_guild_data(self):
        return self.load_json(GUILD_FILE, [])

    def save_guild_data(self, data):
        self.save_json(GUILD_FILE, data)

    def load_guild_upgrade_state(self):
        guild_upgrade_cog = self.bot.get_cog("GuildUpgrades")

        if guild_upgrade_cog is not None and hasattr(guild_upgrade_cog, "load_state"):
            return guild_upgrade_cog.load_state()

        return self.load_json(GUILD_UPGRADE_STATE_FILE, {"active": False})

    def save_guild_upgrade_state(self, data):
        guild_upgrade_cog = self.bot.get_cog("GuildUpgrades")

        if guild_upgrade_cog is not None and hasattr(guild_upgrade_cog, "save_state"):
            guild_upgrade_cog.save_state(data)
            return

        self.save_json(GUILD_UPGRADE_STATE_FILE, data)

    # ========================================================
    # FORMAT HELPERS
    # ========================================================
    def now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def safe_int(self, value, default: int = 0) -> int:
        try:
            return int(value or 0)
        except Exception:
            return default

    def parse_yes_no(self, value: str, default: Optional[bool] = None) -> Optional[bool]:
        normalized = str(value or "").strip().lower()

        if normalized == "" and default is not None:
            return default

        if normalized in {"yes", "y", "true", "1", "on"}:
            return True

        if normalized in {"no", "n", "false", "0", "off"}:
            return False

        return None

    def parse_gold_to_coins(self, text: str, allow_negative: bool = False) -> Optional[int]:
        try:
            value = float(str(text).strip().replace(",", "."))
        except Exception:
            return None

        if not allow_negative and value < 0:
            return None

        return int(round(value * 10000))

    def format_gold(self, coins: int) -> str:
        raffle_cog = self.bot.get_cog("Raffle")

        if raffle_cog is not None and hasattr(raffle_cog, "format_gold"):
            return raffle_cog.format_gold(coins)

        coins = int(coins or 0)
        sign = "-" if coins < 0 else ""
        coins = abs(coins)

        return f"{sign}{coins // 10000}g {(coins % 10000) // 100}s {coins % 100}c"

    def get_remaining_time(self, end_time_str: str) -> str:
        raffle_cog = self.bot.get_cog("Raffle")

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

    def split_lines_for_embed(self, lines: List[str], max_length: int = 3900) -> List[str]:
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

    async def send_text_chunks(self, interaction: discord.Interaction, message: str):
        for chunk in self.split_message(message):
            await interaction.followup.send(chunk, ephemeral=True)

    async def format_discord_user(self, discord_user_id: int, include_id: bool = False):
        for guild in self.bot.guilds:
            member = guild.get_member(int(discord_user_id))

            if member is not None:
                return f"{member.display_name} (`{discord_user_id}`)" if include_id else member.display_name

        try:
            user = await self.bot.fetch_user(int(discord_user_id))

            if user is not None:
                return f"{user.name} (`{discord_user_id}`)" if include_id else user.name
        except Exception:
            pass

        return f"Unknown user (`{discord_user_id}`)" if include_id else "Unknown user"

    # ========================================================
    # GUILD DATA HELPERS
    # ========================================================
    def get_linked_member_for_user(self, user_id: int):
        target = int(user_id)

        for member in self.load_guild_data():
            if member.get("discord_user_id") == target:
                return member

        return None

    def find_guild_member_by_discord_id(self, user_id: int):
        return self.get_linked_member_for_user(user_id)

    def find_guild_member_index_by_discord_id(self, data: list, user_id: int):
        target = int(user_id)

        for index, member in enumerate(data):
            if member.get("discord_user_id") == target:
                return index

        return None

    def find_guild_member_index_by_account_name(self, data: list, account_name: str):
        target = str(account_name or "").strip().lower()

        for index, member in enumerate(data):
            if str(member.get("name", "")).strip().lower() == target:
                return index

        return None

    def get_account_name_suggestions(self, account_name: str, limit: int = 5) -> List[str]:
        names = [
            str(member.get("name", "")).strip()
            for member in self.load_guild_data()
            if str(member.get("name", "")).strip()
        ]

        query = str(account_name or "").strip()

        if not query:
            return names[:limit]

        lower_query = query.lower()
        prefix_matches = [name for name in names if name.lower().startswith(lower_query)]

        if prefix_matches:
            return prefix_matches[:limit]

        return difflib.get_close_matches(query, names, n=limit, cutoff=0.35)

    def get_guild_link_stats(self):
        data = self.load_guild_data()
        linked_count = sum(1 for member in data if member.get("discord_user_id") is not None)

        return {
            "total": len(data),
            "linked": linked_count,
            "unlinked": len(data) - linked_count,
        }

    def get_sorted_guild_members(self, mode: str):
        members = []

        for member in self.load_guild_data():
            discord_user_id = member.get("discord_user_id")
            is_linked = discord_user_id is not None

            if mode == "linked" and not is_linked:
                continue

            if mode == "unlinked" and is_linked:
                continue

            members.append(member)

        members.sort(
            key=lambda item: (
                str(item.get("rank", "")).lower(),
                str(item.get("name", "")).lower(),
            )
        )

        return members

    def get_sorted_donors(self, amount_key: str):
        donors = []

        for member in self.load_guild_data():
            amount = self.safe_int(member.get(amount_key, 0))

            if amount <= 0:
                continue

            donors.append(
                {
                    "name": member.get("name", "Unknown"),
                    "rank": member.get("rank", "Unknown"),
                    "discord_user_id": member.get("discord_user_id"),
                    "amount": amount,
                }
            )

        donors.sort(
            key=lambda item: (
                item["amount"],
                item["name"].lower(),
            ),
            reverse=True,
        )

        return donors

    async def format_donor_line(self, index: int, donor: dict) -> str:
        name = donor.get("name", "Unknown")
        amount = self.safe_int(donor.get("amount", 0))
        discord_user_id = donor.get("discord_user_id")

        if discord_user_id is not None:
            discord_name = await self.format_discord_user(int(discord_user_id), include_id=False)
            return f"**{index}.** 🟢 **{name}** - {discord_name} — **{self.format_gold(amount)}**"

        return f"**{index}.** 🔴 **{name}** — **{self.format_gold(amount)}**"

    async def format_link_member_line(self, index: int, member: dict) -> str:
        name = member.get("name", "Unknown")
        rank = member.get("rank", "Unknown")
        discord_user_id = member.get("discord_user_id")

        if discord_user_id is not None:
            discord_name = await self.format_discord_user(int(discord_user_id), include_id=False)
            return f"**{index}.** 🟢 **{name}** - {discord_name} — {rank}"

        return f"**{index}.** 🔴 **{name}** — {rank}"

    # ========================================================
    # RAFFLE HELPERS / ACTIONS
    # ========================================================
    def get_total_tickets(self, tickets: dict) -> int:
        raffle_cog = self.bot.get_cog("Raffle")

        if raffle_cog is not None and hasattr(raffle_cog, "get_total_tickets"):
            return raffle_cog.get_total_tickets(tickets)

        return sum(
            self.safe_int(entry.get("ticket_count", 0))
            for entry in tickets.values()
            if isinstance(entry, dict)
        )

    def get_raffle_pot_total(self, tickets: dict) -> int:
        raffle_cog = self.bot.get_cog("Raffle")

        if raffle_cog is not None and hasattr(raffle_cog, "get_raffle_pot_total"):
            return raffle_cog.get_raffle_pot_total(tickets)

        return sum(
            self.safe_int(entry.get("raffle_donation_total", 0))
            for entry in tickets.values()
            if isinstance(entry, dict)
        )

    def get_ticket_holders_count(self, tickets: dict) -> int:
        return len(
            [
                entry for entry in tickets.values()
                if isinstance(entry, dict)
                and self.safe_int(entry.get("ticket_count", 0)) > 0
            ]
        )

    def build_weighted_pool(self, tickets: dict) -> list:
        raffle_cog = self.bot.get_cog("Raffle")

        if raffle_cog is not None and hasattr(raffle_cog, "build_weighted_pool"):
            return raffle_cog.build_weighted_pool(tickets)

        pool = []

        for discord_id, entry in tickets.items():
            ticket_count = self.safe_int(entry.get("ticket_count", 0))

            if ticket_count > 0:
                pool.extend([discord_id] * ticket_count)

        return pool

    def get_ticket_holders(self, tickets: dict, include_zero: bool = False) -> list:
        raffle_cog = self.bot.get_cog("Raffle")

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
                    "discord_id": str(discord_id),
                    "gw2_account_name": entry.get("gw2_account_name", "Unknown"),
                    "raffle_donation_total": donation_total,
                    "ticket_count": ticket_count,
                }
            )

        entries.sort(
            key=lambda item: (
                item["ticket_count"],
                item["raffle_donation_total"],
                item["gw2_account_name"].lower(),
            ),
            reverse=True,
        )

        return entries

    async def create_raffle_from_panel(
        self,
        title: str,
        duration_hours_text: str,
        ticket_price_gold_text: str,
        multiple_tickets_text: str,
        winner_takes_all_text: str,
    ) -> str:
        current = self.load_raffle()

        if current.get("active"):
            return (
                "❌ A raffle is already active.\n\n"
                f"Current raffle: **{current.get('title', 'Unknown raffle')}**\n"
                "End it before creating a new one."
            )

        duration_hours = self.safe_int(duration_hours_text, -1)

        if duration_hours <= 0:
            return "❌ Duration must be a positive number of hours."

        ticket_price = self.parse_gold_to_coins(ticket_price_gold_text)

        if ticket_price is None:
            return "❌ Ticket price must be a valid gold amount."

        multiple_tickets = self.parse_yes_no(multiple_tickets_text)

        if multiple_tickets is None:
            return "❌ Multiple tickets must be yes or no."

        winner_takes_all = self.parse_yes_no(winner_takes_all_text)

        if winner_takes_all is None:
            return "❌ Winner takes all must be yes or no."

        now = datetime.now(timezone.utc)
        end_time = now + timedelta(hours=duration_hours)

        raffle = {
            "active": True,
            "title": title or "Guild Raffle",
            "created_at": now.isoformat(),
            "end_time": end_time.isoformat(),
            "ticket_price": ticket_price,
            "multiple_tickets": multiple_tickets,
            "winner_takes_all": winner_takes_all,
            "created_from": "vr_bot_admin_panel",
        }

        self.save_raffle(raffle)
        self.save_tickets({})

        return (
            "✅ **Raffle created**\n\n"
            f"Raffle: **{raffle['title']}**\n"
            f"Duration: **{duration_hours} hour(s)**\n"
            f"Ticket price: **{self.format_gold(ticket_price)}**\n"
            f"Multiple tickets: **{'Yes' if multiple_tickets else 'No'}**\n"
            f"Winner takes all: **{'Yes' if winner_takes_all else 'No'}**"
        )

    async def edit_raffle_from_panel(
        self,
        title: str,
        duration_hours_text: str,
        ticket_price_gold_text: str,
        multiple_tickets_text: str,
        winner_takes_all_text: str,
    ) -> str:
        raffle = self.load_raffle()

        if not raffle.get("active"):
            return "ℹ️ No active raffle to edit."

        changes = []

        if title:
            raffle["title"] = title
            changes.append(f"Title: **{title}**")

        if duration_hours_text:
            duration_hours = self.safe_int(duration_hours_text, -1)

            if duration_hours <= 0:
                return "❌ Duration must be a positive number of hours."

            raffle["end_time"] = (datetime.now(timezone.utc) + timedelta(hours=duration_hours)).isoformat()
            changes.append(f"Duration reset to: **{duration_hours} hour(s) from now**")

        if ticket_price_gold_text:
            ticket_price = self.parse_gold_to_coins(ticket_price_gold_text)

            if ticket_price is None:
                return "❌ Ticket price must be a valid gold amount."

            raffle["ticket_price"] = ticket_price
            changes.append(f"Ticket price: **{self.format_gold(ticket_price)}**")

        if multiple_tickets_text:
            multiple_tickets = self.parse_yes_no(multiple_tickets_text)

            if multiple_tickets is None:
                return "❌ Multiple tickets must be yes or no."

            raffle["multiple_tickets"] = multiple_tickets
            changes.append(f"Multiple tickets: **{'Yes' if multiple_tickets else 'No'}**")

        if winner_takes_all_text:
            winner_takes_all = self.parse_yes_no(winner_takes_all_text)

            if winner_takes_all is None:
                return "❌ Winner takes all must be yes or no."

            raffle["winner_takes_all"] = winner_takes_all
            changes.append(f"Winner takes all: **{'Yes' if winner_takes_all else 'No'}**")

        if not changes:
            return "ℹ️ No changes were entered."

        raffle["updated_at"] = self.now_iso()
        raffle["updated_from"] = "vr_bot_admin_panel"
        self.save_raffle(raffle)

        return "✅ **Raffle updated**\n\n" + "\n".join(f"• {line}" for line in changes)

    async def modify_raffle_tickets_from_panel(
        self,
        mode: str,
        discord_user_id_text: str,
        ticket_count_text: str,
        note: str = "",
    ) -> str:
        raffle = self.load_raffle()

        if not raffle.get("active"):
            return "ℹ️ No active raffle."

        discord_user_id = self.safe_int(discord_user_id_text, -1)

        if discord_user_id <= 0:
            return "❌ Discord user ID must be a valid number."

        delta = self.safe_int(ticket_count_text, -1)

        if delta <= 0:
            return "❌ Ticket count must be a positive number."

        linked_member = self.find_guild_member_by_discord_id(discord_user_id)

        if linked_member is None:
            return (
                "❌ That Discord user is not linked to a GW2 guild account.\n\n"
                "Tickets are tied to linked guild members only."
            )

        tickets = self.load_tickets()
        key = str(discord_user_id)

        ticket_price = self.safe_int(raffle.get("ticket_price", 0))
        current_entry = tickets.get(key, {})

        current_count = self.safe_int(current_entry.get("ticket_count", 0))
        current_total = self.safe_int(current_entry.get("raffle_donation_total", 0))

        if mode == "add":
            if not raffle.get("multiple_tickets") and current_count > 0:
                return "❌ This raffle does not allow multiple tickets and this user already has a ticket."

            if not raffle.get("multiple_tickets") and delta > 1:
                return "❌ This raffle does not allow multiple tickets. Add only 1 ticket."

            new_count = current_count + delta
            new_total = current_total + (ticket_price * delta)
            action_text = "added"

        elif mode == "remove":
            if current_count <= 0:
                return "❌ This user has no raffle tickets to remove."

            remove_count = min(delta, current_count)
            new_count = current_count - remove_count
            new_total = max(0, current_total - (ticket_price * remove_count))
            action_text = "removed"
            delta = remove_count

        else:
            return "❌ Unknown ticket modification mode."

        if new_count <= 0:
            tickets.pop(key, None)
        else:
            tickets[key] = {
                "gw2_account_name": linked_member.get("name", "Unknown"),
                "raffle_donation_total": new_total,
                "ticket_count": new_count,
                "last_updated_at": self.now_iso(),
                "last_updated_from": "vr_bot_admin_panel",
            }

            if note:
                tickets[key]["admin_note"] = note

        self.save_tickets(tickets)

        discord_name = await self.format_discord_user(discord_user_id, include_id=False)

        return (
            f"✅ **Raffle tickets {action_text}**\n\n"
            f"Raffle: **{raffle.get('title', 'Unknown raffle')}**\n"
            f"GW2 account: **{linked_member.get('name', 'Unknown')}**\n"
            f"Discord: **{discord_name}**\n"
            f"Changed by: **{delta} ticket(s)**\n"
            f"Current tickets: **{new_count}**\n"
            f"Raffle donation total: **{self.format_gold(new_total)}**"
        )

    # ========================================================
    # GUILD LINK USER ACTIONS
    # ========================================================
    async def self_link_account_from_panel(self, user: discord.abc.User, account_name: str) -> str:
        account_name = str(account_name or "").strip()

        if not account_name:
            return "❌ Please enter your GW2 account name, for example `Account.1234`."

        data = self.load_guild_data()

        if not data:
            return "❌ No guild data is currently loaded. Ask an officer to run a guild sync first."

        existing_index = self.find_guild_member_index_by_discord_id(data, user.id)

        if existing_index is not None:
            return (
                "✅ Your Discord account is already linked.\n\n"
                f"GW2 account: **{data[existing_index].get('name', 'Unknown')}**"
            )

        account_index = self.find_guild_member_index_by_account_name(data, account_name)

        if account_index is None:
            suggestions = self.get_account_name_suggestions(account_name)

            if suggestions:
                suggestion_text = "\n".join(f"• `{name}`" for name in suggestions)
                return (
                    "❌ I could not find that GW2 account in the synced guild data.\n\n"
                    "Closest matches:\n"
                    f"{suggestion_text}\n\n"
                    "Try again using the exact account name including the numbers after the dot."
                )

            return (
                "❌ I could not find that GW2 account in the synced guild data.\n\n"
                "Make sure you entered the account name exactly, including the numbers after the dot."
            )

        linked_to = data[account_index].get("discord_user_id")

        if linked_to is not None and int(linked_to) != int(user.id):
            return (
                "❌ That GW2 account is already linked to another Discord user.\n\n"
                "Ask an officer/admin if this link needs to be corrected."
            )

        data[account_index]["discord_user_id"] = int(user.id)
        data[account_index]["linked_at"] = self.now_iso()
        data[account_index]["linked_from"] = "vr_bot_user_panel"

        self.save_guild_data(data)

        # Keep active raffle tickets aligned if this user already had a ticket entry from older data.
        tickets = self.load_tickets()
        ticket_entry = tickets.get(str(user.id))

        if isinstance(ticket_entry, dict):
            ticket_entry["gw2_account_name"] = data[account_index].get("name", account_name)
            ticket_entry["last_link_reconciled_at"] = self.now_iso()
            tickets[str(user.id)] = ticket_entry
            self.save_tickets(tickets)

        display_name = user.display_name if hasattr(user, "display_name") else user.name

        return (
            "✅ **Guild account linked**\n\n"
            f"Discord: **{display_name}**\n"
            f"GW2 account: 🟢 **{data[account_index].get('name', account_name)}**\n"
            f"Rank: **{data[account_index].get('rank', 'Unknown')}**"
        )

    # ========================================================
    # GUILD LINK ADMIN ACTIONS
    # ========================================================
    def extract_discord_user_id(self, text: str) -> Optional[int]:
        cleaned = str(text or "").strip()

        if not cleaned:
            return None

        cleaned = cleaned.replace("<@!", "").replace("<@", "").replace(">", "")

        try:
            value = int(cleaned)
        except Exception:
            return None

        if value <= 0:
            return None

        return value

    def normalize_lookup_text(self, text: str) -> str:
        return str(text or "").strip().lower()

    def get_account_match_indices(self, data: list, account_text: str) -> list:
        query = self.normalize_lookup_text(account_text)

        if not query:
            return []

        exact = [
            index for index, member in enumerate(data)
            if self.normalize_lookup_text(member.get("name", "")) == query
        ]

        if exact:
            return exact

        prefix = [
            index for index, member in enumerate(data)
            if self.normalize_lookup_text(member.get("name", "")).startswith(query)
        ]

        if prefix:
            return prefix

        contains = [
            index for index, member in enumerate(data)
            if query in self.normalize_lookup_text(member.get("name", ""))
        ]

        if contains:
            return contains

        names = [str(member.get("name", "")).strip() for member in data]
        close_names = difflib.get_close_matches(str(account_text or "").strip(), names, n=8, cutoff=0.45)

        return [
            index for index, member in enumerate(data)
            if str(member.get("name", "")).strip() in close_names
        ]

    def build_account_match_message(self, indices: list, data: list, intro: str) -> str:
        lines = []

        for index in indices[:10]:
            member = data[index]
            linked = "🟢" if member.get("discord_user_id") is not None else "🔴"
            lines.append(f"• {linked} `{member.get('name', 'Unknown')}` — {member.get('rank', 'Unknown')}")

        extra = ""

        if len(indices) > 10:
            extra = f"\n…and {len(indices) - 10} more matches."

        return (
            f"{intro}\n\n"
            "Matched GW2 accounts:\n"
            f"{chr(10).join(lines)}"
            f"{extra}\n\n"
            "Try again with the exact account name, or type a more specific partial name."
        )

    def resolve_guild_account_index_from_text(self, data: list, account_text: str):
        matches = self.get_account_match_indices(data, account_text)

        if not matches:
            suggestions = self.get_account_name_suggestions(account_text)

            if suggestions:
                suggestion_text = "\n".join(f"• `{name}`" for name in suggestions)
                return None, (
                    "❌ That GW2 account was not found in the synced guild data.\n\n"
                    "Closest matches:\n"
                    f"{suggestion_text}"
                )

            return None, "❌ That GW2 account was not found in the synced guild data."

        if len(matches) > 1:
            return None, self.build_account_match_message(
                matches,
                data,
                "⚠️ Your GW2 account search matched more than one account.",
            )

        return matches[0], None

    async def get_discord_user_match_candidates(self, text: str) -> list:
        query = self.normalize_lookup_text(text).replace("@", "")

        if not query:
            return []

        candidates = []
        seen = set()

        for guild in self.bot.guilds:
            for member in guild.members:
                names = [
                    str(member.display_name or ""),
                    str(member.name or ""),
                    str(getattr(member, "global_name", "") or ""),
                ]

                lowered = [self.normalize_lookup_text(name) for name in names if name]

                if not lowered:
                    continue

                score = None

                if any(name == query for name in lowered):
                    score = 0
                elif any(name.startswith(query) for name in lowered):
                    score = 1
                elif any(query in name for name in lowered):
                    score = 2

                if score is None:
                    continue

                if member.id in seen:
                    continue

                seen.add(member.id)
                candidates.append((score, member.id, member.display_name, member))

        candidates.sort(key=lambda item: (item[0], item[2].lower()))
        return candidates

    async def resolve_discord_user_display_from_text(self, text: str, include_id: bool = True):
        discord_user_id = self.extract_discord_user_id(text)

        if discord_user_id is not None:
            display = await self.format_discord_user(discord_user_id, include_id=include_id)
            return discord_user_id, display

        candidates = await self.get_discord_user_match_candidates(text)

        if not candidates:
            return None, "❌ Discord user must be a valid user ID, @mention, username, or nickname."

        if len(candidates) > 1:
            lines = []

            for _, user_id, display_name, member in candidates[:10]:
                lines.append(f"• `{display_name}` — `{user_id}`")

            extra = ""

            if len(candidates) > 10:
                extra = f"\n…and {len(candidates) - 10} more matches."

            return None, (
                "⚠️ That Discord lookup matched more than one member.\n\n"
                "Matched Discord members:\n"
                f"{chr(10).join(lines)}"
                f"{extra}\n\n"
                "Try again with the exact nickname, @mention, or Discord user ID."
            )

        _, user_id, _, _member = candidates[0]
        display = await self.format_discord_user(user_id, include_id=include_id)
        return user_id, display

    async def find_guild_member_index_by_discord_name_query(self, data: list, query: str):
        candidates = await self.get_discord_user_match_candidates(query)

        if not candidates:
            return None, None

        linked_matches = []

        for _score, user_id, display_name, _member in candidates:
            index = self.find_guild_member_index_by_discord_id(data, user_id)

            if index is not None:
                linked_matches.append((index, user_id, display_name))

        if not linked_matches:
            return None, (
                "❌ Discord member was found, but they are not linked to a tracked GW2 guild account."
            )

        unique_indices = []
        seen = set()

        for index, user_id, display_name in linked_matches:
            if index in seen:
                continue

            seen.add(index)
            unique_indices.append((index, user_id, display_name))

        if len(unique_indices) > 1:
            lines = []

            for index, user_id, display_name in unique_indices[:10]:
                member = data[index]
                lines.append(f"• `{display_name}` — `{member.get('name', 'Unknown')}` — `{user_id}`")

            extra = ""

            if len(unique_indices) > 10:
                extra = f"\n…and {len(unique_indices) - 10} more matches."

            return None, (
                "⚠️ That nickname matched more than one linked member.\n\n"
                "Matches:\n"
                f"{chr(10).join(lines)}"
                f"{extra}\n\n"
                "Try again with the exact nickname, @mention, Discord ID, or GW2 account name."
            )

        return unique_indices[0][0], None

    async def find_guild_member_index_by_query(self, data: list, query: str):
        query = str(query or "").strip()

        if not query:
            return None, None

        account_matches = self.get_account_match_indices(data, query)

        if len(account_matches) == 1:
            return account_matches[0], None

        if len(account_matches) > 1:
            return None, self.build_account_match_message(
                account_matches,
                data,
                "⚠️ Your lookup matched more than one GW2 account.",
            )

        discord_user_id = self.extract_discord_user_id(query)

        if discord_user_id is not None:
            return self.find_guild_member_index_by_discord_id(data, discord_user_id), None

        return await self.find_guild_member_index_by_discord_name_query(data, query)

    async def send_guild_link_update_log(self, message: str):
        guild_link_cog = self.bot.get_cog("GuildLink")

        if guild_link_cog is not None and hasattr(guild_link_cog, "send_link_update"):
            try:
                result = guild_link_cog.send_link_update(message)

                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                pass

    async def reconcile_linked_raffle_entry(self, member: dict, old_discord_id: Optional[int], new_discord_id: Optional[int]):
        raffle = self.load_raffle()

        if not raffle.get("active"):
            return {"updated": False}

        tickets = self.load_tickets()
        account_name = member.get("name", "Unknown")
        changed = False

        if old_discord_id is not None and new_discord_id is not None and int(old_discord_id) != int(new_discord_id):
            old_key = str(old_discord_id)
            new_key = str(new_discord_id)

            if old_key in tickets and new_key not in tickets:
                tickets[new_key] = tickets.pop(old_key)
                changed = True
            elif old_key in tickets and new_key in tickets:
                tickets.pop(old_key, None)
                changed = True

        if new_discord_id is not None:
            key = str(new_discord_id)

            if isinstance(tickets.get(key), dict):
                tickets[key]["gw2_account_name"] = account_name
                tickets[key]["last_link_reconciled_at"] = self.now_iso()
                changed = True

        if changed:
            self.save_tickets(tickets)

        return {"updated": changed}

    def build_guild_link_summary_message(self) -> str:
        stats = self.get_guild_link_stats()

        return (
            "🔗 **Guild Link Summary**\n\n"
            f"Guild members tracked: **{stats['total']}**\n"
            f"Linked: 🟢 **{stats['linked']}**\n"
            f"Unlinked: 🔴 **{stats['unlinked']}**"
        )

    async def guild_link_status_lookup_from_panel(self, query: str) -> str:
        data = self.load_guild_data()

        if not data:
            return "❌ No guild data is currently loaded. Run a guild sync first."

        index, lookup_error = await self.find_guild_member_index_by_query(data, query)

        if index is None:
            if lookup_error:
                return lookup_error

            suggestions = self.get_account_name_suggestions(query)

            if suggestions:
                suggestion_text = "\n".join(f"• `{name}`" for name in suggestions)
                return (
                    "❌ No guild member matched that lookup.\n\n"
                    "Closest GW2 account matches:\n"
                    f"{suggestion_text}"
                )

            return "❌ No guild member matched that lookup."

        member = data[index]
        discord_user_id = member.get("discord_user_id")

        if discord_user_id is None:
            discord_text = "🔴 Not linked"
        else:
            discord_text = "🟢 " + await self.format_discord_user(int(discord_user_id), include_id=True)

        return (
            "🔎 **Guild Link Status**\n\n"
            f"GW2 account: **{member.get('name', 'Unknown')}**\n"
            f"Rank: **{member.get('rank', 'Unknown')}**\n"
            f"Discord: {discord_text}\n"
            f"Weekly donated: **{self.format_gold(self.safe_int(member.get('weekly_gold', 0)))}**\n"
            f"Bot-tracked lifetime donated: **{self.format_gold(self.safe_int(member.get('lifetime_gold', 0)))}**"
        )

    async def force_link_account_from_panel(self, admin_user: discord.abc.User, account_name: str, discord_user_text: str) -> str:
        account_name = str(account_name or "").strip()

        if not account_name:
            return "❌ GW2 account name is required."

        data = self.load_guild_data()

        if not data:
            return "❌ No guild data is currently loaded. Run a guild sync first."

        account_index, account_error = self.resolve_guild_account_index_from_text(data, account_name)

        if account_index is None:
            return account_error

        new_discord_id, resolved_display = await self.resolve_discord_user_display_from_text(discord_user_text, include_id=True)

        if new_discord_id is None:
            return resolved_display

        member = data[account_index]
        old_discord_id = member.get("discord_user_id")
        old_discord_display = None

        if old_discord_id is not None:
            old_discord_display = await self.format_discord_user(int(old_discord_id), include_id=True)

        previous_account_name = None
        previous_index = self.find_guild_member_index_by_discord_id(data, new_discord_id)

        if previous_index is not None and previous_index != account_index:
            previous_account_name = data[previous_index].get("name", "Unknown")
            data[previous_index]["discord_user_id"] = None
            data[previous_index]["unlinked_at"] = self.now_iso()
            data[previous_index]["unlinked_from"] = "vr_bot_admin_panel_force_link_move"

        member["discord_user_id"] = int(new_discord_id)
        member["linked_at"] = self.now_iso()
        member["linked_from"] = "vr_bot_admin_panel_force_link"

        self.save_guild_data(data)

        raffle_result = await self.reconcile_linked_raffle_entry(
            member=member,
            old_discord_id=int(old_discord_id) if old_discord_id is not None else None,
            new_discord_id=int(new_discord_id),
        )

        if old_discord_id is None:
            title = "✅ **Guild link force-created**"
        else:
            title = "✅ **Guild link force-updated**"

        response = (
            f"{title}\n\n"
            f"GW2 account: **{member.get('name', 'Unknown')}**\n"
            f"Linked: 🟢 {resolved_display}"
        )

        if old_discord_display is not None and int(old_discord_id) != int(new_discord_id):
            response += f"\nPrevious Discord: {old_discord_display}"

        if previous_account_name is not None:
            response += (
                f"\n\n⚠️ Discord user was previously linked to "
                f"**{previous_account_name}** and has been moved."
            )

        if raffle_result.get("updated"):
            response += "\n\n🎟️ Active raffle ticket entry was reconciled."

        admin_name = admin_user.display_name if hasattr(admin_user, "display_name") else admin_user.name
        log_message = (
            "🛠️ **Guild link force-updated from panel**\n"
            f"Admin: **{admin_name}**\n"
            f"GW2 account: **{member.get('name', 'Unknown')}**\n"
            f"Linked: 🟢 {resolved_display}"
        )

        if old_discord_display is not None and int(old_discord_id) != int(new_discord_id):
            log_message += f"\nPrevious Discord: {old_discord_display}"

        if previous_account_name is not None:
            log_message += f"\nMoved from previous account: **{previous_account_name}**"

        await self.send_guild_link_update_log(log_message)

        return response

    async def unlink_account_from_panel(self, admin_user: discord.abc.User, query: str) -> str:
        data = self.load_guild_data()

        if not data:
            return "❌ No guild data is currently loaded. Run a guild sync first."

        index, lookup_error = await self.find_guild_member_index_by_query(data, query)

        if index is None:
            if lookup_error:
                return lookup_error

            suggestions = self.get_account_name_suggestions(query)

            if suggestions:
                suggestion_text = "\n".join(f"• `{name}`" for name in suggestions)
                return (
                    "❌ No guild member matched that lookup.\n\n"
                    "Closest GW2 account matches:\n"
                    f"{suggestion_text}"
                )

            return "❌ No guild member matched that lookup."

        member = data[index]
        old_discord_id = member.get("discord_user_id")

        if old_discord_id is None:
            return (
                f"ℹ️ **{member.get('name', 'Unknown')}** is already unlinked.\n"
                "Linked: 🔴 No"
            )

        old_discord_display = await self.format_discord_user(int(old_discord_id), include_id=True)

        member["discord_user_id"] = None
        member["unlinked_at"] = self.now_iso()
        member["unlinked_from"] = "vr_bot_admin_panel"

        self.save_guild_data(data)

        admin_name = admin_user.display_name if hasattr(admin_user, "display_name") else admin_user.name
        await self.send_guild_link_update_log(
            "🔗 **Guild account unlinked from panel**\n"
            f"Admin: **{admin_name}**\n"
            f"GW2 account: **{member.get('name', 'Unknown')}**\n"
            f"Previous Discord: {old_discord_display}"
        )

        return (
            "✅ **Guild account unlinked**\n\n"
            f"GW2 account: **{member.get('name', 'Unknown')}**\n"
            f"Previous Discord: {old_discord_display}\n"
            "Linked: 🔴 No"
        )

    # ========================================================
    # GUILD UPGRADE PANEL ACTIONS
    # ========================================================
    async def run_guild_upgrade_search_from_panel(self, search: str, show_all_text: str):
        guild_upgrade_cog = self.bot.get_cog("GuildUpgrades")

        if guild_upgrade_cog is None:
            return "❌ GuildUpgrades cog is not loaded."

        show_all = self.parse_yes_no(show_all_text, default=True)

        if show_all is None:
            return "❌ Show all must be yes or no."

        try:
            if hasattr(guild_upgrade_cog, "build_upgrade_list_output"):
                return await guild_upgrade_cog.build_upgrade_list_output(
                    search=search or None,
                    show_all=show_all,
                )

            if hasattr(guild_upgrade_cog, "build_upgrade_list_embeds"):
                return await guild_upgrade_cog.build_upgrade_list_embeds(
                    search=search or None,
                    show_all=show_all,
                )

            if hasattr(guild_upgrade_cog, "list_upgrades_for_panel"):
                return await guild_upgrade_cog.list_upgrades_for_panel(
                    search=search or None,
                    show_all=show_all,
                )

            return (
                "⚠️ GuildUpgrades does not expose a panel list/search method yet.\n\n"
                "Fallback command:\n"
                f"`/guild_upgrade list search:{search or ''} show_all:{str(show_all).lower()}`"
            )

        except Exception as error:
            return f"❌ Guild upgrade search failed:\n```text\n{error}\n```"

    async def run_guild_upgrade_start_from_panel(self, number_text: str):
        guild_upgrade_cog = self.bot.get_cog("GuildUpgrades")

        if guild_upgrade_cog is None:
            return "❌ GuildUpgrades cog is not loaded."

        number = self.safe_int(number_text, -1)

        if number <= 0:
            return "❌ Upgrade number must be a positive number."

        try:
            if hasattr(guild_upgrade_cog, "start_upgrade_from_panel"):
                return await guild_upgrade_cog.start_upgrade_from_panel(number)

            if hasattr(guild_upgrade_cog, "start_upgrade_by_number"):
                return await guild_upgrade_cog.start_upgrade_by_number(number)

            if hasattr(guild_upgrade_cog, "panel_start_upgrade"):
                return await guild_upgrade_cog.panel_start_upgrade(number)

            return (
                "⚠️ GuildUpgrades does not expose a panel start method yet.\n\n"
                "Fallback command:\n"
                f"`/guild_upgrade start number:{number}`"
            )

        except Exception as error:
            return f"❌ Guild upgrade start failed:\n```text\n{error}\n```"

    async def run_guild_upgrade_confirm_from_panel(self, number_text: str):
        guild_upgrade_cog = self.bot.get_cog("GuildUpgrades")

        if guild_upgrade_cog is None:
            return "❌ GuildUpgrades cog is not loaded."

        number = self.safe_int(number_text, -1)

        if number <= 0:
            return "❌ Upgrade number must be a positive number."

        try:
            if hasattr(guild_upgrade_cog, "confirm_upgrade_from_panel"):
                return await guild_upgrade_cog.confirm_upgrade_from_panel(number)

            if hasattr(guild_upgrade_cog, "confirm_upgrade_by_number"):
                return await guild_upgrade_cog.confirm_upgrade_by_number(number)

            if hasattr(guild_upgrade_cog, "panel_confirm_upgrade"):
                return await guild_upgrade_cog.panel_confirm_upgrade(number)

            return (
                "⚠️ GuildUpgrades does not expose a panel confirm method yet.\n\n"
                "Fallback command:\n"
                f"`/guild_upgrade confirm number:{number}`"
            )

        except Exception as error:
            return f"❌ Guild upgrade confirm failed:\n```text\n{error}\n```"

    async def run_guild_upgrade_set_channel_from_panel(self, channel_id_text: str):
        channel_id = self.safe_int(channel_id_text, -1)

        if channel_id <= 0:
            return "❌ Channel ID must be a valid number."

        channel = self.bot.get_channel(channel_id)

        if channel is None:
            return "❌ I could not find that channel. Make sure the ID is correct and the bot can see it."

        guild_upgrade_cog = self.bot.get_cog("GuildUpgrades")

        try:
            if guild_upgrade_cog is not None:
                if hasattr(guild_upgrade_cog, "set_upgrade_channel_from_panel"):
                    return await guild_upgrade_cog.set_upgrade_channel_from_panel(channel_id)

                if hasattr(guild_upgrade_cog, "set_channel"):
                    result = guild_upgrade_cog.set_channel(channel_id)

                    if asyncio.iscoroutine(result):
                        result = await result

                    return result or f"✅ Guild upgrade channel set to {channel.mention}."

            state = self.load_guild_upgrade_state()
            state["channel_id"] = channel_id
            state["updated_at"] = self.now_iso()
            state["updated_from"] = "vr_bot_admin_panel"
            self.save_guild_upgrade_state(state)

            return f"✅ Guild upgrade channel saved as {channel.mention}."

        except Exception as error:
            return f"❌ Failed to set guild upgrade channel:\n```text\n{error}\n```"

    # ========================================================
    # DONATION PANEL ACTIONS
    # ========================================================
    async def set_lifetime_donation_from_panel(self, discord_user_id_text: str, lifetime_gold_text: str):
        discord_user_id = self.safe_int(discord_user_id_text, -1)

        if discord_user_id <= 0:
            return "❌ Discord user ID must be a valid number."

        lifetime_coins = self.parse_gold_to_coins(lifetime_gold_text)

        if lifetime_coins is None:
            return "❌ Lifetime gold must be a valid non-negative gold amount."

        data = self.load_guild_data()
        index = self.find_guild_member_index_by_discord_id(data, discord_user_id)

        if index is None:
            return "❌ That Discord user is not linked to a tracked GW2 guild account."

        old_value = self.safe_int(data[index].get("lifetime_gold", 0))
        data[index]["lifetime_gold"] = lifetime_coins
        data[index]["lifetime_gold_updated_at"] = self.now_iso()
        data[index]["lifetime_gold_updated_from"] = "vr_bot_admin_panel"

        self.save_guild_data(data)

        discord_name = await self.format_discord_user(discord_user_id, include_id=False)

        return (
            "✅ **Lifetime donation set**\n\n"
            f"GW2 account: **{data[index].get('name', 'Unknown')}**\n"
            f"Discord: **{discord_name}**\n"
            f"Old lifetime: **{self.format_gold(old_value)}**\n"
            f"New lifetime: **{self.format_gold(lifetime_coins)}**"
        )

    async def adjust_lifetime_donation_from_panel(self, discord_user_id_text: str, adjustment_gold_text: str):
        discord_user_id = self.safe_int(discord_user_id_text, -1)

        if discord_user_id <= 0:
            return "❌ Discord user ID must be a valid number."

        adjustment_coins = self.parse_gold_to_coins(adjustment_gold_text, allow_negative=True)

        if adjustment_coins is None:
            return "❌ Adjustment must be a valid gold amount, for example `25` or `-10`."

        data = self.load_guild_data()
        index = self.find_guild_member_index_by_discord_id(data, discord_user_id)

        if index is None:
            return "❌ That Discord user is not linked to a tracked GW2 guild account."

        old_value = self.safe_int(data[index].get("lifetime_gold", 0))
        new_value = max(0, old_value + adjustment_coins)

        data[index]["lifetime_gold"] = new_value
        data[index]["lifetime_gold_updated_at"] = self.now_iso()
        data[index]["lifetime_gold_updated_from"] = "vr_bot_admin_panel"

        self.save_guild_data(data)

        discord_name = await self.format_discord_user(discord_user_id, include_id=False)

        return (
            "✅ **Lifetime donation adjusted**\n\n"
            f"GW2 account: **{data[index].get('name', 'Unknown')}**\n"
            f"Discord: **{discord_name}**\n"
            f"Adjustment: **{self.format_gold(adjustment_coins)}**\n"
            f"Old lifetime: **{self.format_gold(old_value)}**\n"
            f"New lifetime: **{self.format_gold(new_value)}**"
        )

    async def reset_weekly_donations_from_panel(self):
        data = self.load_guild_data()

        if not data:
            return "ℹ️ No guild data found."

        affected = 0
        total_reset = 0

        for member in data:
            weekly = self.safe_int(member.get("weekly_gold", 0))

            if weekly > 0:
                affected += 1
                total_reset += weekly

            member["weekly_gold"] = 0
            member["weekly_gold_reset_at"] = self.now_iso()
            member["weekly_gold_reset_from"] = "vr_bot_admin_panel"

        self.save_guild_data(data)

        return (
            "✅ **Weekly donations reset**\n\n"
            f"Members affected: **{affected}**\n"
            f"Total weekly gold cleared: **{self.format_gold(total_reset)}**\n\n"
            "Lifetime totals were not changed."
        )

    # ========================================================
    # USER PANEL EMBEDS
    # ========================================================
    def build_user_panel_embed(self, user: discord.abc.User) -> discord.Embed:
        raffle = self.load_raffle()
        upgrade_state = self.load_guild_upgrade_state()
        member = self.get_linked_member_for_user(user.id)

        embed = discord.Embed(
            title="VR Bot",
            description="Useful guild tools and quick checks.",
            color=0x5865F2,
            timestamp=datetime.now(timezone.utc),
        )

        embed.add_field(
            name="Available",
            value=(
                "🎟️ Raffle Status\n"
                "🎫 My Tickets\n"
                "🏗️ Guild Upgrade\n"
                "🔗 Link Status\n"
                "📝 Link Account\n"
                "💰 My Donations\n"
                "👥 Guild Info"
            ),
            inline=False,
        )

        embed.add_field(
            name="Current state",
            value=(
                f"Raffle: **{'Active ✅' if raffle.get('active') else 'Inactive'}**\n"
                f"Guild upgrade: **{'Active ✅' if upgrade_state.get('active') else 'Inactive'}**\n"
                f"Your link: **{'Linked 🟢' if member else 'Unlinked 🔴'}**"
            ),
            inline=False,
        )

        embed.set_footer(
            text=f"Opened by {user.display_name if hasattr(user, 'display_name') else user.name}"
        )

        return embed

    def build_public_raffle_status_embed(self) -> discord.Embed:
        return self.build_raffle_status_embed(public=True)

    async def build_my_tickets_embed(self, user: discord.abc.User) -> discord.Embed:
        raffle = self.load_raffle()

        embed = discord.Embed(
            title="🎫 My Raffle Tickets",
            color=0xE67E22,
            timestamp=datetime.now(timezone.utc),
        )

        if not raffle.get("active"):
            embed.description = "ℹ️ No active raffle."
            return embed

        linked_member = self.get_linked_member_for_user(user.id)
        display_name = user.display_name if hasattr(user, "display_name") else user.name

        if linked_member is None:
            embed.description = (
                f"Discord: **{display_name}**\n"
                "Linked: 🔴 No\n\n"
                "Your Discord account is not linked to a guild account."
            )
            return embed

        tickets = self.load_tickets()
        entry = tickets.get(str(user.id))

        if entry is None:
            embed.description = (
                f"Raffle: **{raffle.get('title', 'Unknown raffle')}**\n"
                f"GW2 account: **{linked_member.get('name', 'Unknown')}**\n"
                "Tickets: **0**\n"
                "Raffle donation total: **0g 0s 0c**"
            )
            return embed

        embed.description = (
            f"Raffle: **{raffle.get('title', 'Unknown raffle')}**\n"
            f"GW2 account: **{entry.get('gw2_account_name', 'Unknown')}**\n"
            f"Tickets: **{self.safe_int(entry.get('ticket_count', 0))}**\n"
            f"Raffle donation total: **{self.format_gold(self.safe_int(entry.get('raffle_donation_total', 0)))}**"
        )

        return embed

    async def build_user_guild_upgrade_output(self) -> List[discord.Embed]:
        guild_upgrade_cog = self.bot.get_cog("GuildUpgrades")
        state = self.load_guild_upgrade_state()

        if not state.get("active"):
            description = "ℹ️ No active guild upgrade tracker."

            if state.get("completed"):
                description = f"✅ Last tracked upgrade was completed:\n\n**{state.get('upgrade_name', 'Unknown')}**"

            return [
                discord.Embed(
                    title="🏗️ Guild Upgrade",
                    description=description,
                    color=0x95A5A6,
                    timestamp=datetime.now(timezone.utc),
                )
            ]

        if guild_upgrade_cog is not None and hasattr(guild_upgrade_cog, "build_upgrade_embed"):
            return [await guild_upgrade_cog.build_upgrade_embed(state, public=True)]

        return [
            discord.Embed(
                title="🏗️ Guild Upgrade",
                description=f"Active tracker: **{state.get('upgrade_name', 'Unknown')}**",
                color=0xC79C38,
                timestamp=datetime.now(timezone.utc),
            )
        ]

    async def build_link_status_embed(self, user: discord.abc.User) -> discord.Embed:
        member = self.get_linked_member_for_user(user.id)

        embed = discord.Embed(
            title="🔗 Guild Link",
            color=0x5865F2,
            timestamp=datetime.now(timezone.utc),
        )

        if member is not None:
            embed.description = (
                "Your Discord account is linked.\n\n"
                f"GW2 account: 🟢 **{member.get('name', 'Unknown')}**\n"
                f"Rank: **{member.get('rank', 'Unknown')}**"
            )
            return embed

        embed.description = (
            "Your Discord account is not linked to a GW2 guild account.\n\n"
            "Use `/vr-bot → Link Account` and enter your GW2 account name exactly, "
            "including the numbers after the dot."
        )

        return embed

    async def build_my_donations_embed(self, user: discord.abc.User) -> discord.Embed:
        member = self.get_linked_member_for_user(user.id)
        raffle = self.load_raffle()
        tickets = self.load_tickets()

        embed = discord.Embed(
            title="💰 My Donations",
            color=0xFFD700,
            timestamp=datetime.now(timezone.utc),
        )

        if member is None:
            embed.description = (
                "Your Discord account is not linked to a GW2 guild account.\n\n"
                "Donation totals can only be shown after your account is linked."
            )
            return embed

        embed.description = (
            f"GW2 account: 🟢 **{member.get('name', 'Unknown')}**\n"
            f"Weekly donated: **{self.format_gold(self.safe_int(member.get('weekly_gold', 0)))}**\n"
            f"Bot-tracked lifetime donated: **{self.format_gold(self.safe_int(member.get('lifetime_gold', 0)))}**"
        )

        if raffle.get("active"):
            entry = tickets.get(str(user.id))

            if entry is None:
                raffle_value = (
                    f"Raffle: **{raffle.get('title', 'Unknown raffle')}**\n"
                    "Raffle donation total: **0g 0s 0c**\n"
                    "Tickets: **0**"
                )
            else:
                raffle_value = (
                    f"Raffle: **{raffle.get('title', 'Unknown raffle')}**\n"
                    f"Raffle donation total: **{self.format_gold(self.safe_int(entry.get('raffle_donation_total', 0)))}**\n"
                    f"Tickets: **{self.safe_int(entry.get('ticket_count', 0))}**"
                )

            embed.add_field(name="Current raffle", value=raffle_value, inline=False)

        embed.set_footer(text="Lifetime total is bot-tracked from recorded deposits.")
        return embed

    def build_guild_info_embed(self) -> discord.Embed:
        raffle = self.load_raffle()
        tickets = self.load_tickets()
        upgrade_state = self.load_guild_upgrade_state()
        link_stats = self.get_guild_link_stats()
        guild_data = self.load_guild_data()

        total_weekly_gold = sum(self.safe_int(member.get("weekly_gold", 0)) for member in guild_data)
        total_lifetime_gold = sum(self.safe_int(member.get("lifetime_gold", 0)) for member in guild_data)

        embed = discord.Embed(
            title="👥 Guild Info",
            color=0x5865F2,
            timestamp=datetime.now(timezone.utc),
        )

        embed.add_field(
            name="Members",
            value=(
                f"Tracked members: **{link_stats['total']}**\n"
                f"Linked: 🟢 **{link_stats['linked']}**\n"
                f"Unlinked: 🔴 **{link_stats['unlinked']}**"
            ),
            inline=False,
        )

        embed.add_field(
            name="Donations",
            value=(
                f"Weekly total: **{self.format_gold(total_weekly_gold)}**\n"
                f"Bot-tracked lifetime total: **{self.format_gold(total_lifetime_gold)}**"
            ),
            inline=False,
        )

        if raffle.get("active"):
            embed.add_field(
                name="Raffle",
                value=(
                    f"Active: ✅ **{raffle.get('title', 'Unknown raffle')}**\n"
                    f"Ticket holders: **{self.get_ticket_holders_count(tickets)}**\n"
                    f"Tickets: **{self.get_total_tickets(tickets)}**"
                ),
                inline=False,
            )
        else:
            embed.add_field(name="Raffle", value="Inactive", inline=False)

        if upgrade_state.get("active"):
            upgrade_value = f"Active: ✅ **{upgrade_state.get('upgrade_name', 'Unknown')}**"
        elif upgrade_state.get("completed"):
            upgrade_value = f"Last completed: **{upgrade_state.get('upgrade_name', 'Unknown')}**"
        else:
            upgrade_value = "Inactive"

        embed.add_field(name="Guild upgrade", value=upgrade_value, inline=False)
        return embed

    # ========================================================
    # ADMIN PANEL EMBEDS / TEXT
    # ========================================================
    def build_admin_panel_embed(self, user: discord.abc.User) -> discord.Embed:
        loaded_count = len(getattr(self.bot, "loaded_extensions", []))
        failed_count = len(getattr(self.bot, "failed_extensions", []))

        embed = discord.Embed(
            title="VR Bot Admin",
            description="Private admin hub for bot and guild tools.",
            color=0x2B2D31,
            timestamp=datetime.now(timezone.utc),
        )

        embed.add_field(
            name="Sections",
            value=(
                "🤖 Bot Controls\n"
                "🔄 Guild Sync\n"
                "🔗 Guild Link\n"
                "🎟️ Raffle\n"
                "🏗️ Guild Upgrades\n"
                "💰 Donations\n"
                "🔎 Role Tools\n"
                "🧹 Guild Bank"
            ),
            inline=False,
        )

        embed.add_field(
            name="Bot state",
            value=f"Loaded modules: ✅ **{loaded_count}**\nFailed modules: ❌ **{failed_count}**",
            inline=False,
        )

        embed.set_footer(
            text=f"Opened by {user.display_name if hasattr(user, 'display_name') else user.name}"
        )

        return embed

    def build_bot_controls_embed(self, user: discord.abc.User) -> discord.Embed:
        embed = discord.Embed(
            title="🤖 Bot Controls",
            description="Private operational controls.",
            color=0x2B2D31,
            timestamp=datetime.now(timezone.utc),
        )

        embed.add_field(
            name="Actions",
            value="🏠 Main Menu\n🤖 Status\n🔁 Sync Commands\n♻️ Restart Bot\n⚙️ Sync Startup Info",
            inline=False,
        )

        embed.set_footer(
            text=f"Opened by {user.display_name if hasattr(user, 'display_name') else user.name}"
        )

        return embed

    def build_bot_status_message(self) -> str:
        admin_panel_cog = self.bot.get_cog("AdminPanel")

        if admin_panel_cog is not None and hasattr(admin_panel_cog, "build_bot_status_message"):
            return admin_panel_cog.build_bot_status_message()

        loaded = list(getattr(self.bot, "loaded_extensions", []))
        failed = list(getattr(self.bot, "failed_extensions", []))

        lines = [
            "🤖 **Bot Status**",
            "",
            f"Loaded modules: ✅ **{len(loaded)}**",
            f"Failed modules: ❌ **{len(failed)}**",
        ]

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

    def build_sync_startup_info_message(self) -> str:
        try:
            should_sync = bool(self.bot.should_sync_on_startup())
        except Exception:
            should_sync = False

        state_text = "Enabled ⚠️" if should_sync else "Disabled ✅"

        return (
            "⚙️ **Sync Startup Info**\n\n"
            f"Slash sync on startup: **{state_text}**\n\n"
            "Recommended state: **Disabled**\n\n"
            "Use the emergency prefix command if you need to change this:\n"
            "`!bot_sync_startup on`\n"
            "`!bot_sync_startup off`"
        )

    def build_guild_sync_panel_embed(self, user: discord.abc.User) -> discord.Embed:
        stats = self.get_guild_link_stats()

        embed = discord.Embed(
            title="🔄 Guild Sync",
            description="Sync and inspect tracked GW2 guild member data.",
            color=0x5865F2,
            timestamp=datetime.now(timezone.utc),
        )

        embed.add_field(
            name="Current",
            value=(
                f"Tracked members: **{stats['total']}**\n"
                f"Linked: 🟢 **{stats['linked']}**\n"
                f"Unlinked: 🔴 **{stats['unlinked']}**"
            ),
            inline=False,
        )

        embed.add_field(
            name="Actions",
            value="🏠 Main Menu\n📊 Status\n⚡ Sync Now\n👥 Members Help",
            inline=False,
        )

        embed.set_footer(
            text=f"Opened by {user.display_name if hasattr(user, 'display_name') else user.name}"
        )

        return embed

    def build_guild_sync_status_message(self) -> str:
        admin_panel_cog = self.bot.get_cog("AdminPanel")

        if admin_panel_cog is not None and hasattr(admin_panel_cog, "build_guild_sync_status_message"):
            return admin_panel_cog.build_guild_sync_status_message()

        data = self.load_guild_data()
        stats = self.get_guild_link_stats()

        total_weekly_gold = sum(self.safe_int(member.get("weekly_gold", 0)) for member in data)
        total_lifetime_gold = sum(self.safe_int(member.get("lifetime_gold", 0)) for member in data)

        return (
            "🔄 **Guild Sync Status**\n\n"
            f"Members tracked: **{stats['total']}**\n"
            f"Linked: 🟢 **{stats['linked']}**\n"
            f"Unlinked: 🔴 **{stats['unlinked']}**\n"
            f"Weekly donated: **{self.format_gold(total_weekly_gold)}**\n"
            f"Bot-tracked lifetime donated: **{self.format_gold(total_lifetime_gold)}**\n\n"
            "🟢 Linked • 🔴 Unlinked"
        )

    def build_guild_link_panel_embed(self, user: discord.abc.User) -> discord.Embed:
        stats = self.get_guild_link_stats()

        embed = discord.Embed(
            title="🔗 Guild Link",
            description="Inspect and manage guild link status.",
            color=0x5865F2,
            timestamp=datetime.now(timezone.utc),
        )

        embed.add_field(
            name="Current",
            value=(
                f"Tracked members: **{stats['total']}**\n"
                f"Linked: 🟢 **{stats['linked']}**\n"
                f"Unlinked: 🔴 **{stats['unlinked']}**"
            ),
            inline=False,
        )

        embed.add_field(
            name="Actions",
            value=(
                "🏠 Main Menu\n"
                "🟢 Linked Members\n"
                "🔴 Unlinked Members\n"
                "🔎 Status Lookup\n"
                "🛠️ Force Link\n"
                "⛓️ Unlink\n"
                "📊 Summary\n"
                "📋 Help"
            ),
            inline=False,
        )

        embed.set_footer(
            text=f"Opened by {user.display_name if hasattr(user, 'display_name') else user.name}"
        )

        return embed

    async def build_guild_link_member_embeds(self, mode: str, title: str) -> List[discord.Embed]:
        members = self.get_sorted_guild_members(mode)

        if not members:
            return [
                discord.Embed(
                    title=title,
                    description="No members found.",
                    color=0x5865F2,
                    timestamp=datetime.now(timezone.utc),
                )
            ]

        lines = []

        for index, member in enumerate(members, 1):
            lines.append(await self.format_link_member_line(index, member))

        chunks = self.split_lines_for_embed(lines, max_length=3900)
        embeds = []

        for page, chunk in enumerate(chunks, 1):
            embed = discord.Embed(
                title=title,
                description=chunk,
                color=0x5865F2,
                timestamp=datetime.now(timezone.utc),
            )

            embed.set_footer(text=f"Page {page}/{len(chunks)} • Members: {len(members)}")
            embeds.append(embed)

        return embeds

    def build_guild_link_help_message(self) -> str:
        return (
            "📋 **Guild Link Help**\n\n"
            "Guild linking connects a Discord member to a GW2 account from `guild_data.json`.\n\n"
            "User tools:\n"
            "`/vr-bot → Link Status`\n"
            "`/vr-bot → Link Account`\n\n"
            "Admin tools in this panel:\n"
            "🔎 Status Lookup — check a GW2 account, Discord ID, or @mention.\n"
            "🛠️ Force Link — link or move a GW2 account to a Discord user.\n"
            "⛓️ Unlink — remove an existing Discord link.\n"
            "📊 Summary — show linked/unlinked counts."
        )

    def build_force_link_help_message(self) -> str:
        return self.build_guild_link_help_message()

    def build_raffle_admin_panel_embed(self, user: discord.abc.User) -> discord.Embed:
        embed = self.build_raffle_status_embed(
            public=False,
            title="🎟️ Raffle Admin",
            footer=f"Opened by {user.display_name if hasattr(user, 'display_name') else user.name}",
        )

        embed.add_field(
            name="Actions",
            value=(
                "🏠 Main Menu\n"
                "🎟️ Status\n"
                "👥 Entries\n"
                "➕ Create\n"
                "✏️ Edit\n"
                "🎫 Add Tickets\n"
                "➖ Remove Tickets\n"
                "🏆 Draw Winner\n"
                "🛑 End Raffle"
            ),
            inline=False,
        )

        return embed

    def build_raffle_status_embed(
        self,
        public: bool = False,
        title: str = "🎟️ Raffle Status",
        footer: Optional[str] = None,
    ) -> discord.Embed:
        raffle = self.load_raffle()
        tickets = self.load_tickets()

        active = bool(raffle.get("active"))
        raffle_title = raffle.get("title", "Unknown raffle")
        total_tickets = self.get_total_tickets(tickets)
        ticket_holders = self.get_ticket_holders_count(tickets)
        pot_total = self.get_raffle_pot_total(tickets)

        embed = discord.Embed(
            title=title,
            color=0xE67E22 if active else 0x95A5A6,
            timestamp=datetime.now(timezone.utc),
        )

        if not active:
            embed.description = "ℹ️ No active raffle."

            winner = raffle.get("winner_gw2_account_name")
            final_pot = raffle.get("final_pot")

            if winner:
                embed.add_field(name="Last winner", value=f"**{winner}**", inline=False)

            if final_pot is not None:
                embed.add_field(name="Final pot", value=f"**{self.format_gold(final_pot)}**", inline=False)

            if footer:
                embed.set_footer(text=footer)

            return embed

        remaining = self.get_remaining_time(raffle.get("end_time", ""))

        embed.description = (
            f"Raffle: **{raffle_title}**\n"
            "Status: **Active ✅**\n"
            f"Time remaining: **{remaining}**\n"
            f"Ticket price: **{self.format_gold(self.safe_int(raffle.get('ticket_price', 0)))}**\n"
            f"Multiple tickets: **{'Yes' if raffle.get('multiple_tickets') else 'No'}**"
        )

        if not public:
            embed.description += f"\nWinner takes all: **{'Yes' if raffle.get('winner_takes_all') else 'No'}**"

        embed.description += f"\n\nTicket holders: **{ticket_holders}**\nTickets: **{total_tickets}**"

        if raffle.get("winner_takes_all") or not public:
            embed.description += f"\nPot: **{self.format_gold(pot_total)}**"

        if footer:
            embed.set_footer(text=footer)

        return embed

    async def build_raffle_entries_embeds(self, include_zero: bool = False) -> List[discord.Embed]:
        raffle_panel_cog = self.bot.get_cog("RafflePanel")

        if raffle_panel_cog is not None and hasattr(raffle_panel_cog, "build_entries_embeds"):
            return await raffle_panel_cog.build_entries_embeds(include_zero=include_zero)

        raffle = self.load_raffle()

        if not raffle.get("active"):
            return [
                discord.Embed(
                    title="👥 Raffle Entries",
                    description="ℹ️ No active raffle.",
                    color=0x95A5A6,
                    timestamp=datetime.now(timezone.utc),
                )
            ]

        tickets = self.load_tickets()
        entries = self.get_ticket_holders(tickets, include_zero=include_zero)

        if not entries:
            return [
                discord.Embed(
                    title=f"👥 Raffle Entries — {raffle.get('title', 'Unknown')}",
                    description="No raffle ticket holders yet.",
                    color=0xE67E22,
                    timestamp=datetime.now(timezone.utc),
                )
            ]

        raffle_cog = self.bot.get_cog("Raffle")

        if raffle_cog is not None and hasattr(raffle_cog, "build_entries_embed"):
            return [
                await raffle_cog.build_entries_embed(
                    raffle=raffle,
                    entries=entries,
                    include_zero=include_zero,
                )
            ]

        lines = []

        for index, entry in enumerate(entries, 1):
            discord_display = await self.format_discord_user(int(entry["discord_id"]), include_id=False)

            lines.append(
                f"**{index}.** **{entry['gw2_account_name']}** — "
                f"{discord_display} — "
                f"🎫 **{entry['ticket_count']}** — "
                f"💰 **{self.format_gold(entry['raffle_donation_total'])}**"
            )

        chunks = self.split_lines_for_embed(lines)
        embeds = []

        for page, chunk in enumerate(chunks, 1):
            embed = discord.Embed(
                title=f"👥 Raffle Entries — {raffle.get('title', 'Unknown')}",
                description=chunk,
                color=0xE67E22,
                timestamp=datetime.now(timezone.utc),
            )

            embed.set_footer(text=f"Page {page}/{len(chunks)}")
            embeds.append(embed)

        return embeds

    def build_guild_upgrade_admin_panel_embed(self, user: discord.abc.User) -> discord.Embed:
        state = self.load_guild_upgrade_state()
        active = bool(state.get("active"))

        embed = discord.Embed(
            title="🏗️ Guild Upgrades",
            color=0xC79C38 if active else 0x95A5A6,
            timestamp=datetime.now(timezone.utc),
        )

        if active:
            embed.description = f"Active tracker: **{state.get('upgrade_name', 'Unknown')}**"
        elif state.get("completed"):
            embed.description = f"Last completed: **{state.get('upgrade_name', 'Unknown')}**"
        else:
            embed.description = "No active tracker."

        embed.add_field(
            name="Actions",
            value=(
                "🏠 Main Menu\n"
                "📊 Status\n"
                "🔍 Search/List\n"
                "▶️ Start\n"
                "✅ Confirm\n"
                "📌 Set Channel\n"
                "🔄 Refresh\n"
                "🛑 End Tracker"
            ),
            inline=False,
        )

        embed.set_footer(
            text=f"Opened by {user.display_name if hasattr(user, 'display_name') else user.name}"
        )

        return embed

    def build_donations_panel_embed(self, user: discord.abc.User) -> discord.Embed:
        data = self.load_guild_data()
        weekly_donors = self.get_sorted_donors("weekly_gold")
        lifetime_donors = self.get_sorted_donors("lifetime_gold")

        total_weekly_gold = sum(self.safe_int(member.get("weekly_gold", 0)) for member in data)
        total_lifetime_gold = sum(self.safe_int(member.get("lifetime_gold", 0)) for member in data)

        embed = discord.Embed(
            title="💰 Donations",
            description="Private donation tracking tools.",
            color=0xFFD700,
            timestamp=datetime.now(timezone.utc),
        )

        embed.add_field(
            name="Current",
            value=(
                f"Weekly donors: **{len(weekly_donors)}**\n"
                f"Lifetime donors: **{len(lifetime_donors)}**\n"
                f"Weekly total: **{self.format_gold(total_weekly_gold)}**\n"
                f"Bot-tracked lifetime total: **{self.format_gold(total_lifetime_gold)}**"
            ),
            inline=False,
        )

        embed.add_field(
            name="Actions",
            value=(
                "🏠 Main Menu\n"
                "📊 Summary\n"
                "🏆 Weekly Donors\n"
                "👑 Lifetime Donors\n"
                "📝 Set Lifetime\n"
                "➕ Adjust Lifetime\n"
                "🧹 Reset Weekly"
            ),
            inline=False,
        )

        embed.set_footer(
            text=f"Opened by {user.display_name if hasattr(user, 'display_name') else user.name}"
        )

        return embed

    def build_donation_summary_embed(self) -> discord.Embed:
        data = self.load_guild_data()
        weekly_donors = self.get_sorted_donors("weekly_gold")
        lifetime_donors = self.get_sorted_donors("lifetime_gold")

        total_weekly_gold = sum(self.safe_int(member.get("weekly_gold", 0)) for member in data)
        total_lifetime_gold = sum(self.safe_int(member.get("lifetime_gold", 0)) for member in data)

        linked_weekly = sum(1 for donor in weekly_donors if donor.get("discord_user_id") is not None)
        linked_lifetime = sum(1 for donor in lifetime_donors if donor.get("discord_user_id") is not None)

        embed = discord.Embed(
            title="📊 Donation Summary",
            color=0xFFD700,
            timestamp=datetime.now(timezone.utc),
        )

        embed.description = (
            f"Weekly donors: **{len(weekly_donors)}**\n"
            f"Linked weekly donors: 🟢 **{linked_weekly}**\n"
            f"Weekly total: **{self.format_gold(total_weekly_gold)}**\n\n"
            f"Lifetime donors: **{len(lifetime_donors)}**\n"
            f"Linked lifetime donors: 🟢 **{linked_lifetime}**\n"
            f"Bot-tracked lifetime total: **{self.format_gold(total_lifetime_gold)}**"
        )

        embed.set_footer(text="Lifetime total is bot-tracked from recorded deposits.")
        return embed

    async def build_donor_list_embeds(self, title: str, amount_key: str, empty_text: str) -> List[discord.Embed]:
        donors = self.get_sorted_donors(amount_key)

        if not donors:
            return [
                discord.Embed(
                    title=title,
                    description=empty_text,
                    color=0xFFD700,
                    timestamp=datetime.now(timezone.utc),
                )
            ]

        lines = []

        for index, donor in enumerate(donors, 1):
            lines.append(await self.format_donor_line(index, donor))

        chunks = self.split_lines_for_embed(lines, max_length=3900)
        embeds = []
        total_gold = sum(self.safe_int(donor.get("amount", 0)) for donor in donors)

        for page, chunk in enumerate(chunks, 1):
            embed = discord.Embed(
                title=title,
                description=chunk,
                color=0xFFD700,
                timestamp=datetime.now(timezone.utc),
            )

            embed.set_footer(
                text=f"Page {page}/{len(chunks)} • Donors: {len(donors)} • Total: {self.format_gold(total_gold)}"
            )

            embeds.append(embed)

        return embeds

    def build_role_tools_panel_embed(self, user: discord.abc.User) -> discord.Embed:
        embed = discord.Embed(
            title="🔎 Role Tools",
            description="Role audit tools.",
            color=0x5865F2,
            timestamp=datetime.now(timezone.utc),
        )

        embed.add_field(
            name="Available",
            value="🏠 Main Menu\n📋 Help\nRole dropdown selector",
            inline=False,
        )

        embed.add_field(
            name="Missing Role Check",
            value=(
                "Use the dropdown below to select a role.\n"
                "The bot will list non-bot members who do not have that role."
            ),
            inline=False,
        )

        embed.set_footer(
            text=f"Opened by {user.display_name if hasattr(user, 'display_name') else user.name}"
        )

        return embed

    def build_missing_role_embeds(
        self,
        guild: Optional[discord.Guild],
        role: discord.Role,
        include_bots: bool = False,
    ) -> List[discord.Embed]:
        if guild is None:
            return [
                discord.Embed(
                    title="🔎 Missing Role Check",
                    description="❌ This can only be used inside the server.",
                    color=0xE74C3C,
                    timestamp=datetime.now(timezone.utc),
                )
            ]

        missing_members = []

        for member in guild.members:
            if not include_bots and member.bot:
                continue

            if role not in member.roles:
                missing_members.append(member)

        missing_members.sort(key=lambda member: member.display_name.lower())

        if not missing_members:
            embed = discord.Embed(
                title=f"🔎 Missing Role: {role.name}",
                description="✅ No matching members are missing this role.",
                color=0x2ECC71,
                timestamp=datetime.now(timezone.utc),
            )

            embed.set_footer(text="Bots excluded.")
            return [embed]

        lines = [f"• {member.mention} — {member.display_name}" for member in missing_members]
        chunks = self.split_lines_for_embed(lines, max_length=3900)
        embeds = []

        for page, chunk in enumerate(chunks, 1):
            embed = discord.Embed(
                title=f"🔎 Missing Role: {role.name}",
                description=chunk,
                color=0x5865F2,
                timestamp=datetime.now(timezone.utc),
            )

            embed.set_footer(
                text=f"Page {page}/{len(chunks)} • Missing: {len(missing_members)} • Bots excluded"
            )

            embeds.append(embed)

        return embeds

    def build_guild_bank_panel_embed(self, user: discord.abc.User) -> discord.Embed:
        embed = discord.Embed(
            title="🧹 Guild Bank",
            description="Private guild bank tools.",
            color=0x5865F2,
            timestamp=datetime.now(timezone.utc),
        )

        embed.add_field(
            name="Available",
            value="🏠 Main Menu\n🧹 Duplicate Stacks",
            inline=False,
        )

        embed.add_field(
            name="Duplicate Stacks",
            value=(
                "Checks the guild bank for unnecessary split stacks.\n"
                "Only items that can be merged into fewer slots are shown."
            ),
            inline=False,
        )

        embed.set_footer(
            text=f"Opened by {user.display_name if hasattr(user, 'display_name') else user.name}"
        )

        return embed

    # ========================================================
    # ADMIN ACTIONS
    # ========================================================
    async def run_bot_sync(self) -> str:
        state = {
            "last_mode": "global",
            "last_success": False,
            "last_count": None,
            "last_error": None,
            "last_attempt_at": self.now_iso(),
        }

        try:
            synced = await self.bot.tree.sync()
            state["last_success"] = True
            state["last_count"] = len(synced)
            self.save_json(BOT_SYNC_STATE_FILE, state)

            return f"✅ **Command sync complete**\n\nSynced commands: **{len(synced)}**"

        except Exception as error:
            error_text = str(error)
            state["last_error"] = error_text
            self.save_json(BOT_SYNC_STATE_FILE, state)

            if "30034" in error_text or "Max number of daily application command creates" in error_text:
                return (
                    "⚠️ **Discord command create limit reached**\n\n"
                    "Discord says the daily application command create limit has been reached.\n"
                    "Do not keep retrying sync today.\n\n"
                    f"```text\n{error_text}\n```"
                )

            return f"❌ **Command sync failed**\n\n```text\n{error_text}\n```"

    async def run_bot_restart(self) -> str:
        async def delayed_restart():
            await asyncio.sleep(2)

            try:
                subprocess.Popen(
                    ["sudo", "systemctl", "restart", "gw2bot"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass

        asyncio.create_task(delayed_restart())

        return (
            "♻️ **Bot restart requested**\n\n"
            "The `gw2bot` service should restart shortly.\n"
            "Use `!bot_status` after it comes back online if needed."
        )

    async def run_guild_sync_now(self) -> str:
        guild_sync_cog = self.bot.get_cog("GuildSync")

        if guild_sync_cog is None:
            return "❌ GuildSync cog is not loaded."

        try:
            result = await guild_sync_cog.sync_guild_data()
            report = await guild_sync_cog.build_sync_report(result, manual=True)

            return report or "🔄 **Guild Changes**\n\nNo members joined or left."

        except Exception as error:
            return f"⚠️ Guild sync failed:\n```text\n{error}\n```"

    async def run_raffle_draw(self) -> str:
        raffle_panel_cog = self.bot.get_cog("RafflePanel")

        if raffle_panel_cog is not None and hasattr(raffle_panel_cog, "draw_raffle_winner"):
            return await raffle_panel_cog.draw_raffle_winner()

        raffle = self.load_raffle()

        if not raffle.get("active"):
            return "❌ No active raffle."

        tickets = self.load_tickets()
        pool = self.build_weighted_pool(tickets)
        pot_total = self.get_raffle_pot_total(tickets)

        raffle["active"] = False
        raffle["ended_at"] = self.now_iso()

        if not pool:
            raffle["final_pot"] = pot_total
            self.save_raffle(raffle)
            return "ℹ️ No valid raffle entries existed. The raffle has been ended."

        winner_discord_id = random.choice(pool)
        winner_entry = tickets[winner_discord_id]
        winner_ticket_count = self.safe_int(winner_entry.get("ticket_count", 0))
        winner_display = await self.format_discord_user(int(winner_discord_id), include_id=False)

        raffle["winner_discord_id"] = winner_discord_id
        raffle["winner_gw2_account_name"] = winner_entry.get("gw2_account_name", "Unknown")

        if raffle.get("winner_takes_all"):
            raffle["final_pot"] = pot_total

        self.save_raffle(raffle)

        msg = (
            "🏆 **Raffle Winner Drawn**\n\n"
            f"Raffle: **{raffle.get('title', 'Unknown raffle')}**\n"
            f"GW2 account: **{winner_entry.get('gw2_account_name', 'Unknown')}**\n"
            f"Discord: **{winner_display}**\n"
            f"Tickets: **{winner_ticket_count}**"
        )

        if raffle.get("winner_takes_all"):
            msg += f"\nPot: **{self.format_gold(pot_total)}**"

        return msg

    async def run_raffle_end(self) -> str:
        raffle_panel_cog = self.bot.get_cog("RafflePanel")

        if raffle_panel_cog is not None and hasattr(raffle_panel_cog, "end_raffle_without_draw"):
            return await raffle_panel_cog.end_raffle_without_draw()

        raffle = self.load_raffle()

        if not raffle.get("active"):
            return "ℹ️ No active raffle."

        tickets = self.load_tickets()
        pot_total = self.get_raffle_pot_total(tickets)
        title = raffle.get("title", "Unknown raffle")

        raffle["active"] = False
        raffle["ended_at"] = self.now_iso()

        if raffle.get("winner_takes_all"):
            raffle["final_pot"] = pot_total

        self.save_raffle(raffle)

        msg = f"🛑 **Raffle ended**\n\nRaffle: **{title}**\nTickets: **{self.get_total_tickets(tickets)}**"

        if raffle.get("winner_takes_all"):
            msg += f"\nFinal pot: **{self.format_gold(pot_total)}**"

        return msg

    async def build_guild_upgrade_admin_status_output(self):
        guild_upgrade_cog = self.bot.get_cog("GuildUpgrades")
        state = self.load_guild_upgrade_state()

        if not state.get("active"):
            if state.get("completed"):
                return f"✅ Last tracked upgrade was completed: **{state.get('upgrade_name', 'Unknown')}**"

            return "ℹ️ No active guild upgrade tracker."

        if guild_upgrade_cog is not None and hasattr(guild_upgrade_cog, "build_upgrade_embed"):
            return [await guild_upgrade_cog.build_upgrade_embed(state, public=False)]

        return f"🏗️ Active tracker: **{state.get('upgrade_name', 'Unknown')}**"

    async def run_guild_upgrade_refresh(self) -> str:
        guild_upgrade_cog = self.bot.get_cog("GuildUpgrades")

        if guild_upgrade_cog is None:
            return "❌ GuildUpgrades cog is not loaded."

        if hasattr(guild_upgrade_cog, "refresh_active_tracker"):
            return await guild_upgrade_cog.refresh_active_tracker()

        return "❌ GuildUpgrades cog does not expose refresh_active_tracker()."

    async def run_guild_upgrade_end(self) -> str:
        guild_upgrade_cog = self.bot.get_cog("GuildUpgrades")

        if guild_upgrade_cog is None:
            return "❌ GuildUpgrades cog is not loaded."

        state = self.load_guild_upgrade_state()

        if not state.get("active"):
            return "ℹ️ No active guild upgrade tracker."

        upgrade_name = state.get("upgrade_name", "Unknown upgrade")

        if hasattr(guild_upgrade_cog, "delete_upgrade_message"):
            deleted = await guild_upgrade_cog.delete_upgrade_message(state)
        else:
            deleted = False

        state["active"] = False
        state["ended_at"] = self.now_iso()
        state["ended_manually"] = True

        self.save_guild_upgrade_state(state)

        if deleted:
            return f"🛑 Stopped tracking **{upgrade_name}** and deleted the public post."

        return f"🛑 Stopped tracking **{upgrade_name}**, but I could not delete the public post."

    async def run_guild_bank_duplicates_check(self):
        guild_bank_cog = self.bot.get_cog("GuildBankDuplicates")

        if guild_bank_cog is None:
            return "❌ GuildBankDuplicates cog is not loaded."

        try:
            if not getattr(guild_bank_cog, "gw2_api_key", None):
                return "❌ GW2 API key is missing from the bot configuration."

            if not getattr(guild_bank_cog, "guild_id", None):
                return "❌ GW2 guild ID is missing from the bot configuration."

            stash_tabs = await guild_bank_cog.fetch_guild_stash()
            grouped_items = guild_bank_cog.collect_stash_items(stash_tabs)
            duplicates = guild_bank_cog.find_mergeable_duplicates(grouped_items)

            item_ids = [item["item_id"] for item in duplicates]
            item_names = await guild_bank_cog.fetch_item_names(item_ids)

            return guild_bank_cog.build_duplicate_embeds(
                duplicates=duplicates,
                item_names=item_names,
            )

        except Exception as error:
            return f"❌ Failed to check guild bank duplicates.\n```text\n{error}\n```"

    # ========================================================
    # COMMANDS
    # ========================================================
    @app_commands.command(name="vr-bot", description="Open the VR Bot user panel.")
    async def vr_bot(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=self.build_user_panel_embed(interaction.user),
            view=VRBotUserPanelView(self, interaction.user.id),
            ephemeral=True,
        )

    @app_commands.command(name="vr-bot_admin", description="Admin only: open the VR Bot admin panel.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def vr_bot_admin(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=self.build_admin_panel_embed(interaction.user),
            view=VRBotAdminPanelView(self, interaction.user.id),
            ephemeral=True,
        )

    @vr_bot_admin.error
    async def vr_bot_admin_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        if isinstance(error, app_commands.MissingPermissions):
            message = "❌ You need administrator permissions to use this command."
        else:
            message = (
                "❌ Something went wrong while running `/vr-bot_admin`.\n"
                f"```text\n{error}\n```"
            )

        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(VRBotPanels(bot))