from app.models import Listing, Opportunity


def calc_opportunity(
    listing: Listing,
    steam_fee: float,
    chisel_cost: float,
    base_item_resale: float = 0.0,
) -> Opportunity:
    gems_total = sum(g.market_price for g in listing.gems)
    gems_net = gems_total * (1 - steam_fee)
    base_item_net = base_item_resale * (1 - steam_fee)

    expected_sell_net = gems_net + base_item_net
    total_cost = listing.buy_price + chisel_cost
    profit = expected_sell_net - total_cost
    roi_percent = (profit / listing.buy_price * 100) if listing.buy_price > 0 else 0.0

    return Opportunity(
        listing=listing,
        gems_total=gems_total,
        expected_sell_net=expected_sell_net,
        profit=profit,
        roi_percent=roi_percent,
    )