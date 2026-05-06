import aiohttp
from urllib.parse import quote

APP_ID = 570
CURRENCY_USD = 1

def parse_price_text(txt: str) -> float:
    cleaned = (
        txt.replace("$", "")
        .replace("USD", "")
        .replace(" ", "")
        .replace(",", ".")
        .strip()
    )
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

async def fetch_item_lowest_price(session: aiohttp.ClientSession, market_hash_name: str) -> float:
    # priceoverview endpoint
    # https://steamcommunity.com/market/priceoverview/?appid=570&currency=1&market_hash_name=...
    url = (
        "https://steamcommunity.com/market/priceoverview/"
        f"?appid={APP_ID}&currency={CURRENCY_USD}&market_hash_name={quote(market_hash_name)}"
    )
    async with session.get(url, timeout=20) as resp:
        if resp.status != 200:
            return 0.0
        data = await resp.json(content_type=None)
        if not data or not data.get("success"):
            return 0.0
        lp = data.get("lowest_price")
        if isinstance(lp, str):
            return parse_price_text(lp)
        return 0.0

async def build_gem_price_map(gem_names: list[str]) -> dict[str, float]:
    result: dict[str, float] = {}
    async with aiohttp.ClientSession(
        headers={"User-Agent": "Mozilla/5.0"}
    ) as session:
        for name in gem_names:
            price = await fetch_item_lowest_price(session, name)
            result[name] = price
    return result