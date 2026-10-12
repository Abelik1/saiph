# SPDX-License-Identifier: AGPL-3.0-or-later
"""Synthetic Python/Kotlin HPKE interoperability, with temporary test keys only.

Run with hosted development dependencies, JDK 22 and the Android SDK configured.
Private fixture files are ignored, temporary and removed even on failed checks.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from tink import proto_keyset_format, secret_key_access

from orion_mini.hosted_crypto import canonical, export_public, generate_recipient, open_envelope, seal
from orion_mini.hosted_session import SealedSession, sign_roster
from orion_mini.hosted_approval import local_root


def main():
    repository = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--android-root", type=Path, default=repository / ".orion-mini/orion-android")
    args = parser.parse_args()
    android = args.android_root.resolve()
    wrapper = android / ("gradlew.bat" if os.name == "nt" else "gradlew")
    if not wrapper.is_file() or not (android / "docs/ORION_PHASE2.md").is_file():
        raise SystemExit("Use the Orion Android fork checkout.")
    output = repository / "test-artifacts/hosted-e2ee"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="synthetic-interop-", dir=output) as folder:
        private = Path(folder) / "fixture.json"
        result = Path(folder) / "kotlin.json"
        recipient = generate_recipient()
        signing = ec.generate_private_key(ec.SECP256R1())
        header = {"protocol_version": 1, "deployment_id": str(uuid4()), "roster_version": 7,
                  "roster_hash": "a" * 64, "id": str(uuid4()), "source": "dev_" + uuid4().hex,
                  "target": "dev_" + uuid4().hex, "expires_at": int(time.time()) + 300}
        payload = {"type": "test.synthetic", "text": "Unicode: ☄ 😀 é < > & / \\ \n \t",
                   "values": [None, True, False, 0, -5, 9007199254740991], "map": {"Ω": "astral 𐀀"}}
        def b64(raw):
            return base64.b64encode(raw).decode("ascii")
        public = b64(signing.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo))
        fixture = {"python_recipient_private_b64": b64(proto_keyset_format.serialize(recipient, secret_key_access.TOKEN)),
                   "python_recipient_public_b64": export_public(recipient),
                   "signing_private_pkcs8_b64": b64(signing.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())),
                   "signing_public_spki_b64": public, "header": header, "payload": payload,
                   "python_ciphertext": seal(export_public(recipient), signing, header, payload), "output_path": str(result)}
        # A real signed approval chain exercises session authority, not just
        # raw HPKE round trips. These identities exist only in this temporary
        # fixture; the root anchor is delivered independently to both clients.
        root_signing = ec.generate_private_key(ec.SECP256R1())
        root_recipient = generate_recipient()
        deployment, root_id, recipient_id = str(uuid4()), "dev_" + uuid4().hex, "dev_" + uuid4().hex
        root = local_root(deployment, root_id, root_signing, root_recipient)
        root_session = SealedSession(Path(folder) / "root.sqlite3", deployment, root.signing_key,
                                     root_id, root_signing, root_recipient)
        chain = []
        approved_members = sorted([root.member(), {"id": recipient_id, "signing_key": public,
                                                  "encryption_key": export_public(recipient)}], key=lambda item: item["id"])
        for version in range(1, 147):
            previous_hash = hashlib.sha256(canonical(chain[-1]["roster"])).hexdigest() if chain else None
            chain.append(sign_roster({"deployment_id": deployment, "version": version,
                                      "previous_hash": previous_hash,
                                      "expires_at": int(time.time()) + (3600 if version == 146 else -1),
                                      "members": [root.member()] if version == 1 else approved_members}, root_signing))
        # Both runtimes must verify historical pages without treating their
        # expired members as content authority, then authorize the fresh head.
        for offset in range(0, len(chain), 16):
            root_session.accept_page(chain[offset:offset + 16], final=offset + 16 >= len(chain))
            if offset + 16 < len(chain):
                try:
                    root_session.current()
                except ValueError:
                    pass
                else:
                    raise SystemExit("Historical page unexpectedly authorized content.")
        fixture.update({"trusted_root": {"deployment_id": deployment, "device": root.member()},
                        "signed_chain": chain, "recipient_device_id": recipient_id,
                        "session_sender_device_id": root_id,
                        "python_session_envelope": root_session.encrypt(recipient_id, payload, ttl_seconds=300)})
        private.write_text(json.dumps(fixture, ensure_ascii=True), encoding="utf-8")
        private.chmod(0o600)
        environment = {**os.environ, "ORION_HPKE_FIXTURE": str(private)}
        subprocess.run([str(wrapper), ":core:network:testDebugUnitTest", "--rerun-tasks",
                        "-PorionIndependent=true", "-PorionFirebase=false",
                        "--console=plain"], cwd=android, env=environment, timeout=600, check=True)
        kotlin = json.loads(result.read_text(encoding="utf-8"))
        if (kotlin["header"] != header or kotlin["recipient_public_b64"] != export_public(recipient)
                or kotlin["signing_public_spki_b64"] != public
                or open_envelope(recipient, signing.public_key(), header, kotlin["kotlin_ciphertext"]) != payload):
            raise SystemExit("Synthetic interoperability verification failed.")
        session_result = json.loads(Path(str(result) + ".session.json").read_text(encoding="utf-8"))
        if (root_session.receive(session_result["kotlin_session_envelope"]) != payload
                or session_result["root_fingerprint"] != root.fingerprint):
            raise SystemExit("Synthetic session interoperability verification failed.")
    receipt = {"python_to_kotlin": True, "kotlin_to_python": True, "synthetic_only": True,
               "temporary_private_fixture_removed": True, "python_tink": "1.16.1", "android_tink": "1.23.0",
               "root_pinned_sessions_both_directions": True,
               "signed_roster_versions": 146, "bounded_roster_page_size": 16,
               "expired_historical_pages_do_not_authorize_content": True}
    (output / "interop-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print("Synthetic Python/Kotlin encrypted envelopes verified in both directions; temporary fixture removed.")


if __name__ == "__main__":
    main()
