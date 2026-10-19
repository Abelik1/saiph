// SPDX-License-Identifier: AGPL-3.0-or-later
import { useId, useState } from "react";
import type { Client } from "./types";
import { Action } from "./ui";
import { Field } from "@/components/ui/field";
import { Textarea } from "@/components/ui/input";
import { Disclosure } from "@/components/ui/disclosure";

type Inspected = { device_id: string; fingerprint: string };
type RequestCode = { code: string; fingerprint: string; root_fingerprint: string; expires_in: number };

/**
 * Join a Saiph account as another computer. Join as another computer asks Saiph
 * Cloud which computer is the account's main computer; pasting its code remains
 * as a fallback. Either way nothing is pinned until the owner compares the whole
 * fingerprint with the main computer's own screen, and the confirmation is bound
 * to that exact fingerprint. The main computer then approves in a pop-up.
 */
export function HostedJoin({ client, waiting }: { client: Client; waiting: boolean }) {
  const id = useId();
  const [code, setCode] = useState("");
  const [inspected, setInspected] = useState<Inspected | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [request, setRequest] = useState<RequestCode | null>(null);
  const [account, setAccount] = useState<Inspected | null>(null);
  const [accountConfirmed, setAccountConfirmed] = useState(false);
  const muted = "m-0 text-sm leading-relaxed text-muted-foreground";

  if (waiting || request) return <div className="grid gap-3" aria-label="Waiting for your main computer">
    <p className={muted}>
      Your main computer shows a pop-up to approve this computer while Saiph is open there. Check that every group of
      the security code it shows matches the one below before approving. If no pop-up appears, choose Add a device on
      its Phone page, or paste the request code there instead.
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

  const paste = <div className="grid gap-3">
    <p className={muted}>
      On your main computer, choose Add a device on its Phone page. Under the QR code, choose
      <b className="text-foreground"> Can't scan? Copy a code instead</b> and paste the computer code here. Sign in here with the same account.
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
        <Action variant="default" size="sm" disabled={!confirmed} run={async () => setRequest(await client.call<RequestCode>("hosted.join", { code: code.trim(), confirmed, fingerprint: inspected.fingerprint }))}>
          Join with this code
        </Action>
      </div>
    </>}
  </div>;

  return <div className="grid gap-3" aria-label="Join as another computer">
    {!account ? <>
      <p className={muted}>Sign in here with the account your main computer uses. Saiph finds your main computer; you then compare its security code.</p>
      <div><Action variant="default" size="sm" run={async () => { setAccount(await client.call<Inspected>("hosted.join.account.inspect")); setAccountConfirmed(false); }}>
        Join as another computer
      </Action></div>
    </> : <>
      <p className={muted}>
        Saiph Cloud says this is your main computer's security code. On your main computer, open Settings → Saiph Cloud,
        or Add a device on its Phone page, to see its code. Compare every group. Continue only if they all match.
      </p>
      <code className="text-[13px] break-words" aria-label="Main computer's security code">{account.fingerprint}</code>
      <label className="flex items-start gap-2 text-[13px]">
        <input type="checkbox" checked={accountConfirmed} onChange={(event) => setAccountConfirmed(event.target.checked)} />
        Every group matches my main computer
      </label>
      <div className="flex flex-wrap gap-2">
        <Action variant="default" size="sm" disabled={!accountConfirmed}
          run={async () => setRequest(await client.call<RequestCode>("hosted.join.account", { fingerprint: account.fingerprint, confirmed: true }))}>
          Trust and ask to join
        </Action>
        <Action variant="ghost" size="sm" run={async () => { setAccount(null); setAccountConfirmed(false); }}>Cancel</Action>
      </div>
    </>}
    <Disclosure summary="Paste the main computer's code instead">{paste}</Disclosure>
  </div>;
}
