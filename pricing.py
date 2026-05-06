from app.models import Listing, Opportunity


def calc_opportunity(
    listing: Listing,
    steam_fee: float,
    chisel_cost: float,
    base_item_resale: float = 0.0,
) -> Opportunity:
    priced_gems = [gem for gem in listing.gems if gem.market_price > 0]
    unknown_gems = [gem for gem in listing.gems if gem.market_price <= 0]

    gems_total = sum(g.market_price for g in priced_gems)
    gems_net = gems_total * (1 - steam_fee)
    base_item_net = base_item_resale * (1 - steam_fee)
    expected_sell_net = gems_net + base_item_net

    if listing.buy_price <= 0:
        return Opportunity(
            listing=listing,
            gems_total=gems_total,
            expected_sell_net=expected_sell_net,
            profit=None,
            roi_percent=None,
            price_status="unknown_price",
            unknown_price_reason="item_price_unknown",
        )

    if listing.gems and not priced_gems:
        return Opportunity(
            listing=listing,
            gems_total=0.0,
            expected_sell_net=0.0,
            profit=None,
            roi_percent=None,
            price_status="unknown_price",
            unknown_price_reason="gem_price_unknown",
        )

    if unknown_gems and listing.value_source == "confirmed":
        price_status = "partial_price"
        unknown_price_reason = "some_gem_prices_unknown"
    else:
        price_status = "priced"
        unknown_price_reason = ""

    total_cost = listing.buy_price + chisel_cost
    profit = expected_sell_net - total_cost
    roi_percent = (profit / listing.buy_price * 100) if listing.buy_price > 0 else None

    return Opportunity(
        listing=listing,
        gems_total=gems_total,
        expected_sell_net=expected_sell_net,
        profit=profit,
        roi_percent=roi_percent,
        price_status=price_status,
        unknown_price_reason=unknown_price_reason,
    )
