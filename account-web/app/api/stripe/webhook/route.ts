// SPDX-License-Identifier: AGPL-3.0-or-later
import {webhook} from "../../../../lib/billing/http";
import {dependencies} from "../../../../lib/billing/runtime";
export const runtime="nodejs";
export const dynamic="force-dynamic";
export const maxDuration=30;
export async function POST(request:Request) {return webhook(request,dependencies());}
