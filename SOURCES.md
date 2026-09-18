# External documentation checked for this consolidation (2026-09-18)

These references support API contracts; they do not validate the trading strategy.

- OpenAI GPT-6 Astra model and rates:
  https://developers.openai.com/api/docs/models/gpt-6-astra
- OpenAI input token-count endpoint:
  https://developers.openai.com/api/docs/guides/token-counting
- Reasoning output usage and incomplete responses:
  https://developers.openai.com/api/docs/guides/reasoning
- Alpaca multi-symbol historical bars and pagination:
  https://docs.alpaca.markets/us/reference/stockbars
- Alpaca account activities, pagination, historical fills:
  https://docs.alpaca.markets/us/reference/getaccountactivities-2
  https://docs.alpaca.markets/us/docs/account-activities
- Alpaca order/bracket behavior:
  https://docs.alpaca.markets/us/docs/orders-at-alpaca
- Alpaca paper simulation limitations:
  https://docs.alpaca.markets/us/docs/paper-trading
- Psycopg executemany/pipeline transactions:
  https://www.psycopg.org/psycopg3/docs/advanced/pipeline.html

No OpenAI or Alpaca authenticated calls were made during implementation. Local
package-index access failed in the tool environment. Runtime integration, actual
billable usage, SQL execution and performance must be verified by the user.
