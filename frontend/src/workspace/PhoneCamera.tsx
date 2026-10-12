// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react';
import type { CameraConfig, CameraStatus, Client } from './types';
import { Action } from './ui';

export function PhoneCamera({camera,config,deviceId,client}:{camera?:CameraStatus;config?:CameraConfig;deviceId?:string;client:Client}) {
  const [facing,setFacing]=useState<NonNullable<CameraConfig['facing']>>(config?.facing || 'front');
  const [quality,setQuality]=useState<NonNullable<CameraConfig['quality']>>(config?.quality || '720p');
  const [rotation,setRotation]=useState<NonNullable<CameraConfig['rotation']>>(config?.rotation || '0');
  const start=async()=>{
    await client.call('settings.save',{link:{camera:{facing,quality,rotation}}});
    await client.call('camera.start',{device_id:deviceId});
  };
  return <div className="phone-camera">
    {!camera?.running && <details><summary>Camera options</summary>
      <label>Phone camera<select value={facing} onChange={event=>setFacing(event.target.value as typeof facing)}><option value="front">Front camera</option><option value="back">Rear camera</option></select></label>
      <label>Video quality<select value={quality} onChange={event=>setQuality(event.target.value as typeof quality)}><option value="720p">720p · 30 fps</option><option value="1080p">1080p · 30 fps</option></select></label>
      <label>Picture rotation<select value={rotation} onChange={event=>setRotation(event.target.value as typeof rotation)}>{(['0','90','180','270'] as const).map(value=><option key={value} value={value}>{value}°</option>)}</select></label>
    </details>}
    {camera?.running ? <Action className="text-button" run={()=>client.call('camera.stop')}>Stop phone camera</Action>
      : <Action className="text-button" disabled={!deviceId || !camera?.available} run={start}>Use phone as webcam</Action>}
    <p className="muted" role="status">{camera?.running ? `${camera.facing === 'back' ? 'Rear' : 'Front'} camera · ${camera.quality || '720p'}. Check the picture in your meeting app.`
      : camera?.available ? 'Your camera starts only when you choose to use it.' : 'Set up the camera once in Settings → Advanced.'}</p>
  </div>;
}
