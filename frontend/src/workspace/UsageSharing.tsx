// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from "react";
import type { Client, UsageBatch, UsageState } from "./types";
import { Action, Card, Modal } from "./ui";

/** The plain-language agreement shown in setup, in the one-time prompt and in Settings. */
export function UsageExplanation() {
  return <>
    <p>Saiph can send anonymous counts of which features you use, once a day, so we know what to improve. It's off unless you agree.</p>
    <ul className="usage-terms">
      <li><b>Sent:</b> which features and screens were used that day, in rough ranges (like "2–5 times"), the app version, Windows or Linux, and how far setup got.</li>
      <li><b>Never sent:</b> your messages, notifications, clipboard, files, contacts, phone numbers, names, app names or anything you type. No account or device ID is attached.</li>
      <li>You can see every batch before it's sent and change your mind any time in Settings. Turning it off deletes the counts on this computer.</li>
    </ul>
  </>;
}

/** The two choices, equally prominent; nothing is pre-selected. */
export function UsageChoice({ client, onDone }: { client: Client; onDone?: () => void }) {
  const choose = (granted: boolean) => async () => { await client.call("usage.consent", { granted }); onDone?.(); };
  return <div className="actions usage-choice">
    <Action run={choose(true)}>Share anonymous usage</Action>
    <Action run={choose(false)}>Don't share</Action>
  </div>;
}

/** Asked once for people who set Saiph up before this choice existed. Closing asks again next time. */
export function UsagePrompt({ client }: { client: Client }) {
  const [open, setOpen] = useState(true);
  if (!open) return null;
  return <Modal title="Help improve Saiph?" close={() => setOpen(false)}>
    <UsageExplanation />
    <UsageChoice client={client} onDone={() => setOpen(false)} />
  </Modal>;
}

function Batch({ batch }: { batch: UsageBatch }) {
  return <pre className="usage-batch" aria-label={"Usage batch for " + batch.day}>{JSON.stringify(batch, null, 2)}</pre>;
}

/** Settings card: the current choice, a switch, and exactly what is sent. */
export function UsageSettings({ usage, client }: { usage?: UsageState; client: Client }) {
  if (!usage?.available) return null;
  const granted = usage.consent === "granted";
  return <Card title="Anonymous usage statistics" subtitle={granted ? "On: anonymous daily counts are shared." : "Off: nothing is counted or sent."}>
    <UsageExplanation />
    <Action run={() => client.call("usage.consent", { granted: !granted })}>{granted ? "Stop sharing and delete local counts" : "Share anonymous usage"}</Action>
    {granted && <details>
      <summary>See what Saiph sends</summary>
      {usage.pending.length ? <><p className="muted">Waiting to be sent:</p>{usage.pending.map((batch) => <Batch key={batch.day} batch={batch} />)}</>
        : <p className="muted">Nothing is waiting. Today's counts are sent after the day ends.</p>}
      {usage.last_sent && <><p className="muted">Last sent:</p><Batch batch={usage.last_sent} /></>}
    </details>}
  </Card>;
}
