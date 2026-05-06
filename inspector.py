import asyncio
import html
import logging
import re
from typing import Any
from urllib.parse import quote

import aiohttp

from app.config import settings
from app.models import Gem, Listing

APP_ID = 570
CURRENCY_USD = 1


def parse_price_to_usd(price_text: str) -> float:
    cleaned = (
        price_text.replace("$", "")
        .replace("USD", "")
        .replace(" ", "")
        .replace(",", ".")
        .strip()
    )
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def build_market_url(market_hash_name: str) -> str:
    return f"https://steamcommunity.com/market/listings/{APP_ID}/{quote(market_hash_name, safe='')}"


def build_search_url(market_hash_name: str) -> str:
    return (
        "https://steamcommunity.com/market/search"
        f"?appid={APP_ID}&q={quote(market_hash_name, safe='')}"
    )

GEM_VALUE_SEPARATOR = r"(?:[:\-]|\n|\r)+"
SOCKET_GEM_PATTERNS = (
    (
        re.compile(rf"\bKinetic(?:\s+Gem)?\s*{GEM_VALUE_SEPARATOR}\s*([^\n\r<]+)", re.IGNORECASE),
        "Kinetic Gem - {name}",
    ),
    (
        re.compile(rf"\bEthereal(?:\s+Gem)?\s*{GEM_VALUE_SEPARATOR}\s*([^\n\r<]+)", re.IGNORECASE),
        "Ethereal Gem - {name}",
    ),
    (
        re.compile(rf"\bPrismatic(?:\s+Gem)?\s*{GEM_VALUE_SEPARATOR}\s*([^\n\r<]+)", re.IGNORECASE),
        "Prismatic Gem - {name}",
    ),
    (
        re.compile(
            rf"\bAutograph(?:ed)?(?:\s+Rune)?\s*{GEM_VALUE_SEPARATOR}\s*([^\n\r<]+)",
            re.IGNORECASE,
        ),
        "Autograph Rune - {name}",
    ),
    (
        re.compile(rf"\bInscribed(?:\s+Gem)?\s*{GEM_VALUE_SEPARATOR}\s*([^\n\r<]+)", re.IGNORECASE),
        "Inscribed Gem - {name}",
    ),
)
TAG_RE = re.compile(r"<[^>]+>")
GEM_PRICE_CACHE: dict[str, float] = {}
GEM_NAME_STOP_RE = re.compile(
    r"(?:socket|gem type|quality|hero|used by|wearable| |\$|marketable|tradable)",
    re.IGNORECASE,
)


def strip_html(value: str) -> str:
    without_tags = TAG_RE.sub("\n", value)
    return html.unescape(without_tags)


def clean_gem_name(raw_name: str) -> str:
    cleaned = strip_html(raw_name)
    cleaned = re.split(r"(?:\s{2,}|\n|\r|<|>|\||•)", cleaned, maxsplit=1)[0]
    cleaned = GEM_NAME_STOP_RE.split(cleaned, maxsplit=1)[0]
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip(" .:-—–\t")
    if not cleaned or len(cleaned) > 80:
        return ""
    if cleaned.lower() in {"empty", "none", "socket", "gem"}:
        return ""
    return cleaned


def iter_description_values(descriptions) -> list[str]:
    values: list[str] = []
    if isinstance(descriptions, dict):
        descriptions = [descriptions]
    if not isinstance(descriptions, list):
        return values

    for description in descriptions:
        if isinstance(description, dict):
            value = description.get("value", "")
            if isinstance(value, str):
                values.append(value)
        elif isinstance(description, str):
            values.append(description)
        elif isinstance(description, list):
            values.extend(iter_description_values(description))
    return values


def extract_gem_market_names_from_text(text: str) -> list[str]:
    found: list[str] = []
    clean_text = strip_html(text)

    for pattern, template in SOCKET_GEM_PATTERNS:
        for match in pattern.finditer(clean_text):
            gem_name = clean_gem_name(match.group(1))
            if not gem_name:
                continue
            market_name = template.format(name=gem_name)
            if market_name not in found:
                found.append(market_name)

    return found


def extract_gem_market_names_from_asset(asset: dict[str, Any]) -> list[str]:
    names: list[str] = []
    if not isinstance(asset, dict):
        return names

    description_groups = (
        asset.get("descriptions", []),
        asset.get("owner_descriptions", []),
    )
    for descriptions in description_groups:
        for value in iter_description_values(descriptions):
            for gem_name in extract_gem_market_names_from_text(value):
                if gem_name not in names:
                    names.append(gem_name)
    return names


def iter_assets(render_data: dict[str, Any]):
    assets_by_app = render_data.get("assets", {}) if isinstance(render_data, dict) else {}
    if not isinstance(assets_by_app, dict):
        return

    app_assets = assets_by_app.get(str(APP_ID), assets_by_app.get(APP_ID, {}))
    if not isinstance(app_assets, dict):
        return

    for context_assets in app_assets.values():
        if isinstance(context_assets, dict):
            for asset in context_assets.values():
                if isinstance(asset, dict):
                    yield asset
        elif isinstance(context_assets, list):
            for asset in context_assets:
                if isinstance(asset, dict):
                    yield asset


def get_listing_asset(render_data: dict[str, Any], listing_info: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(render_data, dict) or not isinstance(listing_info, dict):
        return None

    asset_ref = listing_info.get("asset", {})
    if not isinstance(asset_ref, dict):
        return None

    asset_id = str(asset_ref.get("id", ""))
    context_id = str(asset_ref.get("contextid", "2"))
    app_id = str(asset_ref.get("appid", APP_ID))
    if not asset_id:
        return None

    assets_by_app = render_data.get("assets", {})
    if not isinstance(assets_by_app, dict):
        return None

    app_assets = assets_by_app.get(app_id, {})
    if not isinstance(app_assets, dict):
        return None

    context_assets = app_assets.get(context_id, {})
    if isinstance(context_assets, dict):
        asset = context_assets.get(asset_id)
        return asset if isinstance(asset, dict) else None

    if isinstance(context_assets, list):
        for asset in context_assets:
            if isinstance(asset, dict) and str(asset.get("id", "")) == asset_id:
                return asset

    return None


def extract_listing_price_usd(listing_info: dict[str, Any], fallback_price: float) -> float:
    converted_price = listing_info.get("converted_price")
    converted_fee = listing_info.get("converted_fee", 0)
    if isinstance(converted_price, int):
        fee = converted_fee if isinstance(converted_fee, int) else 0
        return (converted_price + fee) / 100.0

    price_text = listing_info.get("price") or listing_info.get("converted_price_per_unit")
    if isinstance(price_text, str):
        price = parse_price_to_usd(price_text)
        if price > 0:
            return price

    return fallback_price


async def fetch_listing_render(
    session: aiohttp.ClientSession,
    market_hash_name: str,
    count: int,
) -> dict[str, Any]:
    url = (
        f"https://steamcommunity.com/market/listings/{APP_ID}/{quote(market_hash_name, safe='')}/render/"
        f"?query=&start=0&count={count}&currency={CURRENCY_USD}&language=english"
    )
    retries = max(settings.steam_request_retries, 0)
    for attempt in range(retries + 1):
        try:
            async with session.get(url, timeout=20) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"Steam listing render error {resp.status}: {text[:150]}")
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError) as exc:
            if attempt >= retries:
                raise
            await asyncio.sleep(0.5 * (attempt + 1))
            logging.warning(
                "Retry Steam listing render market_hash_name=%s attempt=%s/%s: %s",
                market_hash_name,
                attempt + 2,
                retries + 1,
                exc,
            )
    return {}


async def fetch_priceoverview(session: aiohttp.ClientSession, market_hash_name: str) -> float:
    if market_hash_name in GEM_PRICE_CACHE:
        return GEM_PRICE_CACHE[market_hash_name]

    url = (
        "https://steamcommunity.com/market/priceoverview/"
        f"?appid={APP_ID}&currency={CURRENCY_USD}&market_hash_name={quote(market_hash_name, safe='')}"
    )
    retries = max(settings.steam_request_retries, 0)
    data = {}
    for attempt in range(retries + 1):
        try:
            async with session.get(url, timeout=20) as resp:
                if resp.status != 200:
                    if resp.status in {429, 500, 502, 503, 504}:
                        raise RuntimeError(f"Steam priceoverview error {resp.status}")
                    GEM_PRICE_CACHE[market_hash_name] = 0.0
                    return 0.0
                data = await resp.json(content_type=None)
                break
        except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError) as exc:
            if attempt >= retries:
                GEM_PRICE_CACHE[market_hash_name] = 0.0
                logging.warning("Steam priceoverview failed for %s: %s", market_hash_name, exc)
                return 0.0
            await asyncio.sleep(0.5 * (attempt + 1))

    price = 0.0
    if data.get("success") and isinstance(data.get("lowest_price"), str):
        price = parse_price_to_usd(data["lowest_price"])
    GEM_PRICE_CACHE[market_hash_name] = price
    return price


async def price_confirmed_gems(
    session: aiohttp.ClientSession,
    gem_market_names: list[str],
    include_unpriced: bool = True,
) -> list[Gem]:
    gems: list[Gem] = []
    for market_name in gem_market_names:
        price = await fetch_priceoverview(session, market_name)
        if price <= 0:
            if include_unpriced:
                gems.append(Gem(name=market_name, market_price=0.0, source="confirmed_unpriced"))
            continue
        gems.append(Gem(name=market_name, market_price=price, source="confirmed"))
    return gems


def summarize_asset(asset: dict[str, Any], prefix: str, max_descriptions: int) -> list[str]:
    item_name = asset.get("market_name") or asset.get("name") or "Unknown item"
    gems = extract_gem_market_names_from_asset(asset)
    lines = [f"{prefix} item={item_name}", f"    extracted_gems={gems or 'none'}"]

    description_groups = (
        ("desc", asset.get("descriptions", [])),
        ("owner_desc", asset.get("owner_descriptions", [])),
    )
    printed = 0
    for label, descriptions in description_groups:
        for value in iter_description_values(descriptions):
            if printed >= max_descriptions:
                break
            if not value.strip():
                continue
            normalized = " ".join(strip_html(value).split())
            if len(normalized) > 300:
                normalized = normalized[:300] + "..."
            lines.append(f"    {label}[{printed + 1}] {normalized}")
            printed += 1
        if printed >= max_descriptions:
            break
    return lines


def summarize_listing_render(render_data: dict[str, Any], max_listings: int = 3, max_descriptions: int = 6) -> list[str]:
    listing_info = render_data.get("listinginfo", {})
    if not isinstance(listing_info, dict):
        listing_info = {}

    lines = [f"listing_count={len(listing_info)}"]
    if listing_info:
        for index, (listing_id, info) in enumerate(listing_info.items(), start=1):
            if index > max_listings:
                break
            if not isinstance(info, dict):
                continue
            asset = get_listing_asset(render_data, info)
            if not asset:
                lines.append(f"[{index}] listing_id={listing_id} asset=missing")
                continue
            lines.extend(summarize_asset(asset, f"[{index}] listing_id={listing_id}", max_descriptions))
        return lines

    assets = list(iter_assets(render_data) or [])
    lines.append(f"asset_count={len(assets)}")
    for index, asset in enumerate(assets[:max_listings], start=1):
        lines.extend(summarize_asset(asset, f"[{index}] asset_only", max_descriptions))
    return lines


async def build_confirmed_listing_from_asset(
    session: aiohttp.ClientSession,
    asset: dict[str, Any],
    listing_id: str,
    market_hash_name: str,
    buy_price: float,
) -> Listing | None:
    gem_market_names = extract_gem_market_names_from_asset(asset)
    if not gem_market_names:
        return None

    gems = await price_confirmed_gems(session, gem_market_names)
    if not gems:
        return None

    item_name = asset.get("market_name") or asset.get("name") or market_hash_name
    return Listing(
        listing_id=listing_id,
        item_name=item_name,
        buy_price=buy_price,
        gems=gems,
        market_hash_name=market_hash_name,
        market_url=build_market_url(market_hash_name),
        search_url=build_search_url(market_hash_name),
        value_source="confirmed",
    )


async def fetch_confirmed_socket_listings(
    session: aiohttp.ClientSession,
    market_hash_name: str,
    fallback_price: float,
    max_listings: int,
) -> list[Listing]:
    render_data = await fetch_listing_render(session, market_hash_name, max_listings)
    listing_info = render_data.get("listinginfo", {})
    if not isinstance(listing_info, dict):
        listing_info = {}

    confirmed: list[Listing] = []
    if listing_info:
        for listing_id, info in listing_info.items():
            if not isinstance(info, dict):
                continue
            asset = get_listing_asset(render_data, info)
            if not asset:
                continue
            buy_price = extract_listing_price_usd(info, fallback_price)
            listing = await build_confirmed_listing_from_asset(
                session,
                asset,
                str(listing_id),
                market_hash_name,
                buy_price,
            )
            if listing:
                confirmed.append(listing)
        return confirmed

    for asset_index, asset in enumerate(iter_assets(render_data) or [], start=1):
        listing = await build_confirmed_listing_from_asset(
            session,
            asset,
            f"asset::{market_hash_name}::{asset.get('id', asset_index)}",
            market_hash_name,
            fallback_price,
        )
        if listing:
            confirmed.append(listing)

    return confirmed
