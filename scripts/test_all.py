"""The full offline regression suite. Network connections are blocked."""
import contextlib
import io
import unittest
from unittest.mock import patch

MODULES = (
    'scripts.test_sector_expansion',
    'scripts.test_astra_review',
    'scripts.test_market_ops',
    'scripts.test_research_engine',
    'scripts.test_trade_planner',
    'scripts.test_background_review',
    'scripts.test_profit_tracking',
    'scripts.test_consolidated',
)


def main():
    suite = unittest.TestSuite()
    loader = unittest.defaultTestLoader
    # Block actual sockets, and ignore a user's .env in tests. No real secrets or network.
    with patch('socket.socket.connect', side_effect=AssertionError('Offline suite attempted network access')), \
         patch('dotenv.load_dotenv', return_value=False):
        for module in MODULES:
            suite.addTests(loader.loadTestsFromName(module))
        with contextlib.redirect_stdout(io.StringIO()):
            result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(f'Offline tests run: {result.testsRun}; failures: {len(result.failures)}; errors: {len(result.errors)}')
    print('Broker, database, and model interactions in these tests were mocked. No real accounts contacted.')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
