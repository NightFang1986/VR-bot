import json
import logging
import os
from typing import Any, Dict, Iterable, List, Optional

import aiohttp


logger = logging.getLogger(__name__)


CONFIG_FILE = "config.json"
GW2_API_BASE = "https://api.guildwars2.com/v2"
DEFAULT_BATCH_SIZE = 200


class GW2APIError(Exception):
    """Raised when the GW2 API returns an error response."""

    def __init__(
        self,
        message: str,
        status: Optional[int] = None,
        reason: Optional[str] = None,
        body: Optional[str] = None,
    ):
        super().__init__(message)
        self.status = status
        self.reason = reason
        self.body = body


class GW2ConfigError(Exception):
    """Raised when required GW2 config values are missing."""


class GW2API:
    """
    Shared GW2 API wrapper.

    Handles:
    - config loading
    - API key / guild ID access
    - aiohttp session lifecycle
    - authenticated and public GET requests
    - common guild endpoints
    - batched item and price lookups

    Notes:
    - GW2 can return HTTP 206 Partial Content for batch endpoints when some IDs
      are valid and some are unavailable. For bot output, partial data is still useful.
    """

    def __init__(
        self,
        *,
        config_file: str = CONFIG_FILE,
        api_base: str = GW2_API_BASE,
        session: Optional[aiohttp.ClientSession] = None,
    ):
        self.config_file = config_file
        self.api_base = api_base.rstrip("/")

        self.config = self.load_config()

        self.api_key: Optional[str] = self.config.get("GW2_API_KEY")
        self.guild_id: Optional[str] = self.config.get("GUILD_ID")

        self.session: Optional[aiohttp.ClientSession] = session
        self.created_own_session = session is None

    # =========================
    # CONFIG
    # =========================
    def load_config(self) -> Dict[str, Any]:
        if not os.path.exists(self.config_file):
            logger.error("%s not found.", self.config_file)
            return {}

        try:
            with open(self.config_file, "r") as f:
                return json.load(f)
        except Exception as error:
            logger.exception("Failed to load %s: %s", self.config_file, error)
            return {}

    def require_api_key(self) -> str:
        if not self.api_key:
            raise GW2ConfigError(
                "GW2 API key is missing from config.json. Expected key: GW2_API_KEY"
            )

        return self.api_key

    def require_guild_id(self) -> str:
        if not self.guild_id:
            raise GW2ConfigError(
                "GW2 guild ID is missing from config.json. Expected key: GUILD_ID"
            )

        return self.guild_id

    # =========================
    # SESSION LIFECYCLE
    # =========================
    async def ensure_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
            self.created_own_session = True

    async def close(self):
        if (
            self.created_own_session
            and self.session is not None
            and not self.session.closed
        ):
            await self.session.close()

    async def __aenter__(self):
        await self.ensure_session()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    # =========================
    # CORE REQUESTS
    # =========================
    async def get(
        self,
        endpoint: str,
        *,
        auth: bool = False,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        await self.ensure_session()

        endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        url = f"{self.api_base}{endpoint}"

        headers = {}

        if auth:
            headers["Authorization"] = f"Bearer {self.require_api_key()}"

        async with self.session.get(url, headers=headers, params=params) as response:
            body = await response.text()

            if response.status in (200, 206):
                try:
                    return json.loads(body) if body else None
                except Exception:
                    raise GW2APIError(
                        message=(
                            f"GW2 API returned invalid JSON: "
                            f"{response.status} {response.reason} - {body}"
                        ),
                        status=response.status,
                        reason=response.reason,
                        body=body,
                    )

            raise GW2APIError(
                message=(
                    f"GW2 API request failed: "
                    f"{response.status} {response.reason} - {body}"
                ),
                status=response.status,
                reason=response.reason,
                body=body,
            )

    async def get_authenticated(
        self,
        endpoint: str,
        *,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        return await self.get(endpoint, auth=True, params=params)

    async def get_public(
        self,
        endpoint: str,
        *,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        return await self.get(endpoint, auth=False, params=params)

    # =========================
    # GUILD ENDPOINTS
    # =========================
    async def get_guild_details(self) -> Dict[str, Any]:
        guild_id = self.require_guild_id()
        data = await self.get_authenticated(f"/guild/{guild_id}")
        return data if isinstance(data, dict) else {}

    async def get_guild_members(self) -> List[Dict[str, Any]]:
        guild_id = self.require_guild_id()
        data = await self.get_authenticated(f"/guild/{guild_id}/members")
        return data if isinstance(data, list) else []

    async def get_guild_log(self, since: Optional[int] = None) -> List[Dict[str, Any]]:
        guild_id = self.require_guild_id()

        params = {}

        if since is not None:
            params["since"] = since

        data = await self.get_authenticated(f"/guild/{guild_id}/log", params=params)
        return data if isinstance(data, list) else []

    async def get_guild_treasury(self) -> List[Dict[str, Any]]:
        guild_id = self.require_guild_id()
        data = await self.get_authenticated(f"/guild/{guild_id}/treasury")
        return data if isinstance(data, list) else []

    async def get_guild_stash(self) -> List[Dict[str, Any]]:
        guild_id = self.require_guild_id()
        data = await self.get_authenticated(f"/guild/{guild_id}/stash")
        return data if isinstance(data, list) else []

    async def get_owned_guild_upgrade_ids(self) -> List[int]:
        guild_id = self.require_guild_id()
        data = await self.get_authenticated(f"/guild/{guild_id}/upgrades")
        return data if isinstance(data, list) else []

    async def get_all_guild_upgrades(self) -> List[Dict[str, Any]]:
        data = await self.get_public("/guild/upgrades", params={"ids": "all"})
        return data if isinstance(data, list) else []

    # =========================
    # ITEMS / PRICES
    # =========================
    def clean_ids(self, ids: Iterable[int]) -> List[int]:
        cleaned = []

        for value in ids:
            if value is None:
                continue

            try:
                cleaned.append(int(value))
            except Exception:
                continue

        return sorted(set(cleaned))

    def chunk_ids(
        self,
        ids: Iterable[int],
        *,
        chunk_size: int = DEFAULT_BATCH_SIZE,
    ) -> List[List[int]]:
        cleaned = self.clean_ids(ids)

        return [
            cleaned[index:index + chunk_size]
            for index in range(0, len(cleaned), chunk_size)
        ]

    async def get_items(self, item_ids: Iterable[int]) -> Dict[int, Dict[str, Any]]:
        results: Dict[int, Dict[str, Any]] = {}

        for chunk in self.chunk_ids(item_ids):
            ids_param = ",".join(str(item_id) for item_id in chunk)

            try:
                items = await self.get_public("/items", params={"ids": ids_param})
            except Exception as error:
                logger.warning("Failed to fetch item chunk %s: %s", chunk, error)
                continue

            if not isinstance(items, list):
                continue

            for item in items:
                item_id = item.get("id")

                if item_id is not None:
                    results[int(item_id)] = item

        return results

    async def get_item_names(self, item_ids: Iterable[int]) -> Dict[int, str]:
        items = await self.get_items(item_ids)

        return {
            item_id: item.get("name", f"Unknown Item {item_id}")
            for item_id, item in items.items()
        }

    async def get_prices(self, item_ids: Iterable[int]) -> Dict[int, Dict[str, Any]]:
        results: Dict[int, Dict[str, Any]] = {}

        for chunk in self.chunk_ids(item_ids):
            ids_param = ",".join(str(item_id) for item_id in chunk)

            try:
                prices = await self.get_public(
                    "/commerce/prices",
                    params={"ids": ids_param}
                )
            except Exception as error:
                logger.warning("Failed to fetch price chunk %s: %s", chunk, error)
                continue

            if not isinstance(prices, list):
                continue

            for price in prices:
                item_id = price.get("id")

                if item_id is not None:
                    results[int(item_id)] = price

        return results