# SPDX-License-Identifier: AGPL-3.0-or-later
"""Exercise the actual hosted API/TLS/JWKS in disposable Docker services.

Run explicitly with --run. Existing containers, host credentials and live
services are never mounted or changed. Only a sanitized receipt is retained.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import time
from uuid import uuid4

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID
import jwt
import requests

from orion_mini.hosted_approval import (
    RootApproval, initialize_root, local_root, make_request_code, make_root_code,
    trust_root_code, verify_request_code, prepare_catchup,
)
from orion_mini.hosted_crypto import canonical, generate_recipient
from orion_mini.hosted_session import SealedSession, enrollment
from orion_mini.hosted_transport import HostedTransport, TransportError
from orion_mini.hosted_mailbox import DurableMailbox

ROOT = Path(__file__).resolve().parents[1]
ISSUER = "https://issuer.test/"
AUDIENCE = "https://synthetic.orion.invalid/api"
CLIENT = "synthetic-desktop"


class AcceptanceError(ValueError):
    pass


def run(*args, timeout=300):
    result = subprocess.run(args, capture_output=True, timeout=timeout)
    if result.returncode:
        raise AcceptanceError("Disposable operation failed")
    return result.stdout


def private_directory(path):
    path.chmod(0o700)
    if os.name == "nt":
        sid = run("whoami", "/user", "/fo", "csv", "/nh").decode().strip().split(",")[-1].strip('"')
        if not sid.startswith("S-1-") or not all(c.isdigit() or c in "S-" for c in sid):
            raise AcceptanceError("Cannot protect disposable directory")
        run("icacls", str(path), "/inheritance:r", "/grant:r", "*" + sid + ":(OI)(CI)F")


def certificates(folder):
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Orion disposable acceptance CA")])
    ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(ca_key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
          .not_valid_after(now + timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
          .sign(ca_key, hashes.SHA256()))
    (folder / "ca.crt").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    for purpose, names in (("issuer", [x509.DNSName("issuer.test")]),
                           ("proxy", [x509.DNSName("hub-a.test"), x509.DNSName("hub-b.test")])):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Disposable " + purpose)])
        cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
                .not_valid_after(now + timedelta(days=1)).add_extension(x509.SubjectAlternativeName(names), False)
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), True).sign(ca_key, hashes.SHA256()))
        (folder / (purpose + ".crt")).write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        (folder / (purpose + ".key")).write_bytes(key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    # Only generated TLS certificates/private keys are mounted. The synthetic
    # JWT signing key stays in caller memory; the issuer receives its public JWK.
    signing = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(signing.public_key()))
    public.update({"kid": "synthetic-acceptance", "alg": "RS256", "use": "sig"})
    (folder / "jwks.json").write_text(json.dumps({"keys": [public]}), encoding="utf-8")
    return signing


def account_token(key, subject, **override):
    now = int(time.time())
    claims = {"iss": ISSUER, "aud": AUDIENCE, "azp": CLIENT, "sub": subject, "iat": now - 1, "exp": now + 600}
    claims.update(override)
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "synthetic-acceptance"})


class Client:
    def __init__(self, base, ca, session=None):
        self.base, self.ca, self.session = base, ca, session
        self.http = requests.Session()
        self.http.trust_env = False

    def call(self, method, path, *, token=None, value=None, expected=200):
        raw = canonical(value) if value is not None else b""
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        elif self.session is not None:
            timestamp, nonce = str(int(time.time())), str(uuid4())
            digest = hashlib.sha256(raw).hexdigest()
            signed = f"{method}\n{path}\n{timestamp}\n{nonce}\n{digest}".encode()
            signature = self.session.signing.sign(signed, ec.ECDSA(hashes.SHA256()))
            headers.update({"X-Orion-Device-Id": self.session.device, "X-Orion-Timestamp": timestamp,
                            "X-Orion-Nonce": nonce, "X-Orion-Signature": base64.b64encode(signature).decode()})
        response = self.http.request(method, self.base + path, data=raw, headers=headers,
                                     verify=str(self.ca), timeout=5, allow_redirects=False)
        if response.status_code != expected:
            raise AcceptanceError("Unexpected isolated API result")
        return response.json()


def node(folder, deployment, root=None):
    signing = ec.generate_private_key(ec.SECP256R1())
    recipient = generate_recipient()
    device = "dev_" + uuid4().hex
    if root is None:
        root = local_root(deployment, device, signing, recipient)
    session = SealedSession(folder / (device + ".sqlite3"), deployment, root.signing_key, device, signing, recipient)
    return root, session


def wait_ready(client):
    end = time.monotonic() + 30
    while time.monotonic() < end:
        try:
            if client.call("GET", "/v1/health")["ok"] is True:
                return
        except (requests.RequestException, AcceptanceError):
            pass
        time.sleep(0.2)
    raise AcceptanceError("Disposable services did not become ready")


def mount(source, target):
    return ["--mount", f"type=bind,source={source},target={target},readonly"]


def curated_copy(source, destination):
    resolved = source.resolve()
    if (ROOT not in resolved.parents or source.is_symlink()
            or any(parent.is_symlink() for parent in source.parents if parent != ROOT and ROOT in parent.parents)
            or not resolved.is_file()):
        raise AcceptanceError("Unsafe source in curated build context")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(resolved, destination)


def assert_absent(hubs, containers, sessions, canaries, tokens):
    """Scan while queued bytes still exist; never print matching data/logs."""
    needles = [value.encode() for value in canaries + tokens]
    for hub in hubs:
        raw = run("docker", "exec", hub, "python", "-c",
            "from pathlib import Path; import sys; sys.stdout.buffer.write(b''.join(p.read_bytes() for p in Path('/data').iterdir() if p.is_file()))")
        if any(needle in raw for needle in needles):
            raise AcceptanceError("Sensitive material was present in operator storage")
    for container in containers:
        result = subprocess.run(["docker", "logs", container], capture_output=True, timeout=30)
        if result.returncode or any(needle in result.stdout + result.stderr for needle in needles):
            raise AcceptanceError("Sensitive material was present in operator logs")
    for session in sessions:
        # Client durable state is also ciphertext-only, including WAL pages.
        raw = b"".join(path.read_bytes() for path in session.state.parent.glob(session.state.name + "*") if path.is_file())
        if any(needle in raw for needle in needles):
            raise AcceptanceError("Sensitive material was present in client durable state")


def reopened(session, chain):
    result = SealedSession(session.state, session.deployment, session.pin, session.device, session.signing, session.encryption)
    result.accept_chain(chain)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "test-artifacts/hosted-docker/receipt.json")
    args = parser.parse_args()
    if not args.run:
        parser.error("Pass --run to create and remove disposable services")
    output = args.output.resolve()
    artifacts = (ROOT / "test-artifacts").resolve()
    if artifacts not in output.parents or output.exists():
        parser.error("Use a new receipt path inside test-artifacts")
    output.parent.mkdir(parents=True, exist_ok=True)
    project = "orion-hosted-acceptance-" + uuid4().hex[:12]
    image = project + ":local"
    containers, networks, volumes = [], [], []
    receipt = {"schema": 1, "synthetic_only": True, "real_auth0": False, "native_ui": False,
               "checks": {}, "cleanup": False, "status": "running"}
    step = "prepare"
    files = ["hub/orion_hub/hosted.py", "hub/orion_hub/hosted_auth.py", "hub/orion_hub/hosted_server.py",
             "src/orion_mini/hosted_crypto.py", "src/orion_mini/hosted_session.py", "src/orion_mini/hosted_approval.py",
             "src/orion_mini/hosted_transport.py", "src/orion_mini/hosted_mailbox.py",
             "src/orion_mini/hosted_files.py", "src/orion_mini/hosted_keys.py",
             "scripts/acceptance-hosted-docker.py", "scripts/hosted_acceptance/Dockerfile", "scripts/hosted_acceptance/issuer.py", "scripts/hosted_acceptance/worker.py", "hub/orion_hub/security.py"]
    files = sorted(set(files + [str(path.relative_to(ROOT)).replace("\\", "/")
                    for path in (ROOT / "hub/orion_hub").rglob("*.py")]
                    + ["src/orion_mini/__init__.py"]))
    receipt["source_hashes"] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files}
    receipt["source_commit"] = run("git", "-C", str(ROOT), "rev-parse", "HEAD").decode().strip()
    receipt["source_dirty"] = bool(run("git", "-C", str(ROOT), "status", "--porcelain").strip())
    failure = None
    with tempfile.TemporaryDirectory(prefix="private-", dir=output.parent) as temporary:
        private = Path(temporary).resolve()
        if artifacts not in private.parents:
            raise AcceptanceError("Unsafe disposable workspace")
        private_directory(private)
        try:
            print("Building isolated hosted runtime", flush=True)
            step = "image-build"
            context = private / "context"
            context.mkdir()
            for name in receipt["source_hashes"]:
                if name.startswith("hub/orion_hub/") and name.endswith(".py"):
                    curated_copy(ROOT / name, context / name)
            curated_copy(ROOT / "scripts/hosted_acceptance/Dockerfile", context / "Dockerfile")
            curated_copy(ROOT / "scripts/hosted_acceptance/issuer.py", context / "issuer.py")
            curated_copy(ROOT / "scripts/hosted_acceptance/worker.py", context / "worker.py")
            curated_copy(Path(__file__), context / "acceptance.py")
            client_sources = context / "src/orion_mini"
            client_sources.mkdir(parents=True)
            for module in ("__init__.py", "hosted_crypto.py", "hosted_session.py", "hosted_approval.py", "hosted_transport.py", "hosted_mailbox.py", "hosted_files.py", "hosted_keys.py"):
                curated_copy(ROOT / "src/orion_mini" / module, client_sources / module)
            run("docker", "build", "-t", image, str(context), timeout=600)
            receipt["runtime_image"] = json.loads(run("docker", "image", "inspect", image, "--format", "{{json .Id}}"))
            proxy_image = json.loads(run("docker", "image", "inspect", "nginx:1.27-alpine", "--format", "{{json .Id}}"))
            receipt["proxy_image"] = proxy_image
            fixture = private / "fixture"
            fixture.mkdir()
            jwt_key = certificates(fixture)
            (fixture / "nginx.conf").write_text("""pid /tmp/nginx.pid;
error_log /dev/stderr crit;
events { worker_connections 128; }
http {
 access_log off;
 client_body_temp_path /tmp/client;
 proxy_temp_path /tmp/proxy;
 fastcgi_temp_path /tmp/fastcgi;
 uwsgi_temp_path /tmp/uwsgi;
 scgi_temp_path /tmp/scgi;
 server { listen 8443 ssl; server_name _;
  ssl_certificate /fixture/proxy.crt;
  ssl_certificate_key /fixture/proxy.key;
  client_max_body_size 64k;
  location / { proxy_pass http://127.0.0.1:8766; proxy_set_header Host $http_host; }
 }
}
""", encoding="utf-8")
            ca = fixture / "ca.crt"
            step = "services-start"
            for suffix in ("a", "b"):
                name = project + "-net-" + suffix
                run("docker", "network", "create", "--internal", name)
                networks.append(name)
            issuer = project + "-issuer"
            run("docker", "create", "--name", issuer, "--network", networks[0], "--network-alias", "issuer.test",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--read-only", "--memory", "128m",
                "--sysctl", "net.ipv4.ip_unprivileged_port_start=0", *mount(fixture, "/fixture"), image, "python", "/app/issuer.py")
            containers.append(issuer)
            run("docker", "network", "connect", "--alias", "issuer.test", networks[1], issuer)
            run("docker", "start", issuer)
            deployments, owners, endpoints, hubs, proxies = [], [], [], [], []
            for index, suffix in enumerate(("a", "b")):
                deployment, owner = str(uuid4()), "auth0|synthetic-" + suffix
                deployments.append(deployment)
                owners.append(owner)
                volume, hub, proxy = project + "-data-" + suffix, project + "-hub-" + suffix, project + "-proxy-" + suffix
                run("docker", "volume", "create", volume)
                volumes.append(volume)
                environment = {"ORION_HOSTED_EXPERIMENTAL": "1", "ORION_AUTH0_ISSUER": ISSUER,
                    "ORION_AUTH0_AUDIENCE": AUDIENCE, "ORION_AUTH0_NATIVE_CLIENT_IDS": CLIENT,
                    "ORION_AUTH0_OWNER_SUBJECT": owner, "ORION_HOSTED_DEPLOYMENT_ID": deployment,
                    "ORION_HOSTED_DATABASE": "/data/orion-hosted.sqlite3", "SSL_CERT_FILE": "/fixture/ca.crt"}
                env_args = [item for key, value in environment.items() for item in ("--env", key + "=" + value)]
                run("docker", "run", "-d", "--name", hub, "--network", networks[index], "--network-alias", "hub-" + suffix + ".test",
                    "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--read-only", "--memory", "256m",
                    "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m", "--mount", f"type=volume,source={volume},target=/data",
                    *mount(fixture, "/fixture"), *env_args, image)
                containers.append(hub)
                hubs.append(hub)
                run("docker", "run", "-d", "--name", proxy, "--network", "container:" + hub,
                    "--user", "10001:10001",
                    "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--read-only", "--memory", "64m",
                    "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m", *mount(fixture, "/fixture"),
                    proxy_image, "nginx", "-c", "/fixture/nginx.conf", "-g", "daemon off;")
                containers.append(proxy)
                proxies.append(proxy)
                endpoints.append("https://hub-" + suffix + ".test:8443")
                step = "services-start"
            step = "synthetic-worker"
            client_worker = project + "-client"
            control_folder = private / "control"
            control_folder.mkdir()
            run("docker", "create", "--name", client_worker, "--network", networks[0],
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--read-only", "--memory", "256m",
                "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m", *mount(fixture, "/fixture"),
                "--mount", f"type=bind,source={control_folder},target=/control", image, "sleep", "infinity")
            containers.append(client_worker)
            run("docker", "network", "connect", networks[1], client_worker)
            run("docker", "start", client_worker)
            configuration = {"endpoints": endpoints, "deployments": deployments, "owners": owners,
                "jwt_signing_pem": jwt_key.private_bytes(serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()}
            worker = subprocess.Popen(["docker", "exec", "-i", client_worker, "python", "/app/worker.py"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            worker.stdin.write(json.dumps(configuration).encode())
            worker.stdin.close()
            deadline = time.monotonic() + 300
            print("Testing actual TLS sockets, JWT ownership, device approval and encrypted queues", flush=True)
            while worker.poll() is None and time.monotonic() < deadline:
                request_path, response_path = control_folder / "request.json", control_folder / "response.json"
                if request_path.is_file() and not response_path.exists():
                    request = json.loads(request_path.read_text())
                    if request.get("operation") == "restart-a" and set(request) == {"operation"}:
                        run("docker", "restart", hubs[0])
                        # Namespace-sharing proxies must rejoin the restarted
                        # Hub's namespace, rather than retain its old loopback.
                        run("docker", "restart", proxies[0])
                    elif request.get("operation") == "scan" and set(request) == {"operation", "canaries", "tokens"}:
                        assert_absent(hubs, containers, [], request["canaries"], request["tokens"])
                    else:
                        raise AcceptanceError("Unsupported test control operation")
                    (control_folder / "response.tmp").write_text(json.dumps({"ok": True}))
                    (control_folder / "response.tmp").replace(response_path)
                time.sleep(0.1)
            if worker.poll() is None:
                worker.kill()
                worker.wait(timeout=10)
                raise AcceptanceError("Synthetic client deadline exceeded")
            worker.stdout.read()
            worker.stderr.read()
            worker.stdout.close()
            worker.stderr.close()
            result = json.loads((control_folder / "result.json").read_text())
            receipt["checks"] = result["checks"]
            if result["status"] != "passed" or worker.returncode != 0:
                step = result.get("failed_step", "synthetic-worker")
                receipt["worker_failure"] = {key: result[key] for key in ("error_category", "http_status") if key in result}
                raise AcceptanceError("Synthetic worker failed")
            if any(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest for name, digest in receipt["source_hashes"].items()):
                raise AcceptanceError("Source inputs changed during acceptance")
            receipt["status"] = "passed"
        except Exception:
            failure = step
            receipt["status"], receipt["failed_step"] = "failed", step
            states = []
            for container in containers:
                try:
                    state = json.loads(run("docker", "inspect", container, "--format", "{{json .State}}"))
                    logs = subprocess.run(["docker", "logs", container], capture_output=True, timeout=10)
                    log = logs.stdout + logs.stderr
                    known = [value for value in ("ModuleNotFoundError", "PermissionError", "FileNotFoundError", "ImportError",
                             "ValueError", "OperationalError", "permission denied", "Permission denied", "Connection refused",
                             "Read-only file system", "Operation not permitted", "getpwnam", "unknown directive",
                             "host not found", "BIO_new_file", "open()", "bind()", "mkdir()", "chown", "setuid") if value.encode() in log]
                    states.append({"role": container.removeprefix(project + "-"), "status": state.get("Status"),
                                   "exit_code": state.get("ExitCode"), "error_categories": known})
                    if "-hub-" in container and state.get("Status") == "running":
                        diagnostic = "import jwt,json\ntry:\n jwt.PyJWKClient('https://issuer.test/.well-known/jwks.json',timeout=5).get_signing_key('synthetic-acceptance'); print(json.dumps({'jwks':True}))\nexcept Exception as error:\n print(json.dumps({'jwks':False,'error_category':type(error).__name__,'cause_category':type(error.__cause__).__name__}))"
                        states[-1]["issuer_probe"] = json.loads(run("docker", "exec", container, "python", "-c", diagnostic))
                except Exception:
                    states.append({"role": container.removeprefix(project + "-"), "status": "unavailable"})
            receipt["service_states"] = states
        finally:
            clean = True
            for kind, names in (("container", reversed(containers)), ("volume", reversed(volumes)), ("network", reversed(networks))):
                for name in names:
                    if not name.startswith(project + "-"):
                        clean = False
                        continue
                    try:
                        args = ["docker", "rm", "-f", name] if kind == "container" else ["docker", kind, "rm", name]
                        run(*args)
                    except Exception:
                        clean = False
            try:
                run("docker", "image", "rm", image)
            except Exception:
                clean = False
            receipt["cleanup"] = clean
    receipt["temporary_private_fixture_removed"] = not private.exists()
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    if failure or not receipt["cleanup"]:
        print("Isolated hosted acceptance failed at " + (failure or "cleanup") + "; sanitized receipt retained.")
        return 1
    print("Isolated hosted acceptance passed; disposable services and private fixtures removed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
