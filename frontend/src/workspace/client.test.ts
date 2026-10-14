// SPDX-License-Identifier: AGPL-3.0-or-later
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

describe('native request deadlines', () => {
  let response: (raw:string)=>void;
  let requests: string[][];
  beforeEach(() => {
    vi.useFakeTimers();vi.resetModules();requests=[];
    Object.assign(window, {qt:{webChannelTransport:{}},QWebChannel:class {
      constructor(_transport:unknown, ready:(channel:unknown)=>void) {
        ready({objects:{orionMini:{request:(...args:string[])=>requests.push(args),
          response:{connect:(handler:typeof response)=>{response=handler;}},
          changed:{connect:vi.fn()},dropped:{connect:vi.fn()},dragging:{connect:vi.fn()}}}});
      }
    }});
  });
  afterEach(() => {
    vi.useRealTimers();
    Reflect.deleteProperty(window,'qt');Reflect.deleteProperty(window,'QWebChannel');
  });
  it('keeps a slow component installation pending and accepts its later response', async () => {
    const {desktopClient}=await import('./client');const client=await desktopClient();
    let settled=false;
    const pending=client.call('cloud.client.install').finally(()=>{settled=true;});
    await vi.advanceTimersByTimeAsync(200_000);
    expect(settled).toBe(false);
    response(JSON.stringify({id:requests[0][0],ok:true,result:{installed:true}}));
    await expect(pending).resolves.toEqual({installed:true});
    expect(vi.getTimerCount()).toBe(0);
  });
  it('bounds an installation that never responds', async () => {
    const {desktopClient}=await import('./client');const client=await desktopClient();
    const assertion=expect(client.call('cloud.client.install')).rejects.toThrow('desktop did not respond');
    await vi.advanceTimersByTimeAsync(11*60*1000);await assertion;
  });
  it('answers an unchanged state with the same object, and a changed one with a new object', async () => {
    const {desktopClient}=await import('./client');const client=await desktopClient();
    // The desktop writes packets with Python's json.dumps spacing.
    const packet=(id:string,result:unknown)=>`{"id": "${id}", "ok": true, "result": ${JSON.stringify(result)}}`;
    const first=client.call('state');response(packet(requests[0][0],{phone:{status:'Online'}}));
    const second=client.call('state');response(packet(requests[1][0],{phone:{status:'Online'}}));
    const third=client.call('state');response(packet(requests[2][0],{phone:{status:'Offline'}}));
    const [a,b,c]=await Promise.all([first,second,third]);
    expect(b).toBe(a);
    expect(c).not.toBe(a);
    expect(c).toEqual({phone:{status:'Offline'}});
    // Other methods never reuse a state answer.
    const other=client.call('phone.ring');response(packet(requests[3][0],{phone:{status:'Offline'}}));
    expect(await other).not.toBe(c);
    expect(vi.getTimerCount()).toBe(0);
  });
  it('retains the ordinary request deadline', async () => {
    const {desktopClient}=await import('./client');const client=await desktopClient();
    const assertion=expect(client.call('state')).rejects.toThrow('desktop did not respond');
    await vi.advanceTimersByTimeAsync(150_000);await assertion;
  });
});
