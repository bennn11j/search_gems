import asyncio
import csv
import logging
import os
import time
from datetime import datetime, timezone

from app.config import settings
from app.notifier import TelegramNotifier
from app.pricing import calc_opportunity
from app.scanner import fetch_listings
from app.storage import AlertStorage

alerts_sent_this_hour = 0
hour_window_start = int(time.time())

logging.basicConfig(
    filename=settings.log_file,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def allowed_by_keywords(listing) -> bool:
    if listing.value_source == "confirmed":
        return True

    keywords = [k.strip().lower() for k in settings.require_keywords.split(",") if k.strip()]
    if not keywords:
        return True
    name = listing.item_name.lower()
    return any(k in name for k in keywords)


def compute_confidence_score(opp) -> int:
    score = 0
    name = opp.listing.item_name.lower()

    if opp.roi_percent >= 80:
        score += 35
    elif opp.roi_percent >= 40:
        score += 25
    elif opp.roi_percent >= 20:
        score += 15
    elif opp.roi_percent >= 5:
        score += 8

    if opp.profit >= 0.10:
        score += 25
    elif opp.profit >= 0.05:
        score += 18
    elif opp.profit >= 0.02:
        score += 12
    elif opp.profit >= 0.01:
        score += 6

    if opp.listing.buy_price <= 0.05:
        score += 15
    elif opp.listing.buy_price <= 0.10:
        score += 10
    elif opp.listing.buy_price <= 0.20:
        score += 5

    if "kinetic" in name:
        score += 15
    if "inscribed" in name:
        score += 8
    if "autographed" in name:
        score -= 8

    priced_gems = [g for g in opp.listing.gems if g.market_price > 0]
    unpriced_gems = [g for g in opp.listing.gems if g.market_price <= 0]

    if opp.gems_total > 0:
        score += 10
    if len(priced_gems) >= 2:
        score += 6
    if any(g.name.lower().startswith(("ethereal gem", "prismatic gem", "kinetic gem")) for g in priced_gems):
        score += 8
    if opp.listing.value_source == "confirmed":
        score += 35
    if unpriced_gems:
        score -= min(len(unpriced_gems) * 8, 24)
    if opp.listing.value_source != "confirmed":
        score -= 12

    return max(0, min(score, 100))


def format_alert(opp, score: int) -> str:
    gems_lines = "\n".join(
        [f"- {g.name}: ${g.market_price:.2f} ({g.source})" for g in opp.listing.gems]
    ) or "- нет"
    source_label = "ESTIMATED / ручная проверка нужна"
    warning_text = (
        "⚠️ Это не ссылка на подтвержденный конкретный сокет-лот.\n"
        "Бот отфильтровал standalone gem items и показывает item-кандидат по названию.\n"
        "Проверь сокеты/гемы вручную перед покупкой.\n"
    )
    if opp.listing.value_source == "confirmed":
        source_label = "CONFIRMED / гемы найдены в описании лота"
        warning_text = (
            "✅ Гемы найдены в описании конкретного Steam listing render.\n"
            "Перед покупкой всё равно быстро проверь лот вручную.\n"
        )

    return (
        f"🎯 {opp.listing.item_name}\n"
        f"Status: {source_label}\n"
        f"Confidence: {score}/100\n"
        f"Чистая прибыль: ${opp.profit:.2f} ({opp.roi_percent:.1f}%)\n\n"
        f"Цена лота: ${opp.listing.buy_price:.2f}\n"
        f"Сумма гемов (оценка): ${opp.gems_total:.2f}\n"
        f"Ожидаемая выручка (нетто): ${opp.expected_sell_net:.2f}\n\n"
        f"Гемы:\n{gems_lines}\n\n"
        f"{warning_text}\n"
        f"Market listing:\n{opp.listing.market_url}\n\n"
        f"Fallback search:\n{opp.listing.search_url}"
    )


def append_signal_csv(opp, score: int):
    file_exists = os.path.exists(settings.csv_file)
    with open(settings.csv_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(
                [
                    "timestamp_utc",
                    "item_name",
                    "buy_price",
                    "gems_total_est",
                    "expected_sell_net",
                    "profit",
                    "roi_percent",
                    "confidence_score",
                    "value_source",
                    "market_url",
                    "search_url",
                ]
            )
        writer.writerow(
            [
                datetime.now(timezone.utc).isoformat(),
                opp.listing.item_name,
                f"{opp.listing.buy_price:.4f}",
                f"{opp.gems_total:.4f}",
                f"{opp.expected_sell_net:.4f}",
                f"{opp.profit:.4f}",
                f"{opp.roi_percent:.2f}",
                score,
                opp.listing.value_source,
                opp.listing.market_url,
                opp.listing.search_url,
            ]
        )


async def can_alert(storage: AlertStorage, listing_id: str, cooldown_sec: int) -> bool:
    last_ts = await storage.get_last_alert_ts(listing_id)
    if last_ts is None:
        return True
    return (int(time.time()) - int(last_ts)) >= cooldown_sec


async def mark_alerted(storage: AlertStorage, listing_id: str):
    await storage.upsert_alert_ts(listing_id, int(time.time()))


def check_hourly_limit() -> bool:
    global alerts_sent_this_hour, hour_window_start
    now = int(time.time())
    if now - hour_window_start >= 3600:
        hour_window_start = now
        alerts_sent_this_hour = 0
    return alerts_sent_this_hour < settings.max_alerts_per_hour


def inc_hourly_limit():
    global alerts_sent_this_hour
    alerts_sent_this_hour += 1


def format_gems_for_log(listing) -> str:
    if not listing.gems:
        return "none"
    return "; ".join(
        f"{gem.name}=${gem.market_price:.4f}/{gem.source}" for gem in listing.gems
    )


def has_priced_gem(listing) -> bool:
    return any(gem.market_price > 0 for gem in listing.gems)


def log_decision(reason: str, listing, opp=None, score: int | None = None, extra: str = ""):
    if not settings.debug_skip_details and not reason.startswith("ALERT"):
        return

    parts = [
        f"[{reason}] {listing.item_name}",
        f"source={listing.value_source}",
        f"buy=${listing.buy_price:.4f}",
        f"gems=[{format_gems_for_log(listing)}]",
    ]
    if opp is not None:
        parts.extend(
            [
                f"gems_total=${opp.gems_total:.4f}",
                f"expected_net=${opp.expected_sell_net:.4f}",
                f"profit=${opp.profit:.4f}",
                f"roi={opp.roi_percent:.1f}%",
            ]
        )
    if score is not None:
        parts.append(f"confidence={score}")
    if extra:
        parts.append(extra)

    msg = " ".join(parts)
    print(msg)
    logging.info(msg)


async def run_once(notifier: TelegramNotifier, storage: AlertStorage):
    listings = await fetch_listings(settings.scan_mode, settings.max_listings_per_run)

    if not listings:
        msg = f"[INFO] No listings in mode={settings.scan_mode}"
        print(msg)
        logging.info(msg)
        return

    for listing in listings:
        if listing.buy_price <= 0:
            log_decision("SKIP", listing, extra="reason=missing_buy_price")
            continue

        if listing.buy_price < settings.min_buy_price_usd:
            log_decision(
                "SKIP",
                listing,
                extra=f"reason=below_min_price min=${settings.min_buy_price_usd:.4f}",
            )
            continue

        if not allowed_by_keywords(listing):
            log_decision("SKIP", listing, extra="reason=keyword_filter")
            continue

        if listing.value_source == "confirmed" and not has_priced_gem(listing):
            log_decision(
                "SKIP",
                listing,
                extra="reason=confirmed_gems_unpriced priceoverview_missing=true",
            )
            continue

        opp = calc_opportunity(
            listing=listing,
            steam_fee=settings.steam_sell_fee,
            chisel_cost=settings.chisel_cost_usd,
            base_item_resale=0.00,
        )

        score = compute_confidence_score(opp)
        log_decision("EVAL", listing, opp=opp, score=score, extra="stage=profitability_check")

        if listing.buy_price > settings.max_buy_price_usd and opp.profit < settings.min_profit_usd:
            log_decision(
                "SKIP",
                listing,
                opp=opp,
                score=score,
                extra=f"reason=above_max_price max=${settings.max_buy_price_usd:.4f} not_profitable=true",
            )
            continue

        if opp.profit < settings.min_profit_usd:
            log_decision(
                "SKIP",
                listing,
                opp=opp,
                score=score,
                extra=f"reason=profit_below_min min_profit=${settings.min_profit_usd:.4f}",
            )
            continue

        if opp.roi_percent < settings.min_roi_percent:
            log_decision(
                "SKIP",
                listing,
                opp=opp,
                score=score,
                extra=f"reason=roi_below_min min_roi={settings.min_roi_percent:.1f}%",
            )
            continue

        if score < settings.min_confidence_score:
            log_decision(
                "SKIP",
                listing,
                opp=opp,
                score=score,
                extra=f"reason=confidence_below_min min_confidence={settings.min_confidence_score}",
            )
            continue

        if not await can_alert(storage, listing.listing_id, settings.alert_cooldown_sec):
            log_decision("COOLDOWN", listing, opp=opp, score=score, extra="reason=alert_cooldown")
            continue

        if not check_hourly_limit():
            print("[RATE_LIMIT] max alerts/hour reached")
            logging.info("[RATE_LIMIT] max alerts/hour reached")
            break

        sent = await notifier.send(format_alert(opp, score))
        if sent:
            await mark_alerted(storage, listing.listing_id)
            inc_hourly_limit()
            append_signal_csv(opp, score)
            log_decision("ALERT", listing, opp=opp, score=score)
        else:
            log_decision("WARN", listing, opp=opp, score=score, extra="reason=telegram_send_failed")


async def main():
    notifier = TelegramNotifier(settings.tg_bot_token, settings.tg_chat_id)
    storage = AlertStorage(settings.db_path)
    await storage.init()

    print(f"[BOOT] mode={settings.scan_mode}, db={settings.db_path}, csv={settings.csv_file}")
    logging.info(f"Boot mode={settings.scan_mode}, db={settings.db_path}, csv={settings.csv_file}")

    while True:
        try:
            await run_once(notifier, storage)
        except Exception:
            logging.exception("Unhandled error in main loop")
            print("[ERROR] Unhandled error, check bot.log")
        await asyncio.sleep(settings.scan_interval_sec)


if __name__ == "__main__":
    asyncio.run(main())
