// SPDX-License-Identifier: AGPL-3.0-or-later
import type { ComponentType } from "react";
import type { Client, Page, State } from "./types";

export type WorkspaceProps = { state: State; client: Client; page: Page; navigate: (page: Page) => void };

// The private Workspace add-on replaces this file in its own build. Saiph is Link only.
export const Workspace: ComponentType<WorkspaceProps> | null = null;
