// SPDX-License-Identifier: AGPL-3.0-or-later
import {NextResponse, type NextRequest} from "next/server";
import {getAuth0} from "../../../../lib/auth";
export const dynamic = "force-dynamic";

/** "Sign in to continue" on /account/delete: sign in and come straight back to
 * that page (lib/buy.mjs allows exactly this return path), never the account
 * overview, so the way in from the app shows no plans or prices. */
export async function GET(request: NextRequest) {
  if (request.nextUrl.search) {
    return new NextResponse("Start from the account deletion page.", {status: 400, headers: {"Cache-Control": "private, no-store"}});
  }
  const auth0 = getAuth0();
  if (!auth0) return NextResponse.redirect(new URL("/account/delete", request.nextUrl.origin));
  if (await auth0.getSession(request)) return NextResponse.redirect(new URL("/account/delete", process.env.APP_BASE_URL));
  return auth0.startInteractiveLogin({returnTo: "/account/delete"}, request);
}
