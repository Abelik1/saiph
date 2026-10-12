// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from "react";
import type { Client } from "./types";
import { Action, Card, Empty, Form } from "./ui";

export type HandoffItem = { id: string; kind: "link" | "text" | "file"; value: string; file_id?: string; source: string; status: string };
export function Handoff({ items, devices, currentDeviceId, client }: { items: HandoffItem[]; devices: { id: string; name: string; online?: boolean; capabilities?: string[] }[]; currentDeviceId?: string; client: Client }) {
  const [target, setTarget] = useState("");
  const [value, setValue] = useState("");
  const targets = devices.filter(device => device.id !== currentDeviceId && device.online && device.capabilities?.some(capability => capability === "handoff" || capability === "files"));
  const selected = targets.some(device => device.id === target) ? target : targets[0]?.id || "";
  const capabilities = targets.find(device => device.id === selected)?.capabilities || [];
  return <Card title="Continue on another device" subtitle="Links, files and text you choose to share.">
    {targets.length > 0 && <Form submit={async () => { await client.call("continuity.handoff", { target: selected, kind: /^https?:\/\//i.test(value) ? "link" : "text", value }); setValue(""); }}>
      <label>Send to<select value={selected} onChange={e => setTarget(e.target.value)}>{targets.map(device => <option value={device.id} key={device.id}>{device.name}</option>)}</select></label>
      <label>Link or text<textarea value={value} maxLength={16000} onChange={e => setValue(e.target.value)} /></label>
      <div className="actions"><button disabled={!value.trim() || !capabilities.includes("handoff")}>Send</button><Action disabled={!capabilities.includes("files")} run={() => client.call("continuity.file.choose", { device_id: selected })}>Send a file</Action></div>
    </Form>}
    {!items.length && <Empty title="Ready when you are">Share a link, file or text to continue here.</Empty>}
    {items.slice(0, 20).map(item => <article className="notification-item" key={item.id}>
      <p style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{item.value}</p>
      <div className="actions"><Action run={() => client.call(item.kind === "text" ? "continuity.copy" : "continuity.open", { id: item.id })}>{item.kind === "text" ? "Copy" : "Open"}</Action><Action run={() => client.call("continuity.dismiss", { id: item.id })}>Dismiss</Action></div>
    </article>)}
  </Card>;
}
