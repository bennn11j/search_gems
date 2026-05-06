from dataclasses import dataclass, field


@dataclass
class Gem:
    name: str
    market_price: float
    liquidity_score: float = 1.0
    source: str = "estimated"
    price_status: str = "priced"
    detected_name: str = ""


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
    item_price_status: str = "priced"
    detection_reason: str = ""


@dataclass
class Opportunity:
    listing: Listing
    gems_total: float
    expected_sell_net: float
    profit: float | None
    roi_percent: float | None
    price_status: str = "priced"
    unknown_price_reason: str = ""

    @property
    def total_extractable_value(self) -> float:
        return self.gems_total

    @property
    def total_extractable_value_after_fee(self) -> float:
        return self.expected_sell_net
