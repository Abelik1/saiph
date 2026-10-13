// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from "react";
import type { Client, State } from "./types";
import { Action, Card, Form } from "./ui";
import { ContinuitySettings } from "./ContinuitySettings";
import { Updates } from "./Updates";
import { CameraSettings } from "./CameraSettings";
import { MicrophoneSettings } from "./PhoneMicrophone";
import { HostedSettings } from "./HostedSettings";
import { DeskflowSettings } from "./DeskflowSettings";
import { HotspotSettings } from "./HotspotSettings";
import { RemoteSettings } from "./RemoteSettings";
import { BluetoothLockSettings } from "./BluetoothLockSettings";

export function WorkspaceModule({ installed = false }: { installed?: boolean }) {
  return <Card title="Workspace" subtitle="Optional personal tools."><p>Projects, transcripts, calendar, reminders and assistant tools live in the separate Workspace edition.</p><p className="muted">{installed ? "The Workspace edition is installed on this computer." : "Saiph Link works on its own. Install the Workspace edition separately when a trusted installer is available."}</p></Card>;
}

export function Settings({ state, client }: { state: State; client: Client }) {
  const [tab, setTab] = useState("General"), [name, setName] = useState(state.settings.machine?.name || "");
  const [hub, setHub] = useState(state.settings.hub?.base_url || ""), [code, setCode] = useState("");
  return <>
    <div className="tabs page-tabs" role="tablist" aria-label="Settings sections">{["General", "Advanced"].map(value => <button key={value} role="tab" aria-selected={tab === value} className={tab === value ? "selected" : ""} onClick={() => setTab(value)}>{value}</button>)}</div>
    {tab === "General" ? <div className="columns">
      <div><Card title="This computer"><Form submit={() => client.call("settings.save", {machine:{...state.settings.machine,name}})}><label>Computer name<input value={name} maxLength={40} required onChange={event => setName(event.target.value)} /></label><button>Save this computer</button></Form></Card><WorkspaceModule installed={state.modules?.workspace?.installed} /><Updates client={client} status={state.update_status} /></div>
      <Card title="Startup"><div className="list-row"><div className="grow"><b>Start when I sign in</b><small>{state.settings.start_with_windows ? "On" : "Off"}</small></div><Action run={() => client.call("settings.save", {start_with_windows:!state.settings.start_with_windows})}>{state.settings.start_with_windows ? "Turn off" : "Turn on"}<span className="sr-only"> start when I sign in</span></Action></div><div className="list-row"><div className="grow"><b>Close to the system tray</b><small>Keep Saiph available while its window is closed.</small></div><Action run={() => client.call("settings.save", {close_to_tray:!state.settings.close_to_tray})}>{state.settings.close_to_tray ? "Turn off" : "Turn on"}<span className="sr-only"> close to the system tray</span></Action></div></Card>
    </div> : <div className="columns">
      <ContinuitySettings settings={state.settings} backup={state.backup_status} client={client} workspace={false} />
      <CameraSettings settings={state.settings} camera={state.camera} client={client} />
      <MicrophoneSettings settings={state.settings} microphone={state.microphone} client={client} />
      <DeskflowSettings settings={state.settings} error={state.deskflow?.error} status={state.deskflow} client={client} defaultEnabled={false} />
      <HotspotSettings hotspot={state.hotspot} client={client} />
      <RemoteSettings remote={state.remote} state={state} client={client} />
      <BluetoothLockSettings status={state.bt_lock} client={client} />
      <HostedSettings hosted={state.hosted} client={client} />
      <Card title="Saiph Hub"><Form submit={async () => {await client.call("hub.pair", {base_url:hub,code,name:state.settings.machine?.name || "Saiph desktop"});setCode("");}}><label>Hub address<input aria-label="Saiph Hub address" value={hub} onChange={event => setHub(event.target.value)} /></label><label>One-time pairing code<input aria-label="Saiph Hub pairing code" value={code} inputMode="numeric" maxLength={8} onChange={event => setCode(event.target.value)} /></label><button>Pair desktop</button></Form><p className="muted">{state.settings.hub?.paired ? "This computer is paired." : "Pair once using your server invitation."}</p>{state.phone?.error && <p className="inline-error">{state.phone.error}</p>}</Card>
    </div>}
  </>;
}
