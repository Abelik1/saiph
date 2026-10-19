// SPDX-License-Identifier: AGPL-3.0-or-later
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Updates } from "./Updates";
import type { Client } from "./types";

const release = {schema: 1, platform: "windows-x86_64", profile: "link", build: 2, version: "0.1.1", sha256: "a".repeat(64), bytes: 58_000_000};
function client(answers: Record<string, unknown>) {
  const call = vi.fn(async (method: string) => {
    if (!(method in answers)) throw new Error("unexpected " + method);
    const answer = answers[method];
    return typeof answer === "function" ? (answer as () => unknown)() : answer;
  });
  return {call, subscribe: () => () => {}} as unknown as Client & {call: typeof call};
}

describe("packaged updates", () => {
  it("explains a Saiph account that offers no desktop updates yet, without a download", async () => {
    const api = client({"app.update.check": {supported:false,available:false,release:null,reason:"cloud_unavailable"}});
    render(<Updates client={api} cloud />);
    expect(screen.getByText("Updates come from your Saiph account.")).toBeVisible();
    await userEvent.click(screen.getByRole("button", {name:"Check for updates"}));
    expect(await screen.findByText(/doesn't offer desktop updates yet/)).toBeVisible();
    expect(screen.queryByRole("button", {name:/Download update/})).not.toBeInTheDocument();
  });
  it("asks a signed-out Saiph account to sign in", async () => {
    render(<Updates client={client({"app.update.check": {supported:false,available:false,release:null,reason:"cloud_signed_out"}})} cloud />);
    await userEvent.click(screen.getByRole("button", {name:"Check for updates"}));
    expect(await screen.findByText("Sign in to your Saiph account to check for updates.")).toBeVisible();
  });
  it("reports an interrupted update without displaying raw failure details", () => {
    const api = client({});
    render(<Updates client={api} status={{state:"failed",code:"install_failed"}} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Your installed version is still available");
    expect(api.call).not.toHaveBeenCalled();
  });
  it("shows what's new, downloads with progress, and restarts only after a separate action", async () => {
    let finish: (value: unknown) => void = () => {};
    const api = client({
      "app.update.check": {supported:true,available:true,release,notes:"Faster photo sync.",source:"cloud"},
      "app.update.download": () => new Promise(resolve => { finish = resolve; }),
      "app.update.progress": {state:"downloading",done:29_000_000,total:58_000_000},
      "app.update.restart": {started:true},
    });
    render(<Updates client={api} cloud />);
    expect(api.call).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", {name:"Check for updates"}));
    expect(await screen.findByText("Saiph 0.1.1 is available.")).toBeVisible();
    expect(screen.getByText("Faster photo sync.")).toBeVisible();
    await userEvent.click(screen.getByRole("button", {name:"Download update (58 MB)"}));
    expect(api.call).toHaveBeenCalledWith("app.update.download", {release});
    expect(await screen.findByText(/Downloading… 50% \(29 MB of 58 MB\)/)).toBeVisible();
    expect(screen.getByRole("progressbar", {name:"Download progress"})).toBeVisible();
    expect(screen.queryByRole("button", {name:"Restart to update"})).not.toBeInTheDocument();
    finish({staged:true,version:"0.1.1"});
    expect(await screen.findByText(/0.1.1 is downloaded and verified/)).toBeVisible();
    expect(api.call).not.toHaveBeenCalledWith("app.update.restart");
    await userEvent.click(screen.getByRole("button", {name:"Restart to update"}));
    expect(api.call).toHaveBeenLastCalledWith("app.update.restart");
    expect(await screen.findByText(/Saiph will close and reopen/)).toBeVisible();
  });
  it("returns to the offer when a download fails verification", async () => {
    const api = client({
      "app.update.check": {supported:true,available:true,release,source:"hub"},
      "app.update.download": () => Promise.reject(new Error("Desktop update could not be verified.")),
      "app.update.progress": {state:"failed",done:0,total:0},
    });
    render(<Updates client={api} />);
    await userEvent.click(screen.getByRole("button", {name:"Check for updates"}));
    await userEvent.click(await screen.findByRole("button", {name:/Download update/}));
    expect(await screen.findByRole("button", {name:/Download update/})).toBeEnabled();
    expect(screen.queryByRole("button", {name:"Restart to update"})).not.toBeInTheDocument();
  });
  it("does not offer a download when there is no newer release", async () => {
    render(<Updates client={client({"app.update.check": {supported:true,available:false,release:null,source:"hub"}})} />);
    await userEvent.click(screen.getByRole("button", {name:"Check for updates"}));
    expect(await screen.findByText("You have the latest build available on your server.")).toBeVisible();
    expect(screen.queryByRole("button", {name:/Download update/})).not.toBeInTheDocument();
  });
  it("says a Saiph account computer is current", async () => {
    render(<Updates client={client({"app.update.check": {supported:true,available:false,release,source:"cloud"}})} cloud />);
    await userEvent.click(screen.getByRole("button", {name:"Check for updates"}));
    expect(await screen.findByText("You have the latest version.")).toBeVisible();
  });
  it("explains development builds without offering a packaged install", async () => {
    render(<Updates client={client({"app.update.check": {supported:false,available:false,release:null}})} />);
    await userEvent.click(screen.getByRole("button", {name:"Check for updates"}));
    expect(await screen.findByText("This development build uses its existing source update tools.")).toBeVisible();
    expect(screen.queryByRole("button", {name:/Download update/})).not.toBeInTheDocument();
  });
});
