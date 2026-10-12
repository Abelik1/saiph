#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Verify final project Windows signatures and record the exact verified bytes.

Run on Windows with the SDK SignTool. This never requests or applies signatures.
Publisher and certificate fingerprint must come from independently approved policy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


SIGNATURE_QUERY = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$path = $env:SAIPH_SIGNATURE_PATH
$signature = Get-AuthenticodeSignature -LiteralPath $path
$file = Get-Item -LiteralPath $path
$certificateHash = $null
if ($signature.SignerCertificate) {
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { $certificateHash = ([BitConverter]::ToString($hasher.ComputeHash($signature.SignerCertificate.RawData))).Replace('-', '').ToLowerInvariant() }
    finally { $hasher.Dispose() }
}
[ordered]@{
    status = [string]$signature.Status
    type = [string]$signature.SignatureType
    publisher = if ($signature.SignerCertificate) { $signature.SignerCertificate.Subject } else { $null }
    certificate_sha256 = $certificateHash
    timestamped = [bool]$signature.TimeStamperCertificate
    product = $file.VersionInfo.ProductName
    version = $file.VersionInfo.ProductVersion
} | ConvertTo-Json -Compress
"""


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            result.update(chunk)
    return result.hexdigest()


def verify_file(path: Path, publisher: str, certificate_sha256: str, version: str, signtool: str):
    if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".exe":
        raise ValueError("Expected a regular project .exe file")
    path = path.resolve(strict=True)
    before = digest(path)
    environment = dict(os.environ, SAIPH_SIGNATURE_PATH=str(path))
    query = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", SIGNATURE_QUERY],
                           env=environment, check=True, capture_output=True, text=True, encoding="utf-8")
    signature = json.loads(query.stdout)
    if signature.get("status") != "Valid" or signature.get("type") != "Authenticode":
        raise ValueError("An embedded trusted Authenticode signature is required")
    if signature.get("publisher") != publisher or signature.get("certificate_sha256") != certificate_sha256:
        raise ValueError("Signature does not match the independently approved publisher/certificate")
    if signature.get("timestamped") is not True:
        raise ValueError("A timestamped signature is required")
    if signature.get("product") != "Saiph" or signature.get("version") != version:
        raise ValueError("Windows product/version metadata does not match this release")
    subprocess.run([signtool, "verify", "/pa", "/all", "/v", "/tw", str(path)],
                   check=True, capture_output=True, text=True)
    if digest(path) != before:
        raise ValueError("Artifact changed during signature verification")
    return {"file": path.name, "bytes": path.stat().st_size, "sha256": before, **signature}


def verify(installer: Path, executable: Path, publisher: str, certificate_sha256: str,
           version: str, signtool: str, output: Path):
    if not publisher.strip() or not re.fullmatch(r"[0-9a-f]{64}", certificate_sha256):
        raise ValueError("Expected approved publisher subject and lowercase SHA-256 certificate fingerprint")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?", version):
        raise ValueError("Expected explicit semantic version")
    if installer.resolve() == executable.resolve():
        raise ValueError("Installer and project executable must be distinct")
    if output.exists() or output.is_symlink():
        raise ValueError("Use a fresh signature receipt output")
    records = [verify_file(path, publisher, certificate_sha256, version, signtool)
               for path in (installer, executable)]
    for path, record in zip((installer, executable), records):
        if path.is_symlink() or digest(path) != record['sha256']:
            raise ValueError('Artifact changed before signature receipt creation')
    receipt = {"schema": 1, "verification": "Windows Authenticode and SignTool /pa /all /v /tw",
               "version": version, "artifacts": records}
    with output.open("x", encoding="utf-8") as destination:
        destination.write(json.dumps(receipt, indent=2) + "\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", required=True, type=Path)
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--publisher", required=True)
    parser.add_argument("--certificate-sha256", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--signtool", default="signtool.exe")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verify(args.installer, args.executable, args.publisher, args.certificate_sha256,
           args.version, args.signtool, args.output)
