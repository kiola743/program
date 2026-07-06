"""디스코드 웹훅 알림.

DISCORD_WEBHOOK_URL 이 비어있으면 콘솔 출력으로 대체한다(개발/테스트 시 편의).
"""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger("quant.notify")


class DiscordNotifier:
    def __init__(self, webhook_url: str = ""):
        self.webhook_url = webhook_url

    def send(self, message: str) -> None:
        if not self.webhook_url:
            logger.info("[알림(콘솔 대체)] %s", message)
            return
        try:
            resp = requests.post(self.webhook_url, json={"content": message[:2000]}, timeout=10)
            if resp.status_code >= 300:
                logger.warning("디스코드 웹훅 전송 실패 (%s): %s", resp.status_code, resp.text[:200])
        except requests.RequestException as e:
            logger.warning("디스코드 웹훅 전송 오류: %s", e)

    def trade(self, message: str) -> None:
        self.send(f":arrows_counterclockwise: **체결**\n{message}")

    def error(self, message: str) -> None:
        self.send(f":rotating_light: **에러**\n{message}")

    def info(self, message: str) -> None:
        self.send(f":information_source: {message}")
