# SPDX-License-Identifier: GPL-3.0-only
"""Build pinned, unmodified restic as an extracted Android executable library.

Windows bootstrap is local to the build checkout; no system Go/PATH changes.
Source archives and Go are verified before extraction. Secrets are never inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import tarfile
import urllib.request
import zipfile

RESTIC_COMMIT = "6aa3a516ce654808a1f28f9fa21e9b7c8e6e90bf"
RESTIC_SHA256 = "6318c51f187bafbaf33d1ab6dcb5abde9a94de11476651cbb2982f1ba89ca8a8"
GO_VERSION = "1.26.7"
GO_SHA256 = "f4f534a486e4bc3387fa18f08208f2f854b7aaea8a08f2a2d829a914a05abb11"
ABIS = {"arm64-v8a": ("arm64", "aarch64-linux-android26"), "x86_64": ("amd64", "x86_64-linux-android26")}


def verified_download(url: str, target: Path, expected: str) -> None:
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=120) as response, target.open("wb") as out:
            while chunk := response.read(1024 * 1024):
                out.write(chunk)
    with target.open("rb") as stream:
        actual = hashlib.sha256()
        while chunk := stream.read(1024 * 1024):
            actual.update(chunk)
    if actual.hexdigest() != expected:
        raise RuntimeError("Upstream archive checksum mismatch; nothing extracted")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--android-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--sdk", type=Path, default=Path(os.environ.get("ANDROID_HOME", "")))
    parser.add_argument("--ndk-version", default="28.2.13676358")
    parser.add_argument("--abi", action="append", choices=list(ABIS))
    args = parser.parse_args()
    if os.name != "nt":
        raise RuntimeError("This bootstrap targets the installed Windows NDK; use upstream Linux build on Linux")
    root = args.android_root.absolute()
    cache = root / ".restic-build"
    cache.mkdir(exist_ok=True)
    archive = cache / f"go{GO_VERSION}.windows-amd64.zip"
    verified_download(f"https://go.dev/dl/{archive.name}", archive, GO_SHA256)
    go = cache / "go/bin/go.exe"
    if not go.exists():
        with zipfile.ZipFile(archive) as source:
            for member in source.infolist():
                if ".." in Path(member.filename).parts or member.filename.startswith(("/", "\\")):
                    raise RuntimeError("Unsafe Go archive")
            source.extractall(cache)
    source_archive = cache / f"restic-{RESTIC_COMMIT}.tar.gz"
    verified_download(f"https://codeload.github.com/restic/restic/tar.gz/{RESTIC_COMMIT}", source_archive, RESTIC_SHA256)
    source = cache / f"restic-{RESTIC_COMMIT}"
    if not source.exists():
        with tarfile.open(source_archive) as tar:
            for member in tar.getmembers():
                if member.islnk() or member.issym() or ".." in Path(member.name).parts or member.name.startswith("/"):
                    raise RuntimeError("Unsafe restic archive")
            tar.extractall(cache)
    toolchain = args.sdk.absolute() / "ndk" / args.ndk_version / "toolchains/llvm/prebuilt/windows-x86_64/bin"
    if not (toolchain / "clang.exe").is_file():
        raise RuntimeError("Installed Windows Android NDK is required")
    for abi in args.abi or ABIS:
        goarch, target = ABIS[abi]
        output = root / "restic-android/src/main/jniLibs" / abi / "librestic.so"
        output.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, GOOS="android", GOARCH=goarch, CGO_ENABLED="1", GOTOOLCHAIN="local",
                   GOROOT=str(cache / "go"), GOCACHE=str(cache / "go-cache"), GOPATH=str(cache / "go-path"),
                   CC=str(toolchain / "clang.exe"),
                   CGO_CFLAGS=f'--target={target} "--sysroot={(toolchain.parent / "sysroot").as_posix()}" "-resource-dir={(toolchain.parent / "lib/clang/19").as_posix()}" "-B{toolchain.as_posix()}"',
                   CGO_LDFLAGS=f'--target={target} "--sysroot={(toolchain.parent / "sysroot").as_posix()}" "-resource-dir={(toolchain.parent / "lib/clang/19").as_posix()}" "-B{toolchain.as_posix()}" -Wl,-z,max-page-size=16384')
        subprocess.run([str(go), "build", "-trimpath", "-buildvcs=false", "-ldflags",
                        "-s -w -buildid= -X main.version=0.19.1", "-o", str(output), "./cmd/restic"],
                       cwd=source, env=env, check=True)
        elf = subprocess.check_output([str(toolchain / "llvm-readelf.exe"), "-h", "-l", "-d", str(output)], text=True)
        if "DYN (Shared object file)" not in elf or "libc.so" not in elf:
            raise RuntimeError("restic must be an Android Bionic PIE executable")
        if any(int(line.split()[-1], 16) < 16384 for line in elf.splitlines() if line.lstrip().startswith("LOAD ")):
            raise RuntimeError("Android executable lacks 16 KB page alignment")
        print(f"Built {abi}: restic 0.19.1; Bionic; 16 KB alignment; sha256={hashlib.sha256(output.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
