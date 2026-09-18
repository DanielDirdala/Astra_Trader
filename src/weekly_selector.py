from datetime import (
    date,
    timedelta,
)

from src.candidate_builder import (
    CandidateBuilder,
)

from src.database import Database

from config import (
    WEEKLY_CANDIDATE_COUNT,
)


def monday_for_date(
    value=None,
):

    value = (
        value
        or date.today()
    )

    return (
        value
        - timedelta(
            days=value.weekday()
        )
    )


class WeeklySelector:

    def __init__(
        self,
        database=None,
    ):

        self.db = (
            database
            or Database()
        )

        self.builder = (
            CandidateBuilder(
                self.db
            )
        )

    def build_candidates(
        self,
        scan_id=None,
        limit=None,
    ):

        if scan_id is None:

            scan_id = (
                self.db
                .get_latest_scan_id()
            )

        if scan_id is None:

            raise RuntimeError(
                "No scanner results exist."
            )

        if limit is None:

            limit = (
                WEEKLY_CANDIDATE_COUNT
            )

        results = (
            self.db
            .get_scan_results(
                scan_id,
                limit,
            )
        )

        week_start = (
            monday_for_date()
        )

        output = []

        for scan_result in results:

            package = (
                self.builder
                .build(
                    scan_result
                )
            )

            candidate = {
                "week_start":
                    week_start,

                "symbol":
                    scan_result[
                        "symbol"
                    ],

                "quantitative_score":
                    float(
                        scan_result[
                            "technical_score"
                        ]
                    ),

                "momentum_score":
                    float(
                        scan_result[
                            "momentum_score"
                        ]
                    ),

                "candidate_data":
                    package,
            }

            self.db.save_weekly_candidate(
                candidate
            )

            output.append(
                candidate
            )

        return output