import discord
from discord.ext import commands, tasks
import json
import os
from datetime import datetime, timezone
from typing import Optional

from services.gw2_api import GW2API, GW2APIError, GW2ConfigError


CONFIG_FILE = "config.json"

with open(CONFIG_FILE, "r") as f:
    CONFIG = json.load(f)


class GuildUpgradeEndConfirmView(discord.ui.View):
    def __init__(self, cog: "GuildUpgrades", owner_id: int):
        super().__init__(timeout=120)
        self.cog = cog
        self.owner_id = owner_id

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
        label="Confirm End",
        style=discord.ButtonStyle.danger,
        emoji="🛑"
    )
    async def confirm_end(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await interaction.response.defer(ephemeral=True)

        state = self.cog.load_state()

        if not state.get("active"):
            await self.disable_buttons()
            return await interaction.followup.send(
                "ℹ️ No active guild upgrade tracker.",
                ephemeral=True
            )

        upgrade_name = state.get("upgrade_name", "Unknown upgrade")
        deleted = await self.cog.delete_upgrade_message(state)

        state["active"] = False
        state["ended_at"] = self.cog.now_iso()
        state["ended_manually"] = True

        self.cog.save_state(state)

        await self.disable_buttons()

        if deleted:
            await interaction.followup.send(
                f"🛑 Stopped tracking **{upgrade_name}** and deleted the public post.",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"🛑 Stopped tracking **{upgrade_name}**, but I could not delete the public post.",
                ephemeral=True
            )

    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.secondary,
        emoji="↩️"
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await interaction.response.defer(ephemeral=True)
        await self.disable_buttons()

        await interaction.followup.send(
            "✅ Cancelled. The active tracker was not changed.",
            ephemeral=True
        )


class GuildUpgradePanelView(discord.ui.View):
    def __init__(self, cog: "GuildUpgrades", owner_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "❌ This guild upgrade panel belongs to someone else.",
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
        emoji="📊"
    )
    async def status_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await interaction.response.defer(ephemeral=True)

        state = self.cog.load_state()

        if not state.get("active"):
            if state.get("completed"):
                return await interaction.followup.send(
                    f"✅ Last tracked upgrade was completed: **{state.get('upgrade_name', 'Unknown')}**",
                    ephemeral=True
                )

            return await interaction.followup.send(
                "ℹ️ No active guild upgrade tracker.",
                ephemeral=True
            )

        embed = await self.cog.build_upgrade_embed(state, public=False)
        channel_id = state.get("channel_id")
        started_by = await self.cog.format_started_by(state, include_id=False)

        await interaction.followup.send(
            f"🏗️ Active tracker: **{state.get('upgrade_name', 'Unknown')}**\n"
            f"{started_by}\n"
            f"Channel: <#{channel_id}>",
            embed=embed,
            ephemeral=True
        )

    @discord.ui.button(
        label="Refresh",
        style=discord.ButtonStyle.primary,
        emoji="🔄"
    )
    async def refresh_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await interaction.response.defer(ephemeral=True)

        message = await self.cog.refresh_active_tracker()
        await interaction.followup.send(message, ephemeral=True)

    @discord.ui.button(
        label="List Help",
        style=discord.ButtonStyle.secondary,
        emoji="📋"
    )
    async def list_help_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await interaction.response.defer(ephemeral=True)

        await interaction.followup.send(
            (
                "📋 **Guild Upgrade List Help**\n\n"
                "Use:\n"
                "`/guild_upgrade list`\n\n"
                "Search smaller/raw upgrades with:\n"
                "`/guild_upgrade list search:brawling show_all:true`\n\n"
                "Then prepare a tracker with:\n"
                "`/guild_upgrade start number:<number>`\n\n"
                "After reviewing the preview, publish it with:\n"
                "`/guild_upgrade confirm number:<number>`"
            ),
            ephemeral=True
        )

    @discord.ui.button(
        label="End Tracker",
        style=discord.ButtonStyle.danger,
        emoji="🛑"
    )
    async def end_tracker_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        state = self.cog.load_state()

        if not state.get("active"):
            return await interaction.response.send_message(
                "ℹ️ No active guild upgrade tracker.",
                ephemeral=True
            )

        upgrade_name = state.get("upgrade_name", "Unknown upgrade")

        view = GuildUpgradeEndConfirmView(
            cog=self.cog,
            owner_id=interaction.user.id
        )

        await interaction.response.send_message(
            (
                f"⚠️ **Confirm End Tracker**\n\n"
                f"This will stop tracking **{upgrade_name}** and delete the public upgrade post.\n\n"
                f"Are you sure?"
            ),
            view=view,
            ephemeral=True
        )


class GuildUpgrades(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        self.CONFIG_FILE = CONFIG_FILE
        self.STATE_FILE = "guild_upgrade_state.json"
        self.CACHE_FILE = "guild_upgrade_cache.json"
        self.PENDING_FILE = "guild_upgrade_pending.json"

        self.api: Optional[GW2API] = None

        self.ensure_config_defaults()

        poll_minutes = self.get_poll_interval()
        self.auto_refresh.change_interval(minutes=poll_minutes)
        self.auto_refresh.start()

    MAJOR_UPGRADE_KEYWORDS = [
        "restoration",
        "excavation",
        "aetherium",
        "mining rate",
        "capacity",
        "guild vault",
        "vault",
        "bank",
        "treasure trove",
        "guild trader",
        "trader",
        "armorer",
        "weaponsmith",
        "market",
        "tavern",
        "workshop",
        "war room",
        "arena",
        "portal",
        "guild portal",
        "mission",
        "guild hall",
        "synthesis output",
        "synthesizer",
    ]

    NOISY_UPGRADE_KEYWORDS = [
        "banner",
        "banners",
        "decoration",
        "decorations",
        "schematic",
        "schematics",
        "claimable",
        "objective aura",
        "objective auras",
        "consumable",
        "consumables",
        "wvw",
        "world versus world",
        "pvp",
        "swiftness",
        "waypoint",
        "karma",
        "magic find",
        "experience",
        "gathering bonus",
        "guild catapult",
        "guild arrow cart",
        "guild ballista",
        "guild trebuchet",
        "tactic",
        "improvement",
    ]

    async def cog_load(self):
        self.api = GW2API()
        await self.api.ensure_session()

    async def cog_unload(self):
        self.auto_refresh.cancel()

        if self.api is not None:
            await self.api.close()

    async def get_api(self) -> GW2API:
        if self.api is None:
            self.api = GW2API()
            await self.api.ensure_session()

        return self.api

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

    def load_config(self):
        return self.load_json(self.CONFIG_FILE, {})

    def save_config(self, data):
        self.save_json(self.CONFIG_FILE, data)

    def ensure_config_defaults(self):
        config = self.load_config()
        changed = False

        if "GUILD_UPGRADE_CHANNEL_ID" not in config:
            config["GUILD_UPGRADE_CHANNEL_ID"] = None
            changed = True

        if "GUILD_UPGRADE_POLL_INTERVAL" not in config:
            config["GUILD_UPGRADE_POLL_INTERVAL"] = 10
            changed = True

        if changed:
            self.save_config(config)

    def get_upgrade_channel_id(self):
        config = self.load_config()
        return config.get("GUILD_UPGRADE_CHANNEL_ID")

    def set_upgrade_channel_id(self, channel_id: int):
        config = self.load_config()
        config["GUILD_UPGRADE_CHANNEL_ID"] = channel_id
        self.save_config(config)

    def get_poll_interval(self) -> int:
        config = self.load_config()

        try:
            interval = int(config.get("GUILD_UPGRADE_POLL_INTERVAL", 10))
        except Exception:
            interval = 10

        return max(5, min(interval, 60))

    def load_state(self):
        return self.load_json(self.STATE_FILE, {"active": False})

    def save_state(self, data):
        self.save_json(self.STATE_FILE, data)

    def load_cache(self):
        return self.load_json(
            self.CACHE_FILE,
            {
                "generated_at": None,
                "entries": []
            }
        )

    def save_cache(self, data):
        self.save_json(self.CACHE_FILE, data)

    def load_pending(self):
        return self.load_json(self.PENDING_FILE, {})

    def save_pending(self, data):
        self.save_json(self.PENDING_FILE, data)

    def format_gold(self, coins: int) -> str:
        if coins is None:
            return "Unknown"

        coins = int(coins or 0)
        gold = coins // 10000
        silver = (coins % 10000) // 100
        copper = coins % 100

        return f"{gold}g {silver}s {copper}c"

    def format_number(self, value):
        if value is None:
            return "Not exposed by API"

        try:
            return f"{int(value):,}"
        except Exception:
            return str(value)

    def format_pct(self, value: float) -> str:
        return f"{round(float(value), 1)}%"

    def now_iso(self):
        return datetime.now(timezone.utc).isoformat()

    def format_refresh_time(self, iso_value: str):
        if not iso_value:
            return "Unknown"

        try:
            dt = datetime.fromisoformat(iso_value)
            return dt.strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            return iso_value

    async def format_discord_user(self, discord_user_id: int, include_id: bool = False):
        if discord_user_id is None:
            return "Unknown user"

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

    async def format_started_by(self, tracker: dict, include_id: bool = False):
        started_by = tracker.get("started_by")

        if started_by is None:
            return "Started by: ⚠️ Unknown"

        discord_name = await self.format_discord_user(
            int(started_by),
            include_id=include_id
        )

        return f"Started by: ✅ {discord_name}"

    async def fetch_guild_details(self):
        api = await self.get_api()
        return await api.get_guild_details()

    async def fetch_all_upgrades(self):
        api = await self.get_api()
        return await api.get_all_guild_upgrades()

    async def fetch_owned_upgrade_ids(self):
        api = await self.get_api()
        return await api.get_owned_guild_upgrade_ids()

    async def fetch_treasury(self):
        api = await self.get_api()
        return await api.get_guild_treasury()

    async def fetch_item_details(self, item_ids):
        api = await self.get_api()
        return await api.get_items(item_ids)

    async def fetch_prices(self, item_ids):
        api = await self.get_api()
        return await api.get_prices(item_ids)

    async def is_upgrade_completed(self, upgrade_id: int) -> bool:
        owned_ids = set(await self.fetch_owned_upgrade_ids())
        return int(upgrade_id) in owned_ids

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

    def normalize_text(self, value: str) -> str:
        return str(value or "").lower().strip()

    def is_major_upgrade(self, upgrade: dict) -> bool:
        name = self.normalize_text(upgrade.get("name", ""))
        upgrade_type = self.normalize_text(upgrade.get("type", ""))

        searchable = f"{name} {upgrade_type}"

        if any(noisy in searchable for noisy in self.NOISY_UPGRADE_KEYWORDS):
            return False

        return any(keyword in searchable for keyword in self.MAJOR_UPGRADE_KEYWORDS)

    def matches_search(self, upgrade: dict, search: Optional[str]) -> bool:
        if search is None or search.strip() == "":
            return True

        query = search.lower().strip()
        name = self.normalize_text(upgrade.get("name", ""))
        upgrade_type = self.normalize_text(upgrade.get("type", ""))

        return query in name or query in upgrade_type

    def classify_resource_text(self, name: str, resource_type: str = ""):
        text = f"{self.normalize_text(name)} {self.normalize_text(resource_type)}"

        if "favor" in text:
            return "favor"

        if "aetherium" in text:
            return "aetherium"

        return None

    def classify_guild_resource(self, resource: dict):
        return (
            resource.get("resource_kind")
            or self.classify_resource_text(
                resource.get("name", ""),
                resource.get("type", "")
            )
            or "other"
        )

    def get_guild_resource_value(self, guild_details: dict, resource_kind: str):
        if not isinstance(guild_details, dict):
            return None

        lookup_keys = {
            "favor": [
                "favor",
                "guild_favor",
                "current_favor",
            ],
            "aetherium": [
                "aetherium",
                "guild_aetherium",
                "current_aetherium",
            ],
        }

        keys = lookup_keys.get(resource_kind.lower(), [resource_kind.lower()])

        for key in keys:
            if key in guild_details:
                return guild_details.get(key)

        return None

    def hydrate_guild_resources(self, guild_resources: list, guild_details: dict):
        hydrated = []

        for resource in guild_resources:
            resource = dict(resource)
            kind = self.classify_guild_resource(resource)

            current = None

            if kind in ("favor", "aetherium"):
                current = self.get_guild_resource_value(guild_details, kind)

            resource["resource_kind"] = kind
            resource["current"] = current

            hydrated.append(resource)

        return hydrated

    def get_treasury_counts(self, treasury_data):
        counts = {}

        for entry in treasury_data:
            item_id = entry.get("item_id")
            count = entry.get("count", 0)

            if item_id is None:
                continue

            counts[int(item_id)] = int(count)

        return counts

    def get_costs_from_upgrade(self, upgrade: dict):
        item_costs = []
        guild_resources = []

        for cost in upgrade.get("costs", []):
            item_id = cost.get("item_id")
            count = int(cost.get("count", 0))

            if count <= 0:
                continue

            cost_type = cost.get("type", "unknown")
            name = cost.get("name") or cost_type or "Unknown requirement"
            resource_kind = self.classify_resource_text(name, cost_type)

            if resource_kind in ("favor", "aetherium"):
                guild_resources.append(
                    {
                        "type": cost_type,
                        "name": name,
                        "required": count,
                        "resource_kind": resource_kind,
                        "source_item_id": int(item_id) if item_id is not None else None
                    }
                )
                continue

            if item_id is not None:
                item_costs.append(
                    {
                        "type": "item",
                        "item_id": int(item_id),
                        "name": name,
                        "required": count
                    }
                )
                continue

            guild_resources.append(
                {
                    "type": cost_type,
                    "name": name,
                    "required": count,
                    "resource_kind": "other",
                    "source_item_id": None
                }
            )

        return item_costs, guild_resources

    def get_item_costs_from_upgrade(self, upgrade: dict):
        item_costs, _guild_resources = self.get_costs_from_upgrade(upgrade)
        return item_costs

    def calculate_upgrade_progress(self, upgrade: dict, treasury_counts: dict):
        item_costs = self.get_item_costs_from_upgrade(upgrade)

        total_required = 0
        total_current = 0

        for cost in item_costs:
            required = int(cost.get("required", 0))
            current = min(int(treasury_counts.get(cost["item_id"], 0)), required)

            total_required += required
            total_current += current

        if total_required <= 0:
            return 0.0

        return (total_current / total_required) * 100

    def is_upgrade_available(self, upgrade: dict, owned_ids: set):
        upgrade_id = upgrade.get("id")

        if upgrade_id in owned_ids:
            return False

        prerequisites = upgrade.get("prerequisites", [])

        for prereq_id in prerequisites:
            if prereq_id not in owned_ids:
                return False

        return True

    async def build_upgrade_tracker(self, upgrade_id: int, list_number: Optional[int] = None):
        all_upgrades = await self.fetch_all_upgrades()
        treasury = await self.fetch_treasury()
        guild_details = await self.fetch_guild_details()
        treasury_counts = self.get_treasury_counts(treasury)

        upgrade = None

        for candidate in all_upgrades:
            if int(candidate.get("id")) == int(upgrade_id):
                upgrade = candidate
                break

        if upgrade is None:
            raise Exception(f"Upgrade ID {upgrade_id} was not found.")

        raw_costs, guild_resources = self.get_costs_from_upgrade(upgrade)
        guild_resources = self.hydrate_guild_resources(guild_resources, guild_details)

        item_ids = [
            cost["item_id"]
            for cost in raw_costs
            if cost.get("item_id") is not None
        ]

        item_details = await self.fetch_item_details(item_ids)
        prices = await self.fetch_prices(item_ids)

        items = []

        total_required = 0
        total_current = 0
        estimated_remaining_cost = 0
        unknown_price_count = 0

        for cost in raw_costs:
            item_id = int(cost.get("item_id"))
            required = int(cost.get("required", 0))

            item = item_details.get(item_id, {})
            price = prices.get(item_id)

            name = item.get("name") or cost.get("name") or f"Unknown item #{item_id}"
            current = min(int(treasury_counts.get(item_id, 0)), required)
            remaining = max(0, required - current)

            progress_pct = 0

            if required > 0:
                progress_pct = (current / required) * 100

            buyout_price = None
            tp_buyable = False
            remaining_cost = None

            if price:
                sells = price.get("sells", {})
                quantity = int(sells.get("quantity", 0))
                unit_price = int(sells.get("unit_price", 0))

                if quantity > 0 and unit_price > 0:
                    tp_buyable = True
                    buyout_price = unit_price
                    remaining_cost = unit_price * remaining
                    estimated_remaining_cost += remaining_cost
                else:
                    unknown_price_count += 1
            else:
                unknown_price_count += 1

            total_required += required
            total_current += current

            items.append(
                {
                    "item_id": item_id,
                    "name": name,
                    "required": required,
                    "current": current,
                    "remaining": remaining,
                    "progress_pct": progress_pct,
                    "tp_buyable": tp_buyable,
                    "buyout_price": buyout_price,
                    "remaining_cost": remaining_cost,
                    "note": None
                }
            )

        overall_progress = 0.0

        if total_required > 0:
            overall_progress = (total_current / total_required) * 100

        items.sort(
            key=lambda item: (
                item["remaining_cost"] if item["remaining_cost"] is not None else -1,
                item["remaining"],
                100 - item["progress_pct"]
            ),
            reverse=True
        )

        guild_resources.sort(
            key=lambda resource: (
                self.classify_guild_resource(resource),
                self.normalize_text(resource.get("name", "")),
                int(resource.get("required", 0))
            )
        )

        return {
            "active": True,
            "upgrade_id": int(upgrade.get("id")),
            "upgrade_name": upgrade.get("name", f"Upgrade #{upgrade_id}"),
            "upgrade_type": upgrade.get("type", "Unknown"),
            "list_number": list_number,
            "progress_pct": overall_progress,
            "estimated_remaining_cost": estimated_remaining_cost,
            "unknown_price_count": unknown_price_count,
            "items": items,
            "guild_resources": guild_resources,
            "last_refresh": self.now_iso()
        }

    def chunk_lines(self, lines, max_length=1000):
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

    def item_tp_text(self, item: dict):
        if item.get("tp_buyable") and item.get("remaining_cost") is not None:
            return self.format_gold(int(item["remaining_cost"]))

        return "No TP price"

    def guild_resource_icon(self, resource: dict):
        kind = self.classify_guild_resource(resource)

        if kind == "favor":
            return "🏛️"

        if kind == "aetherium":
            return "⚙️"

        return "🔹"

    def build_needed_item_block(self, item: dict):
        name = item.get("name", "Unknown item")
        current = int(item.get("current", 0))
        required = int(item.get("required", 0))
        remaining = int(item.get("remaining", 0))
        tp_text = self.item_tp_text(item)

        return (
            f"🔸 **{name}**\n"
            f"Donated: **{current} / {required}**\n"
            f"Still needed: **{remaining}**\n"
            f"TP estimate: **{tp_text}**\n"
        )

    def build_completed_item_line(self, item: dict):
        name = item.get("name", "Unknown item")
        current = int(item.get("current", 0))
        required = int(item.get("required", 0))

        return f"✅ **{name}** — **{current} / {required}** complete"

    def build_guild_resource_line(self, resource: dict):
        icon = self.guild_resource_icon(resource)
        name = resource.get("name", "Unknown guild resource")
        required = int(resource.get("required", 0))
        current = resource.get("current")
        kind = self.classify_guild_resource(resource)

        if current is None:
            current_text = "Not exposed by API" if kind == "favor" else "Check in-game"

            return (
                f"{icon} **{name}**\n"
                f"Current: **{current_text}**\n"
                f"Required: **{self.format_number(required)}**"
            )

        remaining = max(0, required - int(current))

        return (
            f"{icon} **{name}**\n"
            f"Current: **{self.format_number(current)}**\n"
            f"Required: **{self.format_number(required)}**\n"
            f"Still needed: **{self.format_number(remaining)}**"
        )

    async def build_upgrade_embed(self, tracker: dict, public: bool = True):
        upgrade_name = tracker.get("upgrade_name", "Unknown upgrade")
        progress = self.format_pct(float(tracker.get("progress_pct", 0)))
        estimated_cost = self.format_gold(int(tracker.get("estimated_remaining_cost", 0)))
        unknown_prices = int(tracker.get("unknown_price_count", 0))
        poll_interval = self.get_poll_interval()
        started_by_text = await self.format_started_by(tracker, include_id=False)

        embed = discord.Embed(
            title="🏗️ Guild Upgrade Project",
            color=0xC79C38,
            timestamp=datetime.now(timezone.utc)
        )

        description = (
            f"We are currently working toward:\n\n"
            f"**{upgrade_name}**\n\n"
            f"Every contribution helps push this upgrade forward.\n"
            f"Deposited treasury materials are tracked automatically by the bot.\n\n"
            f"📊 Depositable material progress: **{progress}**\n"
            f"💰 Estimated remaining TP buyout: **{estimated_cost}**\n"
            f"🔄 Auto-refresh: **Every {poll_interval} minutes**"
        )

        if public is False:
            description += f"\n{started_by_text}"

        if unknown_prices > 0:
            description += f"\n⚠️ Items without TP price: **{unknown_prices}**"

        embed.description = description

        items = tracker.get("items", [])
        guild_resources = tracker.get("guild_resources", [])

        needed_items = [
            item for item in items
            if int(item.get("remaining", 0)) > 0
        ]

        completed_items = [
            item for item in items
            if int(item.get("remaining", 0)) <= 0
        ]

        if needed_items:
            needed_blocks = [
                self.build_needed_item_block(item)
                for item in needed_items
            ]
            needed_chunks = self.chunk_lines(needed_blocks, max_length=1000)

            for index, chunk in enumerate(needed_chunks[:20], 1):
                field_name = "📦 Materials Still Needed" if index == 1 else f"📦 Materials Still Needed ({index})"

                embed.add_field(
                    name=field_name,
                    value=chunk,
                    inline=False
                )

            if len(needed_chunks) > 20:
                embed.add_field(
                    name="⚠️ Output truncated",
                    value="Some needed materials were hidden because Discord embeds have field limits.",
                    inline=False
                )
        else:
            embed.add_field(
                name="📦 Materials Still Needed",
                value="✅ No remaining depositable materials needed.",
                inline=False
            )

        if guild_resources:
            resource_lines = [
                self.build_guild_resource_line(resource)
                for resource in guild_resources
            ]

            resource_lines.append("")
            resource_lines.append("*Guild resources are generated/managed by the guild, not deposited directly by players.*")

            resource_chunks = self.chunk_lines(resource_lines, max_length=1000)

            for index, chunk in enumerate(resource_chunks[:3], 1):
                field_name = "🏛️ Guild Resources" if index == 1 else f"🏛️ Guild Resources ({index})"

                embed.add_field(
                    name=field_name,
                    value=chunk,
                    inline=False
                )

        if completed_items:
            completed_lines = [
                self.build_completed_item_line(item)
                for item in completed_items
            ]
            completed_chunks = self.chunk_lines(completed_lines, max_length=1000)

            for index, chunk in enumerate(completed_chunks[:3], 1):
                field_name = "✅ Completed Materials" if index == 1 else f"✅ Completed Materials ({index})"

                embed.add_field(
                    name=field_name,
                    value=chunk,
                    inline=False
                )

        embed.add_field(
            name="💡 How to help",
            value=(
                "Deposit the listed materials into the guild treasury.\n"
                "The bot will update this post automatically as progress changes."
            ),
            inline=False
        )

        last_refresh = self.format_refresh_time(tracker.get("last_refresh"))
        embed.set_footer(text=f"Last updated: {last_refresh}")

        return embed

    async def build_completed_upgrade_embed(self, tracker: dict):
        upgrade_name = tracker.get("upgrade_name", "Unknown upgrade")
        completed_at = tracker.get("completed_at") or self.now_iso()

        embed = discord.Embed(
            title="✅ Guild Upgrade Completed",
            color=0x2ECC71,
            timestamp=datetime.now(timezone.utc)
        )

        embed.description = (
            f"The guild upgrade project has been completed:\n\n"
            f"**{upgrade_name}**\n\n"
            f"Nice work everyone. 🎉"
        )

        started_by = tracker.get("started_by")

        if started_by is not None:
            started_by_text = await self.format_started_by(
                tracker,
                include_id=False
            )

            embed.add_field(
                name="Started by",
                value=started_by_text.replace("Started by: ", ""),
                inline=False
            )

        embed.set_footer(
            text=f"Completed: {self.format_refresh_time(completed_at)}"
        )

        return embed

    def build_list_message(self, entries, show_all: bool, search: Optional[str], hidden_count: int):
        if not entries:
            if show_all:
                return "ℹ️ No available guild upgrades found."
            return (
                "ℹ️ No major available guild upgrades found.\n"
                "Try `/guild_upgrade list show_all:true` to view the raw list."
            )

        title = "🏗️ **Available Guild Upgrades**"
        mode = "Raw list" if show_all else "Major upgrades only"

        lines = [
            title,
            f"Mode: **{mode}**",
        ]

        if search:
            lines.append(f"Search: **{search}**")

        if not show_all and hidden_count > 0:
            lines.append(f"Hidden small/noisy upgrades: **{hidden_count}**")

        lines.extend(
            [
                "",
                "Use `/guild_upgrade start number:<number>` to prepare a tracker.",
                ""
            ]
        )

        for entry in entries:
            lines.append(
                f"**{entry['number']}.** {entry['name']} — "
                f"{self.format_pct(entry['progress_pct'])} depositable materials ready"
            )

        return "\n".join(lines)

    async def get_configured_channel(self):
        channel_id = self.get_upgrade_channel_id()

        if not channel_id:
            return None

        channel = self.bot.get_channel(int(channel_id))

        if channel is not None:
            return channel

        try:
            return await self.bot.fetch_channel(int(channel_id))
        except Exception:
            return None

    async def fetch_upgrade_message(self, tracker: dict):
        channel_id = tracker.get("channel_id")
        message_id = tracker.get("message_id")

        if not channel_id or not message_id:
            return None

        channel = self.bot.get_channel(int(channel_id))

        if channel is None:
            try:
                channel = await self.bot.fetch_channel(int(channel_id))
            except Exception:
                return None

        try:
            return await channel.fetch_message(int(message_id))
        except discord.NotFound:
            return None
        except Exception:
            return None

    async def post_upgrade_message(self, tracker: dict):
        channel = await self.get_configured_channel()

        if channel is None:
            raise Exception("No valid guild upgrade channel configured.")

        embed = await self.build_upgrade_embed(tracker, public=True)
        message = await channel.send(embed=embed)

        tracker["channel_id"] = channel.id
        tracker["message_id"] = message.id

        self.save_state(tracker)

        return message

    async def edit_upgrade_message(self, tracker: dict):
        message = await self.fetch_upgrade_message(tracker)

        if message is None:
            return False

        try:
            embed = await self.build_upgrade_embed(tracker, public=True)
            await message.edit(embed=embed)
            return True
        except Exception:
            return False

    async def edit_upgrade_message_completed(self, tracker: dict):
        message = await self.fetch_upgrade_message(tracker)

        if message is None:
            return False

        try:
            embed = await self.build_completed_upgrade_embed(tracker)
            await message.edit(embed=embed)
            return True
        except Exception:
            return False

    async def delete_upgrade_message(self, tracker: dict):
        message = await self.fetch_upgrade_message(tracker)

        if message is None:
            return True

        try:
            await message.delete()
            return True
        except discord.NotFound:
            return True
        except Exception:
            return False

    async def complete_active_upgrade(self, state: dict):
        completed_state = dict(state)
        completed_state["active"] = False
        completed_state["completed"] = True
        completed_state["completed_at"] = self.now_iso()
        completed_state["last_refresh"] = self.now_iso()

        edited = await self.edit_upgrade_message_completed(completed_state)
        self.save_state(completed_state)

        return completed_state, edited

    async def refresh_active_tracker(self) -> str:
        state = self.load_state()

        if not state.get("active"):
            return "ℹ️ No active guild upgrade tracker."

        upgrade_id = int(state["upgrade_id"])

        if await self.is_upgrade_completed(upgrade_id):
            completed_state, edited = await self.complete_active_upgrade(state)

            if edited:
                return (
                    f"✅ **{completed_state.get('upgrade_name', 'Unknown')}** is complete.\n"
                    f"The public post has been updated to Completed."
                )

            return (
                f"✅ **{completed_state.get('upgrade_name', 'Unknown')}** is complete,\n"
                f"but I could not edit the public post."
            )

        refreshed = await self.build_upgrade_tracker(
            upgrade_id=upgrade_id,
            list_number=state.get("list_number")
        )

        refreshed["channel_id"] = state.get("channel_id")
        refreshed["message_id"] = state.get("message_id")
        refreshed["started_by"] = state.get("started_by")
        refreshed["started_at"] = state.get("started_at")

        self.save_state(refreshed)

        edited = await self.edit_upgrade_message(refreshed)

        if edited:
            return f"✅ Refreshed and updated public post for **{refreshed['upgrade_name']}**."

        return f"⚠️ Refreshed data for **{refreshed['upgrade_name']}**, but could not edit the public post."


    # ========================================================
    # PANEL-CALLABLE BACKEND METHODS
    # ========================================================
    def split_long_text(self, message: str, max_length: int = 1900):
        chunks = []
        current = ""

        for line in str(message or "").splitlines():
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

    async def get_available_upgrade_entries(
        self,
        show_all: bool = False,
        search: Optional[str] = None,
        limit: int = 25,
    ):
        limit = max(5, min(int(limit), 75))

        all_upgrades = await self.fetch_all_upgrades()
        owned_ids = set(await self.fetch_owned_upgrade_ids())
        treasury = await self.fetch_treasury()
        treasury_counts = self.get_treasury_counts(treasury)

        available = []
        hidden_count = 0

        for upgrade in all_upgrades:
            if not self.is_upgrade_available(upgrade, owned_ids):
                continue

            if not self.matches_search(upgrade, search):
                continue

            is_major = self.is_major_upgrade(upgrade)

            if not show_all and not is_major:
                hidden_count += 1
                continue

            progress = self.calculate_upgrade_progress(upgrade, treasury_counts)

            available.append(
                {
                    "upgrade_id": int(upgrade.get("id")),
                    "name": upgrade.get("name", f"Upgrade #{upgrade.get('id')}"),
                    "type": upgrade.get("type", "Unknown"),
                    "progress_pct": progress,
                    "is_major": is_major,
                }
            )

        available.sort(
            key=lambda entry: (
                entry["progress_pct"],
                entry["name"].lower(),
            ),
            reverse=True,
        )

        available = available[:limit]

        entries = []

        for index, entry in enumerate(available, 1):
            entries.append(
                {
                    "number": index,
                    "upgrade_id": entry["upgrade_id"],
                    "name": entry["name"],
                    "type": entry["type"],
                    "progress_pct": entry["progress_pct"],
                    "is_major": entry["is_major"],
                }
            )

        cache = {
            "generated_at": self.now_iso(),
            "show_all": show_all,
            "search": search,
            "limit": limit,
            "hidden_count": hidden_count,
            "entries": entries,
        }

        self.save_cache(cache)

        return entries, hidden_count

    async def build_upgrade_list_output(
        self,
        search: Optional[str] = None,
        show_all: bool = False,
        limit: int = 25,
    ):
        try:
            entries, hidden_count = await self.get_available_upgrade_entries(
                show_all=show_all,
                search=search,
                limit=limit,
            )

            message = self.build_list_message(
                entries=entries,
                show_all=show_all,
                search=search,
                hidden_count=hidden_count,
            )

            return self.split_long_text(message)

        except Exception as error:
            return self.friendly_error_message(error)

    async def list_upgrades_for_panel(
        self,
        search: Optional[str] = None,
        show_all: bool = False,
        limit: int = 25,
    ):
        return await self.build_upgrade_list_output(
            search=search,
            show_all=show_all,
            limit=limit,
        )

    def get_panel_pending_key(self, user_id: Optional[int] = None) -> str:
        if user_id is None:
            return "panel"

        return str(user_id)

    async def start_upgrade_from_panel(
        self,
        number: int,
        user_id: Optional[int] = None,
    ):
        try:
            state = self.load_state()

            if state.get("active"):
                return "❌ A guild upgrade tracker is already active. End it before starting another."

            cache = self.load_cache()
            entries = cache.get("entries", [])

            selected = None

            for entry in entries:
                if int(entry.get("number")) == int(number):
                    selected = entry
                    break

            if selected is None:
                return "❌ That number was not found. Use **Search/List** again first."

            tracker = await self.build_upgrade_tracker(
                upgrade_id=int(selected["upgrade_id"]),
                list_number=int(number),
            )

            if user_id is not None:
                tracker["started_by"] = int(user_id)
            else:
                tracker["started_by"] = None

            pending = self.load_pending()
            pending[self.get_panel_pending_key(user_id)] = {
                "created_at": self.now_iso(),
                "number": int(number),
                "upgrade_id": tracker["upgrade_id"],
                "tracker": tracker,
                "source": "vr_bot_admin_panel",
            }
            self.save_pending(pending)

            embed = await self.build_upgrade_embed(tracker, public=False)

            message = (
                f"✅ Prepared upgrade tracker for **#{number} {tracker['upgrade_name']}**.\n"
                f"Review the preview below.\n\n"
                f"Use **Confirm** with number **{number}** to publish it."
            )

            return [message, embed]

        except Exception as error:
            return self.friendly_error_message(error)

    async def start_upgrade_by_number(self, number: int):
        return await self.start_upgrade_from_panel(number=number)

    async def panel_start_upgrade(self, number: int):
        return await self.start_upgrade_from_panel(number=number)

    async def confirm_upgrade_from_panel(
        self,
        number: int,
        user_id: Optional[int] = None,
    ):
        try:
            state = self.load_state()

            if state.get("active"):
                return "❌ A guild upgrade tracker is already active. End it before starting another."

            channel_id = self.get_upgrade_channel_id()

            if not channel_id:
                return "❌ No guild upgrade channel configured. Use **Set Channel** first."

            pending = self.load_pending()
            user_pending = pending.get(self.get_panel_pending_key(user_id))

            if not user_pending and user_id is not None:
                user_pending = pending.get("panel")

            if not user_pending:
                return "❌ No pending upgrade preview found. Use **Start** first."

            prepared_number = int(user_pending.get("number"))

            if prepared_number != int(number):
                return (
                    f"❌ Confirmation number does not match.\n"
                    f"Prepared: **#{prepared_number}**\n"
                    f"You entered: **#{number}**"
                )

            cache = self.load_cache()
            cached_entry = None

            for entry in cache.get("entries", []):
                if int(entry.get("number")) == int(number):
                    cached_entry = entry
                    break

            if cached_entry is None:
                return "❌ Cached list entry no longer exists. Use **Search/List** again."

            if int(cached_entry["upgrade_id"]) != int(user_pending["upgrade_id"]):
                return "❌ Cached upgrade no longer matches the pending preview. Use **Search/List** again."

            tracker = await self.build_upgrade_tracker(
                upgrade_id=int(user_pending["upgrade_id"]),
                list_number=int(number),
            )

            if user_id is not None:
                tracker["started_by"] = int(user_id)
            else:
                tracker["started_by"] = user_pending.get("tracker", {}).get("started_by")

            tracker["started_at"] = self.now_iso()

            message = await self.post_upgrade_message(tracker)

            pending.pop(self.get_panel_pending_key(user_id), None)

            if user_id is not None:
                pending.pop("panel", None)

            self.save_pending(pending)

            if tracker.get("started_by") is not None:
                starter = await self.format_discord_user(int(tracker["started_by"]))
                started_by_text = f"Started by: ✅ {starter}\n"
            else:
                started_by_text = "Started by: ⚠️ Unknown\n"

            return (
                f"✅ Guild upgrade tracker posted for **#{number} {tracker['upgrade_name']}**.\n"
                f"{started_by_text}"
                f"Channel: <#{message.channel.id}>"
            )

        except Exception as error:
            return self.friendly_error_message(error)

    async def confirm_upgrade_by_number(self, number: int):
        return await self.confirm_upgrade_from_panel(number=number)

    async def panel_confirm_upgrade(self, number: int):
        return await self.confirm_upgrade_from_panel(number=number)

    async def set_upgrade_channel_from_panel(self, channel_id: int):
        try:
            channel = self.bot.get_channel(int(channel_id))

            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(int(channel_id))
                except Exception:
                    return "❌ I could not find that channel. Make sure the ID is correct and the bot can see it."

            self.set_upgrade_channel_id(int(channel_id))

            return f"✅ Guild upgrade channel set to {channel.mention}."

        except Exception as error:
            return self.friendly_error_message(error)

    def set_channel(self, channel_id: int):
        self.set_upgrade_channel_id(int(channel_id))
        return f"✅ Guild upgrade channel set to <#{int(channel_id)}>"


    @tasks.loop(minutes=10)
    async def auto_refresh(self):
        await self.bot.wait_until_ready()

        state = self.load_state()

        if not state.get("active"):
            return

        try:
            upgrade_id = int(state["upgrade_id"])

            if await self.is_upgrade_completed(upgrade_id):
                completed_state, edited = await self.complete_active_upgrade(state)

                if edited:
                    print(
                        f"✅ Guild upgrade completed and public post updated: "
                        f"{completed_state.get('upgrade_name', 'Unknown')}"
                    )
                else:
                    print(
                        f"⚠️ Guild upgrade completed, but public post could not be updated: "
                        f"{completed_state.get('upgrade_name', 'Unknown')}"
                    )

                return

            refreshed = await self.build_upgrade_tracker(
                upgrade_id=upgrade_id,
                list_number=state.get("list_number")
            )

            refreshed["channel_id"] = state.get("channel_id")
            refreshed["message_id"] = state.get("message_id")
            refreshed["started_by"] = state.get("started_by")
            refreshed["started_at"] = state.get("started_at")

            self.save_state(refreshed)
            edited = await self.edit_upgrade_message(refreshed)

            if edited:
                print(
                    f"🏗️ Guild upgrade auto-refresh complete: "
                    f"{refreshed.get('upgrade_name', 'Unknown')}"
                )
            else:
                print("⚠️ Guild upgrade auto-refresh completed, but message edit failed.")

        except Exception as e:
            print(f"❌ Guild upgrade auto-refresh error: {e}")

    @auto_refresh.before_loop
    async def before_auto_refresh(self):
        await self.bot.wait_until_ready()

async def setup(bot: commands.Bot):
    await bot.add_cog(GuildUpgrades(bot))