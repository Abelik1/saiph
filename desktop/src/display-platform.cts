// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * The argument Saiph must restart with on a Linux Wayland session, or undefined when none is needed.
 *
 * Electron picks its display platform before any app code runs. A switch appended from
 * here reaches only the child processes, so the window stays on Wayland while the GPU
 * process draws for X11: it crashes and no window ever appears. The platform has to be on
 * the real command line, which covers the menu entry, autostart and a directly run tar install.
 */
export function missingDisplayPlatform(platform: string, env: NodeJS.ProcessEnv, argv: readonly string[]): string | undefined {
  if (platform !== "linux" || !env.DISPLAY || !(env.WAYLAND_DISPLAY || env.XDG_SESSION_TYPE === "wayland")) return undefined;
  if (argv.some(value => value === "--ozone-platform" || value.startsWith("--ozone-platform="))) return undefined;
  return `--ozone-platform=${env.ORION_MINI_ELECTRON_PLATFORM || "x11"}`;
}
