// SPDX-License-Identifier: AGPL-3.0-or-later
import type { Client, State } from "./types";
import { Action, Card } from "./ui";

export function Enrollment({ state, client }: { state: State; client: Client }) {
  if (state.settings?.hub?.paired) return null;
  const invitation = state.enrollment;
  return <Card title="Welcome to Saiph" subtitle="Use a private invitation from your server to add this computer.">
    <p>Your devices share one private workspace. Setup keeps their keys on each device.</p>
    {invitation?.ready ? <>
      <p role="status">{invitation.approved ? "Waiting for your server. Pairing continues automatically while your invitation is valid." : "Your invitation is ready. Approve it to pair this computer."}</p>
      {state.components && !state.components.mesh_running && <>
        <p>Complete the secure connection once. Your operating system or browser may ask for approval.</p>
        <Action disabled={state.components.busy} run={() => state.components?.mesh_installed
          ? client.call("components.sign_in", {id:invitation.id}) : client.call("components.install")}>
          {state.components.mesh_installed ? "Continue browser sign-in" : "Install connection component"}
        </Action>
        <p className="muted" role="status">{state.components.message}</p>
      </>}
      {!invitation.approved && <Action run={() => client.call("enrollment.approve", { id: invitation.id })}>Use invitation</Action>}
      <Action className="text-button" run={() => client.call("enrollment.cancel", { id: invitation.id })}>Cancel</Action>
    </> : <Action run={() => client.call("enrollment.choose")}>Open server invitation</Action>}
    <p className="muted">Keep the invitation private. Your server can make a fresh one if it expires.</p>
  </Card>;
}
