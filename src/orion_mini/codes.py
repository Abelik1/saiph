# SPDX-License-Identifier: AGPL-3.0-or-later
"""Find one-time verification codes in phone notifications. Local only; never logged."""
from __future__ import annotations

import re

KEYWORDS = re.compile(r"\b(code|codes|otp|passcode|one[- ]time|verification|verify|2fa|two[- ]factor|security|login|sign[- ]in|pin|token|confirm)\b", re.IGNORECASE)
# 4–8 digits, or two groups of three/four digits joined by a space or dash.
# A prefix such as "G-" is allowed; digits joined to other numbers, amounts or
# decimals are not. A full stop may end the sentence.
CANDIDATE = re.compile(r"(?<![\w.,/:+])(?<!\d-)(\d{3,4})[ -](\d{3,4})(?![\w,/:-]|\.\d)|(?<![\w.,/:+])(?<!\d-)(\d{4,8})(?![\w,/:%-]|\.\d)")


def verification_code(*parts):
    """The code in a verification message, or None. Requires a code keyword nearby."""
    text = " ".join(str(part) for part in parts if part)[:1000]
    if not KEYWORDS.search(text):
        return None
    for match in CANDIDATE.finditer(text):
        code = match.group(3) or match.group(1) + match.group(2)
        if 4 <= len(code) <= 8 and not re.fullmatch(r"(19|20)\d\d", code):  # Skip years.
            return code
    return None
