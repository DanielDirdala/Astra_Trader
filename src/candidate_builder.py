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
                database=self.db
            )
        )

    def build_news(
        self,
        symbol,
    ):

        rows = (
            self.db
            .get_recent_news(
                symbol=symbol,
                days=7,
                limit=15,
            )
        )

        output = []

        for row in rows:

            output.append(
                {
                    "published_at":
                        (
                            row[
                                "published_at"
                            ].isoformat()
                            if row[
                                "published_at"
                            ]
                            else None
                        ),

                    "source":
                        row[
                            "source"
                        ],

                    "headline":
                        row[
                            "headline"
                        ],

                    "summary":
                        row[
                            "summary"
                        ],

                    "url":
                        row[
                            "url"
                        ],
                }
            )

        return output

    def build(
        self,
        scan_result,
        market_context=None,
    ):

        symbol = (
            scan_result[
                "symbol"
            ]
        )

        if market_context is None:

            market_context = (
                self.market_context
                .build()
            )

        quantitative = {
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

            "momentum_score":
                float(
                    scan_result[
                        "momentum_score"
                    ]
                ),

            "technical_score":
                float(
                    scan_result[
                        "technical_score"
                    ]
                ),
        }

        metadata = (
            scan_result.get(
                "metadata"
            )
            or {}
        )

        return {
            "symbol":
                symbol,

            "quantitative":
                quantitative,

            "technical_metadata":
                metadata,

            "recent_news":
                self.build_news(
                    symbol
                ),

            "market_context":
                market_context,
        }