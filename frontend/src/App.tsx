// SPDX-License-Identifier: AGPL-3.0-or-later
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown, Cloud as CloudIcon, FolderOpen, Settings as SettingsIcon, Smartphone } from "lucide-react";
import { desktopClient } from "./workspace/client";
import type { Client, Page, State } from "./workspace/types";
import { Phone } from "./workspace/Phone";
import { Cloud } from "./workspace/Cloud";
import { Settings } from "./workspace/Settings";
import { SetupWizard } from "./workspace/SetupWizard";
import { Workspace } from "./workspace/edition";
import { SaiphMark, WaveField, WaveLoader, gather } from "./workspace/waves";
import "./workspace/workspace.css";
import "./workspace/link.css";
import "./workspace/waves.css";

const workspacePages: Page[] = ["Today", "Assistant", "Library", "Calendar", "Tasks", "Reminders", "Inbox", "Plugins"];

export function workspaceAvailable(state: State) {
  return Workspace !== null && state.modules?.workspace?.installed !== false && state.modules?.workspace?.enabled !== false;
}

export default function App({ providedClient }: { providedClient?: Client } = {}) {
  // One string field for the whole window, so it carries on across screens.
  return <><WaveField /><Screens providedClient={providedClient} /></>;
}

function Screens({ providedClient }: { providedClient?: Client }) {
  const [client, setClient] = useState<Client | null>(providedClient || null);
  const [state, setState] = useState<State | null>(null);
  const [page, setPage] = useState<Page>("Phone");
  const [error, setError] = useState("");
  const [guide, setGuide] = useState(false);
  const fetching = useRef(false), last = useRef("");
  useEffect(() => {
    if (providedClient) return;
    let active = true;
    desktopClient().then(value => { if (active) setClient(value); }).catch(error => { if (active) setError(error.message); });
    return () => { active = false; };
  }, [providedClient]);
  const refresh = useCallback(async () => {
    if (!client || fetching.current) return;
    fetching.current = true;
    try {
      const value = await client.call<State>("state"), raw = JSON.stringify(value);
      if (last.current !== raw) { last.current = raw; setState(value); }
      setError("");
    } catch (error) { setError(error instanceof Error ? error.message : String(error)); }
    finally { fetching.current = false; }
  }, [client]);
  useEffect(() => { if (!client) return; void refresh(); return client.subscribe(() => void refresh()); }, [client, refresh]);
  const hasWorkspace = state ? workspaceAvailable(state) : false;
  useEffect(() => { if (!hasWorkspace && workspacePages.includes(page)) setPage("Phone"); }, [hasWorkspace, page]);
  useEffect(() => { if (state?.enrollment?.ready && !state.settings.hub?.paired) setPage("Phone"); }, [state?.enrollment?.id, state?.enrollment?.ready, state?.settings.hub?.paired]);
  const opening = !state || !client;
  // While connecting, the background strings gather into a knot behind the mark.
  useEffect(() => { if (opening && !error) return gather(window.innerWidth / 2, window.innerHeight / 2, 150); }, [opening, error]);
  if (!state || !client) return <div className="connection-screen"><SaiphMark size={72} /><h1>saiph</h1>
    {error ? <p role="alert">{error}</p> : <WaveLoader label="Opening Saiph…" />}</div>;
  // First run, or re-run from Settings: the setup guide takes the whole window.
  if (guide || state.setup?.show) return <div className="workspace-shell link-shell setup-shell"><main className="page-content">
    <SetupWizard state={state} client={client} close={() => { setGuide(false); void refresh(); }} /></main></div>;
  const workspacePage = workspacePages.includes(page) || (page === "Settings" && hasWorkspace);
  return <div className="workspace-shell link-shell">
    <header className="link-header">
      <div className="brand"><span className="brand-mark"><SaiphMark size={30} /></span><b>saiph</b></div>
      <nav aria-label="Main navigation">
        <button aria-label="Phone" aria-current={page === "Phone" ? "page" : undefined} onClick={() => setPage("Phone")}><Smartphone size={18} />Phone</button>
        <button aria-label="Cloud" aria-current={page === "Cloud" ? "page" : undefined} onClick={() => setPage("Cloud")}><CloudIcon size={18} />Cloud</button>
        {hasWorkspace && <details className="workspace-navigation"><summary className={workspacePages.includes(page) ? "active" : ""}><FolderOpen size={18} />Workspace<ChevronDown size={14} /></summary><div className="workspace-nav-menu">{workspacePages.map(name => <button key={name} aria-label={name} aria-current={page === name ? "page" : undefined} onClick={event => {setPage(name);event.currentTarget.closest("details")?.removeAttribute("open");}}>{name}</button>)}</div></details>}
        <button aria-label="Settings" aria-current={page === "Settings" ? "page" : undefined} onClick={() => setPage("Settings")}><SettingsIcon size={18} />Settings</button>
      </nav>
      <span className="computer-name">{state.settings.machine?.name || "This computer"}</span>
    </header>
    <main className="page-content">
      {!workspacePage && <header className="page-header" key={page}><h1>{page}</h1><p>{page === "Phone" ? "Your everyday phone, with room to do more." : page === "Cloud" ? "Your files, close at hand." : "Make Saiph feel at home."}</p></header>}
      {error && <p role="alert" className="inline-error">{error}</p>}
      {page === "Phone" && <Phone state={state} client={client} />}
      {page === "Cloud" && <Cloud state={state} client={client} />}
      {page === "Settings" && !hasWorkspace && <Settings state={state} client={client} openSetup={() => setGuide(true)} />}
      {hasWorkspace && Workspace && <div hidden={!workspacePage}><Suspense fallback={<p role="status">Opening Workspace…</p>}><Workspace state={state} client={client} page={page} navigate={setPage} /></Suspense></div>}
    </main>
  </div>;
}
