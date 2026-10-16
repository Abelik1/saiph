// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from "react";
import { FolderOpen, Files, FileText, ArrowUpRight } from "lucide-react";
import type { Client, CloudInfo, CloudPreparation, State } from "./types";
import { Action } from "./ui";
import { PreferenceCard as Card } from "./PreferenceCard";
import { SettingsShortcut } from "./Navigation";

export function Cloud({ state, client }: { state: State; client: Client }) {
  const cloud = state.cloud_status;
  const [setup, setSetup] = useState<CloudInfo | null>(null);
  const [library, setLibrary] = useState("");
  const [prepared, setPrepared] = useState<CloudPreparation | null>(null);
  const [installed, setInstalled] = useState(false);
  const hasProfile = Boolean(cloud?.profile_present);
  const canSetup = Boolean(cloud?.installed && cloud.inspection_complete && !hasProfile && !prepared);
  const settingsSection = state.modules?.workspace?.installed === false ? "Connections" : "Advanced";
  const description = state.settings.cloud?.enabled === false ? `Cloud folders are off. Enable them in Settings → ${settingsSection}.`
    : cloud?.state === "inspection_pending" ? "Checking file sync…"
    : !cloud?.installed ? "Local folders · file sync is not set up"
    : !cloud.inspection_complete ? "Existing profile needs inspection. It has been kept."
    : cloud.service_state === "needs_attention" ? `File sync needs attention in Settings → ${settingsSection}.`
    : cloud.service_state === "unavailable" ? "File sync is unavailable. Saiph checks its background service automatically."
    : cloud.service_state === "reachable" ? "Sync service available. Transfer completion has not been verified."
    : cloud.selected_libraries > 0 ? cloud.management_available === false ? "Library links found. Transfer progress is not available here." : "Library links found. Check progress in the file sync app."
    : hasProfile ? "Existing profile · no library links found"
    : "Choose a library to set up file sync.";
  return <div className="mx-auto grid w-full max-w-4xl gap-6">
    <Card title="Cloud folder">
      <div className="flex flex-wrap items-center gap-3"><Action variant="default" run={() => client.call("cloud.open", {folder:"root"})}><FolderOpen size={16} />Open Cloud folder</Action><SettingsShortcut target="Connections">Cloud settings</SettingsShortcut></div>
      <p role="status">{description}</p>
    </Card>
    {!cloud?.installed && cloud?.inspection_complete && cloud.installation_supported && <Card title="Set up file sync" subtitle="An optional component for the folders you choose.">
      <p>Install Seafile for folder sync. Windows may ask for administrator approval. Existing folders and accounts are kept.</p>
      {installed ? <p role="status">File sync is installed. Saiph is checking the new component before library setup.</p> : <Action className="primary" run={async () => {
        try { await client.call("cloud.client.install"); setInstalled(true); }
        catch { throw new Error("File sync installation could not finish. Existing folders and profiles were kept."); }
      }}>Install file sync</Action>}
    </Card>}
    {cloud?.installed && <Card title="File sync" subtitle="Choose what belongs on this computer.">
      {hasProfile ? <p>Existing account and library links are kept. {cloud.service_state && cloud.service_state !== 'not_managed' ? 'Saiph maintains its background sync service.' : cloud.management_available !== false ? 'Manage them in the file sync app.' : 'No graphical file sync app is installed.'}</p> : prepared ? <p role="status">{prepared.state === "existing_binding" ? "Your existing account and library links were preserved." : prepared.needs_library_link ? "Your account is prepared. Finish linking your chosen library in the file sync app; Saiph has not confirmed transfers yet." : "Your library link was requested. Saiph maintains its background service; transfers have not been confirmed yet."}</p> : <p>Choose one library and its local folder.</p>}
      {cloud.inspection_complete && cloud.management_available !== false && <Action run={async () => {
        try { await client.call("cloud.client.open"); }
        catch { throw new Error(`The file sync app could not be opened. Check its installation in Settings → ${settingsSection}.`); }
      }}>Manage file sync</Action>}
      {canSetup && !setup && <Action className="primary" disabled={!state.settings.hub?.paired} run={async () => {
        try { setSetup(await client.call<CloudInfo>("cloud.info")); setLibrary(""); }
        catch { throw new Error("File sync setup is temporarily unavailable. Try again when your server is reachable."); }
      }}>Set up file sync</Action>}
      {canSetup && !state.settings.hub?.paired && <p className="muted">Use your server invitation on the Phone page before setting up file sync.</p>}
      {canSetup && setup && <div className="grid gap-4 border-t border-border pt-4">
        {!setup.configured ? <p role="status">File sync is not enabled on your server yet. Your server owner can finish Cloud setup.</p> : !setup.libraries.length ? <p role="status">No libraries are available for this device yet. Your server owner can choose which libraries to share.</p> : <>
          <fieldset><legend>Choose a library</legend>{setup.libraries.map(item => <label className="check" key={item.id}><input type="radio" name="cloud-library" value={item.id} checked={library === item.id} onChange={() => setLibrary(item.id)} /><span>{item.name}{item.permission === "r" ? " · read only" : ""}</span></label>)}</fieldset>
          <p className="muted">Your operating system will ask you to choose the folder. Your existing files and other library links stay in place.</p>
          <Action className="primary" disabled={!library} run={async () => {
            try {
              const result = await client.call<CloudPreparation>("cloud.setup", {libraries:[library]});
              if (!result.cancelled) { setPrepared(result); setSetup(null); }
            } catch { throw new Error("File sync setup could not finish. Your existing account and folders were kept."); }
          }}>Choose folder and continue</Action>
        </>}
        <button type="button" className="text-button" onClick={() => { setSetup(null); setLibrary(""); }}>Cancel setup</button>
      </div>}
    </Card>}
    <div className="grid gap-4 sm:grid-cols-2">{[{folder:"Shared",icon:Files},{folder:"Documents",icon:FileText}].map(({folder,icon:Icon}) => <Card key={folder} title={folder}><div className="flex items-center justify-between gap-4"><Icon size={28} strokeWidth={1.5} className="text-muted-foreground" /><Action variant="secondary" ariaLabel={"Open " + folder + " folder"} run={() => client.call("cloud.open", {folder})}>Open folder<ArrowUpRight size={15} /></Action></div></Card>)}</div>
  </div>;
}
