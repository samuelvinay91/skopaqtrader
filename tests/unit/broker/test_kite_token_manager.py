"""Tests for Kite Connect token manager."""

from datetime import datetime, time, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from skopaq.broker.kite_token_manager import (
    KITE_SESSION_EXPIRY_TIME,
    KiteTokenExpiredError,
    KiteTokenHealth,
    KiteTokenManager,
)


@pytest.fixture
def tmp_kite_dir(tmp_path):
    """Redirect Kite token storage to a temp directory."""
    token_dir = tmp_path / ".skopaq"
    with (
        patch("skopaq.broker.kite_token_manager.KITE_TOKEN_DIR", token_dir),
        patch("skopaq.broker.kite_token_manager.KITE_TOKEN_FILE", token_dir / "kite_token.enc"),
        patch("skopaq.broker.kite_token_manager.KITE_KEY_FILE", token_dir / "kite_token.key"),
    ):
        yield token_dir


@pytest.fixture
def mgr(tmp_kite_dir):
    return KiteTokenManager()


class TestKiteTokenManager:
    def test_no_token_stored(self, mgr):
        health = mgr.get_health()
        assert not health.valid
        assert "No Kite token stored" in health.warning

    def test_set_and_get_token(self, mgr):
        mgr.set_token("kite-access-token-123")
        health = mgr.get_health()
        assert health.valid
        assert health.access_token == "kite-access-token-123"
        assert health.remaining.total_seconds() > 0

    def test_get_token_returns_string(self, mgr):
        mgr.set_token("kite-xyz")
        assert mgr.get_token() == "kite-xyz"

    def test_get_token_raises_when_no_token(self, mgr):
        with pytest.raises(KiteTokenExpiredError):
            mgr.get_token()

    def test_clear_token(self, mgr):
        mgr.set_token("to-be-cleared")
        mgr.clear()
        health = mgr.get_health()
        assert not health.valid

    def test_encryption_persists(self, mgr, tmp_kite_dir):
        mgr.set_token("persistent-kite-token")
        # Create a new manager (simulates restart)
        mgr2 = KiteTokenManager()
        assert mgr2.get_token() == "persistent-kite-token"

    def test_expiry_is_next_6am_ist(self, mgr):
        mgr.set_token("test-token")
        health = mgr.get_health()
        assert health.valid
        assert health.expires_at is not None
        # Expiry should be at 6:00 AM IST (00:30 UTC)
        ist = timezone(timedelta(hours=5, minutes=30))
        expiry_ist = health.expires_at.astimezone(ist)
        assert expiry_ist.hour == 6
        assert expiry_ist.minute == 0


class TestKiteTokenManagerNextExpiry:
    def test_before_6am_expires_today(self):
        """If it's 3 AM IST, token should expire at 6 AM today."""
        ist = timezone(timedelta(hours=5, minutes=30))
        fake_now = datetime(2024, 3, 15, 3, 0, tzinfo=ist)

        with patch("skopaq.broker.kite_token_manager.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.combine = datetime.combine
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            expiry = KiteTokenManager._next_expiry()

            expected = datetime(2024, 3, 15, 6, 0, tzinfo=ist).astimezone(timezone.utc)
            assert expiry == expected

    def test_after_6am_expires_tomorrow(self):
        """If it's 10 AM IST, token should expire at 6 AM tomorrow."""
        ist = timezone(timedelta(hours=5, minutes=30))
        fake_now = datetime(2024, 3, 15, 10, 0, tzinfo=ist)

        with patch("skopaq.broker.kite_token_manager.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.combine = datetime.combine
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            expiry = KiteTokenManager._next_expiry()

            expected = datetime(2024, 3, 16, 6, 0, tzinfo=ist).astimezone(timezone.utc)
            assert expiry == expected


class TestKiteTokenManagerLoginUrl:
    def test_login_url_format(self):
        url = KiteTokenManager.get_login_url("my_api_key")
        assert url == "https://kite.zerodha.com/connect/login?v=3&api_key=my_api_key"


@pytest.mark.asyncio
class TestKiteGenerateSession:
    async def test_generate_session_success(self, mgr):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "data": {
                "access_token": "generated-access-token",
                "user_id": "AB1234",
            },
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("skopaq.broker.kite_token_manager.httpx.AsyncClient", return_value=mock_client):
            token = await mgr.generate_session("api_key", "api_secret", "request_token")

        assert token == "generated-access-token"
        assert mgr.get_token() == "generated-access-token"

    async def test_generate_session_failure(self, mgr):
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Invalid request token"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("skopaq.broker.kite_token_manager.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(KiteTokenExpiredError, match="Session generation failed"):
                await mgr.generate_session("api_key", "api_secret", "bad_token")

    async def test_generate_session_api_error(self, mgr):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "error",
            "message": "Invalid checksum",
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("skopaq.broker.kite_token_manager.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(KiteTokenExpiredError, match="Invalid checksum"):
                await mgr.generate_session("api_key", "api_secret", "request_token")


class TestKiteTokenHealth:
    def test_dataclass_fields(self):
        health = KiteTokenHealth(valid=True, access_token="tok")
        assert health.valid
        assert health.access_token == "tok"
        assert health.expires_at is None
        assert health.remaining is None
        assert health.warning == ""
