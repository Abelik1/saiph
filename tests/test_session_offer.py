# SPDX-License-Identifier: AGPL-3.0-or-later
"""Session offers: the shared format, expiry and replay limits. Synthetic values only."""
import base64
import json
from copy import deepcopy
from pathlib import Path

import pytest

from orion_mini.session_offer import MAX_LIFETIME, SESSION_OFFER, OfferError, OfferReceipts, build_offer, read_offer

VECTORS = json.loads((Path(__file__).resolve().parents[1] / "android" / "app" / "src" / "test" / "resources"
                      / "session-offer-vectors.json").read_text(encoding="utf-8"))
NOW = VECTORS["now"]


@pytest.mark.parametrize("case", VECTORS["cases"], ids=lambda case: case["name"])
def test_shared_vectors_match_the_android_phone(case):
    if case["valid"]:
        assert read_offer(deepcopy(case["payload"]), NOW) == case["payload"]
    else:
        with pytest.raises(OfferError):
            read_offer(deepcopy(case["payload"]), NOW)


def valid():
    return deepcopy(VECTORS["cases"][0]["payload"])


def test_vectors_cover_both_outcomes_and_every_rule():
    names = {case["name"] for case in VECTORS["cases"]}
    assert sum(case["valid"] for case in VECTORS["cases"]) >= 2
    assert {"expired", "too far ahead", "deadline differs from invitation", "unknown service", "extra field",
            "version boolean", "public address"} <= names


def test_build_binds_a_fresh_id_to_the_invitation_deadline():
    invite = valid()["invite"]
    first, second = build_offer("camera", invite, NOW), build_offer("camera", invite, NOW)
    assert first["type"] == SESSION_OFFER and first["expires_at"] == NOW + 90 and first["invite"] == invite
    assert first["id"] != second["id"]
    with pytest.raises(OfferError):
        build_offer("screen", invite, NOW)
    with pytest.raises(OfferError):
        build_offer("camera", invite, NOW + 90)  # Never outlives the invitation.


def test_offer_lifetime_never_exceeds_the_camera_invitation_limit():
    assert MAX_LIFETIME == 120


def test_offer_shape_is_exact_and_plain_json():
    offer = build_offer("camera", valid()["invite"], NOW)
    assert set(offer) == {"type", "version", "id", "service", "expires_at", "invite"}
    assert json.loads(json.dumps(offer)) == offer
    # The invitation is carried verbatim: the phone's scanner parser sees exactly what a QR would show.
    encoded = offer["invite"].split(":", 2)[2]
    assert json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))["expires"] == offer["expires_at"]


def test_receipts_show_each_offer_once_and_stay_bounded():
    receipts = OfferReceipts(limit=2)
    offer = read_offer(valid(), NOW)
    assert receipts.claim(offer, NOW)
    assert not receipts.claim(offer, NOW)
    assert receipts.claim({**offer, "id": "d" * 32}, NOW)
    assert not receipts.claim({**offer, "id": "e" * 32}, NOW)  # Full: refuse rather than forget a live offer.
    assert receipts.claim({**offer, "id": "e" * 32}, offer["expires_at"])  # Expired entries drop out.
