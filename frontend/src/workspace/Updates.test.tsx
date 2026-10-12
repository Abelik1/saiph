// SPDX-License-Identifier: AGPL-3.0-or-later
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Updates } from "./Updates";
import type { Client } from "./types";

const release = {schema: 1, platform: "windows-x86_64", profile: "link", build: 2, version: "0.1.1", sha256: "a".repeat(64), bytes: 100};
function client(answer: unknown) { return {call: vi.fn().mockResolvedValue(answer), subscribe: () => () => {}} as unknown as Client; }

describe("packaged updates", () => {
  it("reports an interrupted update without displaying raw failure details", () => {
    const api = client({});
    render(<Updates client={api} status={{state:"failed",code:"install_failed"}} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Your installed version is still available");
    expect(api.call).not.toHaveBeenCalled();
  });
  it("checks first and installs only after a separate deliberate action", async () => {
    const api = client({supported:true,available:true,release});
    render(<Updates client={api} />);
    expect(api.call).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", {name:"Check for updates"}));
    expect(await screen.findByText("Saiph 0.1.1 is available.")).toBeVisible();
    expect(api.call).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", {name:"Install update"}));
    expect(api.call).toHaveBeenLastCalledWith("app.update.install", {release});
  });
  it("does not offer installation when the server has no newer release", async () => {
    render(<Updates client={client({supported:true,available:false,release:null})} />);
    await userEvent.click(screen.getByRole("button", {name:"Check for updates"}));
    expect(await screen.findByText("You have the latest build available on your server.")).toBeVisible();
    expect(screen.queryByRole("button", {name:"Install update"})).not.toBeInTheDocument();
  });
  it("explains development builds without offering a packaged install", async () => {
    render(<Updates client={client({supported:false,available:false,release:null})} />);
    await userEvent.click(screen.getByRole("button", {name:"Check for updates"}));
    expect(await screen.findByText("This development build uses its existing source update tools.")).toBeVisible();
    expect(screen.queryByRole("button", {name:"Install update"})).not.toBeInTheDocument();
  });
});
