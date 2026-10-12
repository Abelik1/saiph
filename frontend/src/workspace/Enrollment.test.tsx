// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Enrollment } from "./Enrollment";
import type { Client, State } from "./types";

describe("Private server enrollment", () => {
  it("opens an invitation and requires a separate approval without showing networking details", async () => {
    const call = vi.fn().mockResolvedValue({});
    const client = { call } as unknown as Client;
    const state = { settings: { hub: { paired: false } } } as State;
    const view = render(<Enrollment state={state} client={client} />);
    fireEvent.click(screen.getByRole("button", { name: "Open server invitation" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("enrollment.choose"));
    expect(call).not.toHaveBeenCalledWith("enrollment.approve", expect.anything());
    view.rerender(<Enrollment state={{ ...state, enrollment: {ready:true,id:"invite",expires_at:null,custom_mesh:false} }} client={client} />);
    fireEvent.click(screen.getByRole("button", { name: "Use invitation" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("enrollment.approve", { id: "invite" }));
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button", {name:/Connect|Refresh|Sync/})).toBeNull();
  });
  it("leaves an already paired computer's workspace visible", () => {
    const state = { settings: { hub: { paired: true } } } as State;
    const view = render(<Enrollment state={state} client={{call:vi.fn()} as unknown as Client} />);
    expect(view.container).toBeEmptyDOMElement();
  });
});
