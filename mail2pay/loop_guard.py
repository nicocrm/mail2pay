"""Decide whether an error-reply email is safe to send.

Centralizes loop-prevention rules (R5, R7, R8 in the requirements doc) so the
handler stays linear and the rules are testable in isolation.
"""

from __future__ import annotations

import re

_NO_REPLY_RE = re.compile(
    r"^(no-?reply|do-?not-?reply|mailer-daemon|postmaster)$",
    re.IGNORECASE,
)


def should_send_error_reply(
    from_addr: str, self_from: str
) -> tuple[bool, str | None]:
    """Return ``(send, suppression_reason)``.

    ``send`` is ``True`` when an error-reply email may be sent to ``from_addr``.
    When ``False``, ``suppression_reason`` is a short stable token suitable for
    structured logging (``"self_loop"`` | ``"no_reply_local_part"``).
    """
    if from_addr.lower() == self_from.lower():
        return False, "self_loop"

    local = from_addr.rsplit("@", 1)[0]
    if _NO_REPLY_RE.match(local):
        return False, "no_reply_local_part"

    return True, None
