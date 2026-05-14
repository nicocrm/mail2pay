"""Clerk Backend API lookup — is this email a registered user?"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

_CLERK_API_BASE = "https://api.clerk.com/v1"
_TIMEOUT_SECONDS = 5.0


class ClerkLookupError(Exception):
    """Raised when a Clerk user lookup cannot be completed reliably.

    This is retryable: the caller should surface a 5xx so the upstream
    webhook is retried rather than silently dropping a legitimate email on
    a transient Clerk outage.
    """


def is_registered_user(
    email: str,
    secret_key: str,
    *,
    client: httpx.Client | None = None,
) -> bool:
    """Return True iff *email* matches a verified Clerk user.

    Matching rules:
    * Input is stripped and lower-cased before comparison.
    * The user's email must appear in Clerk's ``email_addresses`` list and
      have ``verification.status == "verified"``.
    * Empty or whitespace-only input returns ``False`` without making an
      HTTP call.

    Raises :class:`ClerkLookupError` on network errors, timeouts, 5xx
    responses, or misconfiguration (e.g. 401). The caller should treat this
    as retryable.
    """
    normalised = (email or "").strip().lower()
    if not normalised:
        return False

    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=_TIMEOUT_SECONDS)

    try:
        try:
            response = client.get(
                f"{_CLERK_API_BASE}/users",
                params={"email_address": normalised, "limit": 1},
                headers={"Authorization": f"Bearer {secret_key}"},
            )
        except httpx.HTTPError as exc:
            raise ClerkLookupError(f"Clerk request failed: {exc}") from exc

        if response.status_code >= 500:
            raise ClerkLookupError(
                f"Clerk returned {response.status_code}: {response.text[:200]}"
            )
        if response.status_code == 401 or response.status_code == 403:
            raise ClerkLookupError(
                f"Clerk auth failed ({response.status_code}) — check CLERK_SECRET_KEY"
            )
        if response.status_code >= 400:
            # 4xx other than auth: treat as no-match rather than raising.
            # E.g. malformed email parameter → user simply isn't registered.
            logger.info(
                "Clerk returned %s for email lookup; treating as unregistered",
                response.status_code,
            )
            return False

        try:
            users = response.json()
        except ValueError as exc:
            raise ClerkLookupError(f"Clerk returned non-JSON body: {exc}") from exc

        if not isinstance(users, list) or not users:
            return False

        for user in users:
            for addr in user.get("email_addresses") or []:
                stored = (addr.get("email_address") or "").strip().lower()
                if stored != normalised:
                    continue
                verification = addr.get("verification") or {}
                if verification.get("status") == "verified":
                    return True
        return False
    finally:
        if owns_client:
            client.close()
