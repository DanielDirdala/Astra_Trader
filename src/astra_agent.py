import json

from config import (
    ASTRA_API_KEY,
    ASTRA_API_URL,
    ASTRA_MODEL,
)


class AstraAgent:

    PROMPT_VERSION = "v1"

    def build_weekly_prompt(
        self,
        candidates,
    ):

        instructions = """
You are reviewing swing-trading candidates.

The Python system has supplied quantitative
market data, recent news, and broad market
context.

The quantitative ranking is screening evidence,
not a command.

Independently evaluate each candidate.

Return structured JSON containing:

- market_summary
- selected_stocks
- rejected_stocks

For each selected stock include:

- symbol
- action: BUY, SELL, HOLD, or WATCH
- confidence
- entry_price
- stop_price
- target_price
- expected_holding_days
- setup_type
- thesis
- bull_case
- bear_case
- invalidation_reason

You may select zero stocks if none appear
attractive.

Do not assume that the highest Python score
must be selected.
"""

        payload = {
            "instructions":
                instructions,

            "candidates":
                candidates,
        }

        return json.dumps(
            payload,
            indent=2,
            default=str,
        )

    def analyze_week(
        self,
        candidates,
    ):

        prompt = (
            self.build_weekly_prompt(
                candidates
            )
        )

        if not ASTRA_API_URL:

            return {
                "status":
                    "MODEL_NOT_CONNECTED",

                "message":
                    (
                        "Astra provider has not "
                        "been configured yet."
                    ),

                "prompt":
                    prompt,
            }

        raise NotImplementedError(
            "Astra API adapter must be "
            "implemented for your specific "
            "Astra provider."
        )