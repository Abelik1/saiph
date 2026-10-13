// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from "react";
import { FolderOpen, Files, FileText, ArrowUpRight } from "lucide-react";
import type { Client, CloudInfo, CloudPreparation, State } from "./types";
import { Action, Card } from "./ui";
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
  const description = state.settings.cloud?.enabled === false ? `Cloud folders are turned off in Settings → ${settingsSection}.`
    : cloud?.state === "inspection_pending" ? "Checking your existing file sync setup…"
    : !cloud?.installed ? "Your folders are available locally. The file sync service is not set up on this computer yet."
    : !cloud.inspection_complete ? "An existing file sync profile needs inspection. Saiph has kept it unchanged."
    : cloud.service_state === "needs_attention" ? `File sync needs attention in Settings → ${settingsSection}. Your folders and existing setup have been kept.`
    : cloud.service_state === "unavailable" ? "File sync is temporarily unavailable. Saiph checks its background service automatically while it is open."
    : cloud.service_state === "reachable" ? "The file sync service is available in the background. Transfer completion has not been verified here."
    : cloud.selected_libraries > 0 ? cloud.management_available === false ? "Existing library links were found. Transfer progress is not available here." : "Existing library links were found. Open your file sync app to check transfer progress."
    : hasProfile ? "Existing file sync configuration was found. No library links were detected."
    : "The file sync client is installed. Choose a library and folder below to set it up.";
  return <div className="cloud-page">
    <Card title="A familiar place for your files" subtitle="Keep the folders you choose available across your devices."><FolderOpen size={42} strokeWidth={1} className="cloud-symbol" /><p>Use your Cloud folder like any other folder. With a library linked, your file service handles changes in the background.</p><Action className="primary" run={() => client.call("cloud.open", {folder:"root"})}><FolderOpen size={16} />Open Cloud folder</Action><p className="muted" role="status">{description}</p><SettingsShortcut target="Connections">Cloud settings</SettingsShortcut></Card>
    {!cloud?.installed && cloud?.inspection_complete && cloud.installation_supported && <Card title="Set up file sync" subtitle="An optional component for the folders you choose.">
      <p>Install the Seafile sync component once. Your operating system may ask for administrator approval. Your existing folders and accounts stay in place.</p>
      {installed ? <p role="status">File sync is installed. Saiph is checking the new component before library setup.</p> : <Action className="primary" run={async () => {
        try { await client.call("cloud.client.install"); setInstalled(true); }
        catch { throw new Error("File sync installation could not finish. Existing folders and profiles were kept."); }
      }}>Install file sync</Action>}
    </Card>}
    {cloud?.installed && <Card title="File sync" subtitle="Choose what belongs on this computer.">
      {hasProfile ? <p>Your existing account and library links stay in place. {cloud.service_state && cloud.service_state !== 'not_managed' ? 'Saiph maintains its background file sync service while it is open.' : cloud.management_available !== false ? 'Manage them in the file sync app.' : 'No graphical file sync app is installed.'}</p> : prepared ? <p role="status">{prepared.state === "existing_binding" ? "Your existing account and library links were preserved." : prepared.needs_library_link ? "Your account is prepared. Finish linking your chosen library in the file sync app; Saiph has not confirmed transfers yet." : "Your library link was requested. Saiph maintains its background service; transfers have not been confirmed yet."}</p> : <p>Set up one library and choose its local folder once. Your file sync service handles later changes automatically.</p>}
      {cloud.inspection_complete && cloud.management_available !== false && <Action run={async () => {
        try { await client.call("cloud.client.open"); }
        catch { throw new Error(`The file sync app could not be opened. Check its installation in Settings → ${settingsSection}.`); }
      }}>Manage file sync</Action>}
      {canSetup && !setup && <Action className="primary" disabled={!state.settings.hub?.paired} run={async () => {
        try { setSetup(await client.call<CloudInfo>("cloud.info")); setLibrary(""); }
        catch { throw new Error("File sync setup is temporarily unavailable. Try again when your server is reachable."); }
      }}>Set up file sync</Action>}
      {canSetup && !state.settings.hub?.paired && <p className="muted">Use your server invitation on the Phone page before setting up file sync.</p>}
      {canSetup && setup && <div className="cloud-setup">
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
    <div className="cloud-folders">{[{folder:"Shared",title:"Shared",text:"Files you send between devices.",icon:Files},{folder:"Documents",title:"Documents",text:"A place for documents you want nearby.",icon:FileText}].map(({folder,title,text,icon:Icon}) => <Card key={folder} title={title}><Icon size={27} strokeWidth={1.25} /><p>{text}</p><Action className="text-button" run={() => client.call("cloud.open", {folder})}>Open folder<ArrowUpRight size={15} /></Action></Card>)}</div>
  </div>;
}
