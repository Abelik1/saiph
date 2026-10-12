// SPDX-License-Identifier: AGPL-3.0-or-later
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { PhoneCamera } from './PhoneCamera';
import { CameraSettings } from './CameraSettings';
import type { CameraStatus, Client, Settings } from './types';

const ready:CameraStatus={available:true,running:false,verified:false,mode:'windows-obs',device_id:null,message:'Ready'};
describe('Phone camera',()=>{
  it('starts only on an explicit click and stops the active capture',async()=>{
    const call=vi.fn().mockResolvedValue(ready);const client={call} as unknown as Client;
    const view=render(<PhoneCamera camera={ready} deviceId="phone" client={client}/>);
    expect(call).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button',{name:'Use phone as webcam'}));
    await waitFor(()=>expect(call).toHaveBeenCalledWith('camera.start',{device_id:'phone'}));
    view.rerender(<PhoneCamera camera={{...ready,running:true,device_id:'phone'}} deviceId="other-phone" client={client}/>);
    fireEvent.click(screen.getByRole('button',{name:'Stop phone camera'}));
    await waitFor(()=>expect(call).toHaveBeenCalledWith('camera.stop'));
  });
  it('does not offer webcam launch for missing platform prerequisites',()=>{
    render(<PhoneCamera camera={{...ready,available:false,mode:'unavailable'}} deviceId="phone" client={{call:vi.fn()} as unknown as Client}/>);
    expect(screen.getByRole('button',{name:'Use phone as webcam'})).toBeDisabled();
    expect(screen.getByText('Set up the camera once in Settings → Advanced.')).toBeVisible();
  });
  it('starts the chosen rear camera options only after preference saving succeeds',async()=>{
    const call=vi.fn().mockResolvedValue({});
    render(<PhoneCamera camera={ready} deviceId="phone" client={{call} as unknown as Client}/>);
    fireEvent.click(screen.getByText('Camera options'));
    fireEvent.change(screen.getByLabelText('Phone camera'),{target:{value:'back'}});
    fireEvent.change(screen.getByLabelText('Video quality'),{target:{value:'1080p'}});
    fireEvent.change(screen.getByLabelText('Picture rotation'),{target:{value:'90'}});
    expect(call).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button',{name:'Use phone as webcam'}));
    await waitFor(()=>expect(call).toHaveBeenNthCalledWith(2,'camera.start',{device_id:'phone'}));
    expect(call).toHaveBeenNthCalledWith(1,'settings.save',{link:{camera:{facing:'back',quality:'1080p',rotation:'90'}}});
  });
  it('explains setup only in Advanced and saves bounded local preferences',async()=>{
    const call=vi.fn().mockResolvedValue({});
    render(<CameraSettings settings={{link:{camera:{}}} as Settings} camera={ready} client={{call} as unknown as Client}/>);
    expect(call).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('Linux loopback device'),{target:{value:'/dev/video10'}});
    fireEvent.click(screen.getByRole('button',{name:'Save camera preferences'}));
    await waitFor(()=>expect(call).toHaveBeenCalledWith('settings.save',{link:{camera:{v4l2_sink:'/dev/video10'}}}));
    fireEvent.click(screen.getByRole('button',{name:'Open the upstream camera setup guide'}));
    await waitFor(()=>expect(call).toHaveBeenCalledWith('camera.help'));
    expect(call).not.toHaveBeenCalledWith('camera.start',expect.anything());
  });
});
