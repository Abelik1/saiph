// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from "react";
import type { Client, DeskflowConfig, DeskflowStatus, Settings } from "./types";
import { Action, Card, Form } from "./ui";

export function DeskflowSettings({ settings, error, status, client, defaultEnabled = true }: { settings: Settings; error?: string; status?: DeskflowStatus; client: Client; defaultEnabled?: boolean }) {
  const [config, setConfig] = useState<DeskflowConfig>(() => ({
    enabled: defaultEnabled,
    role: navigator.platform.startsWith("Win") ? "desktop" : "laptop",
    desktop: "100.64.0.2",
    ...settings.link?.deskflow,
  }));
  const text = (key: "desktop" | "local" | "certificate" | "executable", value: string) =>
    setConfig(current => ({ ...current, [key]: value }));

  const setup = status?.setup;
  const saved = settings.link?.deskflow;
  const certificate = config.certificate || (setup?.certificates.length === 1 ? setup.certificates[0] : "");
  const local = config.local || (setup?.mesh_addresses.length === 1 ? setup.mesh_addresses[0] : "");
  const checks: [string, boolean, string][] = setup ? [
    ["Deskflow installed", !!setup.executable, setup.executable || "Install upstream Deskflow, or enter its core executable below."],
    ["Certificate", !!certificate, certificate || (setup.certificates.length > 1 ? "Several certificates found; enter the one Deskflow uses." : "Open the Deskflow GUI once to create it.")],
    ["Peer fingerprint approved", setup.trusted, setup.trusted ? "Trust file found" : "Approve the other computer's fingerprint in the Deskflow GUI (" + setup.trust_file + ")."],
    ["Mesh address", !!local || config.role === "laptop", local || (config.role === "laptop" ? "Not needed for the laptop" : "Join the mesh, or enter this computer's mesh address.")],
    ["Running", !!status?.running, status?.running ? "Sharing is running" : saved?.enabled ? "Waiting to start" : "Off"],
  ] : [];
  return <Card title="Keyboard and mouse sharing" subtitle="Deskflow setup for this computer. Saiph resumes sharing automatically after setup.">
    <p role="status" className={error && config.enabled !== false ? "inline-error" : "muted"}>
      {config.enabled === false ? "Sharing is switched off in these preferences." : error || "Connection has not been verified here. Test moving the pointer between both computers after setup."}
    </p>
    {checks.length > 0 && <ul className="setup-checklist" aria-label="Deskflow setup checks">
      {checks.map(([label, done, detail]) => <li key={label} className={done ? "done" : "pending"}><b>{done ? "✓" : "○"} {label}</b> <small>{detail}</small></li>)}
    </ul>}
    {setup && (setup.certificates.length === 1 && !config.certificate || setup.mesh_addresses.length === 1 && !config.local && config.role === "desktop") &&
      <button type="button" className="text-button" onClick={() => setConfig(current => ({ ...current,
        ...(setup.certificates.length === 1 && !current.certificate ? { certificate: setup.certificates[0] } : {}),
        ...(setup.mesh_addresses.length === 1 && !current.local && current.role === "desktop" ? { local: setup.mesh_addresses[0] } : {}) }))}>Use detected settings</button>}
    {saved?.enabled && <Action className="text-button" run={() => client.call("deskflow.restart")}>Restart sharing</Action>}
    <Form successMessage="Sharing preferences saved." submit={() => {
      const saved = { ...config };
      if (!saved.local) delete saved.local;
      if (!saved.executable) delete saved.executable;
      return client.call("settings.save", { link: { deskflow: saved } });
    }}>
      <label className="check"><input type="checkbox" checked={config.enabled !== false} onChange={event => setConfig(current => ({ ...current, enabled: event.target.checked }))} />Share keyboard and mouse</label>
      <label>This computer's role<select value={config.role} onChange={event => setConfig(current => ({ ...current, role: event.target.value as DeskflowConfig["role"] }))}><option value="desktop">Desktop · keyboard and mouse host</option><option value="laptop">Laptop · follows the desktop</option></select></label>
      <label>Desktop mesh address<input value={config.desktop || ""} placeholder="100.64.0.2" maxLength={64} required={config.enabled !== false} onChange={event => text("desktop", event.target.value)} /></label>
      <label>This computer's mesh address<input value={config.local ?? (config.role === "desktop" ? "100.64.0.2" : "")} placeholder={config.role === "desktop" ? "100.64.0.2" : "Optional for the laptop"} maxLength={64} onChange={event => text("local", event.target.value)} /></label>
      <label>Existing Deskflow certificate path<input value={config.certificate || ""} placeholder="Certificate path shown in Deskflow settings" maxLength={4096} onChange={event => text("certificate", event.target.value)} /></label>
      <label>Deskflow core executable<input value={config.executable || ""} placeholder="Find installed or Saiph portable Deskflow" maxLength={4096} onChange={event => text("executable", event.target.value)} /></label>
      <button>Save sharing preferences</button>
    </Form>
    <details><summary>One-time certificate trust setup</summary>
      <p>Switch sharing off here and save before setup. Open the upstream Deskflow GUI on both computers; it generates its certificate automatically. Set the desktop as server and laptop as client, using the mesh addresses above and computer names desktop and laptop. Bind the server to its mesh address. Keep TLS and peer fingerprint checks enabled, and turn Deskflow clipboard sharing off.</p>
      <p>Start sharing in that GUI once. Compare each peer's SHA-256 fingerprint with the fingerprint displayed on the other computer before accepting it. Stop sharing and quit both GUIs after trust is saved, then save each existing certificate path here.</p>
      <p>On Linux, copy the GUI's approved trusted-servers and trusted-clients files from its tls folder into deskflow/tls in Saiph's data folder. Windows normally shares C:\ProgramData\Deskflow\tls; if Deskflow uses a portable settings folder, copy its approved trust files into Saiph's deskflow/tls instead. Keep certificate files private.</p>
      <p className="muted">The complete platform paths and upstream source links are in docs/ORION_DESKFLOW.md. After setup, Saiph supervises Deskflow automatically; moving to the right of the desktop enters the laptop.</p>
    </details>
  </Card>;
}
