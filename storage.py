from typing import Optional

import aiosqlite


class AlertStorage:
    def __init__(self, db_path: str = "alerts.db"):
        self.db_path = db_path

    async def init(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS sent_alerts (
                    listing_id TEXT PRIMARY KEY,
                    last_alert_ts INTEGER NOT NULL
                )
                """
            )
            await db.commit()

    async def get_last_alert_ts(self, listing_id: str) -> Optional[int]:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT last_alert_ts FROM sent_alerts WHERE listing_id = ?",
                (listing_id,),
            )
            row = await cur.fetchone()
            return row[0] if row else None

    async def upsert_alert_ts(self, listing_id: str, ts: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO sent_alerts (listing_id, last_alert_ts)
                VALUES (?, ?)
                ON CONFLICT(listing_id) DO UPDATE SET last_alert_ts=excluded.last_alert_ts
                """,
                (listing_id, ts),
            )
            await db.commit()