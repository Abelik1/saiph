// SPDX-License-Identifier: AGPL-3.0-or-later
import {adminTrialAction} from "../../../../lib/billing/admin";
import {dependencies} from "../../../../lib/billing/runtime";
export const runtime="nodejs";
export const dynamic="force-dynamic";
export async function POST(request:Request) {return adminTrialAction(request,dependencies());}
