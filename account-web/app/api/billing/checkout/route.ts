// SPDX-License-Identifier: AGPL-3.0-or-later
import {ownerAction} from "../../../../lib/billing/http";
import {dependencies} from "../../../../lib/billing/runtime";
export const runtime="nodejs";
export const dynamic="force-dynamic";
export async function POST(request:Request) {return ownerAction(request,"checkout",dependencies());}
