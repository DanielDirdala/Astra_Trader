from src.database import Database

from src.market_context import (
    MarketContext,
)


class CandidateBuilder:

    def __init__(
        self,
        database=None,
    ):

        self.db = (
            database
            or Database()
        )

        self.market_context = (
            MarketContext(
                self.db
            )
        )

    def build(
        self,
        scan_result,
    ):

        symbol = (
            scan_result[
                "symbol"
            ]
        )

        news = (
            self.db
            .get_recent_news(
                symbol,
                days=7,
                limit=15,
            )
        )

        news_items = []

        for article in news:

            news_items.append(
                {
                    "published_at":
                        str(
                            article[
                                "published_at"
                            ]
                        ),

                    "source":
                        article[
                            "source"
                        ],

                    "headline":
                        article[
                            "headline"
                        ],

                    "summary":
                        article[
                            "summary"
                        ],

                    "url":
                        article[
                            "url"
                        ],
                }
            )

        return {
            "symbol":
                symbol,

            "quantitative":
                {
                    "price":
                        float(
                            scan_result[
                                "price"
                            ]
                        ),

                    "return_1d":
                        float(
                            scan_result[
                                "return_1d"
                            ]
                        ),

                    "return_5d":
                        float(
                            scan_result[
                                "return_5d"
                            ]
                        ),

                    "return_20d":
                        float(
                            scan_result[
                                "return_20d"
                            ]
                        ),

                    "rsi_14":
                        (
                            float(
                                scan_result[
                                    "rsi_14"
                                ]
                            )
                            if scan_result[
                                "rsi_14"
                            ] is not None
                            else None
                        ),

                    "atr_pct":
                        float(
                            scan_result[
                                "atr_pct"
                            ]
                        ),

                    "volume_ratio":
                        float(
                            scan_result[
                                "volume_ratio"
                            ]
                        ),

                    "relative_strength_spy":
                        float(
                            scan_result[
                                "relative_strength_spy"
                            ]
                        ),

                    "relative_strength_qqq":
                        float(
                            scan_result[
                                "relative_strength_qqq"
                            ]
                        ),

                    "technical_score":
                        float(
                            scan_result[
                                "technical_score"
                            ]
                        ),
                },

            "news":
                news_items,

            "market":
                self.market_context.build(),
        }
    