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
  it('waits for the footer one-click update through its download, and bounds it', async () => {
    const {desktopClient}=await import('./client');const client=await desktopClient();
    let settled=false;
    const pending=client.call('app.update.now').finally(()=>{settled=true;});
    await vi.advanceTimersByTimeAsync(20*60*1000);
    expect(settled).toBe(false);
    response(JSON.stringify({id:requests[0][0],ok:true,result:{started:true}}));
    await expect(pending).resolves.toEqual({started:true});
    const assertion=expect(client.call('app.update.now')).rejects.toThrow('desktop did not respond');
    await vi.advanceTimersByTimeAsync(30*60*1000);await assertion;
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
  it('sends the last native revision and resolves compact replies without losing updates', async () => {
    const {desktopClient}=await import('./client');const client=await desktopClient();
    const first=client.call('state');response(JSON.stringify({id:requests[0][0],ok:true,revision:'a'.repeat(64),result:{phone:{online:true}}}));
    const a=await first;
    const same=client.call('state');expect(JSON.parse(requests[1][2])).toEqual({revision:'a'.repeat(64)});
    response(JSON.stringify({id:requests[1][0],ok:true,revision:'a'.repeat(64),unchanged:true}));
    expect(await same).toBe(a);
    const fresh=client.call('state');response(JSON.stringify({id:requests[2][0],ok:true,revision:'b'.repeat(64),result:{phone:{online:false}}}));
    expect(await fresh).toEqual({phone:{online:false}});
    const next=client.call('state');expect(JSON.parse(requests[3][2])).toEqual({revision:'b'.repeat(64)});
    response(JSON.stringify({id:requests[3][0],ok:true,revision:'b'.repeat(64),unchanged:true}));await next;
    expect(vi.getTimerCount()).toBe(0);
  });
  it('retains untouched photo/message subtrees when only a connection field changes', async () => {
    const {desktopClient}=await import('./client');const client=await desktopClient();
    const state={phone:{online:true},phone_features:{photos:[{id:'p',preview:'synthetic'}],messages:[{id:'m',body:'synthetic'}]}};
    const first=client.call<typeof state>('state');response(JSON.stringify({id:requests[0][0],ok:true,result:state}));const a=await first;
    const second=client.call<typeof state>('state');response(JSON.stringify({id:requests[1][0],ok:true,result:{...state,phone:{online:false}}}));const b=await second;
    expect(b).not.toBe(a);expect(b.phone).not.toBe(a.phone);expect(b.phone_features).toBe(a.phone_features);
    const third=client.call<typeof state>('state');response(JSON.stringify({id:requests[2][0],ok:true,result:{...state,phone_features:{...state.phone_features,photos:[]}}}));const c=await third;
    expect(c.phone_features.photos).toEqual([]);expect(c.phone_features.messages).toBe(a.phone_features.messages);
  });
  it('refuses an unmatched compact reply rather than returning stale data', async () => {
    const {desktopClient}=await import('./client');const client=await desktopClient();
    const pending=client.call('state');const assertion=expect(pending).rejects.toThrow('fresh snapshot');
    response(JSON.stringify({id:requests[0][0],ok:true,revision:'a'.repeat(64),unchanged:true}));await assertion;
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe('dashboard refresh signal', () => {
  afterEach(() => { Reflect.deleteProperty(window,'qt');Reflect.deleteProperty(window,'QWebChannel'); });
  it('listens to the held refresh signal when the shell offers one', async () => {
    vi.resetModules();
    const changed={connect:vi.fn()}, refresh={connect:vi.fn()};
    Object.assign(window, {qt:{webChannelTransport:{}},QWebChannel:class {
      constructor(_transport:unknown, ready:(channel:unknown)=>void) {
        ready({objects:{orionMini:{request:vi.fn(),response:{connect:vi.fn()},changed,refresh,dropped:{connect:vi.fn()},dragging:{connect:vi.fn()}}}});
      }
    }});
    const {desktopClient}=await import('./client');const client=await desktopClient();
    const listener=()=>{};client.subscribe(listener);
    expect(refresh.connect).toHaveBeenCalledWith(listener);
    expect(changed.connect).not.toHaveBeenCalled();
  });
});
