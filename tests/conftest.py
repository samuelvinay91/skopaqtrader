"""Shared test fixtures."""

import os

import pytest

# Ensure tests don't accidentally use real credentials
os.environ.setdefault("SKOPAQ_TRADING_MODE", "paper")
os.environ.setdefault("SKOPAQ_SUPABASE_URL", "")
os.environ.setdefault("SKOPAQ_SUPABASE_SERVICE_KEY", "")
