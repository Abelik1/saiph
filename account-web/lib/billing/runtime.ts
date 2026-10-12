// SPDX-License-Identifier: AGPL-3.0-or-later
import "server-only";
import {getAuth0} from "../auth";
import {withBillingStore} from "./db";
import {createStripe} from "./service";
import type {Dependencies} from "./http";
export function dependencies():Dependencies {
  return {env:process.env,createStripe,withStore:withBillingStore,getSession:async()=>getAuth0()?.getSession() ?? null};
}
