"""Tests for mail2pay.clerk — Clerk Backend API user lookup."""

from __future__ import annotations

import httpx
import pytest

from mail2pay.clerk import ClerkLookupError, is_registered_user


def _make_client(handler):
    """Build an httpx.Client backed by MockTransport calling `handler`."""
    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport)


def _user_payload(email: str, *, verified: bool = True) -> dict:
    return {
        "id": "user_123",
        "email_addresses": [
            {
                "email_address": email,
                "verification": {"status": "verified" if verified else "unverified"},
            }
        ],
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_returns_true_when_clerk_finds_verified_user():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["email_address"] == "alice@example.com"
        assert request.headers["authorization"] == "Bearer sk_test_xyz"
        return httpx.Response(200, json=[_user_payload("alice@example.com")])

    with _make_client(handler) as client:
        assert is_registered_user("alice@example.com", "sk_test_xyz", client=client) is True


def test_case_insensitive_match():
    """Input `Alice@Example.com` matches stored `alice@example.com`."""
    def handler(request: httpx.Request) -> httpx.Response:
        # Normalisation: the module sends the lowercased form
        assert request.url.params["email_address"] == "alice@example.com"
        return httpx.Response(200, json=[_user_payload("alice@example.com")])

    with _make_client(handler) as client:
        assert is_registered_user("Alice@Example.com", "sk", client=client) is True


# ---------------------------------------------------------------------------
# Negative cases — return False without raising
# ---------------------------------------------------------------------------

def test_empty_list_returns_false():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    with _make_client(handler) as client:
        assert is_registered_user("ghost@example.com", "sk", client=client) is False


def test_unverified_email_returns_false():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_user_payload("a@b.com", verified=False)])

    with _make_client(handler) as client:
        assert is_registered_user("a@b.com", "sk", client=client) is False


def test_plus_addressing_is_distinct():
    """`a+tag@b.com` and `a@b.com` are distinct addresses in Clerk."""
    def handler(request: httpx.Request) -> httpx.Response:
        # Clerk is queried with the exact address; it returns no match
        assert request.url.params["email_address"] == "a+tag@b.com"
        return httpx.Response(200, json=[])

    with _make_client(handler) as client:
        assert is_registered_user("a+tag@b.com", "sk", client=client) is False


def test_empty_input_short_circuits_without_http_call():
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(200, json=[])

    with _make_client(handler) as client:
        assert is_registered_user("", "sk", client=client) is False
        assert is_registered_user("   ", "sk", client=client) is False
    assert call_count["n"] == 0


def test_4xx_other_than_auth_returns_false():
    """Malformed-email 400 from Clerk is treated as 'not registered', not an error."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"errors": [{"message": "bad"}]})

    with _make_client(handler) as client:
        assert is_registered_user("weird@local", "sk", client=client) is False


# ---------------------------------------------------------------------------
# Error cases — raise ClerkLookupError (retryable)
# ---------------------------------------------------------------------------

def test_clerk_5xx_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream down")

    with _make_client(handler) as client:
        with pytest.raises(ClerkLookupError):
            is_registered_user("a@b.com", "sk", client=client)


def test_network_error_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with _make_client(handler) as client:
        with pytest.raises(ClerkLookupError):
            is_registered_user("a@b.com", "sk", client=client)


def test_401_raises_as_misconfiguration():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"errors": [{"message": "unauthenticated"}]})

    with _make_client(handler) as client:
        with pytest.raises(ClerkLookupError):
            is_registered_user("a@b.com", "sk_bad", client=client)


def test_non_json_response_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>nope</html>")

    with _make_client(handler) as client:
        with pytest.raises(ClerkLookupError):
            is_registered_user("a@b.com", "sk", client=client)
