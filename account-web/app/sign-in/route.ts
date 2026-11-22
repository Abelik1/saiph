// SPDX-License-Identifier: AGPL-3.0-or-later
import {NextResponse, type NextRequest} from "next/server";
import {getAuth0} from "../../lib/auth";
import {methodParameters, signInMethod} from "../../lib/policy.mjs";
export const dynamic = "force-dynamic";

/** "Continue with email" on the home page. /auth/login refuses every query (proxy.ts),
 * so the email method starts here instead; it always returns to /account. */
export async function GET(request: NextRequest) {
  const method = signInMethod(request.nextUrl.searchParams);
  if (!method) {
    return new NextResponse("Start sign-in from the account page.", {status: 400, headers: {"Cache-Control": "private, no-store"}});
  }
  const auth0 = getAuth0();
  if (!auth0) return NextResponse.redirect(new URL("/", request.nextUrl.origin));
  if (await auth0.getSession(request)) return NextResponse.redirect(new URL("/account", process.env.APP_BASE_URL));
  return auth0.startInteractiveLogin({returnTo: "/account", authorizationParameters: methodParameters(method)}, request);
}
