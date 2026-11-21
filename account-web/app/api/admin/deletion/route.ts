// SPDX-License-Identifier: AGPL-3.0-or-later
import {adminDeletionAction,deletionRateLimit} from "../../../../lib/billing/deletion";
import {dependencies} from "../../../../lib/billing/runtime";
export const runtime="nodejs";
export const dynamic="force-dynamic";
const allow=deletionRateLimit();
export async function POST(request:Request) {return adminDeletionAction(request,{...dependencies(),allow});}
