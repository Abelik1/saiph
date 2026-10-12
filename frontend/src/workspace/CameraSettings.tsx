// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react';
import type { CameraConfig, CameraStatus, Client, Settings } from './types';
import { Action, Card, Form } from './ui';

export function CameraSettings({settings,camera,client}:{settings:Settings;camera?:CameraStatus;client:Client}) {
  const [config,setConfig]=useState<CameraConfig>(()=>settings.link?.camera || {});
  const text=(key:keyof CameraConfig,value:string)=>setConfig(current=>({...current,[key]:value}));
  return <Card title="Phone camera" subtitle="One-time setup for this computer. Capture always starts deliberately.">
    <p className="muted">{camera?.message || 'Camera readiness appears here automatically.'}</p>
    <p>Authorize your paired phone for USB debugging once. Choose the front or rear camera, video quality and rotation on the Phone page. This camera session does not capture microphone audio.</p>
    <p>On Windows, create an OBS profile, scene collection and scene named Orion Phone. Add only a Window Capture source for Orion Phone Camera from scrcpy.exe, select Window title must match, and disable all audio sources. Save and quit OBS. Saiph starts its Virtual Camera; an existing OBS session stays yours.</p>
    <p>On Linux, configure an existing v4l2loopback device for your user. Saiph verifies its driver and sends the camera there.</p>
    <Action className="text-button" run={()=>client.call('camera.help')}>Open the upstream camera setup guide</Action>
    <Form submit={()=>client.call('settings.save',{link:{camera:config}})}>
      <label className="check"><input type="checkbox" checked={config.enabled!==false} onChange={event=>setConfig(current=>({...current,enabled:event.target.checked}))}/>Allow deliberate phone camera capture</label>
      <label>Linux loopback device<input value={config.v4l2_sink || ''} placeholder="/dev/video10" onChange={event=>text('v4l2_sink',event.target.value)}/></label>
      <label>OBS profile<input value={config.obs_profile ?? 'Orion Phone'} onChange={event=>text('obs_profile',event.target.value)}/></label>
      <label>OBS scene collection<input value={config.obs_collection ?? 'Orion Phone'} onChange={event=>text('obs_collection',event.target.value)}/></label>
      <label>OBS scene<input value={config.obs_scene ?? 'Orion Phone'} onChange={event=>text('obs_scene',event.target.value)}/></label>
      <details><summary>Tool and configuration paths</summary>
        <label>OBS scene file<input value={config.obs_scene_file || ''} placeholder="Use the standard OBS folder" onChange={event=>text('obs_scene_file',event.target.value)}/></label>
        <label>OBS executable<input value={config.obs_executable || ''} placeholder="Find the installed OBS Studio" onChange={event=>text('obs_executable',event.target.value)}/></label>
        <label>scrcpy executable<input value={config.scrcpy_executable || ''} placeholder="Find installed or Saiph portable scrcpy" onChange={event=>text('scrcpy_executable',event.target.value)}/></label>
      </details>
      <button>Save camera preferences</button>
    </Form>
    <p className="muted">Readiness confirms the local tools and configuration. Verify video in your meeting app after starting the camera.</p>
  </Card>;
}
