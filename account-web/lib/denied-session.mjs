// SPDX-License-Identifier: AGPL-3.0-or-later
import {isAccountCookie} from "./policy.mjs";
/** Remove newly written SDK sessions from a denied callback response.
 * @param {import("next/server").NextResponse} response */
export function expireDeniedSessionCookies(response) {
  for (const cookie of response.cookies.getAll()) {
    if (isAccountCookie(cookie.name)) response.cookies.set({name: cookie.name, value: "", path: "/",
      secure: true, httpOnly: true, sameSite: "lax", expires: new Date(0)});
  }
}
