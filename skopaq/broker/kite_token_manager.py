"""Kite Connect token lifecycle management.

Kite Connect uses a 2-step OAuth flow:
    1. User logs in at ``https://kite.zerodha.com/connect/login?v=3&api_key=xxx``
    2. Redirected back with ``request_token`` in query params
    3. Exchange ``request_token`` for ``access_token`` via API call
    4. ``access_token`` is valid from login until ~6:00 AM next day

This module manages the ``access_token`` lifecycle:
    - Encrypted storage at rest (same pattern as INDstocks TokenManager)
    - Token health checks with expiry warnings
    - ``generate_session()`` to exchange request_token → access_token

Unlike INDstocks (24-hour rolling), Kite tokens expire at a fixed daily time
(~6:00 AM IST), so we always set expiry to next 6 AM.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

_IST = timezone(timedelta(hours=5, minutes=30))

KITE_TOKEN_DIR = Path.home() / ".skopaq"
KITE_TOKEN_FILE = KITE_TOKEN_DIR / "kite_token.enc"
KITE_KEY_FILE = KITE_TOKEN_DIR / "kite_token.key"

# Kite sessions expire at ~6:00 AM IST daily
KITE_SESSION_EXPIRY_TIME = time(6, 0)

# Warn at these intervals before expiry
WARN_THRESHOLDS = [
    timedelta(hours=2),
    timedelta(hours=1),
    timedelta(minutes=30),
    timedelta(minutes=10),
]

# Kite Connect session API
KITE_API_BASE = "https://api.kite.trade"


@dataclass
class KiteTokenHealth:
    """Current Kite token status."""

    valid: bool
    access_token: str = ""
    expires_at: Optional[datetime] = None
    remaining: Optional[timedelta] = None
    warning: str = ""


class KiteTokenManager:
    """Manages Kite Connect access_token encryption, storage, and expiry.

    Usage::

        mgr = KiteTokenManager()

        # Option 1: Set access_token directly (if obtained externally)
        mgr.set_token("your_access_token")

        # Option 2: Exchange request_token for access_token
        await mgr.generate_session(api_key, api_secret, request_token)

        # Get token for API calls
        token = mgr.get_token()
    """

    def __init__(self) -> None:
        self._fernet: Optional[Fernet] = None
        self._warned_thresholds: set[int] = set()

    def _ensure_key(self) -> Fernet:
        """Load or create encryption key."""
        if self._fernet is not None:
            return self._fernet

        KITE_TOKEN_DIR.mkdir(parents=True, exist_ok=True)

        if KITE_KEY_FILE.exists():
            key = KITE_KEY_FILE.read_bytes()
        else:
            key = Fernet.generate_key()
            KITE_KEY_FILE.write_bytes(key)
            KITE_KEY_FILE.chmod(0o600)

        self._fernet = Fernet(key)
        return self._fernet

    def set_token(self, access_token: str) -> None:
        """Encrypt and store an access token.

        Kite tokens expire at ~6:00 AM IST daily.  If current time is
        before 6 AM, expiry is today at 6 AM; otherwise tomorrow at 6 AM.

        Args:
            access_token: The access_token from Kite session API.
        """
        expires_at = self._next_expiry()
        fernet = self._ensure_key()
        payload = json.dumps({
            "access_token": access_token,
            "expires_at": expires_at.isoformat(),
            "stored_at": datetime.now(timezone.utc).isoformat(),
        })
        encrypted = fernet.encrypt(payload.encode())
        KITE_TOKEN_FILE.write_bytes(encrypted)
        KITE_TOKEN_FILE.chmod(0o600)
        self._warned_thresholds.clear()
        logger.info("Kite token stored, expires at %s", expires_at.isoformat())

    async def generate_session(
        self, api_key: str, api_secret: str, request_token: str,
    ) -> str:
        """Exchange request_token for access_token and store it.

        This calls ``POST /session/token`` on Kite Connect API.

        Args:
            api_key: Kite Connect app API key.
            api_secret: Kite Connect app API secret.
            request_token: The request_token from login redirect.

        Returns:
            The access_token string.
        """
        # Kite requires checksum = SHA256(api_key + request_token + api_secret)
        checksum = hashlib.sha256(
            f"{api_key}{request_token}{api_secret}".encode()
        ).hexdigest()

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{KITE_API_BASE}/session/token",
                data={
                    "api_key": api_key,
                    "request_token": request_token,
                    "checksum": checksum,
                },
            )

        if resp.status_code >= 400:
            raise KiteTokenExpiredError(
                f"Session generation failed ({resp.status_code}): {resp.text}"
            )

        data = resp.json()
        if isinstance(data, dict) and data.get("status") == "error":
            raise KiteTokenExpiredError(
                f"Session generation failed: {data.get('message', 'Unknown error')}"
            )

        session_data = data.get("data", data) if isinstance(data, dict) else {}
        access_token = session_data.get("access_token", "")

        if not access_token:
            raise KiteTokenExpiredError(
                "No access_token in session response"
            )

        self.set_token(access_token)
        logger.info("Kite session generated successfully")
        return access_token

    def get_health(self) -> KiteTokenHealth:
        """Check current token validity and remaining time."""
        if not KITE_TOKEN_FILE.exists():
            return KiteTokenHealth(
                valid=False,
                warning="No Kite token stored. Run: skopaq kite login",
            )

        try:
            fernet = self._ensure_key()
            encrypted = KITE_TOKEN_FILE.read_bytes()
            payload = json.loads(fernet.decrypt(encrypted).decode())
        except Exception as exc:
            return KiteTokenHealth(
                valid=False, warning=f"Kite token decryption failed: {exc}"
            )

        access_token = payload["access_token"]
        expires_at = datetime.fromisoformat(payload["expires_at"])
        now = datetime.now(timezone.utc)
        remaining = expires_at - now

        if remaining.total_seconds() <= 0:
            return KiteTokenHealth(
                valid=False,
                expires_at=expires_at,
                remaining=timedelta(0),
                warning="Kite token EXPIRED. Login again at market open.",
            )

        warning = ""
        for threshold in WARN_THRESHOLDS:
            mins = int(threshold.total_seconds() / 60)
            if remaining <= threshold and mins not in self._warned_thresholds:
                warning = f"Kite token expires in {remaining}. Login again before market open."
                self._warned_thresholds.add(mins)
                logger.warning(warning)
                break

        return KiteTokenHealth(
            valid=True,
            access_token=access_token,
            expires_at=expires_at,
            remaining=remaining,
            warning=warning,
        )

    def get_token(self) -> str:
        """Return the current access_token or raise if expired/missing."""
        health = self.get_health()
        if not health.valid:
            raise KiteTokenExpiredError(health.warning)
        return health.access_token

    def clear(self) -> None:
        """Delete stored Kite token."""
        if KITE_TOKEN_FILE.exists():
            KITE_TOKEN_FILE.unlink()
        self._warned_thresholds.clear()
        logger.info("Kite token cleared")

    @staticmethod
    def get_login_url(api_key: str) -> str:
        """Return the Kite Connect login URL for the given API key.

        The user must visit this URL in a browser to complete OAuth login.
        After login, Kite redirects to the registered redirect URL with
        ``?request_token=xxx&status=success`` in the query params.
        """
        return f"https://kite.zerodha.com/connect/login?v=3&api_key={api_key}"

    @staticmethod
    def _next_expiry() -> datetime:
        """Calculate the next Kite session expiry (6:00 AM IST).

        If current IST time is before 6 AM, expiry is today at 6 AM.
        If current IST time is after 6 AM, expiry is tomorrow at 6 AM.
        """
        now_ist = datetime.now(_IST)
        today_expiry = datetime.combine(
            now_ist.date(), KITE_SESSION_EXPIRY_TIME, tzinfo=_IST,
        )

        if now_ist < today_expiry:
            return today_expiry.astimezone(timezone.utc)
        else:
            return (today_expiry + timedelta(days=1)).astimezone(timezone.utc)


class KiteTokenExpiredError(Exception):
    """Raised when the Kite Connect access_token is expired or missing."""
