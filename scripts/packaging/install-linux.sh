#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# Native bundle installer; no Python/Node or developer checkout needed on target.
set -eu
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
install_root=${ORION_INSTALL_ROOT:-"$HOME/.local/lib/orion"}
isolated=${ORION_INSTALL_ISOLATED:-0}
config_root=${XDG_CONFIG_HOME:-"$HOME/.config"}
data_root=${XDG_DATA_HOME:-"$HOME/.local/share"}
# Integration is only installed at finite per-user locations. Reject shell and
# desktop-entry metacharacters rather than interpolate them into launchers.
for path in "$install_root" "$HOME" "$config_root" "$data_root"; do
  case "$path" in /*) ;; *) echo "Integration paths must be absolute." >&2; exit 1 ;; esac
  case "$path" in *'"'*|*'$'*|*'`'*|*'\'*|*'%'*|*'
'*) echo "Unsafe integration path." >&2; exit 1 ;; esac
done
safe_path() {
  checked=${1%/}
  [ -n "$checked" ] || checked=/
  while [ "$checked" != / ]; do
    [ ! -L "$checked" ] || { echo "Integration symlink retained." >&2; return 1; }
    checked=${checked%/*}
    [ -n "$checked" ] || checked=/
  done
}
launcher="$HOME/.local/bin/orion"
desktop="$data_root/applications/orion.desktop"
autostart="$config_root/autostart/orion.desktop"
mime="$data_root/mime/packages/orion-enrollment.xml"
# File-manager "Send to phone" actions: GNOME Files (Nautilus) scripts and KDE Dolphin service menus.
nautilus="$data_root/nautilus/scripts/Send to phone (Saiph)"
servicemenu="$data_root/kio/servicemenus/saiph-send-to-phone.desktop"
integration_work=
stage=
committed=0
changed=
new_activation=0
new_integration_marker=0
cleanup() {
  result=$?
  trap - EXIT HUP INT TERM
  # Restore only exact content written by this invocation. A concurrent user
  # modification or symlink is retained; prior active release stays selected.
  if [ "$committed" != 1 ] && [ -n "$integration_work" ]; then
    for name in $changed; do
      case "$name" in launcher) target=$launcher ;; desktop) target=$desktop ;; autostart) target=$autostart ;; mime) target=$mime ;; nautilus) target=$nautilus ;; servicemenu) target=$servicemenu ;; esac
      if safe_path "$target" && [ -f "$target" ] && cmp -s "$target" "$integration_work/$name"; then
        if [ -f "$integration_work/old-$name" ]; then
          temporary=$(mktemp "${target}.orion.XXXXXXXX")
          cp -p "$integration_work/old-$name" "$temporary" && mv -Tf -- "$temporary" "$target"
        else rm -- "$target"; fi
      fi
    done
  fi
  if [ "$committed" != 1 ] && [ "$new_integration_marker" = 1 ] && safe_path "$install_root/integration-created" && [ -f "$install_root/integration-created" ] && [ ! -s "$install_root/integration-created" ]; then
    rm -- "$install_root/integration-created"
  fi
  if [ "$new_activation" = 1 ] && [ -L "$install_root/current.new" ] && [ "$(readlink "$install_root/current.new")" = "releases/$version" ]; then
    rm -- "$install_root/current.new"
  fi
  [ -z "$stage" ] || [ ! -d "$stage" ] || rm -rf -- "$stage"
  [ -z "$integration_work" ] || [ ! -d "$integration_work" ] || rm -rf -- "$integration_work"
  exit "$result"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
prepare_integration() {
  integration_work=$(mktemp -d "${TMPDIR:-/tmp}/orion-integration.XXXXXXXX")
  printf '#!/bin/sh\n# ORION_OWNED=1\nif [ "$#" = 1 ]; then case "$1" in *.orion-enrollment) exec "%s/current/app/OrionMini" --enrollment "$1" ;; esac; fi\nexec "%s/current/app/OrionMini" "$@"\n' "$install_root" "$install_root" > "$integration_work/launcher"
  chmod u+x "$integration_work/launcher"
  printf '[Desktop Entry]\n# ORION_OWNED=1\nType=Application\nName=Saiph\nExec="%s" %%f\nIcon=%s/current/app/_internal/assets/orion-mini-icon.png\nTerminal=false\nCategories=Utility;\nMimeType=application/x-orion-enrollment;\n' "$launcher" "$install_root" > "$integration_work/desktop"
  printf '[Desktop Entry]\n# ORION_OWNED=1\nType=Application\nName=Saiph\nExec="%s"\nTerminal=false\nX-GNOME-Autostart-enabled=true\n' "$launcher" > "$integration_work/autostart"
  sed 's/X-GNOME-Autostart-enabled=true/X-GNOME-Autostart-enabled=false/' "$integration_work/autostart" > "$integration_work/autostart-disabled"
  printf '<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info"><mime-type type="application/x-orion-enrollment"><comment>Saiph device enrollment</comment><glob pattern="*.orion-enrollment"/></mime-type></mime-info>\n' > "$integration_work/mime-legacy"
  { printf '<!-- ORION_OWNED=1 -->\n'; cat "$integration_work/mime-legacy"; } > "$integration_work/mime"
  printf '#!/bin/sh\n# ORION_OWNED=1\nexec "%s" --send-files "$@"\n' "$launcher" > "$integration_work/nautilus"
  printf '[Desktop Entry]\n# ORION_OWNED=1\nType=Service\nMimeType=all/allfiles;\nActions=sendToPhone;\nX-KDE-Priority=TopLevel\n\n[Desktop Action sendToPhone]\nName=Send to phone (Saiph)\nIcon=%s/current/app/_internal/assets/orion-mini-icon.png\nExec="%s" --send-files %%F\n' "$install_root" "$launcher" > "$integration_work/servicemenu"
  # Both file managers only run executable entries.
  chmod u+x "$integration_work/nautilus" "$integration_work/servicemenu"
  # Accept only exact older label variants; arbitrary marker-bearing files stay unowned.
  for name in desktop autostart autostart-disabled mime mime-legacy; do
    sed -e 's/Name=Saiph/Name=Orion/' -e 's/Saiph device enrollment/Orion device enrollment/' "$integration_work/$name" > "$integration_work/orion-$name"
  done
}
owned_integration() {
  name=$1; target=$2
  safe_path "$target" && [ -f "$target" ] || return 1
  cmp -s "$target" "$integration_work/$name" && return 0
  if [ "$name" != launcher ] && cmp -s "$target" "$integration_work/orion-$name"; then return 0; fi
  if [ "$name" = autostart ]; then
    cmp -s "$target" "$integration_work/autostart-disabled" && return 0
    cmp -s "$target" "$integration_work/orion-autostart-disabled" && return 0
  fi
  if [ "$name" = mime ]; then
    cmp -s "$target" "$integration_work/mime-legacy" && return 0
    cmp -s "$target" "$integration_work/orion-mime-legacy" && return 0
  fi
  return 1
}
preflight_integration() {
  name=$1; target=$2
  safe_path "$target" || exit 1
  if [ -e "$target" ]; then
    owned_integration "$name" "$target" || { echo "Existing unrelated integration retained." >&2; exit 1; }
    cp -p -- "$target" "$integration_work/old-$name"
  fi
}
write_integration() {
  name=$1; target=$2
  preflight_integration "$name" "$target"
  [ ! -f "$target" ] || ! cmp -s "$target" "$integration_work/$name" || return 0
  temporary=$(mktemp "${target}.orion.XXXXXXXX")
  cp -p -- "$integration_work/$name" "$temporary"
  mv -Tf -- "$temporary" "$target"
  changed="$changed $name"
}
# Ownership checks precede any active-release or launch integration mutation.
safe_path "$install_root" || exit 1
for marker in "$install_root/orion-owned" "$install_root/integration-created" "$install_root/releases"; do
  safe_path "$marker" || exit 1
done
if [ -e "$install_root/integration-created" ] && [ ! -f "$install_root/integration-created" ]; then echo "Unrelated integration marker retained." >&2; exit 1; fi
if [ "$isolated" != 1 ]; then
  prepare_integration
  if [ "${1:-}" != --uninstall ]; then
    preflight_integration launcher "$launcher"
    preflight_integration desktop "$desktop"
    preflight_integration autostart "$autostart"
    preflight_integration mime "$mime"
    preflight_integration nautilus "$nautilus"
    preflight_integration servicemenu "$servicemenu"
  fi
fi
case "$install_root" in /*) ;; *) echo "Install root must be absolute." >&2; exit 1 ;; esac
case "$install_root" in /|"$HOME"|"$HOME/"|*'..'*|*'
'*) echo "Unsafe install root." >&2; exit 1 ;; esac
if [ "$isolated" != 1 ] && [ "$install_root" != "$HOME/.local/lib/orion" ]; then echo "Custom roots require explicit isolated test mode." >&2; exit 1; fi
# One inode and one lock across installs and uninstall. Do not remove the lock
# file on exit: a waiting process must not acquire a second replacement inode.
if [ "${1:-}" != --uninstall ]; then
  [ "$(uname -s)" = Linux ] && [ "$(uname -m)" = x86_64 ] || { echo "This package requires x86-64 Linux." >&2; exit 1; }
  [ -f "$source_dir/LINUX_COMPATIBILITY" ] || { echo "Package compatibility receipt is missing." >&2; exit 1; }
  read compatibility_platform compatibility_libc required_glibc unexpected < "$source_dir/LINUX_COMPATIBILITY"
  [ "$compatibility_platform" = linux-x86_64 ] && [ "$compatibility_libc" = glibc ] && [ -z "$unexpected" ] || { echo "Invalid package compatibility receipt." >&2; exit 1; }
  printf '%s\n' "$required_glibc" | grep -Eq '^[0-9]+\.[0-9]+$' || { echo "Invalid package glibc requirement." >&2; exit 1; }
  actual_glibc=$(getconf GNU_LIBC_VERSION 2>/dev/null | sed -n 's/^glibc \([0-9][0-9]*\.[0-9][0-9]*\)$/\1/p')
  [ -n "$actual_glibc" ] || { echo "This package requires a glibc Linux distribution such as Ubuntu." >&2; exit 1; }
  oldest=$(printf '%s\n%s\n' "$required_glibc" "$actual_glibc" | sort -V | head -n 1)
  [ "$oldest" = "$required_glibc" ] || { echo "This package needs glibc $required_glibc or newer; this system has $actual_glibc. Ask for a compatible Saiph package." >&2; exit 1; }
fi
command -v flock >/dev/null 2>&1 || { echo "flock (util-linux) is required." >&2; exit 1; }
mkdir -p -- "$(dirname -- "$install_root")"
lock_file="$install_root.install.lock"
if [ -L "$lock_file" ]; then echo "Unsafe installer lock." >&2; exit 1; fi
if [ -e "$lock_file" ] && [ ! -f "$lock_file" ]; then echo "Unrelated installer lock retained." >&2; exit 1; fi
exec 9>>"$lock_file"
flock -n 9 || { echo "Another Saiph installation is running; retry after it finishes." >&2; exit 1; }
version=$(cat "$source_dir/VERSION")
printf '%s\n' "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.-]+)?$' || { echo "Invalid version." >&2; exit 1; }
if [ -L "$install_root" ]; then echo "Install root is a symlink; retained." >&2; exit 1; fi
if [ -e "$install_root" ] && [ ! -f "$install_root/orion-owned" ]; then echo "Existing directory is not a Saiph install; retained." >&2; exit 1; fi
if [ -e "$install_root/current" ] || [ -L "$install_root/current" ]; then
  [ -L "$install_root/current" ] || { echo "Unrelated active path retained." >&2; exit 1; }
  previous=$(readlink "$install_root/current")
  printf '%s\n' "$previous" | grep -Eq '^releases/[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.-]+)?$' || { echo "Unrelated active link retained." >&2; exit 1; }
  safe_path "$install_root/$previous" || exit 1
fi
if [ "${1:-}" = --uninstall ]; then
  [ -f "$install_root/orion-owned" ] || exit 1
  # Retain installed releases and user data. Remove only owned launch integration,
  # allowing recovery and library replacement without recursive user-file deletion.
  if [ "$isolated" != 1 ]; then
    for name in launcher desktop autostart mime nautilus servicemenu; do
      case "$name" in launcher) target=$launcher ;; desktop) target=$desktop ;; autostart) target=$autostart ;; mime) target=$mime ;; nautilus) target=$nautilus ;; servicemenu) target=$servicemenu ;; esac
      if owned_integration "$name" "$target"; then rm -- "$target"; fi
    done
  fi
  if [ -L "$install_root/current" ]; then rm -- "$install_root/current"; fi
  echo "Saiph launch integration removed; releases, keys and user files retained."
  exit 0
fi
command -v sha256sum >/dev/null 2>&1 || { echo "sha256sum is required." >&2; exit 1; }
(cd "$source_dir" && sha256sum -c SHA256SUMS >/dev/null) || { echo "Package integrity check failed." >&2; exit 1; }
mkdir -p -- "$install_root/releases"
touch "$install_root/orion-owned"
release="$install_root/releases/$version"
if [ -e "$release" ]; then
  # Same refusal as before; only the explanation is written for testers.
  if [ -L "$install_root/current" ] && [ "$(readlink "$install_root/current")" = "releases/$version" ]; then
    echo "Saiph $version is already installed. Nothing changed. Open Saiph from your applications menu." >&2
  else
    echo "Saiph $version was installed here before and its files were kept, so nothing changed. Install a newer Saiph version instead." >&2
  fi
  exit 1
fi
stage=$(mktemp -d "$install_root/.staging.XXXXXXXX")
cp -R "$source_dir/app" "$source_dir/licenses" "$source_dir/package-manifest.json" "$stage/"
# Keep the verified installer with its version so removing launch integration
# never depends on retaining the extracted download. User data is preserved.
cp "$source_dir/install.sh" "$source_dir/VERSION" "$stage/"
chmod u+x "$stage/install.sh"
chmod u+x "$stage/app/OrionMini"
if [ "$isolated" != 1 ]; then
  mkdir -p "$HOME/.local/bin" "$data_root/applications" "$data_root/mime/packages" "$config_root/autostart"
  write_integration launcher "$launcher"
  write_integration desktop "$desktop"
  # Never restore an opt-out (removed or disabled) on upgrade.
  if [ -f "$autostart" ]; then
    if cmp -s "$autostart" "$integration_work/autostart-disabled" || cmp -s "$autostart" "$integration_work/orion-autostart-disabled"; then
      cp "$integration_work/autostart-disabled" "$integration_work/autostart"
    fi
    write_integration autostart "$autostart"
  elif [ ! -f "$install_root/integration-created" ]; then
    write_integration autostart "$autostart"
  fi
  write_integration mime "$mime"
  mkdir -p "$data_root/nautilus/scripts" "$data_root/kio/servicemenus"
  write_integration nautilus "$nautilus"
  write_integration servicemenu "$servicemenu"
fi
# Refuse unrelated active pointers and stale temporary links before activation.
if [ -e "$install_root/current.new" ] || [ -L "$install_root/current.new" ]; then echo "Existing activation staging retained." >&2; exit 1; fi
if [ "$isolated" != 1 ] && [ ! -f "$install_root/integration-created" ]; then
  touch "$install_root/integration-created"
  new_integration_marker=1
fi
ln -s "releases/$version" "$install_root/current.new"
new_activation=1
mv -- "$stage" "$release"
stage=
mv -Tf -- "$install_root/current.new" "$install_root/current"
new_activation=0
committed=1
if [ "$isolated" != 1 ]; then
  command -v update-mime-database >/dev/null 2>&1 && update-mime-database "$data_root/mime" >/dev/null 2>&1 || true
  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$data_root/applications" >/dev/null 2>&1 || true
fi

echo "Saiph installed. Open it from your application menu; setup guides the official connection component."
