import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "skills/token-usage/scripts"))
from official_pricing import (
    RATE_CARD_URL, SPEED_URL, Rate, cache_path, fetch_document,
    load_pricing, parse_fast_rates, parse_rate_card, read_cache, refresh_cache,
)


# Synthetic documentation fixtures keep tests independent of the network.
RATES = """<table><tr><th>Credits per 1M tokens</th><th>Input Tokens</th>
<th>Cached input tokens</th><th>Output Tokens</th></tr>
<tr><td>GPT-6 Astra</td><td>250 credits</td><td>25 credits</td><td>1,250 credits</td></tr>
<tr><td>GPT-5.6 Sol</td><td>100 credits</td><td>10 credits</td><td>500 credits</td></tr>
<tr><td>GPT-9 Future</td><td>200 credits</td><td>20 credits</td><td>900 credits</td></tr>
<tr><td>GPT-5.3-Codex-Spark</td><td colspan="3">research preview</td></tr></table>"""
SPEED = """## Fast mode
GPT-5.6 and GPT-5.5 consume credits at 2.5x the Standard rate; GPT-5.4 consumes
credits at 2x the Standard rate.
GPT-6 Astra Fast mode consumes credits at 2.5x the Standard rate where available.
GPT-9 Future Fast mode consumes credits at 3x the Standard rate.
Use `/fast on` in the CLI. API priority costs 2x.
"""


def fixture_fetch(url):
    return {RATE_CARD_URL + ".md": RATES, SPEED_URL + ".md": SPEED}[url]


class PricingTests(unittest.TestCase):
    def test_discovers_unlisted_new_model_and_commas(self):
        rates, unavailable = parse_rate_card(RATES)
        self.assertEqual(rates["gpt-9-future"], Rate(200, 20, 900))
        self.assertEqual(rates["gpt-6-astra"].output, 1250)
        self.assertEqual(unavailable, ["gpt-5.3-codex-spark"])
        fast = parse_fast_rates(SPEED, rates)
        self.assertEqual(fast, {"gpt-5.6-sol": 2.5, "gpt-6-astra": 2.5, "gpt-9-future": 3})

    def test_markdown_rate_table(self):
        doc = """| Credits per 1M tokens | Input Tokens | Cached input tokens | Output Tokens |
| --- | --- | --- | --- |
| GPT-A | 10 credits | 1 credit | 20 credits |
| GPT-B | 20 credits | 2 credits | 30 credits |
| GPT-C | 30 credits | 3 credits | 40 credits |
"""
        self.assertEqual(parse_rate_card(doc)[0]["gpt-a"], Rate(10, 1, 20))

    def test_unrelated_table_and_invalid_prices_are_rejected(self):
        for doc in (RATES.replace("Credits per 1M tokens", "Dollars per request"),
                    RATES.replace("250 credits", "NaN credits"),
                    RATES.replace("250 credits", "-250 credits"),
                    RATES.replace("25 credits", "25000 credits")):
            with self.assertRaises(ValueError):
                parse_rate_card(doc)

    def test_successful_cache_new_model_and_failure_preserves_rates(self):
        with tempfile.TemporaryDirectory() as directory:
            first = refresh_cache(directory, fetch=fixture_fetch, now=10000)
            self.assertEqual(first["checked_at"], 10000)
            def broken(url):
                raise OSError("offline")
            failed = refresh_cache(directory, force=True, fetch=broken, now=11000)
            self.assertEqual(failed["rates"], first["rates"])
            self.assertEqual(failed["checked_at"], 10000)
            self.assertTrue(failed["error"])
            rates, fast, meta = load_pricing(directory, auto=False)
            self.assertEqual(rates["gpt-9-future"], Rate(200, 20, 900))
            self.assertEqual(fast["gpt-9-future"], 3)
            self.assertEqual(meta["status"], "stale")
            self.assertIn("gpt-5.3-codex", meta["legacy_models"])

    def test_background_refresh_ttl_unknown_model_and_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            refresh_cache(directory, fetch=fixture_fetch, now=10000)
            with patch("official_pricing.subprocess.Popen") as spawn, patch("official_pricing.time.time", return_value=11000):
                load_pricing(directory)
                spawn.assert_not_called()
                load_pricing(directory, {"gpt-10-new"})
                spawn.assert_called_once()
                self.assertEqual(spawn.call_args.kwargs["stdout"], -3)
            with patch("official_pricing.subprocess.Popen") as spawn, patch("official_pricing.time.time", return_value=40000):
                load_pricing(directory, auto=False)
                spawn.assert_not_called()
                load_pricing(directory)
                spawn.assert_called_once()

    def test_failure_backoff(self):
        with tempfile.TemporaryDirectory() as directory:
            def broken(url):
                raise OSError("offline")
            refresh_cache(directory, fetch=broken, now=10000)
            with patch("official_pricing.subprocess.Popen") as spawn, patch("official_pricing.time.time", return_value=10001):
                rates, fast, meta = load_pricing(directory)
                spawn.assert_not_called()
                self.assertIn("gpt-6-astra", rates)
                self.assertEqual(meta["status"], "bundled")

    def test_corrupt_cache_does_not_break_local_tokens(self):
        with tempfile.TemporaryDirectory() as directory:
            path = cache_path(directory)
            path.parent.mkdir(parents=True)
            for payload in ([1], {"version": 1, "rates": {"bad": {"input": float("nan"), "cached": 1, "output": 2}}}):
                path.write_text(json.dumps(payload))
                self.assertEqual(read_cache(directory), {})
                self.assertIn("gpt-6-astra", load_pricing(directory, auto=False)[0])

    def test_only_public_official_https_requests(self):
        for url in ("http://learn.chatgpt.com/docs/pricing.md", "https://example.org/prices", "https://learn.chatgpt.com.evil.test/prices"):
            with self.assertRaises(ValueError):
                fetch_document(url)


if __name__ == "__main__":
    unittest.main()
