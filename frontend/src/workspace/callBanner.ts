// SPDX-License-Identifier: AGPL-3.0-or-later
import { createContext } from "react";

/** True where the app shows its own bar for a ringing call, so a page shows the call without repeating its buttons. */
export const CallBanner = createContext(false);
