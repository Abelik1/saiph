#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# Saiph @VERSION@ setup for linux-x86_64: per-user, no administrator rights.
#
# Everything after this script is the unchanged release archive @ARCHIVE@.
# This wrapper only checks that archive's SHA-256, unpacks it into a private
# folder and runs its own orion/install.sh as you. Installation, upgrade,
# manifests, retained data/pairing/start-up choices and uninstall are exactly
# those of the archive. Started from a file manager it shows dialogs (zenity or
# kdialog) or opens a terminal window; started from a terminal it prints text.
#
#   sh <this file>                 install
#   sh <this file> --text          install with terminal output only
#   sh <this file> --extract DIR   verify and unpack the archive into a new DIR
#
# Uninstall later with: ~/.local/lib/orion/current/install.sh --uninstall
set -eu
version='@VERSION@'
archive_name='@ARCHIVE@'
payload_bytes='@PAYLOAD_BYTES@'
payload_sha256='@PAYLOAD_SHA256@'
title='Saiph setup'
self=$0
case "$self" in /*) ;; *) self=$(pwd -P)/$self ;; esac
work=
saved_log=
in_terminal=0

cleanup() {
  result=$?
  trap - EXIT HUP INT TERM
  case "$work" in */saiph-setup.*) [ ! -d "$work" ] || rm -rf -- "$work" ;; esac
  exit "$result"
}

usage() {
  echo "Usage: sh $(basename -- "$self") [--text | --extract DIRECTORY]" >&2
}

require_tools() {
  for tool in tail wc sha256sum cut tar gzip mktemp; do
    command -v "$tool" >/dev/null 2>&1 || { echo "Saiph setup needs the standard '$tool' command." >&2; return 1; }
  done
}

# Copy the embedded archive to $1 and accept it only with the recorded hash.
# A changed or truncated download cannot match because the archive is read
# from the end of this file.
extract_payload() {
  require_tools || return 1
  [ -f "$self" ] || { echo "Saiph setup cannot read its own file." >&2; return 1; }
  size=$(wc -c < "$self" | tr -d ' \t')
  [ "$size" -gt "$payload_bytes" ] 2>/dev/null || { echo "This Saiph download is incomplete. Download it again." >&2; return 1; }
  tail -c "$payload_bytes" -- "$self" > "$1" || { echo "Saiph setup could not copy its package; check free disk space." >&2; return 1; }
  actual=$(sha256sum -- "$1" | cut -d ' ' -f 1)
  [ "$actual" = "$payload_sha256" ] || { echo "This Saiph download is damaged or incomplete. Download it again." >&2; return 1; }
}

install_steps() {
  echo "Checking the Saiph $version download..."
  extract_payload "$work/$archive_name" || return 1
  mkdir -- "$work/files"
  tar -xzf "$work/$archive_name" -C "$work/files" || { echo "Saiph setup could not unpack its package; check free disk space." >&2; return 1; }
  rm -f -- "$work/$archive_name"
  [ -f "$work/files/orion/install.sh" ] || { echo "This Saiph download has no installer." >&2; return 1; }
  # Run through sh so a temporary folder mounted without execute permission
  # still works; install.sh copies the app and never runs it from here.
  sh "$work/files/orion/install.sh"
}

extract_only() {
  destination=$1
  case "$destination" in '') usage; return 2 ;; esac
  if [ -e "$destination" ] || [ -L "$destination" ]; then
    echo "Choose a folder that does not exist yet; $destination is retained." >&2; return 1
  fi
  mkdir -p -- "$destination"
  extract_payload "$destination/$archive_name" || { rm -f -- "$destination/$archive_name"; rmdir -- "$destination" 2>/dev/null; return 1; }
  tar -xzf "$destination/$archive_name" -C "$destination"
  echo "Unpacked Saiph $version into $destination/orion; the original archive is $destination/$archive_name."
}

prepare_work() {
  cache_root=${XDG_CACHE_HOME:-"$HOME/.cache"}
  case "$cache_root" in /*) ;; *) cache_root=$HOME/.cache ;; esac
  # A user's cache folder avoids small RAM-backed /tmp mounts for large bundles.
  mkdir -p -- "$cache_root"
  trap cleanup EXIT
  trap 'exit 1' HUP INT TERM
  work=$(mktemp -d "$cache_root/saiph-setup.XXXXXXXX")
  saved_log=$cache_root/saiph-setup.log
}

# Keep the latest result for support without following a planted symlink.
save_log() {
  temporary=$(mktemp "$saved_log.XXXXXXXX") || return 0
  cat -- "$work/install.log" > "$temporary" 2>/dev/null && mv -f -- "$temporary" "$saved_log" || rm -f -- "$temporary"
}

launch_app() {
  app=$HOME/.local/bin/orion
  [ -x "$app" ] || return 0
  if command -v setsid >/dev/null 2>&1; then
    setsid "$app" </dev/null >/dev/null 2>&1 &
  else
    nohup "$app" </dev/null >/dev/null 2>&1 &
  fi
}

intro="Install Saiph $version for your user account?

Saiph is installed in your home folder, so no administrator password is needed. Existing Saiph data, pairing and start-up choices are kept."
done_text="Saiph $version is installed. You can open it from your applications menu at any time."
installed_text="Saiph $version is already installed. Nothing changed. You can open it from your applications menu at any time."

# install.sh refuses a version that is already active without changing anything;
# report that as a normal outcome instead of a failure.
already_installed() {
  root=$HOME/.local/lib/orion
  [ "${ORION_INSTALL_ISOLATED:-0}" != 1 ] || root=${ORION_INSTALL_ROOT:-$root}
  [ -L "$root/current" ] && [ "$(readlink "$root/current")" = "releases/$version" ] && [ -d "$root/releases/$version" ]
}

# Defaults for the options checklist reflect what is installed now, so an upgrade
# never silently re-enables something the person turned off.
autostart_default() {
  entry=${XDG_CONFIG_HOME:-$HOME/.config}/autostart/orion.desktop
  if [ -f "$entry" ]; then
    grep -q '^X-GNOME-Autostart-enabled=false' "$entry" && echo FALSE || echo TRUE
  elif [ -e "$HOME/.local/lib/orion/integration-created" ]; then echo FALSE
  else echo TRUE; fi
}

file_actions_default() {
  scripts=${XDG_DATA_HOME:-$HOME/.local/share}/nautilus/scripts/"Send to phone (Saiph)"
  if [ -e "$HOME/.local/lib/orion/integration-created" ] && [ ! -f "$scripts" ]; then echo FALSE; else echo TRUE; fi
}

# Exports SAIPH_AUTOSTART and SAIPH_FILE_ACTIONS (on|off) for install.sh from the ticked options.
apply_choices() {
  case "$1" in *autostart*) SAIPH_AUTOSTART=on ;; *) SAIPH_AUTOSTART=off ;; esac
  case "$1" in *fileactions*) SAIPH_FILE_ACTIONS=on ;; *) SAIPH_FILE_ACTIONS=off ;; esac
  export SAIPH_AUTOSTART SAIPH_FILE_ACTIONS
}

failure_text() {
  printf 'Saiph could not be installed.\n\n%s\n\nDetails were saved to %s.' "$(tail -n 6 -- "$work/install.log" 2>/dev/null)" "$saved_log"
}

zenity_install() {
  if already_installed; then
    if zenity --question --no-markup --width=440 --title="$title" --ok-label="Open Saiph" --cancel-label=Close --text="$installed_text"; then launch_app; fi
    return 0
  fi
  zenity --question --no-markup --width=440 --title="$title" --ok-label=Next --cancel-label=Cancel --text="$intro" || return 0
  choices=$(zenity --list --checklist --width=480 --height=250 --title="$title" --text="Choose options" --ok-label=Install --cancel-label=Cancel \
    --column=Use --column=Key --column=Option --hide-column=2 --print-column=2 --separator=" " \
    "$(autostart_default)" autostart "Start Saiph when I sign in" \
    "$(file_actions_default)" fileactions "Add \"Send to phone\" to GNOME Files and Dolphin") || return 0
  apply_choices "$choices"
  : > "$work/status"
  (
    if install_steps > "$work/install.log" 2>&1; then echo 0 > "$work/status"; else echo "$?" > "$work/status"; fi
  ) | zenity --progress --pulsate --auto-close --no-cancel --width=440 --title="$title" --text="Installing Saiph $version..." >/dev/null 2>&1 || true
  status=$(cat -- "$work/status" 2>/dev/null) || status=1
  [ -n "$status" ] || status=1
  save_log
  if [ "$status" = 0 ]; then
    if zenity --question --no-markup --width=440 --title="$title" --ok-label="Open Saiph" --cancel-label=Close --text="$done_text"; then launch_app; fi
  else
    zenity --error --no-markup --width=480 --title="$title" --text="$(failure_text)" || true
  fi
  return "$status"
}

kdialog_install() {
  if already_installed; then
    if kdialog --title "$title" --yes-label "Open Saiph" --no-label Close --yesno "$installed_text"; then launch_app; fi
    return 0
  fi
  kdialog --title "$title" --yes-label Next --no-label Cancel --yesno "$intro" || return 0
  on() { [ "$1" = TRUE ] && echo on || echo off; }
  choices=$(kdialog --title "$title" --checklist "Choose options" \
    autostart "Start Saiph when I sign in" "$(on "$(autostart_default)")" \
    fileactions "Add \"Send to phone\" to GNOME Files and Dolphin" "$(on "$(file_actions_default)")") || return 0
  apply_choices "$choices"
  kdialog --title "$title" --passivepopup "Installing Saiph $version. This can take a minute." 10 >/dev/null 2>&1 || true
  if install_steps > "$work/install.log" 2>&1; then status=0; else status=$?; fi
  save_log
  if [ "$status" = 0 ]; then
    if kdialog --title "$title" --yes-label "Open Saiph" --no-label Close --yesno "$done_text"; then launch_app; fi
  else
    kdialog --title "$title" --error "$(failure_text)" || true
  fi
  return "$status"
}

text_install() {
  if already_installed; then
    echo "$installed_text"
    if [ "$in_terminal" = 1 ]; then printf 'Press Enter to close this window. '; read -r _ || true; fi
    return 0
  fi
  if [ "$in_terminal" = 1 ]; then
    printf '%s\n\nPress Enter to install, or close this window to cancel. ' "$intro"
    read -r _ || return 0
  fi
  if install_steps; then status=0; else status=$?; fi
  [ "$status" = 0 ] || echo "Saiph could not be installed; see the messages above." >&2
  if [ "$in_terminal" = 1 ]; then
    printf 'Press Enter to close this window. '
    read -r _ || true
  elif ! [ -t 1 ] && command -v notify-send >/dev/null 2>&1; then
    if [ "$status" = 0 ]; then notify-send "$title" "$done_text" || true
    else notify-send "$title" "Saiph could not be installed. Run this file from a terminal to see why." || true; fi
  fi
  return "$status"
}

# Re-run in a terminal window when no dialog tool exists. An argument, not the
# environment, marks that run: some terminals start commands from a server.
# A missing or failing terminal falls back to an install with a notification.
open_terminal() {
  for terminal in x-terminal-emulator gnome-terminal konsole xfce4-terminal mate-terminal xterm; do
    command -v "$terminal" >/dev/null 2>&1 || continue
    case "$terminal" in
      gnome-terminal) gnome-terminal -- sh "$self" --in-terminal && return 0 ;;
      xfce4-terminal|mate-terminal) "$terminal" -x sh "$self" --in-terminal && return 0 ;;
      *) "$terminal" -e sh "$self" --in-terminal && return 0 ;;
    esac
  done
  return 1
}

main() {
  mode=auto
  case "$#:${1:-}" in
    0:) ;;
    1:--text) mode=text ;;
    1:--in-terminal) mode=text; in_terminal=1 ;;
    2:--extract) extract_only "$2"; return ;;
    1:--help|1:-h) usage; return 0 ;;
    *) usage; return 2 ;;
  esac
  if [ "$mode" = auto ]; then
    if [ -t 0 ] && [ -t 1 ]; then mode=text
    elif [ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then mode=text
    elif command -v zenity >/dev/null 2>&1; then mode=zenity
    elif command -v kdialog >/dev/null 2>&1; then mode=kdialog
    elif open_terminal; then return 0
    else mode=text
    fi
  fi
  prepare_work
  case "$mode" in
    zenity) zenity_install ;;
    kdialog) kdialog_install ;;
    *) text_install ;;
  esac
}

main "$@"; exit $?
# The release archive follows this line; nothing below is shell script.
