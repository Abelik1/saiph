// SPDX-License-Identifier: AGPL-3.0-or-later
import type { Client, State } from "./types";
import { Action } from "./ui";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";

export function Enrollment({ state, client }: { state: State; client: Client }) {
  if (state.settings?.hub?.paired) return null;
  const invitation = state.enrollment;
  return <Card className="string-edge">
    <CardHeader>
      <CardTitle>Welcome to Saiph</CardTitle>
      <CardDescription>Use a private invitation from your server to add this computer.</CardDescription>
    </CardHeader>
    <CardContent className="grid justify-items-start gap-3 text-[13px] [&_p]:m-0">
    <p>Your devices share one private workspace. Setup keeps their keys on each device.</p>
    {invitation?.ready ? <>
      <p role="status">{invitation.approved ? "Waiting for your server. Pairing continues automatically while your invitation is valid." : "Your invitation is ready. Approve it to pair this computer."}</p>
      {state.components && !state.components.mesh_running && <>
        <p>Complete the secure connection once. Your operating system or browser may ask for approval.</p>
        <Action variant="default" disabled={state.components.busy} run={() => state.components?.mesh_installed
          ? client.call("components.sign_in", {id:invitation.id}) : client.call("components.install")}>
          {state.components.mesh_installed ? "Continue browser sign-in" : "Install connection component"}
        </Action>
        <p className="text-muted-foreground" role="status">{state.components.message}</p>
      </>}
      {!invitation.approved && <Action variant="default" run={() => client.call("enrollment.approve", { id: invitation.id })}>Use invitation</Action>}
      <Action className="text-button" run={() => client.call("enrollment.cancel", { id: invitation.id })}>Cancel</Action>
    </> : <Action variant="default" run={() => client.call("enrollment.choose")}>Open server invitation</Action>}
    </CardContent>
    <CardFooter><p className="m-0 text-[12.5px] text-muted-foreground">Keep the invitation private. Your server can make a fresh one if it expires.</p></CardFooter>
  </Card>;
}
