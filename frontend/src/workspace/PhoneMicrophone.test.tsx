// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { PhoneMicrophone, MicrophoneSettings } from './PhoneMicrophone';
import type { Client, MicrophoneStatus, Settings } from './types';

const ready:MicrophoneStatus={available:true,running:false,muted:false,verified:false,mode:'linux-pulse',device_id:null,message:'Ready'};
describe('Phone microphone',()=>{
  it('starts only deliberately and offers explicit mute, unmute and stop',async()=>{
    const call=vi.fn().mockResolvedValue({}),client={call} as unknown as Client;
    const view=render(<PhoneMicrophone microphone={ready} deviceId="phone" deviceName="Test phone" client={client}/>);
    expect(call).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button',{name:'Use phone as microphone'}));
    await waitFor(()=>expect(call).toHaveBeenCalledWith('microphone.start',{device_id:'phone'}));
    view.rerender(<PhoneMicrophone microphone={{...ready,running:true,device_id:'phone'}} deviceName="Test phone" client={client}/>);
    expect(screen.getByRole('status')).toHaveTextContent('Test phone microphone · Capturing audio');
    fireEvent.click(screen.getByRole('button',{name:'Mute phone microphone'}));
    await waitFor(()=>expect(call).toHaveBeenCalledWith('microphone.mute',{muted:true}));
    view.rerender(<PhoneMicrophone microphone={{...ready,running:true,muted:true,device_id:'phone'}} client={client}/>);
    fireEvent.click(screen.getByRole('button',{name:'Unmute phone microphone'}));
    await waitFor(()=>expect(call).toHaveBeenCalledWith('microphone.mute',{muted:false}));
    fireEvent.click(screen.getByRole('button',{name:'Stop phone microphone'}));
    await waitFor(()=>expect(call).toHaveBeenCalledWith('microphone.stop'));
  });
  it('does not offer capture without a paired online phone or supported adapter',()=>{
    const view=render(<PhoneMicrophone microphone={ready} client={{call:vi.fn()} as unknown as Client}/>);
    expect(screen.getByRole('button',{name:'Use phone as microphone'})).toBeDisabled();
    view.rerender(<PhoneMicrophone microphone={{...ready,available:false}} deviceId="phone" client={{call:vi.fn()} as unknown as Client}/>);
    expect(screen.getByRole('button',{name:'Use phone as microphone'})).toBeDisabled();
  });
  it('opt-in setup cannot start capture and turning off is always offered',async()=>{
    const call=vi.fn().mockResolvedValue({}),client={call} as unknown as Client;
    const view=render(<MicrophoneSettings settings={{} as Settings} client={client}/>);
    expect(call).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button',{name:'Enable phone microphone'}));
    await waitFor(()=>expect(call).toHaveBeenCalledWith('settings.save',{link:{microphone:{enabled:true}}}));
    view.rerender(<MicrophoneSettings settings={{link:{microphone:{enabled:true}}} as Settings} client={client}/>);
    fireEvent.click(screen.getByRole('button',{name:'Turn off phone microphone'}));
    await waitFor(()=>expect(call).toHaveBeenCalledWith('settings.save',{link:{microphone:{enabled:false}}}));
    expect(call).not.toHaveBeenCalledWith('microphone.start',expect.anything());
  });
});
