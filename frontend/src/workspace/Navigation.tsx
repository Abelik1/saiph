// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from "react";
import type { ReactNode } from "react";
import { useSettingsNavigation } from "./settingsNavigation";
import type { SettingsTarget } from "./settingsNavigation";

// Mount on the first visit, then retain in-memory drafts until the app closes.
export function RetainedView({
  active,
  children,
}: {
  active: boolean;
  children: ReactNode | (() => ReactNode);
}) {
  const [visited, setVisited] = useState(active);
  if (active && !visited) setVisited(true);
  return visited || active ? (
    <div hidden={!active}>
      {typeof children === "function" ? children() : children}
    </div>
  ) : null;
}

export function SettingsShortcut({
  target,
  children,
}: {
  target: SettingsTarget;
  children: ReactNode;
}) {
  const { openSettings } = useSettingsNavigation();
  return openSettings ? (
    <button
      type="button"
      className="text-button"
      onClick={() => openSettings(target)}
    >
      {children}
    </button>
  ) : null;
}
