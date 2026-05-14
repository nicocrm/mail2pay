import pytest

from mail2pay.loop_guard import should_send_error_reply

SELF = "bot@mail2pay.example"


def test_ordinary_sender_is_allowed():
    assert should_send_error_reply("alice@example.com", SELF) == (True, None)


# --- R5: self-loop (AE3) ---------------------------------------------------

def test_self_loop_exact_match_suppressed():
    send, reason = should_send_error_reply(SELF, SELF)
    assert send is False
    assert reason == "self_loop"


@pytest.mark.parametrize(
    "from_addr",
    [
        "BOT@mail2pay.example",
        "Bot@Mail2Pay.Example",
        "bot@MAIL2PAY.EXAMPLE",
    ],
)
def test_self_loop_case_insensitive(from_addr):
    send, reason = should_send_error_reply(from_addr, SELF)
    assert send is False
    assert reason == "self_loop"


# --- R7: no-reply local-part (AE5) -----------------------------------------

@pytest.mark.parametrize(
    "local",
    [
        "no-reply",
        "noreply",
        "do-not-reply",
        "donotreply",
        "DoNotReply",
        "NoReply",
        "mailer-daemon",
        "MAILER-DAEMON",
        "postmaster",
    ],
)
def test_no_reply_local_part_suppressed(local):
    send, reason = should_send_error_reply(f"{local}@acme.com", SELF)
    assert send is False
    assert reason == "no_reply_local_part"


@pytest.mark.parametrize(
    "local",
    [
        "notifications",
        "noreplypal",      # not an exact match — allowed
        "reply-no",        # allow-list is anchored
        "autoresponder",   # intentionally out of scope for v1
    ],
)
def test_non_matching_local_parts_allowed(local):
    send, reason = should_send_error_reply(f"{local}@acme.com", SELF)
    assert send is True
    assert reason is None


# --- Robustness ------------------------------------------------------------

def test_malformed_address_without_at_does_not_crash():
    # EmailStr upstream normally prevents this, but the guard must not blow up.
    send, reason = should_send_error_reply("no-reply", SELF)
    # rsplit with no `@` yields the whole string, so no-reply still matches.
    assert send is False
    assert reason == "no_reply_local_part"


def test_self_loop_takes_precedence_over_no_reply():
    self_addr = "no-reply@mail2pay.example"
    send, reason = should_send_error_reply(self_addr, self_addr)
    assert send is False
    assert reason == "self_loop"
