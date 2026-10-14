// SPDX-License-Identifier: AGPL-3.0-or-later
// Design preview: the real app shell on synthetic data, for `npm run dev` only.
// Open /preview.html. Not part of the production build.
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../index.css";
import App from "../App.tsx";
import { fixtureClient } from "./fixture";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App providedClient={fixtureClient()} />
  </StrictMode>,
);
