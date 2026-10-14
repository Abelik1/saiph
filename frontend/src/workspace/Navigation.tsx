// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from "react";
import type { ReactNode } from "react";
import { useSettingsNavigation } from "./settingsNavigation";
import type { SettingsTarget } from "./settingsNavigation";
import { Button } from "@/components/ui/button";

// Mount on the first visit, then retain in-memory drafts until the app closes.
export function RetainedView({
  active,
  children,
  className,
}: {
  active: boolean;
  children: ReactNode | (() => ReactNode);
  className?: string;
}) {
  const [visited, setVisited] = useState(active);
  if (active && !visited) setVisited(true);
  return visited || active ? (
    <div hidden={!active} className={className}>
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
    <Button variant="tonal" size="sm" onClick={() => openSettings(target)}>
      {children}
    </Button>
  ) : null;
}
