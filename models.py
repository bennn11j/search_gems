from dataclasses import dataclass, field


@dataclass
class Gem:
    name: str
    market_price: float
    liquidity_score: float = 1.0
    source: str = "estimated"


@dataclass
class Listing:
    listing_id: str
    item_name: str
    buy_price: float
    gems: list[Gem] = field(default_factory=list)
    market_hash_name: str = ""
    market_url: str = ""
    search_url: str = ""
    value_source: str = "estimated"


@dataclass
class Opportunity:
    listing: Listing
    gems_total: float
    expected_sell_net: float
    profit: float
    roi_percent: float