// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from "react";
import type { Client } from "./types";
import { Action, Card } from "./ui";

type Release = {schema: number; platform: string; profile: string; build: number; version: string; sha256: string; bytes: number};
type Check = {supported: boolean; available: boolean; release: Release | null};

export function Updates({ client, status }: { client: Client; status?: {state: string; code: string} }) {
  const [result, setResult] = useState<Check | null>(null);
  const [installing, setInstalling] = useState(false);
  return <Card title="Updates" subtitle="Keep this edition of Saiph up to date.">
    {status?.state === "failed" && <p className="inline-error" role="alert">The previous update did not finish. Your installed version is still available. Check for updates to try again.</p>}
    <p className="muted" role="status">{installing ? "Verifying your update. Saiph will close and reopen when installation finishes." : !result ? "Updates come from your paired Saiph server." : !result.supported ? "This development build uses its existing source update tools." : result.available ? `Saiph ${result.release?.version} is available.` : "You have the latest build available on your server."}</p>
    <Action disabled={installing} run={async () => setResult(await client.call<Check>("app.update.check"))}>Check for updates</Action>
    {result?.available && result.release && <Action className="primary" disabled={installing} run={async () => {
      setInstalling(true);
      try { await client.call("app.update.install", {release: result.release}); }
      catch (error) { setInstalling(false); throw error; }
    }}>Install update</Action>}
  </Card>;
}
