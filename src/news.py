from datetime import (
    datetime,
    timedelta,
    timezone,
)

import requests

from config import (
    ALPACA_API_KEY,
    ALPACA_SECRET_KEY,
)

from src.database import Database


NEWS_URL = (
    "https://data.alpaca.markets/"
    "v1beta1/news"
)


class NewsService:

    def __init__(
        self,
        database=None,
    ):

        self.db = (
            database
            or Database()
        )

    def fetch(
        self,
        symbol,
        days=7,
        limit=20,
    ):

        end = datetime.now(
            timezone.utc
        )

        start = (
            end
            - timedelta(
                days=days
            )
        )

        headers = {
            "APCA-API-KEY-ID":
                ALPACA_API_KEY,

            "APCA-API-SECRET-KEY":
                ALPACA_SECRET_KEY,
        }

        params = {
            "symbols":
                symbol.upper(),

            "start":
                start.isoformat(),

            "end":
                end.isoformat(),

            "sort":
                "desc",

            "limit":
                min(
                    limit,
                    50
                ),

            "include_content":
                "false",
        }

        response = requests.get(
            NEWS_URL,
            headers=headers,
            params=params,
            timeout=30,
        )

        response.raise_for_status()

        payload = response.json()

        return payload.get(
            "news",
            []
        )

    def fetch_and_store(
        self,
        symbol,
        days=7,
        limit=20,
    ):

        articles = self.fetch(
            symbol,
            days,
            limit,
        )

        stored = []

        for article in articles:

            article_symbols = (
                article.get(
                    "symbols"
                )
                or []
            )

            if symbol.upper() not in (
                item.upper()
                for item
                in article_symbols
            ):
                continue

            event = {
                "symbol":
                    symbol.upper(),

                "alpaca_news_id":
                    article.get("id"),

                "published_at":
                    article.get(
                        "created_at"
                    ),

                "source":
                    article.get(
                        "source"
                    ),

                "headline":
                    article.get(
                        "headline"
                    ),

                "summary":
                    article.get(
                        "summary"
                    ),

                "url":
                    article.get(
                        "url"
                    ),

                "event_type":
                    "news",

                "raw_data":
                    article,
            }

            self.db.save_news_event(
                event
            )

            stored.append(
                event
            )

        return stored