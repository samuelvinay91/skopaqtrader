"""Tests for INDstocks token manager."""

import json
import time
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from skopaq.broker.token_manager import TokenExpiredError, TokenManager


@pytest.fixture
def tmp_token_dir(tmp_path):
    """Redirect token storage to a temp directory."""
    token_dir = tmp_path / ".skopaq"
    with (
        patch("skopaq.broker.token_manager.TOKEN_DIR", token_dir),
        patch("skopaq.broker.token_manager.TOKEN_FILE", token_dir / "token.enc"),
        patch("skopaq.broker.token_manager.KEY_FILE", token_dir / "token.key"),
    ):
        yield token_dir


@pytest.fixture
def mgr(tmp_token_dir):
    return TokenManager()


class TestTokenManager:
    def test_no_token_stored(self, mgr):
        health = mgr.get_health()
        assert not health.valid
        assert "No token stored" in health.warning

    def test_set_and_get_token(self, mgr):
        mgr.set_token("my-secret-token", ttl_hours=24)
        health = mgr.get_health()
        assert health.valid
        assert health.token == "my-secret-token"
        assert health.remaining.total_seconds() > 0

    def test_get_token_returns_string(self, mgr):
        mgr.set_token("bearer-xyz")
        assert mgr.get_token() == "bearer-xyz"

    def test_expired_token(self, mgr):
        # Set token with 0 TTL — immediately expired
        mgr.set_token("old-token", ttl_hours=0)
        health = mgr.get_health()
        assert not health.valid
        assert "EXPIRED" in health.warning

    def test_get_token_raises_when_expired(self, mgr):
        mgr.set_token("old-token", ttl_hours=0)
        with pytest.raises(TokenExpiredError):
            mgr.get_token()

    def test_clear_token(self, mgr):
        mgr.set_token("to-be-cleared")
        mgr.clear()
        health = mgr.get_health()
        assert not health.valid

    def test_warning_thresholds(self, mgr):
        # Set token expiring in 25 minutes — should trigger 30min warning
        mgr.set_token("expiring-soon", ttl_hours=25 / 60)
        health = mgr.get_health()
        assert health.valid
        assert health.warning  # Should have a warning

    def test_encryption_persists(self, mgr, tmp_token_dir):
        mgr.set_token("persistent-token")
        # Create a new manager (simulates restart)
        mgr2 = TokenManager()
        assert mgr2.get_token() == "persistent-token"
