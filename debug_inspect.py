import argparse
import asyncio

import aiohttp

from app.inspector import (
    extract_gem_market_names_from_asset,
    fetch_listing_render,
    get_listing_asset,
    strip_html,
)


def short(text: str, limit: int = 500) -> str:
    normalized = " ".join(strip_html(text).split())
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit] + "..."


async def inspect_market_hash_name(market_hash_name: str, count: int):
    async with aiohttp.ClientSession(
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    ) as session:
        data = await fetch_listing_render(session, market_hash_name, count)

    listing_info = data.get("listinginfo", {})
    print(f"market_hash_name={market_hash_name}")
    print(f"listing_count={len(listing_info) if isinstance(listing_info, dict) else 0}")

    if not isinstance(listing_info, dict) or not listing_info:
        print("No listinginfo returned by Steam render endpoint.")
        return

    for index, (listing_id, info) in enumerate(listing_info.items(), start=1):
        if not isinstance(info, dict):
            continue
        asset = get_listing_asset(data, info)
        if not asset:
            print(f"[{index}] listing_id={listing_id} asset=missing")
            continue

        item_name = asset.get("market_name") or asset.get("name") or market_hash_name
        gems = extract_gem_market_names_from_asset(asset)
        print(f"[{index}] listing_id={listing_id} item={item_name}")
        print(f"    extracted_gems={gems or 'none'}")

        descriptions = asset.get("descriptions", [])
        for desc_index, description in enumerate(descriptions[:8], start=1):
            value = description.get("value", "") if isinstance(description, dict) else ""
            if isinstance(value, str) and value.strip():
                print(f"    desc[{desc_index}] {short(value)}")


def main():
    parser = argparse.ArgumentParser(description="Debug Steam listing render gem extraction.")
    parser.add_argument("market_hash_name", help="Exact Steam market hash name to inspect")
    parser.add_argument("--count", type=int, default=10, help="Number of listings to sample")
    args = parser.parse_args()
    asyncio.run(inspect_market_hash_name(args.market_hash_name, args.count))


if __name__ == "__main__":
    main()