// SPDX-License-Identifier: AGPL-3.0-or-later
import type { Client, HostedState } from "./types";
import { Action } from "./ui";
import { Disclosure } from "@/components/ui/disclosure";

/** One explicit sign-in action selects the bundled connection before opening the browser. */
export async function signInToSaiph(client: Client, hosted: HostedState, google = true) {
  if (!hosted.enabled) await client.call("hosted.enable", { enabled: true });
  // Turning Hosted back on keeps an existing sign-in; only open the browser when it is needed.
  if (hosted.account?.status !== "signed_in") await client.call("hosted.sign_in", { google });
}

export function HostedSignIn({ client, hosted }: { client: Client; hosted: HostedState }) {
  const signingIn = hosted.account?.status === "signing_in";
  return <>
    <p>{signingIn ? "Finish signing in in your browser, then return to Saiph." : "Use the same Saiph account on your phone and computer."}</p>
    {!signingIn && !hosted.identity && <p className="muted">New to Saiph Cloud? Start your free trial (no card needed) or subscribe on the Saiph website with the account you sign in with here.</p>}
    <Action variant="default" disabled={!hosted.configured || signingIn || hosted.self_hosted_paired}
      run={() => signInToSaiph(client, hosted)}>{signingIn ? "Waiting for sign-in…" : "Continue with Google"}</Action>
    {!signingIn && <Disclosure className="mt-3" summary="Other sign-in options">
      <p>Use your original sign-in method to keep the same account.</p>
      <Action disabled={!hosted.configured || hosted.self_hosted_paired} run={() => signInToSaiph(client, hosted, false)}>Use email or another provider</Action>
    </Disclosure>}
  </>;
}
