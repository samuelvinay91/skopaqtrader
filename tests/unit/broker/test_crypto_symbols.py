"""Tests for crypto symbol mapping utilities."""

import pytest

from skopaq.broker.crypto_symbols import (
    CRYPTO_TOP_20,
    from_binance_pair,
    to_binance_pair,
    to_yfinance_ticker,
)


class TestToBinancePair:
    def test_bare_coin(self):
        assert to_binance_pair("BTC") == "BTCUSDT"

    def test_already_binance_format(self):
        assert to_binance_pair("BTCUSDT") == "BTCUSDT"

    def test_yfinance_format(self):
        assert to_binance_pair("BTC-USD") == "BTCUSDT"

    def test_case_insensitive(self):
        assert to_binance_pair("btcusdt") == "BTCUSDT"
        assert to_binance_pair("eth") == "ETHUSDT"

    def test_custom_quote_currency(self):
        assert to_binance_pair("BTC", quote="BUSD") == "BTCBUSD"

    def test_with_busd_suffix(self):
        assert to_binance_pair("ETHBUSD") == "ETHBUSD"


class TestToYfinanceTicker:
    def test_from_binance_pair(self):
        assert to_yfinance_ticker("BTCUSDT") == "BTC-USD"

    def test_from_bare_coin(self):
        assert to_yfinance_ticker("BTC") == "BTC-USD"

    def test_already_yfinance_format(self):
        assert to_yfinance_ticker("BTC-USD") == "BTC-USD"

    def test_eth_conversion(self):
        assert to_yfinance_ticker("ETHUSDT") == "ETH-USD"

    def test_case_insensitive(self):
        assert to_yfinance_ticker("btcusdt") == "BTC-USD"


class TestFromBinancePair:
    def test_btcusdt(self):
        assert from_binance_pair("BTCUSDT") == ("BTC", "USDT")

    def test_ethbusd(self):
        assert from_binance_pair("ETHBUSD") == ("ETH", "BUSD")

    def test_solusdc(self):
        assert from_binance_pair("SOLUSDC") == ("SOL", "USDC")

    def test_case_insensitive(self):
        assert from_binance_pair("btcusdt") == ("BTC", "USDT")


class TestCryptoTop20:
    def test_has_20_symbols(self):
        assert len(CRYPTO_TOP_20) == 20

    def test_all_end_with_usdt(self):
        for sym in CRYPTO_TOP_20:
            assert sym.endswith("USDT"), f"{sym} does not end with USDT"

    def test_contains_btc_and_eth(self):
        assert "BTCUSDT" in CRYPTO_TOP_20
        assert "ETHUSDT" in CRYPTO_TOP_20

    def test_no_duplicates(self):
        assert len(set(CRYPTO_TOP_20)) == len(CRYPTO_TOP_20)
