import os

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


class Settings(BaseModel):
    tg_bot_token: str = os.getenv("TG_BOT_TOKEN", "")
    tg_chat_id: str = os.getenv("TG_CHAT_ID", "")

    steam_sell_fee: float = float(os.getenv("STEAM_SELL_FEE", "0.13"))
    min_profit_usd: float = float(os.getenv("MIN_PROFIT_USD", "0.01"))
    min_roi_percent: float = float(os.getenv("MIN_ROI_PERCENT", "5"))
    chisel_cost_usd: float = float(os.getenv("CHISEL_COST_USD", "0.00"))

    scan_interval_sec: int = int(os.getenv("SCAN_INTERVAL_SEC", "90"))
    max_listings_per_run: int = int(os.getenv("MAX_LISTINGS_PER_RUN", "30"))

    alert_cooldown_sec: int = int(os.getenv("ALERT_COOLDOWN_SEC", "900"))
    log_file: str = os.getenv("LOG_FILE", "bot.log")
    db_path: str = os.getenv("DB_PATH", "alerts.db")
    scan_mode: str = os.getenv("SCAN_MODE", "real").lower()

    max_buy_price_usd: float = float(os.getenv("MAX_BUY_PRICE_USD", "0.20"))
    min_buy_price_usd: float = float(os.getenv("MIN_BUY_PRICE_USD", "0.01"))
    max_alerts_per_hour: int = int(os.getenv("MAX_ALERTS_PER_HOUR", "20"))
    confirm_socket_gems: bool = os.getenv("CONFIRM_SOCKET_GEMS", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    listing_sample_count: int = int(os.getenv("LISTING_SAMPLE_COUNT", "10"))
    inspect_debug: bool = os.getenv("INSPECT_DEBUG", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    socket_search_queries: str = os.getenv(
        "SOCKET_SEARCH_QUERIES",
        "Kinetic Gem,Ethereal Gem,Prismatic Gem,Autograph Rune",
    )
    discovery_queries: str = os.getenv("DISCOVERY_QUERIES", "__EMPTY__,Inscribed,Autographed")
    discovery_pages_per_query: int = int(os.getenv("DISCOVERY_PAGES_PER_QUERY", "1"))
    search_page_size: int = int(os.getenv("SEARCH_PAGE_SIZE", "40"))
    require_keywords: str = os.getenv("REQUIRE_KEYWORDS", "inscribed,autographed")
    exclude_standalone_gems: bool = os.getenv("EXCLUDE_STANDALONE_GEMS", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    min_confidence_score: int = int(os.getenv("MIN_CONFIDENCE_SCORE", "55"))
    csv_file: str = os.getenv("CSV_FILE", "signals.csv")


settings = Settings()