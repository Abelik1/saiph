# Third-party software and notices

Saiph's own app and Hub source uses AGPL-3.0-or-later; `sdk/` uses MIT.
Third-party components keep their own licences. This summary is not a substitute
for the component notices shipped with a particular build.

* **PySide6 / Qt / Qt WebEngine:** versioned licence texts and attribution reports
  are retained under `scripts/packaging/notices/qt-*/`. Qt WebEngine incorporates
  Chromium and its own third-party components. Use the reports matching the exact
  bundled Qt version. A package version alone does not establish wheel provenance.
* **Python and frontend dependencies:** the packaging tool collects available
  installed-distribution licence/notice files and a frontend dependency inventory.
  Review the actual bundle, including Python, OpenSSL, cryptography and platform
  runtimes. Missing notices must be supplied before distribution.
  The six reviewed PyWinRT 3.2.1 packages have retained upstream MIT notices and
  exact source provenance under `scripts/packaging/notices/pywinrt-3.2.1/`;
  packaging uses these only for the reviewed names and exact version.
* **qrcode (python-qrcode):** the desktop and Hub use `qrcode>=8,<9`,
  distributed under the BSD 3-Clause licence. Retain its upstream licence and
  copyright notice in distributed bundles; see
  [python-qrcode](https://github.com/lincolnloop/python-qrcode).
* **Android:** the Android app in `android/` is derived from
  [Sefirah](https://github.com/shrimqy/Sefirah-Android). Its GPL licence and upstream
  credits must travel with its corresponding source and APK distributions.
* **AppAuth for Android 0.11.1:** the opt-in Hosted preview uses the
  [OpenID Foundation native OAuth client](https://github.com/openid/AppAuth-Android/tree/0.11.1),
  licensed under Apache-2.0. Retain its upstream licence and notices in APK
  distributions. AppAuth uses the system browser and PKCE; no client secret
  is included in source or builds.
* **Optional services:** third-party Seafile, Immich, Tailscale and Headscale
  installations have their own licences; connecting to a service does not bundle
  that service in this source tree.
* **Deskflow:** the public integration launches a separately installed
  [Deskflow](https://github.com/deskflow/deskflow). Its executables are not bundled.
  Any later binary bundling must first retain that exact release's upstream
  licences, notices, source obligations and hashes; this integration does not
  relicense Deskflow.

The one-folder native layout keeps shared libraries separate. Follow
`scripts/packaging/REPLACEABLE_LIBRARIES.md` and the generated
`native-provenance.json`; verify replacement on each shipping platform and retain
matching source, notices and build provenance. An inventory or a source URL alone
does not close the corresponding-source or replacement verification requirements.

Do not sign upstream libraries as if they were authored by Saiph. Keep their
existing signatures and attribution. The release maintainer must resolve any
remaining review items in the package's provenance report before public release.
