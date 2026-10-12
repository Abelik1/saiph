# Third-party library replacement and source handoff

Saiph uses Qt and Qt for Python. Qt/PySide portions are available under the
upstream LGPL/GPL alternatives described in the accompanying licence texts.
Their copyright remains with The Qt Company and other upstream contributors.
These notices do not grant a new licence to Saiph-owned code.

The native package keeps shared libraries and Python binding extensions under
`app/_internal`. Runtime startup does not verify their package hashes or require
the owner's publisher key. Package/update hashes protect download integrity;
they are not a restriction on local debugging or replacing libraries.

For interface-compatible replacement, close Saiph and keep a copy of the complete
installed release. Build the matching Qt modules, PySide and Shiboken sources for
the same operating system, architecture, Python ABI and compiler/runtime as that
release. Replace the relevant Qt libraries, binding extensions, plugins and
WebEngine helper/resources together. Keep resource locations and dependent
libraries coherent. Launch the application executable directly from the modified
release. A standard update may select a fresh release, so retain the modified
copy separately when testing library changes.

No Saiph terms prohibit reverse engineering for debugging modifications to the
LGPL-covered libraries. Standard installation, native library replacement and
relink acceptance remain platform-specific checks. This document alone does not
prove compliance or guarantee that an arbitrary incompatible Qt build will work.

`native-provenance.json` lists actual native file hashes and candidate upstream
source archives for the build's exact Qt/PySide versions. Before giving a release
to another person, retain and provide the complete corresponding sources,
attributions, configuration and patches required by those versions. A URL or a
version inventory alone is not the complete source handoff. Keep the Android
fork's GPL licence and corresponding source handoff separately.
