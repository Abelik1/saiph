// SPDX-License-Identifier: AGPL-3.0-or-later
import { createContext, useContext, useState } from "react";

export type SettingsTarget = "Connections" | "Devices";
export const SettingsNavigation = createContext<{
  openSettings?: (target: SettingsTarget) => void;
  request?: { section: string; id: number };
}>({});
export const useSettingsNavigation = () => useContext(SettingsNavigation);

export function useSettingsSection<T extends string>(initial: T) {
  const { request } = useSettingsNavigation();
  const [tab, setTab] = useState<T>((request?.section as T) || initial);
  const [handled, setHandled] = useState(request?.id);
  if (handled !== request?.id) {
    setHandled(request?.id);
    if (request) setTab(request.section as T);
  }
  return [tab, setTab] as const;
}
