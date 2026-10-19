// SPDX-License-Identifier: AGPL-3.0-or-later
import type { Client, HostedAccess } from "./types";
import { Action } from "./ui";
import { Badge } from "@/components/ui/badge";

/** Free trial days left, or why Cloud is paused, with a way to subscribe. Wording only:
 * the service decides access, and a subscription reconnects on the next check. */
export function CloudAccessNotice({access, client}: {access?: HostedAccess | null; client: Client}) {
  if (!access || access.state === "active" || !access.message) return null;
  const ended = access.state !== "trial";
  return <div className="grid gap-2" role={ended ? "alert" : "status"} aria-label="Saiph Cloud access">
    <p className="m-0">
      <Badge tone={ended ? "attention" : "good"}>
        {access.state === "trial" ? `Free trial · ${access.days_left} day${access.days_left === 1 ? "" : "s"} left`
          : access.state === "trial_ended" ? "Free trial ended" : "No Cloud access"}
      </Badge>
    </p>
    <p className="m-0">{access.message}</p>
    <div className="flex flex-wrap items-center gap-3">
      <Action variant={ended ? "default" : "tonal"} run={() => client.call("help.open", {link: "plans"})}>
        {access.state === "none" ? "Start free trial or subscribe" : "Subscribe"}
      </Action>
    </div>
  </div>;
}
