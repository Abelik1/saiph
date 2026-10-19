// SPDX-License-Identifier: AGPL-3.0-or-later
import {NextResponse, type NextRequest} from "next/server";
import {getAuth0} from "../../../lib/auth";
export const dynamic = "force-dynamic";

/** "Continue with Google" on /trial: sign in and come back to /trial, which
 * starts the trial (lib/buy.mjs allows exactly this return path). */
export async function GET(request: NextRequest) {
  const auth0 = getAuth0();
  if (request.nextUrl.search) {
    return new NextResponse("Start your free trial on usesaiph.com.", {status: 400, headers: {"Cache-Control": "private, no-store"}});
  }
  if (!auth0) return NextResponse.redirect(new URL("/trial", request.nextUrl.origin));
  if (await auth0.getSession(request)) return NextResponse.redirect(new URL("/trial", process.env.APP_BASE_URL));
  return auth0.startInteractiveLogin({returnTo: "/trial"}, request);
}
