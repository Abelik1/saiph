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
  it('retains the ordinary request deadline', async () => {
    const {desktopClient}=await import('./client');const client=await desktopClient();
    const assertion=expect(client.call('state')).rejects.toThrow('desktop did not respond');
    await vi.advanceTimersByTimeAsync(150_000);await assertion;
  });
});
