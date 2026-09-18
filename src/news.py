from datetime import datetime, timedelta, timezone

import requests

from config import (
    ALPACA_API_KEY,
    ALPACA_SECRET_KEY,
)

from src.database import Database


NEWS_URL = "https://data.alpaca.markets/v1beta1/news"


class NewsService:

    def __init__(self, database=None):

        self.db = database or Database()

    def fetch(
        self,
        symbol: str,
        days: int = 7,
        limit: int = 20,
    ):

        symbol = symbol.upper()

        end = datetime.now(timezone.utc)

        start = end - timedelta(days=days)

        headers = {
            "APCA-API-KEY-ID": ALPACA_API_KEY,
            "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
        }

        params = {
            "symbols": symbol,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "sort": "desc",
            "limit": min(limit, 50),
            "include_content": "false",
        }

        response = requests.get(
            NEWS_URL,
            headers=headers,
            params=params,
            timeout=30,
        )

        response.raise_for_status()

        payload = response.json()

        return payload.get("news", [])

    def fetch_and_store(
        self,
        symbol: str,
        days: int = 7,
        limit: int = 20,
    ):

        symbol = symbol.upper()

        articles = self.fetch(
            symbol=symbol,
            days=days,
            limit=limit,
        )

        stored = 0

        for article in articles:

            symbols = article.get("symbols") or []

            if symbol not in [
                item.upper()
                for item in symbols
            ]:
                continue

            event = {
                "symbol": symbol,

                "alpaca_news_id":
                    article.get("id"),

                "published_at":
                    article.get("created_at"),

                "source":
                    article.get("source"),

                "headline":
                    article.get("headline"),

                "summary":
                    article.get("summary"),

                "url":
                    article.get("url"),

                "event_type":
                    "news",

                "raw_data":
                    article,
            }

            self.db.save_news_event(
                event
            )

            stored += 1

        return stored