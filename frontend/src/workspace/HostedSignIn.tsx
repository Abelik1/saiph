// SPDX-License-Identifier: AGPL-3.0-or-later
import type { Client, HostedState } from "./types";
import { Action } from "./ui";

export type SignInMethod = "google" | "email";

/** One explicit sign-in action selects the bundled connection before opening the browser:
 * Google opens Google's account chooser, email opens the email-and-password form. */
export async function signInToSaiph(client: Client, hosted: HostedState, method: SignInMethod = "google") {
  if (!hosted.enabled) await client.call("hosted.enable", { enabled: true });
  // Turning Hosted back on keeps an existing sign-in; only open the browser when it is needed.
  if (hosted.account?.status !== "signed_in") await client.call("hosted.sign_in", method === "email" ? { email: true } : { google: true });
}

export function HostedSignIn({ client, hosted }: { client: Client; hosted: HostedState }) {
  const signingIn = hosted.account?.status === "signing_in";
  const blocked = !hosted.configured || signingIn || hosted.self_hosted_paired;
  return <>
    <p>{signingIn ? "Finish signing in in your browser, then return to Saiph." : "Use the same Saiph account on your phone and computer."}</p>
    {!signingIn && !hosted.identity && <p className="muted">New to Saiph Cloud? Start a 14-day free trial with a card, then €9.99/month unless you cancel. Use the Saiph website with the account you sign in with here.</p>}
    <div className="grid gap-2">
      <Action variant="default" disabled={blocked} run={() => signInToSaiph(client, hosted)}>{signingIn ? "Waiting for sign-in…" : "Continue with Google"}</Action>
      {!signingIn && <Action variant="secondary" disabled={blocked} run={() => signInToSaiph(client, hosted, "email")}>Continue with email</Action>}
    </div>
    {!signingIn && <p className="muted">Use the same choice on every device to keep one account.</p>}
  </>;
}
