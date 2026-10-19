// SPDX-License-Identifier: AGPL-3.0-or-later
import {NextResponse, type NextRequest} from "next/server";
import {getAuth0} from "../../../../lib/auth";
import {buyPath, isPlan, offerValue} from "../../../../lib/buy.mjs";
export const dynamic = "force-dynamic";

/** "Continue with Google" on /buy/<plan>: start sign-in and come back to that
 * exact page (lib/buy.mjs), so the chosen plan reaches Stripe Checkout. */
export async function GET(request: NextRequest, {params}: {params: Promise<{plan: string}>}) {
  const {plan} = await params;
  const auth0 = getAuth0();
  const keys = [...request.nextUrl.searchParams.keys()];
  const offer = offerValue(request.nextUrl.searchParams.get("offer"));
  if (!isPlan(plan) || keys.some(key => key !== "offer") || (keys.length > 0 && !offer)) {
    return new NextResponse("Choose a plan on usesaiph.com.", {status: 400, headers: {"Cache-Control": "private, no-store"}});
  }
  const returnTo = buyPath(plan, offer);
  if (!auth0) return NextResponse.redirect(new URL(returnTo, request.nextUrl.origin));
  if (await auth0.getSession(request)) return NextResponse.redirect(new URL(returnTo, process.env.APP_BASE_URL));
  return auth0.startInteractiveLogin({returnTo}, request);
}
