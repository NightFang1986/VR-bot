import math
import json
import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

import aiohttp
import discord
from discord.ext import commands


logger = logging.getLogger(__name__)


CONFIG_FILE = "config.json"
GW2_API_BASE = "https://api.guildwars2.com/v2"
MAX_STACK_SIZE = 250


class GuildBankDuplicates(commands.Cog):
    """
    Checks the GW2 guild bank for unnecessary split stacks.

    Behavior:
        - Admin only
        - Ephemeral
        - Scans all guild stash tabs
        - Reports only items where actual stacks > required stacks
        - Does not report valid full stacks like 250 + 250
        - Assumes normal GW2 max stack size of 250
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        config = self.load_config()

        self.gw2_api_key: Optional[str] = config.get("GW2_API_KEY")
        self.guild_id: Optional[str] = config.get("GUILD_ID")

        self.session: Optional[aiohttp.ClientSession] = None
        self.created_own_session = False

    # =========================
    # CONFIG
    # =========================
    def load_config(self) -> Dict[str, Any]:
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error("config.json not found.")
            return {}
        except Exception as error:
            logger.exception("Failed to load config.json: %s", error)
            return {}

    # =========================
    # SESSION LIFECYCLE
    # =========================
    async def cog_load(self):
        bot_session = getattr(self.bot, "session", None)

        if bot_session is not None and not bot_session.closed:
            self.session = bot_session
            self.created_own_session = False
            return

        self.session = aiohttp.ClientSession()
        self.created_own_session = True

    async def cog_unload(self):
        if (
            self.created_own_session
            and self.session is not None
            and not self.session.closed
        ):
            await self.session.close()

    async def ensure_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
            self.created_own_session = True

    # =========================
    # GW2 API
    # =========================
    async def gw2_get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None
    ) -> Any:
        if not self.gw2_api_key:
            raise RuntimeError("Missing GW2 API key.")

        await self.ensure_session()

        headers = {
            "Authorization": f"Bearer {self.gw2_api_key}"
        }

        url = f"{GW2_API_BASE}{endpoint}"

        async with self.session.get(url, headers=headers, params=params) as response:
            if response.status == 200:
                return await response.json()

            text = await response.text()

            raise RuntimeError(
                f"GW2 API request failed: {response.status} {response.reason} - {text}"
            )

    async def fetch_guild_stash(self) -> List[Dict[str, Any]]:
        if not self.guild_id:
            raise RuntimeError("Missing GW2 guild ID.")

        return await self.gw2_get(f"/guild/{self.guild_id}/stash")

    async def fetch_item_names(self, item_ids: List[int]) -> Dict[int, str]:
        """
        Fetch item names from /v2/items in chunks.
        """
        if not item_ids:
            return {}

        item_names: Dict[int, str] = {}
        unique_ids = sorted(set(int(item_id) for item_id in item_ids))
        chunk_size = 200

        for i in range(0, len(unique_ids), chunk_size):
            chunk = unique_ids[i:i + chunk_size]
            ids_param = ",".join(str(item_id) for item_id in chunk)

            try:
                items = await self.gw2_get("/items", params={"ids": ids_param})
            except Exception as error:
                logger.warning("Failed to fetch item names for chunk %s: %s", chunk, error)
                continue

            for item in items:
                item_id = item.get("id")
                name = item.get("name", f"Unknown Item {item_id}")

                if item_id is not None:
                    item_names[int(item_id)] = name

        return item_names

    # =========================
    # DUPLICATE DETECTION
    # =========================
    def collect_stash_items(
        self,
        stash_tabs: List[Dict[str, Any]]
    ) -> Dict[int, Dict[str, Any]]:
        """
        Groups all guild stash items by item_id.

        Output:
        {
            item_id: {
                "total": int,
                "stacks": [
                    {
                        "tab_name": str,
                        "slot": int,
                        "count": int,
                    }
                ]
            }
        }
        """
        grouped: Dict[int, Dict[str, Any]] = defaultdict(
            lambda: {
                "total": 0,
                "stacks": []
            }
        )

        for tab in stash_tabs:
            tab_name = tab.get("name") or "Unknown Tab"
            inventory = tab.get("inventory") or []

            for slot_index, slot in enumerate(inventory):
                if not slot:
                    continue

                item_id = slot.get("id")
                count = int(slot.get("count", 0))

                if item_id is None or count <= 0:
                    continue

                item_id = int(item_id)

                grouped[item_id]["total"] += count
                grouped[item_id]["stacks"].append(
                    {
                        "tab_name": tab_name,
                        "slot": slot_index + 1,
                        "count": count,
                    }
                )

        return grouped

    def find_mergeable_duplicates(
        self,
        grouped_items: Dict[int, Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Reports only items that use more stacks than needed.

        Examples:
            250 + 250 = total 500
            required_stacks = 2
            actual_stacks = 2
            Not reported.

            100 + 100 = total 200
            required_stacks = 1
            actual_stacks = 2
            Reported.
        """
        duplicates: List[Dict[str, Any]] = []

        for item_id, data in grouped_items.items():
            total = int(data["total"])
            stacks = data["stacks"]

            actual_stacks = len(stacks)
            required_stacks = math.ceil(total / MAX_STACK_SIZE)

            if actual_stacks <= required_stacks:
                continue

            duplicates.append(
                {
                    "item_id": item_id,
                    "total": total,
                    "actual_stacks": actual_stacks,
                    "required_stacks": required_stacks,
                    "wasted_slots": actual_stacks - required_stacks,
                    "stacks": stacks,
                }
            )

        duplicates.sort(
            key=lambda item: (
                item["wasted_slots"],
                item["actual_stacks"],
                item["total"],
            ),
            reverse=True,
        )

        return duplicates

    # =========================
    # EMBEDS
    # =========================
    def build_no_duplicates_embed(self) -> discord.Embed:
        return discord.Embed(
            title="✅ Guild Bank Stack Check",
            description=(
                "No unnecessary split stacks found.\n"
                "Everything is already stacked efficiently."
            ),
            color=discord.Color.green(),
        )

    def build_duplicate_embeds(
        self,
        duplicates: List[Dict[str, Any]],
        item_names: Dict[int, str],
    ) -> List[discord.Embed]:
        if not duplicates:
            return [self.build_no_duplicates_embed()]

        total_freeable_slots = sum(item["wasted_slots"] for item in duplicates)

        header = (
            f"Found **{len(duplicates)}** item type(s) with unnecessary split stacks.\n"
            f"Potentially freeable slots: **{total_freeable_slots}**\n"
            f"Max stack size used: **{MAX_STACK_SIZE}**"
        )

        embeds: List[discord.Embed] = []

        current_embed = discord.Embed(
            title="🧹 Guild Bank Stack Check",
            description=header,
            color=discord.Color.orange(),
        )

        field_count = 0

        for duplicate in duplicates:
            item_id = int(duplicate["item_id"])
            item_name = item_names.get(item_id, f"Unknown Item {item_id}")

            total = int(duplicate["total"])
            actual_stacks = int(duplicate["actual_stacks"])
            required_stacks = int(duplicate["required_stacks"])
            wasted_slots = int(duplicate["wasted_slots"])

            field_name = f"{item_name} — x{total}"

            stack_lines = []

            for stack in sorted(
                duplicate["stacks"],
                key=lambda stack_data: (
                    stack_data["tab_name"],
                    stack_data["slot"]
                )
            ):
                stack_lines.append(
                    f"• {stack['tab_name']}: slot {stack['slot']} — x{stack['count']}"
                )

            field_value = (
                f"Stacks: **{actual_stacks}**, should fit in **{required_stacks}**\n"
                f"Freeable slot(s): **{wasted_slots}**\n"
                + "\n".join(stack_lines)
            )

            if len(field_value) > 1024:
                field_value = field_value[:1000].rstrip() + "\n…"

            # Keep pages readable and safely below Discord embed field limits.
            if field_count >= 8:
                embeds.append(current_embed)

                current_embed = discord.Embed(
                    title="🧹 Guild Bank Stack Check — Continued",
                    color=discord.Color.orange(),
                )
                field_count = 0

            current_embed.add_field(
                name=field_name[:256],
                value=field_value,
                inline=False,
            )
            field_count += 1

        if field_count > 0:
            embeds.append(current_embed)

        for index, embed in enumerate(embeds, start=1):
            embed.set_footer(
                text=(
                    f"Page {index}/{len(embeds)} • "
                    f"Potentially freeable slots: {total_freeable_slots}"
                )
            )

        return embeds


async def setup(bot: commands.Bot):
    await bot.add_cog(GuildBankDuplicates(bot))
