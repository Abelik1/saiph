// SPDX-License-Identifier: AGPL-3.0-or-later
import { useId, useState } from "react";
import type { Client } from "./types";
import { Action } from "./ui";
import { Field } from "@/components/ui/field";
import { Textarea } from "@/components/ui/input";

type Inspected = { device_id: string; fingerprint: string };
type RequestCode = { code: string; fingerprint: string; root_fingerprint: string; expires_in: number };

/**
 * Join a Saiph account as another computer. The main computer's code is pinned
 * only after the owner compares its whole fingerprint; the main computer then
 * approves this computer's request code. Joining alone grants nothing.
 */
export function HostedJoin({ client, waiting }: { client: Client; waiting: boolean }) {
  const id = useId();
  const [code, setCode] = useState("");
  const [inspected, setInspected] = useState<Inspected | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [request, setRequest] = useState<RequestCode | null>(null);
  const muted = "m-0 text-[12.5px] leading-relaxed text-muted-foreground";

  if (waiting || request) return <div className="grid gap-3" aria-label="Waiting for your main computer">
    <p className={muted}>
      Open Saiph on your main computer: this computer appears there by itself under Settings → Saiph account.
      Check that every group of the fingerprint it shows matches the one below before approving. If it does not appear,
      paste the request code there instead.
    </p>
    {request ? <>
      <Field label="Request code for your main computer" htmlFor={id + "-request"}>
        <Textarea id={id + "-request"} readOnly value={request.code} rows={4} onFocus={(event) => event.currentTarget.select()} />
      </Field>
      <p className={muted}>This computer's fingerprint</p>
      <code className="text-[13px] break-words">{request.fingerprint}</code>
      <p className={muted}>The code expires in {Math.round(request.expires_in / 60)} minutes. Show a new one if it runs out.</p>
    </> : <p className={muted}>This computer has asked to join and is waiting for approval.</p>}
    <div><Action variant="tonal" size="sm" run={async () => setRequest(await client.call<RequestCode>("hosted.join.request"))}>
      {request ? "Show a new request code" : "Show request code"}
    </Action></div>
  </div>;

  return <div className="grid gap-3" aria-label="Join as another computer">
    <p className={muted}>
      Already using Saiph Hosted on another computer? On that main computer, open Settings → Saiph Hosted, choose
      <b className="text-foreground"> Show root approval code</b> and paste the code here. Sign in here with the same account.
    </p>
    <Field label="Main computer's code" htmlFor={id + "-root"}>
      <Textarea id={id + "-root"} value={code} rows={3} spellCheck={false}
        onChange={(event) => { setCode(event.target.value); setInspected(null); setConfirmed(false); }} />
    </Field>
    {!inspected ? <div>
      <Action variant="tonal" size="sm" disabled={!code.trim()} run={async () => { setInspected(await client.call<Inspected>("hosted.join.inspect", { code: code.trim() })); setConfirmed(false); }}>
        Check code
      </Action>
    </div> : <>
      <p className={muted}>Compare every group of this fingerprint with your main computer's screen:</p>
      <code className="text-[13px] break-words">{inspected.fingerprint}</code>
      <label className="flex items-start gap-2 text-[13px]">
        <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
        The whole fingerprint matches my main computer
      </label>
      <div>
        <Action variant="default" size="sm" disabled={!confirmed} run={async () => setRequest(await client.call<RequestCode>("hosted.join", { code: code.trim(), confirmed }))}>
          Join as another computer
        </Action>
      </div>
    </>}
  </div>;
}
