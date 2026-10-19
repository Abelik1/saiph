# Saiph distribution inventory

This preview includes a native PyInstaller application bundle, the existing
React frontend, hashes for every distributed file, Python package versions
represented in the build analysis, production frontend dependencies and their
available licence files. Runtime data, device keys, tokens, service configuration
and the development checkout are never package inputs.

PyInstaller's bootloader exception permits bundled applications to use their own
licence: https://pyinstaller.org/en/stable/license.html. Keep its copyright and
licence when distributing the bootloader.

PySide6 and Qt require applicable Qt/Python licence texts, native third-party
notices, and a matching source/relink compliance plan. Dynamically linked Qt
libraries remain separate and replaceable in `_internal`; do not add integrity
enforcement to normal runtime or prohibit debugging/replacement. Qt WebEngine
also includes Chromium components with their own notices. The installed wheels'
commercial licence text alone is not the full open-source notice set:
https://doc.qt.io/qtforpython-6/licenses.html and
https://doc.qt.io/qt-6/qtwebengine-licensing.html.

Bundled PyAV/FFmpeg, CTranslate2/OpenMP, ONNX Runtime, NumPy/BLAS, cryptography/
OpenSSL, Python and WinRT native libraries need their own exact-version notice
and source inventory. The generated manifest identifies their actual binaries;
the inventory marks missing wheel notices rather than inventing licence terms.
For the six reviewed PyWinRT 3.2.1 packages whose wheels omit their MIT notice,
packaging supplies the retained upstream notice with its exact version, upstream
commit and hash. Other versions or packages do not inherit that exception.
The build interpreter's licence is retained separately with its version; matching
its packaged native bytes and transitive notices still requires release review.
Reviewed PySide6/Shiboken wheels at 6.8.3 or 6.11.2 that omit notices use the
matching retained Qt LGPL/GPL texts and PySide attribution report. Packaging
verifies those licence hashes and source-version evidence; this does not close
the separate wheel build-provenance or library-replacement review.

Windows native builds isolate the PyInstaller child process from developer PATH
tools. Its DLL search uses the selected interpreter and Windows system roots;
the frontend build retains its separate Node tool environment. After collection,
the builder rejects native Analysis inputs outside the selected interpreter,
virtual environment and Windows system roots, changed collected bytes and native
files absent from Analysis. The build-only `native-build-origins.json` retains
local input paths for review; do not publish that developer-path receipt inside
the product. Native package inventory matches every represented native wheel's
RECORD and actual build-interpreter files by hash. These origin matches do not
independently authenticate downloaded wheels or close source/build/replacement
reviews. Retained upstream notice hashes use canonical LF text so a Windows Git
checkout's CRLF conversion cannot change their packaged licence evidence.

Tailscale and Seafile are installed through their official channels only after
the owner consents. Existing installations are reused. Their accounts, licence
agreements and updater remain upstream; this package does not embed owner mesh
credentials or copy their binaries. Optional cloud/backup/capture facilities do
not block Saiph's basic setup. Bundling ADB/scrcpy, restic or Deskflow later
requires adding exact binary hashes and their Apache/BSD/GPL source obligations
to this distribution inventory first.

Windows now bundles Saiph's own camera filters built from the pinned
UnityCapture filter source under `native/camera/upstream/`, with its MIT notice,
Microsoft DirectShow copyright headers, explicit Saiph adaptations and a matching
source/build/hash receipt. These are separate from the MIT SDK. No Unity runtime,
OBS Studio or scrcpy is required by the integrated camera session. Their optional
legacy paths remain available. Package inventories verify the exact component
bytes; actual registration, meeting-app interoperability and independent source
and licensing review remain release acceptance work.

External friend distribution is pending completed native notices/matching source,
publisher signing, clean installation, upgrade, permission and recovery checks.
This artifact is explicitly an internal preview, not an externally reviewed
release. Hashes detect corruption; an unsigned installer is not an authenticated
publisher or secure update channel.
