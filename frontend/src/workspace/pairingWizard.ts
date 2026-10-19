// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useSyncExternalStore } from "react";

/** Whether a connection wizard is on screen; the global approval pop-up waits while it handles requests. */
let open = 0;
const listeners = new Set<() => void>();
const notify = () => listeners.forEach(listener => listener());

export function useWizardOpen(active = true) {
  useEffect(() => {
    if (!active) return;
    open += 1; notify();
    return () => { open -= 1; notify(); };
  }, [active]);
}

export const isWizardOpen = () => open > 0;

export function useAnyWizardOpen(): boolean {
  return useSyncExternalStore(listener => { listeners.add(listener); return () => { listeners.delete(listener); }; }, () => open > 0);
}
