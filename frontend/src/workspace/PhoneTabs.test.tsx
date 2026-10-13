// SPDX-License-Identifier: AGPL-3.0-or-later
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { PhoneTabs } from "./PhoneTabs";
import type { PhoneFeatureState } from "./PhoneTabs";
import type { Client } from "./types";
const info: PhoneFeatureState = { threads:[{id:"t",device_id:"phone",thread:7,recipients:["Synthetic sender"],message:{body:"Synthetic SMS",timestamp:1}}],messages:[{id:"m",device_id:"phone",thread:7,body:"Synthetic SMS",timestamp:1,direction:"incoming"}],calls:[{device_id:"phone",state:"ringing",number:"Synthetic caller",name:""}],photos:[{id:"p",photo_id:"17",device_id:"phone",name:"Photo.jpg",timestamp:1,preview:"data:image/jpeg;base64,AA=="}],files:[] };
const phone={id:"phone",name:"Galaxy",online:true,capabilities:["sms","photos","calls","call-control","files"]};
describe("Phone tabs",()=>{
 it("shows photo preparation when the first drag is released before download finishes",async()=>{
  const call=vi.fn().mockResolvedValue({preparing:true});render(<PhoneTabs features={info} phone={phone} client={{call} as unknown as Client}/>);
  fireEvent.click(screen.getByRole("button",{name:"Photos"}));fireEvent.dragStart(screen.getByAltText("Photo.jpg").parentElement!);
  await waitFor(()=>expect(screen.getByRole("status")).toHaveTextContent("The original is downloading"));
  expect(call).toHaveBeenCalledWith("phone.photo.drag",{device_id:"phone",photo_id:"17"});
 });
 it("opens conversations automatically and targets the owning phone for reply",async()=>{
  const call=vi.fn().mockResolvedValue({queued:true});render(<PhoneTabs features={info} phone={phone} client={{call} as unknown as Client}/>);
  await waitFor(()=>expect(call).toHaveBeenCalledWith("phone.sms.open",{device_id:"phone",thread:7}));
  fireEvent.change(screen.getByLabelText("SMS reply"),{target:{value:"Synthetic reply"}});fireEvent.click(screen.getByRole("button",{name:"Send"}));
  await waitFor(()=>expect(call).toHaveBeenCalledWith("phone.sms.send",{device_id:"phone",thread:7,text:"Synthetic reply"}));
  expect(screen.queryByRole("button",{name:/Connect|Refresh|Sync/})).toBeNull();
 });
 it("offers explicit photo saves and call control without computer audio",async()=>{
  const call=vi.fn().mockResolvedValue({queued:true});render(<PhoneTabs features={info} phone={phone} client={{call} as unknown as Client}/>);
  fireEvent.click(screen.getByRole("button",{name:"Photos"}));fireEvent.click(screen.getByRole("button",{name:"Save photo"}));
  await waitFor(()=>expect(call).toHaveBeenCalledWith("phone.photo.save",{device_id:"phone",photo_id:"17"}));
  fireEvent.click(screen.getByRole("button",{name:"Calls"}));expect(screen.getByText("Call audio stays on your phone.")).toBeVisible();
  fireEvent.click(screen.getByRole("button",{name:"Answer"}));await waitFor(()=>expect(call).toHaveBeenCalledWith("phone.call",{device_id:"phone",operation:"answer"}));
 });
 it("shows saving, then saved with its folder, and never saves twice while in flight",async()=>{
  let finish:(value:unknown)=>void=()=>{};
  const call=vi.fn((method:string)=>method==="phone.photo.save"?new Promise((resolve)=>{finish=resolve;}):Promise.resolve({opened:true}));
  render(<PhoneTabs features={info} phone={phone} client={{call} as unknown as Client}/>);
  fireEvent.click(screen.getByRole("button",{name:"Photos"}));fireEvent.click(screen.getByRole("button",{name:"Save photo"}));
  const saving=await screen.findByRole("button",{name:"Saving…"});expect(saving).toBeDisabled();
  expect(screen.getByRole("status")).toHaveTextContent("Saving the original");
  fireEvent.click(saving);expect(call.mock.calls.filter(([m])=>m==="phone.photo.save")).toHaveLength(1);
  finish({status:"saved",saved:true,existing:false,name:"Photo.jpg",path:"/home/owner/Downloads/Orion/Photo.jpg",folder:"Downloads → Orion",file_id:"f1"});
  await waitFor(()=>expect(screen.getByRole("status")).toHaveTextContent("Saved to Downloads → Orion"));
  expect(screen.getByRole("status")).toHaveAttribute("title","/home/owner/Downloads/Orion/Photo.jpg");
  expect(screen.queryByRole("button",{name:"Save photo"})).toBeNull();
  fireEvent.click(screen.getByRole("button",{name:"Show in folder"}));
  await waitFor(()=>expect(call).toHaveBeenCalledWith("phone.file.open",{id:"f1"}));
 });
 it("follows the recorded save until the original arrives",()=>{
  const client={call:vi.fn().mockResolvedValue({})} as unknown as Client;
  const saving={...info,photo_saves:[{id:"k",device_id:"phone",photo_id:"17",status:"saving" as const,updated_at:"1"}]};
  const {rerender}=render(<PhoneTabs features={saving} phone={phone} client={client}/>);
  fireEvent.click(screen.getByRole("button",{name:"Photos"}));
  expect(screen.getByRole("button",{name:"Saving…"})).toBeDisabled();
  rerender(<PhoneTabs features={{...info,photo_saves:[{...saving.photo_saves[0],status:"saved",folder:"Downloads → Orion",path:"/p/Photo.jpg",file_id:"f1",updated_at:"2"}]}} phone={phone} client={client}/>);
  expect(screen.getByRole("status")).toHaveTextContent("Saved to Downloads → Orion");
  rerender(<PhoneTabs features={{...info,photo_saves:[{...saving.photo_saves[0],status:"failed",error:"Your phone did not send the photo. Try again.",updated_at:"3"}]}} phone={phone} client={client}/>);
  expect(screen.getByRole("alert")).toHaveTextContent("did not send");expect(screen.getByRole("button",{name:"Save photo"})).toBeEnabled();
 });
 it("shows a clear error when a save cannot start",async()=>{
  const call=vi.fn().mockRejectedValue(new Error("Orion is offline. This action has not been sent."));
  render(<PhoneTabs features={info} phone={phone} client={{call} as unknown as Client}/>);
  fireEvent.click(screen.getByRole("button",{name:"Photos"}));fireEvent.click(screen.getByRole("button",{name:"Save photo"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("Orion is offline");
  expect(screen.getByRole("button",{name:"Save photo"})).toBeEnabled();
 });
 it("retains offline SMS while disabling outgoing actions",()=>{
  render(<PhoneTabs features={info} phone={{...phone,online:false}} client={{call:vi.fn()} as unknown as Client}/>);
  expect(screen.getByText("Synthetic SMS",{selector:"p"})).toBeVisible();expect(screen.getByRole("button",{name:"Send"})).toBeDisabled();
 });
 it("keeps group conversations readable without promising MMS replies",()=>{
  const group={...info,threads:[{...info.threads[0],recipients:["First","Second"]}]};
  render(<PhoneTabs features={group} phone={phone} client={{call:vi.fn().mockResolvedValue({})} as unknown as Client}/>);
  expect(screen.getByText("Synthetic SMS",{selector:"p"})).toBeVisible();expect(screen.getByRole("button",{name:"Send"})).toBeDisabled();
  expect(screen.getByText(/Group replies stay in your phone's messaging app\./)).toBeVisible();
 });
});
