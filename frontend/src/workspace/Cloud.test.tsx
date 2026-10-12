// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Cloud } from "./Cloud";
import type { Client, State } from "./types";

function fixture(profile=false, paired=true) {
  const state={cloud_status:{installed:true,inspection_complete:true,profile_present:profile,prepared:false,selected_libraries:profile?1:0,state:"installed"},settings:{hub:{paired},cloud:{enabled:true}}} as unknown as State;
  const call=vi.fn().mockImplementation((method:string) => Promise.resolve(method === "cloud.info" ? {configured:true,state:"ready",libraries:[{id:"library-a",name:"Family documents",permission:"rw"},{id:"library-b",name:"Reference",permission:"r"}]} : method === "cloud.setup" ? {state:"prepared",needs_library_link:true} : {opened:true}));
  return {state,call,client:{call} as unknown as Client};
}

describe("Cloud onboarding", () => {
  it('does not direct an unmanaged CLI profile to a missing graphical app', () => {
    const {state,client}=fixture(true);
    state.cloud_status={...state.cloud_status!,management_available:false,service_state:'not_managed'};
    render(<Cloud state={state} client={client} />);
    expect(screen.getByRole('status')).toHaveTextContent('Transfer progress is not available here');
    expect(screen.queryByRole('button',{name:'Manage file sync'})).toBeNull();
  });
  it.each(['reachable','unavailable','needs_attention'] as const)("shows managed service %s without requiring a separate GUI", (service_state) => {
    const {state,call,client}=fixture(true);
    state.cloud_status={...state.cloud_status!,management_available:false,service_state};
    render(<Cloud state={state} client={client} />);
    expect(screen.queryByRole('button',{name:'Manage file sync'})).toBeNull();
    expect(screen.queryByRole('button',{name:'Set up file sync'})).toBeNull();
    expect(screen.getByText(/Saiph maintains its background/)).toBeVisible();
    expect(screen.getByRole('status')).toHaveTextContent(service_state === 'reachable' ? 'Transfer completion has not been verified' : service_state === 'unavailable' ? 'checks its background service automatically' : 'needs attention');
    expect(call).not.toHaveBeenCalled();
  });
  it("installs the optional component only after a deliberate action", async () => {
    const {state,call,client}=fixture();
    state.cloud_status={installed:false,inspection_complete:true,profile_present:false,prepared:false,selected_libraries:0,state:"not_detected",installation_supported:true};
    render(<Cloud state={state} client={client} />);
    expect(call).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button",{name:"Install file sync"}));
    await waitFor(()=>expect(call).toHaveBeenCalledWith("cloud.client.install"));
    expect(await screen.findByText(/File sync is installed/)).toBeVisible();
    expect(call).not.toHaveBeenCalledWith("cloud.info");
  });
  it("preserves an existing profile and opens its management app without reprovisioning", async () => {
    const {state,call,client}=fixture(true); render(<Cloud state={state} client={client} />);
    expect(call).not.toHaveBeenCalled();
    expect(screen.queryByRole("button",{name:"Set up file sync"})).toBeNull();
    fireEvent.click(screen.getByRole("button",{name:"Manage file sync"}));
    await waitFor(()=>expect(call).toHaveBeenCalledWith("cloud.client.open"));
    expect(call).not.toHaveBeenCalledWith("cloud.info");
  });

  it("requests libraries deliberately and requires one choice before the native folder picker", async () => {
    const {state,call,client}=fixture(); render(<Cloud state={state} client={client} />);
    expect(call).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button",{name:"Set up file sync"}));
    const first=await screen.findByRole("radio",{name:"Family documents"});
    expect(first).not.toBeChecked();
    expect(screen.getByRole("button",{name:"Choose folder and continue"})).toBeDisabled();
    fireEvent.click(first);
    fireEvent.click(screen.getByRole("button",{name:"Choose folder and continue"}));
    await waitFor(()=>expect(call).toHaveBeenCalledWith("cloud.setup",{libraries:["library-a"]}));
    expect(await screen.findByText(/Your account is prepared/)).toHaveTextContent("Saiph has not confirmed transfers yet");
    expect(screen.queryByRole("button",{name:/^Sync$|^Refresh$|^Connect$/})).toBeNull();
  });

  it("leaves the one-time choices available when the folder picker is cancelled", async () => {
    const {state,call,client}=fixture();
    call.mockImplementation((method:string)=>Promise.resolve(method === "cloud.setup" ? {cancelled:true} : {configured:true,state:"ready",libraries:[{id:"library-a",name:"Documents",permission:"rw"}]}));
    render(<Cloud state={state} client={client} />);
    fireEvent.click(screen.getByRole("button",{name:"Set up file sync"}));
    fireEvent.click(await screen.findByRole("radio",{name:"Documents"}));
    fireEvent.click(screen.getByRole("button",{name:"Choose folder and continue"}));
    await waitFor(()=>expect(call).toHaveBeenCalledWith("cloud.setup",{libraries:["library-a"]}));
    expect(screen.getByRole("button",{name:"Cancel setup"})).toBeVisible();
    expect(screen.queryByText(/Your account is prepared/)).toBeNull();
  });

  it("shows a safe setup failure instead of backend details", async () => {
    const {state,call,client}=fixture(); call.mockRejectedValue(new Error("synthetic backend credential detail"));
    render(<Cloud state={state} client={client} />);
    fireEvent.click(screen.getByRole("button",{name:"Set up file sync"}));
    expect(await screen.findByRole("alert")).toHaveTextContent("File sync setup is temporarily unavailable");
    expect(screen.queryByText(/synthetic backend/)).toBeNull();
  });

  it("requires pairing before offering server-backed setup", () => {
    const {state,client}=fixture(false,false); render(<Cloud state={state} client={client} />);
    expect(screen.getByRole("button",{name:"Set up file sync"})).toBeDisabled();
  });
});
