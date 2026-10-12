// SPDX-License-Identifier: AGPL-3.0-or-later
import {getAuth0} from "../../../../lib/auth";
import {redeemBeta} from "../../../../lib/beta-http.mjs";
import {betaCall} from "../../../../lib/beta";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function POST(request:Request) {
  return redeemBeta(request, {env:process.env,
    getSession:async () => (await getAuth0()?.getSession()) ?? null,
    call:(_path:string, code?:string) => betaCall("/v1/beta/redeem", code)});
}
