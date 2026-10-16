// SPDX-License-Identifier: AGPL-3.0-or-later
import { useId } from "react";
import type { ReactNode } from "react";
import {
  AudioLines,
  Bot,
  Cable,
  FolderOpen,
  Monitor,
  Shield,
  SlidersHorizontal,
  Sparkles,
  Download,
} from "lucide-react";

const icons = {
  General: Monitor,
  Connections: Cable,
  Devices: AudioLines,
  Updates: Download,
  AI: Bot,
  Accounts: Shield,
  Projects: FolderOpen,
  Advanced: SlidersHorizontal,
};
const descriptions: Record<string, string> = {
  General: "Your computer, startup and everyday preferences.",
  Connections: "Your account, Cloud folder and connection preferences.",
  Devices: "Camera, microphone and controls for this computer.",
  Updates: "Keep this computer up to date.",
  AI: "Choose how your assistant runs and which models it uses.",
  Accounts: "Manage the accounts connected to your workspace.",
  Projects: "Project folders, context and recording locations.",
  Advanced: "Optional integrations and detailed configuration.",
};
export function SettingsLayout<T extends string>({
  tabs,
  selected,
  onSelect,
  children,
}: {
  tabs: readonly T[];
  selected: T;
  onSelect: (tab: T) => void;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <div className="settings-layout">
      <aside className="settings-sidebar">
        <h1 className="settings-sidebar-title">Settings</h1>
        <div
          role="tablist"
          aria-label="Settings sections"
          aria-orientation="vertical"
        >
          {tabs.map((tab, index) => {
            const Icon = icons[tab as keyof typeof icons] || Sparkles;
            return (
              <button
                key={tab}
                id={`${id}-${tab}`}
                role="tab"
                aria-controls={`${id}-panel`}
                aria-selected={selected === tab}
                tabIndex={selected === tab ? 0 : -1}
                onClick={(event) => {
                  event.currentTarget
                    .closest(".app-scroll")
                    ?.scrollTo?.({ top: 0 });
                  onSelect(tab);
                }}
                onKeyDown={(event) => {
                  if (
                    !["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)
                  )
                    return;
                  event.preventDefault();
                  const next =
                    event.key === "Home"
                      ? tabs[0]
                      : event.key === "End"
                        ? tabs[tabs.length - 1]
                        : tabs[
                            (index +
                              (event.key === "ArrowDown" ? 1 : -1) +
                              tabs.length) %
                              tabs.length
                          ];
                  onSelect(next);
                  event.currentTarget
                    .closest(".app-scroll")
                    ?.scrollTo?.({ top: 0 });
                  document.getElementById(`${id}-${next}`)?.focus();
                }}
              >
                <Icon size={17} />
                {tab}
              </button>
            );
          })}
        </div>
        <p>Preferences for this computer</p>
      </aside>
      <section
        className="settings-content"
        id={`${id}-panel`}
        role="tabpanel"
        aria-labelledby={`${id}-${selected}`}
      >
        <header className="settings-section-title">
          <h2>{selected}</h2>
          <p>{descriptions[selected]}</p>
        </header>
        {children}
      </section>
    </div>
  );
}
