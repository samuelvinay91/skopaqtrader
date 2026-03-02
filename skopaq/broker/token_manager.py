"""INDstocks API token lifecycle management.

Tokens expire every 24 hours and must be regenerated manually from the
INDstocks dashboard.  This module encrypts the token at rest, tracks expiry,
sends warnings, and auto-falls-back to paper mode when expired.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

TOKEN_DIR = Path.home() / ".skopaq"
TOKEN_FILE = TOKEN_DIR / "token.enc"
KEY_FILE = TOKEN_DIR / "token.key"

# Warn at these intervals before expiry
WARN_THRESHOLDS = [
    timedelta(hours=2),
    timedelta(hours=1),
    timedelta(minutes=30),
    timedelta(minutes=10),
]


@dataclass
class TokenHealth:
    """Current token status."""

    valid: bool
    token: str = ""
    expires_at: Optional[datetime] = None
    remaining: Optional[timedelta] = None
    warning: str = ""


class TokenManager:
    """Manages INDstocks API token encryption, storage, and expiry tracking."""

    def __init__(self) -> None:
        self._fernet: Optional[Fernet] = None
        self._warned_thresholds: set[int] = set()

    def _ensure_key(self) -> Fernet:
        """Load or create encryption key."""
        if self._fernet is not None:
            return self._fernet

        TOKEN_DIR.mkdir(parents=True, exist_ok=True)

        if KEY_FILE.exists():
            key = KEY_FILE.read_bytes()
        else:
            key = Fernet.generate_key()
            KEY_FILE.write_bytes(key)
            KEY_FILE.chmod(0o600)

        self._fernet = Fernet(key)
        return self._fernet

    def set_token(self, token: str, ttl_hours: float = 24.0) -> None:
        """Encrypt and store a new API token.

        Args:
            token: The Bearer token from INDstocks dashboard.
            ttl_hours: Hours until expiry (default 24).
        """
        fernet = self._ensure_key()
        expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
        payload = json.dumps({
            "token": token,
            "expires_at": expires_at.isoformat(),
            "stored_at": datetime.now(timezone.utc).isoformat(),
        })
        encrypted = fernet.encrypt(payload.encode())
        TOKEN_FILE.write_bytes(encrypted)
        TOKEN_FILE.chmod(0o600)
        self._warned_thresholds.clear()
        logger.info("Token stored, expires at %s", expires_at.isoformat())

    def get_health(self) -> TokenHealth:
        """Check current token validity and remaining time."""
        if not TOKEN_FILE.exists():
            return TokenHealth(valid=False, warning="No token stored. Run: skopaq token set <token>")

        try:
            fernet = self._ensure_key()
            encrypted = TOKEN_FILE.read_bytes()
            payload = json.loads(fernet.decrypt(encrypted).decode())
        except Exception as exc:
            return TokenHealth(valid=False, warning=f"Token decryption failed: {exc}")

        token = payload["token"]
        expires_at = datetime.fromisoformat(payload["expires_at"])
        now = datetime.now(timezone.utc)
        remaining = expires_at - now

        if remaining.total_seconds() <= 0:
            return TokenHealth(
                valid=False,
                expires_at=expires_at,
                remaining=timedelta(0),
                warning="Token EXPIRED. Regenerate from INDstocks dashboard.",
            )

        warning = ""
        for threshold in WARN_THRESHOLDS:
            mins = int(threshold.total_seconds() / 60)
            if remaining <= threshold and mins not in self._warned_thresholds:
                warning = f"Token expires in {remaining}. Refresh from INDstocks dashboard."
                self._warned_thresholds.add(mins)
                logger.warning(warning)
                break

        return TokenHealth(
            valid=True,
            token=token,
            expires_at=expires_at,
            remaining=remaining,
            warning=warning,
        )

    def get_token(self) -> str:
        """Return the current token or raise if expired/missing."""
        health = self.get_health()
        if not health.valid:
            raise TokenExpiredError(health.warning)
        return health.token

    def clear(self) -> None:
        """Delete stored token."""
        if TOKEN_FILE.exists():
            TOKEN_FILE.unlink()
        self._warned_thresholds.clear()
        logger.info("Token cleared")


class TokenExpiredError(Exception):
    """Raised when the INDstocks token is expired or missing."""
