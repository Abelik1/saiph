// SPDX-License-Identifier: AGPL-3.0-or-later
import { useId, useState } from "react";
import { FileUp, Send } from "lucide-react";
import type { Client } from "./types";
import { Action, Form } from "./ui";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Textarea } from "@/components/ui/input";
import { Item, ItemActions, ItemContent } from "@/components/ui/item";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export type HandoffItem = { id: string; kind: "link" | "text" | "file"; value: string; file_id?: string; source: string; status: string };
/** Links, text and files to another device. `phoneId` is the phone a page already offers a file button for. */
export function Handoff({ items, devices, currentDeviceId, phoneId, client }: { items: HandoffItem[]; devices: { id: string; name: string; online?: boolean; capabilities?: string[] }[]; currentDeviceId?: string; phoneId?: string; client: Client }) {
  const [target, setTarget] = useState("");
  const [value, setValue] = useState("");
  const targetId = useId(), valueId = useId();
  const targets = devices.filter(device => device.id !== currentDeviceId && device.online && device.capabilities?.some(capability => capability === "handoff" || capability === "files"));
  const selected = targets.some(device => device.id === target) ? target : targets[0]?.id || "";
  const capabilities = targets.find(device => device.id === selected)?.capabilities || [];
  return <div className="grid gap-4">
    {targets.length > 0 && <Form className="grid gap-3" submit={async () => { await client.call("continuity.handoff", { target: selected, kind: /^https?:\/\//i.test(value) ? "link" : "text", value }); setValue(""); }}>
      <Field label="Send to" htmlFor={targetId}>
        <Select value={selected} onValueChange={setTarget}>
          <SelectTrigger id={targetId} className="max-w-72"><SelectValue /></SelectTrigger>
          <SelectContent>{targets.map(device => <SelectItem value={device.id} key={device.id}>{device.name}</SelectItem>)}</SelectContent>
        </Select>
      </Field>
      <Field label="Link or text" htmlFor={valueId}><Textarea id={valueId} value={value} maxLength={16000} onChange={e => setValue(e.target.value)} /></Field>
      <div className="flex flex-wrap gap-2"><Button type="submit" variant="tonal" disabled={!value.trim() || !capabilities.includes("handoff")}><Send />Send</Button>{selected !== phoneId && <Action variant="secondary" disabled={!capabilities.includes("files")} run={() => client.call("continuity.file.choose", { device_id: selected })}><FileUp />Send a file</Action>}</div>
    </Form>}
    {!items.length && <p className="m-0 text-[12.5px] text-muted-foreground">Links and text sent to this computer appear here.</p>}
    {items.slice(0, 20).map(item => <Item key={item.id} variant="outline" size="sm">
      <ItemContent><p className="m-0 text-[13px] text-foreground" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{item.value}</p></ItemContent>
      <ItemActions><Action variant="tonal" size="sm" run={() => client.call(item.kind === "text" ? "continuity.copy" : "continuity.open", { id: item.id })}>{item.kind === "text" ? "Copy" : "Open"}</Action><Action variant="ghost" size="sm" run={() => client.call("continuity.dismiss", { id: item.id })}>Dismiss</Action></ItemActions>
    </Item>)}
  </div>;
}
