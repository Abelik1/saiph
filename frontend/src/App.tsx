// SPDX-License-Identifier: AGPL-3.0-or-later
import {
  Suspense,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import {
  ChevronDown,
  PhoneCall,
  Cloud as CloudIcon,
  FolderOpen,
  Settings as SettingsIcon,
  Smartphone,
} from "lucide-react";
import { desktopClient } from "./workspace/client";
import type { Client, Page, State } from "./workspace/types";
import { Phone } from "./workspace/Phone";
import { Cloud } from "./workspace/Cloud";
import { Settings } from "./workspace/Settings";
import { SetupWizard } from "./workspace/SetupWizard";
import { UsagePrompt } from "./workspace/UsageSharing";
import { Workspace } from "./workspace/edition";
import { RetainedView } from "./workspace/Navigation";
import { SaiphMark, WaveField, WaveLoader, gather } from "./workspace/waves";
import { SettingsNavigation } from "./workspace/settingsNavigation";
import { CallBanner } from "./workspace/callBanner";
import { Action } from "./workspace/ui";
import type { SettingsTarget } from "./workspace/settingsNavigation";

const workspacePages: Page[] = ["Today", "Assistant", "Library", "Calendar", "Tasks", "Reminders", "Inbox", "Plugins"];

/** A top-level place. The current one carries Saiph's ringing string. */
function NavItem({ name, icon: Icon, page, navigate }: { name: Page; icon: typeof Smartphone; page: Page; navigate: (page: Page) => void }) {
  const current = page === name;
  return (
    <button
      type="button"
      data-slot="nav-item"
      aria-label={name}
      aria-current={current ? "page" : undefined}
      onClick={() => navigate(name)}
      className={"relative inline-flex cursor-pointer items-center gap-2 border-0 bg-transparent px-3.5 text-[13px] font-medium outline-none transition-colors focus-visible:ring-[3px] focus-visible:ring-ring/35 [&_svg]:size-[18px] " + (current ? "text-foreground" : "text-muted-foreground hover:text-foreground")}
    >
      <Icon aria-hidden="true" />
      {name}
      {current && <span aria-hidden="true" className="wave-underline" style={{ bottom: 10 }} />}
    </button>
  );
}

/** One honest line about the connection: green only while a device is actually online. */
function connection(state: State) {
  const devices = state.phone?.devices || [];
  const online = devices.filter((device) => device.online);
  if (online.length) return { tone: "bg-status-on", text: online.length === 1 ? `${online[0].name} connected` : `${online.length} devices connected` };
  if (state.settings.hub?.paired || devices.length) return { tone: "bg-status-warn", text: devices.length ? "Waiting for your devices" : "No devices yet" };
  return { tone: "bg-muted-foreground/60", text: "Not set up" };
}

/** A ringing call reaches you on every page, and is announced to screen readers. */
function IncomingCall({ state, client }: { state: State; client: Client }) {
  const call = state.phone_features?.calls.find((row) => row.state === "ringing");
  const phone = call && state.phone?.devices.find((device) => device.id === call.device_id);
  if (!call || !phone) return null;
  const control = phone.online && phone.capabilities.includes("call-control");
  return (
    <div role="alert" className="string-edge relative z-10 flex flex-wrap items-center gap-3 border-b border-secondary-border bg-popover px-8 py-2.5 max-[1100px]:px-6">
      <span className="flex size-8 items-center justify-center rounded-full bg-secondary text-secondary-foreground [&_svg]:size-4"><PhoneCall /></span>
      <span className="min-w-0 flex-1 text-[13px]"><b className="font-semibold">Incoming call</b> · {call.name || call.number} <span className="text-muted-foreground">on {phone.name}</span></span>
      {control
        ? <div className="flex gap-2">
            <Action variant="default" size="sm" run={() => client.call("phone.call", { device_id: phone.id, operation: "answer" })}>Answer</Action>
            <Action variant="destructive" size="sm" run={() => client.call("phone.call", { device_id: phone.id, operation: "reject" })}>Decline</Action>
          </div>
        : <small className="text-[12px] text-muted-foreground">Answer on your phone, or allow call control in Saiph on it.</small>}
    </div>
  );
}

export function workspaceAvailable(state: State) {
  return (
    Workspace !== null &&
    state.modules?.workspace?.installed !== false &&
    state.modules?.workspace?.enabled !== false
  );
}

export default function App({
  providedClient,
}: { providedClient?: Client } = {}) {
  // One string field for the whole window, so it carries on across screens.
  return (
    <>
      <WaveField />
      <Screens providedClient={providedClient} />
    </>
  );
}

function Screens({ providedClient }: { providedClient?: Client }) {
  const [client, setClient] = useState<Client | null>(providedClient || null);
  const [state, setState] = useState<State | null>(null);
  const [page, setPage] = useState<Page>("Phone");
  const [error, setError] = useState("");
  const [guide, setGuide] = useState(false);
  const scroll = useRef<HTMLElement>(null);
  const positions = useRef<Partial<Record<Page, number>>>({});
  const [settingsRequest, setSettingsRequest] = useState<{
    section: string;
    id: number;
  }>();
  const navigate = useCallback(
    (next: Page) => {
      positions.current[page] = scroll.current?.scrollTop || 0;
      setPage(next);
    },
    [page],
  );
  useLayoutEffect(() => {
    if (scroll.current) scroll.current.scrollTop = positions.current[page] || 0;
  }, [page]);
  const fetching = useRef(false),
    last = useRef<State | null>(null);
  useEffect(() => {
    if (providedClient) return;
    let active = true;
    desktopClient()
      .then((value) => {
        if (active) setClient(value);
      })
      .catch((error) => {
        if (active) setError(error.message);
      });
    return () => {
      active = false;
    };
  }, [providedClient]);
  const refresh = useCallback(async () => {
    if (!client || fetching.current) return;
    fetching.current = true;
    try {
      // The desktop client answers an unchanged state with the same object.
      const value = await client.call<State>("state");
      if (last.current !== value) {
        last.current = value;
        setState(value);
      }
      setError("");
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error));
    } finally {
      fetching.current = false;
    }
  }, [client]);
  useEffect(() => {
    if (!client) return;
    void refresh();
    return client.subscribe(() => void refresh());
  }, [client, refresh]);
  const hasWorkspace = state ? workspaceAvailable(state) : false;
  useEffect(() => {
    if (!hasWorkspace && workspacePages.includes(page)) setPage("Phone");
  }, [hasWorkspace, page]);
  useEffect(() => {
    if (state?.enrollment?.ready && !state.settings.hub?.paired)
      setPage("Phone");
  }, [
    state?.enrollment?.id,
    state?.enrollment?.ready,
    state?.settings.hub?.paired,
  ]);
  // Screens are counted for the local "Your week" summary, and shared only after the owner agreed.
  const counting = state?.usage?.consent === "granted" || state?.insights?.enabled === true;
  useEffect(() => {
    if (client && counting) void client.call("usage.screen", { screen: page.toLowerCase() }).catch(() => undefined);
  }, [client, counting, page]);
  const openSettings = useCallback(
    (target: SettingsTarget) => {
      setSettingsRequest((current) => ({
        section: hasWorkspace ? "Advanced" : target,
        id: (current?.id || 0) + 1,
      }));
      positions.current.Settings = 0;
      navigate("Settings");
    },
    [hasWorkspace, navigate],
  );
  const opening = !state || !client;
  // While connecting, the background strings curl around the mark.
  useEffect(() => {
    if (opening && !error)
      return gather(window.innerWidth / 2, window.innerHeight / 2, 150);
  }, [opening, error]);
  if (!state || !client)
    return (
      <div className="connection-screen">
        <SaiphMark size={72} />
        <h1>saiph</h1>
        {error ? (
          <p role="alert">{error}</p>
        ) : (
          <WaveLoader label="Opening Saiph…" />
        )}
      </div>
    );
  // First run, or re-run from Settings: the setup guide takes the whole window.
  if (guide || state.setup?.show) return <div className="workspace-shell link-shell setup-shell"><main className="page-content">
    <SetupWizard state={state} client={client} close={() => { setGuide(false); void refresh(); }} /></main></div>;
  const workspacePage =
    workspacePages.includes(page) || (page === "Settings" && hasWorkspace);
  const status = connection(state);
  return (
    <SettingsNavigation.Provider
      value={{ openSettings, request: settingsRequest }}
    >
      <CallBanner.Provider value={true}>
      <div className="workspace-shell link-shell relative z-[1] grid h-dvh min-h-0 grid-rows-[64px_auto_minmax(0,1fr)_28px] bg-transparent">
        {state.usage?.available && state.usage.consent === null && <UsagePrompt client={client} />}
        <header className="link-header relative z-20 flex min-h-0 items-center gap-10 border-b border-border bg-chrome px-8 max-[1100px]:gap-6 max-[1100px]:px-6">
          <div className="flex shrink-0 items-center gap-2.5">
            <span className="grid size-9 place-items-center rounded-[11px] border border-secondary-border bg-[radial-gradient(circle_at_50%_45%,color-mix(in_srgb,var(--wave-1)_16%,transparent),var(--background)_70%)]">
              <SaiphMark size={26} animated={false} />
            </span>
            <b className="bg-[linear-gradient(90deg,var(--foreground),var(--wave-2)_60%,var(--wave-3))] bg-clip-text text-[22px] font-semibold tracking-[-0.04em] text-transparent">saiph</b>
          </div>
          <nav aria-label="Main navigation" className="flex items-stretch gap-1 self-stretch">
            <NavItem name="Phone" icon={Smartphone} page={page} navigate={navigate} />
            <NavItem name="Cloud" icon={CloudIcon} page={page} navigate={navigate} />
            {hasWorkspace && (
              <details className="workspace-navigation">
                <summary
                  className={workspacePages.includes(page) ? "active" : ""}
                >
                  <FolderOpen size={18} />
                  Workspace
                  <ChevronDown size={14} />
                </summary>
                <div className="workspace-nav-menu">
                  {workspacePages.map((name) => (
                    <button
                      key={name}
                      aria-label={name}
                      aria-current={page === name ? "page" : undefined}
                      onClick={(event) => {
                        navigate(name);
                        event.currentTarget
                          .closest("details")
                          ?.removeAttribute("open");
                      }}
                    >
                      {name}
                    </button>
                  ))}
                </div>
              </details>
            )}
            <NavItem name="Settings" icon={SettingsIcon} page={page} navigate={navigate} />
          </nav>
          <span className="ml-auto flex max-w-56 items-center gap-2 truncate text-[12px] text-muted-foreground max-[850px]:hidden" title={status.text}>
            <span aria-hidden="true" className={"size-2 shrink-0 rounded-full " + status.tone} />
            {state.settings.machine?.name || "This computer"}
          </span>
        </header>
        <div><IncomingCall state={state} client={client} /></div>
        <main
          ref={scroll}
          className="app-scroll"
          tabIndex={0}
          aria-label={page + " content"}
        >
          <div className="page-content mx-auto w-full max-w-[1480px] px-8 pt-7 pb-12 max-[1100px]:px-6">
            {!workspacePage && page !== "Settings" && page !== "Phone" && (
              <header className="mb-6 grid gap-1 motion-safe:animate-[saiph-rise_.5s_var(--ease)_both]" key={page}>
                <h1 className="m-0 text-[26px] font-semibold tracking-[-0.035em]">{page}</h1>
                <p className="m-0 text-[13px] text-muted-foreground">Your files, close at hand.</p>
              </header>
            )}
            {page === "Phone" && <h1 className="sr-only">Phone</h1>}
            {error && (
              <p role="alert" className="inline-error">
                {error}
              </p>
            )}
            <RetainedView active={page === "Phone"}>
              <Phone state={state} client={client} active={page === "Phone"} />
            </RetainedView>
            <RetainedView active={page === "Cloud"}>
              <Cloud state={state} client={client} />
            </RetainedView>
            {!hasWorkspace && (
              <RetainedView active={page === "Settings"}>
                <Settings state={state} client={client} openSetup={() => setGuide(true)} />
              </RetainedView>
            )}
            {hasWorkspace && Workspace && (
              <div className="workspace-container" hidden={!workspacePage}>
                <Suspense fallback={<p role="status">Opening Workspace…</p>}>
                  <Workspace
                    state={state}
                    client={client}
                    page={page}
                    navigate={navigate}
                  />
                </Suspense>
              </div>
            )}
          </div>
        </main>
        <footer className="app-footer flex items-center justify-between gap-4 border-t border-border bg-chrome px-8 text-[10.5px] tracking-[0.02em] text-muted-foreground">
          <span className="flex items-center gap-1.5"><span aria-hidden="true" className={"size-1.5 rounded-full " + status.tone} />{status.text}</span>
          <span>Saiph</span>
        </footer>
      </div>
      </CallBanner.Provider>
    </SettingsNavigation.Provider>
  );
}
