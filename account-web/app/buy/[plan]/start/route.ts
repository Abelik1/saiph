// SPDX-License-Identifier: AGPL-3.0-or-later
import {NextResponse, type NextRequest} from "next/server";
import {getAuth0} from "../../../../lib/auth";
import {buyPath, isPlan, offerValue} from "../../../../lib/buy.mjs";
import {methodParameters, signInMethod} from "../../../../lib/policy.mjs";
export const dynamic = "force-dynamic";

/** "Continue with Google" (or `?with=email`) on /buy/<plan>: start sign-in and come back to
 * that exact page (lib/buy.mjs), so the chosen plan reaches Stripe Checkout. */
export async function GET(request: NextRequest, {params}: {params: Promise<{plan: string}>}) {
  const {plan} = await params;
  const auth0 = getAuth0();
  const query = request.nextUrl.searchParams;
  const method = signInMethod(query, ["offer"]);
  const offer = offerValue(query.get("offer"));
  if (!isPlan(plan) || !method || (query.has("offer") && !offer)) {
    return new NextResponse("Choose a plan on usesaiph.com.", {status: 400, headers: {"Cache-Control": "private, no-store"}});
  }
  const returnTo = buyPath(plan, offer);
  if (!auth0) return NextResponse.redirect(new URL(returnTo, request.nextUrl.origin));
  if (await auth0.getSession(request)) return NextResponse.redirect(new URL(returnTo, process.env.APP_BASE_URL));
  return auth0.startInteractiveLogin({returnTo, authorizationParameters: methodParameters(method)}, request);
}
