import asyncio
import logging

import aiohttp
from urllib.parse import quote

from app.config import settings
from app.inspector import (
    build_confirmed_listing_from_asset,
    fetch_confirmed_socket_listings,
    fetch_listing_render,
    summarize_listing_render,
)
from app.models import Gem, Listing

APP_ID = 570
CURRENCY_USD = 1

STANDALONE_GEM_PREFIXES = (
    "kinetic:",
    "ethereal:",
    "prismatic:",
    "autograph:",
    "kinetic gem",
    "inscribed gem",
    "autograph rune",
    "autographed rune",
    "ethereal gem",
    "prismatic gem",
    "genuine gem",
    "strange gem",
    "ascendant gem",
    "foulfell shard",
)
STANDALONE_GEM_MARKERS = (
    " gem -",
    " rune -",
    " autograph:",
    " sticker",
)


def parse_csv_setting(raw_value: str) -> tuple[str, ...]:
    return tuple(value.strip().lower() for value in raw_value.split(",") if value.strip())


def log_scanner_event(level: int, message: str):
    print(message)
    logging.log(level, message)


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


def extract_price(result: dict) -> float:
    txt = result.get("sell_price_text", "")
    if txt:
        return parse_price_to_usd(txt)
    sp = result.get("sell_price")
    if isinstance(sp, int):
        return sp / 100.0
    return 0.0


def build_market_url(market_hash_name: str) -> str:
    return f"https://steamcommunity.com/market/listings/{APP_ID}/{quote(market_hash_name, safe='')}"


def build_search_url(market_hash_name: str) -> str:
    return (
        "https://steamcommunity.com/market/search"
        f"?appid={APP_ID}&q={quote(market_hash_name, safe='')}"
    )


def is_standalone_gem_item(name: str) -> bool:
    lowered_name = name.lower().strip()
    if lowered_name.startswith(STANDALONE_GEM_PREFIXES):
        return True
    if lowered_name.startswith("autographed ") and any(
        token in lowered_name for token in (" gem", " rune")
    ):
        return True
    return any(marker in lowered_name for marker in STANDALONE_GEM_MARKERS)


def is_socket_candidate(name: str, broad_discovery: bool = False) -> bool:
    lowered_name = name.lower()
    if settings.exclude_standalone_gems and is_standalone_gem_item(lowered_name):
        return False

    excluded_keywords = parse_csv_setting(settings.exclude_item_keywords)
    if any(keyword in lowered_name for keyword in excluded_keywords):
        return False

    if broad_discovery:
        return True

    candidate_keywords = parse_csv_setting(settings.candidate_keywords)
    if not candidate_keywords:
        return True
    return any(keyword in lowered_name for keyword in candidate_keywords)


async def fetch_market_search_page(
    session,
    query: str,
    start: int = 0,
    count: int = 30,
    search_descriptions: bool = False,
) -> dict:
    search_descriptions_flag = 1 if search_descriptions else 0
    url = (
        "https://steamcommunity.com/market/search/render/"
        f"?query={quote(query)}"
        f"&start={start}&count={count}"
        f"&search_descriptions={search_descriptions_flag}"
        f"&sort_column=price&sort_dir=asc"
        f"&appid={APP_ID}"
        f"&norender=1"
        f"&currency={CURRENCY_USD}"
    )
    retries = max(settings.steam_request_retries, 0)
    for attempt in range(retries + 1):
        try:
            async with session.get(url, timeout=20) as resp:
                if resp.status != 200:
                    txt = await resp.text()
                    raise RuntimeError(f"Steam search error {resp.status}: {txt[:150]}")
                return await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError) as exc:
            if attempt >= retries:
                raise
            await asyncio.sleep(0.5 * (attempt + 1))
            log_scanner_event(
                logging.WARNING,
                f"[WARN] retry Steam search query={query or '<empty>'} "
                f"start={start} attempt={attempt + 2}/{retries + 1}: {exc}",
            )
    return {}


async def fetch_listings_mock(limit: int = 20) -> list[Listing]:
    raw = [
        {
            "listing_id": "1001",
            "item_name": "Kinetic: Everlasting Hair",
            "buy_price": 0.03,
            "market_hash_name": "Kinetic: Everlasting Hair",
            "gems": [("Estimated Kinetic Value", 0.09)],
        },
        {
            "listing_id": "1002",
            "item_name": "Inscribed: Random Item",
            "buy_price": 0.08,
            "market_hash_name": "Inscribed: Random Item",
            "gems": [("Estimated Inscribed Value", 0.01)],
        },
    ][:limit]

    out: list[Listing] = []
    for r in raw:
        gems = [Gem(name=n, market_price=p, source="mock") for n, p in r["gems"]]
        market_hash_name = r["market_hash_name"]
        out.append(
            Listing(
                listing_id=r["listing_id"],
                item_name=r["item_name"],
                buy_price=r["buy_price"],
                gems=gems,
                market_hash_name=market_hash_name,
                market_url=build_market_url(market_hash_name),
                search_url=build_search_url(market_hash_name),
                value_source="estimated",
                item_price_status="priced",
                detection_reason="mock_fixture",
            )
        )
    return out


def estimate_gems_by_keywords(name: str) -> list[Gem]:
    lowered_name = name.lower()

    if settings.exclude_standalone_gems and is_standalone_gem_item(lowered_name):
        return []

    estimates = (
        ("inscribed", "Estimated Inscribed Socket Value", 0.03),
        ("autographed", "Estimated Autographed Socket Value", 0.02),
        ("kinetic", "Estimated Kinetic Socket Value", 0.08),
        ("ethereal", "Estimated Ethereal Socket Value", 0.10),
        ("prismatic", "Estimated Prismatic Socket Value", 0.10),
        ("ascendant", "Estimated Ascendant Socket Value", 0.05),
        ("foulfell", "Estimated Foulfell Socket Value", 0.05),
    )

    gems = []
    for marker, gem_name, fallback_price in estimates:
        if marker in lowered_name:
            gems.append(
                Gem(
                    name=gem_name,
                    market_price=fallback_price,
                    source="estimated_keyword",
                    price_status="estimated",
                )
            )

    if "socket" in lowered_name and not gems:
        gems.append(
            Gem(
                name="Unknown Socket Property",
                market_price=0.0,
                source="estimated_unpriced",
                price_status="unknown_price",
            )
        )

    return gems



def parse_query_list(raw_queries: str) -> list[str]:
    queries: list[str] = []
    for raw_query in raw_queries.split(","):
        query = raw_query.strip()
        if not query:
            continue
        if query == "__EMPTY__":
            query = ""
        queries.append(query)
    return queries


def build_confirmed_search_jobs() -> list[tuple[str, bool]]:
    jobs: list[tuple[str, bool]] = []
    for query in parse_query_list(settings.socket_search_queries):
        jobs.append((query, True))
    for query in parse_query_list(settings.discovery_queries):
        jobs.append((query, False))
    return jobs


async def build_confirmed_listing_from_search_result(
    session,
    result: dict,
    market_hash_name: str,
    price: float,
) -> Listing | None:
    asset_description = result.get("asset_description")
    if not isinstance(asset_description, dict):
        return None

    asset_id = asset_description.get("id") or result.get("assetid") or market_hash_name
    return await build_confirmed_listing_from_asset(
        session,
        asset_description,
        f"search_asset::{market_hash_name}::{asset_id}",
        market_hash_name,
        price,
    )


async def fetch_listings_real(limit: int = 20) -> list[Listing]:
    # Confirmed mode uses two discovery paths:
    # 1) description search for gem terms;
    # 2) broad low-price market-name discovery, then listing render inspection.
    # The second path is important because socketed gems are often stored only
    # on concrete listing assets and are not indexed by Steam search.
    if settings.confirm_socket_gems:
        search_jobs = build_confirmed_search_jobs()
    else:
        search_jobs = [("Inscribed", False), ("Autographed", False)]

    out: list[Listing] = []
    seen = set()
    unconfirmed_market_hash_names: list[str] = []
    stats = {
        "search_results": 0,
        "skipped_standalone": 0,
        "candidate_market_items": 0,
        "search_asset_confirmed": 0,
        "inspected_market_items": 0,
        "confirmed_listings": 0,
        "estimated_candidates": 0,
        "filtered_candidates": 0,
        "inspect_failures": 0,
        "duplicate_listing": 0,
    }

    async with aiohttp.ClientSession(
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    ) as session:
        for query, search_descriptions in search_jobs:
            for page in range(max(settings.discovery_pages_per_query, 1)):
                start = page * settings.search_page_size
                try:
                    data = await fetch_market_search_page(
                        session,
                        query,
                        start=start,
                        count=settings.search_page_size,
                        search_descriptions=search_descriptions,
                    )
                except Exception as e:
                    display_query = query or "<empty>"
                    log_scanner_event(logging.WARNING, f"[WARN] query '{display_query}' failed: {e}")
                    continue

                results = data.get("results", [])
                stats["search_results"] += len(results)
                if settings.inspect_debug:
                    display_query = query or "<empty>"
                    print(
                        f"[DEBUG] query='{display_query}' "
                        f"search_descriptions={int(search_descriptions)} "
                        f"start={start} search_results={len(results)}"
                    )

                for result in results:
                    name = result.get("name") or "Unknown item"
                    market_hash_name = result.get("hash_name") or name
                    listing_id = f"search::{market_hash_name}"

                    if listing_id in seen:
                        stats.setdefault("duplicate_listing", 0)
                        stats["duplicate_listing"] += 1
                        if settings.debug_skip_details:
                            log_scanner_event(
                                logging.INFO,
                                f"[SKIP] {name} reason=duplicate_listing listing_id={listing_id}",
                            )
                        continue
                    seen.add(listing_id)

                    if settings.exclude_standalone_gems and is_standalone_gem_item(name):
                        stats["skipped_standalone"] += 1
                        continue

                    broad_discovery = settings.confirm_socket_gems and not query and not search_descriptions
                    if not is_socket_candidate(name, broad_discovery=broad_discovery):
                        stats.setdefault("filtered_candidates", 0)
                        stats["filtered_candidates"] += 1
                        continue

                    stats["candidate_market_items"] += 1

                    price = extract_price(result)
                    if price <= 0:
                        continue

                    if settings.confirm_socket_gems:
                        search_asset_listing = await build_confirmed_listing_from_search_result(
                            session,
                            result,
                            market_hash_name,
                            price,
                        )
                        if search_asset_listing:
                            stats["search_asset_confirmed"] += 1
                            stats["confirmed_listings"] += 1
                            out.append(search_asset_listing)
                            if len(out) >= limit:
                                return out
                            continue

                        stats["inspected_market_items"] += 1
                        try:
                            confirmed_listings = await fetch_confirmed_socket_listings(
                                session,
                                market_hash_name=market_hash_name,
                                fallback_price=price,
                                max_listings=settings.listing_sample_count,
                            )
                        except Exception as e:
                            stats["inspect_failures"] += 1
                            log_scanner_event(
                                logging.WARNING,
                                f"[WARN] inspect '{market_hash_name}' failed: {e}",
                            )
                            if stats["inspect_failures"] >= settings.max_inspect_failures_per_run:
                                log_scanner_event(
                                    logging.WARNING,
                                    "[WARN] too many listing-render failures; stopping current scan early",
                                )
                                return out
                            confirmed_listings = []

                        if settings.inspect_debug:
                            log_scanner_event(
                                logging.DEBUG,
                                "[DEBUG] inspect "
                                f"market_hash_name='{market_hash_name}' "
                                f"confirmed_listings={len(confirmed_listings)}",
                            )

                        if not confirmed_listings and len(unconfirmed_market_hash_names) < 10:
                            unconfirmed_market_hash_names.append(market_hash_name)

                        stats["confirmed_listings"] += len(confirmed_listings)
                        for confirmed_listing in confirmed_listings:
                            out.append(confirmed_listing)
                            if len(out) >= limit:
                                return out
                        continue

                    gems = estimate_gems_by_keywords(name)
                    if not gems:
                        continue

                    stats["estimated_candidates"] += 1
                    out.append(
                        Listing(
                            listing_id=listing_id,
                            item_name=name,
                            buy_price=price,
                            gems=gems,
                            market_hash_name=market_hash_name,
                            market_url=build_market_url(market_hash_name),
                            search_url=build_search_url(market_hash_name),
                            value_source="estimated",
                            item_price_status="priced" if price > 0 else "unknown_price",
                            detection_reason="keyword_estimate",
                        )
                    )

                    if len(out) >= limit:
                        return out

    if not out:
        log_scanner_event(
            logging.INFO,
            "[INFO] scanner stats: "
            f"search_results={stats['search_results']}, "
            f"skipped_standalone={stats['skipped_standalone']}, "
            f"filtered_candidates={stats['filtered_candidates']}, "
            f"duplicate_listing={stats['duplicate_listing']}, "
            f"candidate_market_items={stats['candidate_market_items']}, "
            f"search_asset_confirmed={stats['search_asset_confirmed']}, "
            f"inspected_market_items={stats['inspected_market_items']}, "
            f"inspect_failures={stats['inspect_failures']}, "
            f"confirmed_listings={stats['confirmed_listings']}, "
            f"estimated_candidates={stats['estimated_candidates']}",
        )
        if settings.inspect_debug and unconfirmed_market_hash_names:
            async with aiohttp.ClientSession(
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
            ) as debug_session:
                for market_hash_name in unconfirmed_market_hash_names:
                    try:
                        render_data = await fetch_listing_render(
                            debug_session,
                            market_hash_name,
                            min(settings.listing_sample_count, 5),
                        )
                        summary_lines = summarize_listing_render(render_data)
                    except Exception as e:
                        log_scanner_event(logging.WARNING, f"[WARN] debug render sample failed for '{market_hash_name}': {e}")
                        continue

                    if summary_lines == ["listing_count=0"] and market_hash_name != unconfirmed_market_hash_names[-1]:
                        continue

                    print(
                        "[INFO] To inspect Steam's raw listing descriptions, run: "
                        f"python -m app.debug_inspect \"{market_hash_name}\" "
                        f"--count {settings.listing_sample_count}"
                    )
                    print(f"[DEBUG] render sample for '{market_hash_name}':")
                    for line in summary_lines:
                        print(f"[DEBUG] {line}")
                    break
    return out


async def fetch_listings(mode: str, limit: int = 20) -> list[Listing]:
    if mode == "real":
        return await fetch_listings_real(limit)
    return await fetch_listings_mock(limit)
