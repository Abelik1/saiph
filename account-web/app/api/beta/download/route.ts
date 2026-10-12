// SPDX-License-Identifier: AGPL-3.0-or-later
import {getAuth0} from "../../../../lib/auth";
import {betaDownload} from "../../../../lib/beta";
import {downloadBeta} from "../../../../lib/beta-download-http.mjs";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function POST(request:Request) {
  return downloadBeta(request, {env:process.env,
    getSession:async () => (await getAuth0()?.getSession()) ?? null,
    download:betaDownload});
}
