import aiohttp


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id

    async def send(self, text: str) -> bool:
        if not self.token or not self.chat_id:
            print("[WARN] TG credentials missing. Message:\n", text)
            return False

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=15) as resp:
                    if resp.status != 200:
                        print("[WARN] Telegram error:", resp.status, await resp.text())
                        return False
                    return True
        except Exception as e:
            print("[WARN] Telegram send exception:", e)
            return False