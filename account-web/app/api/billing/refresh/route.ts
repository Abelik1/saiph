// SPDX-License-Identifier: AGPL-3.0-or-later
import {refresh} from "../../../../lib/billing/http";
import {dependencies} from "../../../../lib/billing/runtime";
export const runtime="nodejs";
export const dynamic="force-dynamic";
export const maxDuration=60;
// Vercel Cron sends Authorization: Bearer CRON_SECRET; no browser session is used.
export async function GET(request:Request) {return refresh(request,dependencies());}
