// SPDX-License-Identifier: AGPL-3.0-or-later
// Deterministic ad treatment of the string contours in frontend/src/workspace/waves.tsx.
// The app's current field is static; this campaign adds timed drift and plucks.
(() => {
 const stage=document.getElementById('stage');
 const canvas=document.createElement('canvas');canvas.id='wave-background';canvas.setAttribute('aria-hidden','true');stage.prepend(canvas);
 const front=document.createElementNS('http://www.w3.org/2000/svg','svg');front.id='wave-transition';front.setAttribute('aria-hidden','true');
 front.innerHTML='<defs><linearGradient id="wave-front-colour" x1="0" y1="0" x2="1" y2="0"><stop stop-color="#22d3ee"/><stop offset=".45" stop-color="#67e8f9"/><stop offset="1" stop-color="#a78bfa"/></linearGradient></defs>'+ '<path/>'.repeat(6);
 stage.append(front);
 const mark=document.createElementNS('http://www.w3.org/2000/svg','svg');mark.id='brand-wave';mark.setAttribute('viewBox','0 0 150 20');mark.setAttribute('aria-hidden','true');
 mark.innerHTML='<path/><path/><path/>';document.getElementById('brand').append(mark);
 const svg=document.querySelector('#device-art .art-route');
 svg.innerHTML='<defs><linearGradient id="device-wave-colour" x1="1" y1="0" x2="0" y2="1"><stop stop-color="#a78bfa"/><stop offset=".5" stop-color="#67e8f9"/><stop offset="1" stop-color="#22d3ee"/></linearGradient></defs><path/><path/><path/><circle r="3"/><circle r="2.3"/><circle r="2"/>';
 const context=canvas.getContext('2d');let cacheKey='',gradients=[];
 const clamp=n=>Math.max(0,Math.min(1,n));
 const smooth=n=>{const p=clamp(n);return p*p*(3-2*p)};
 window.campaignBeat=(ad,scene,index)=>{const duration=(ad.scenes[index+1]?.at??ad.duration)-scene.at;return {hold:duration<=3?.65:duration>=5?1.05:.85,oscillate:.7,unveil:1.05,duration}};
 window.campaignCurtain=(ad,scene,index,local)=>{
  const beat=window.campaignBeat(ad,scene,index);
  const charge=clamp((local-beat.hold)/beat.oscillate),opening=clamp((local-beat.hold-beat.oscillate)/beat.unveil);
  return {...beat,charge,opening,reveal:smooth(opening),textOut:smooth(charge),phase:local<beat.hold?'headline':charge<1?'oscillating':opening<1?'opening':'revealed'};
 };
 // Two horizontal, oscillating edges part above and below the centre of the art.
 // Both the illustration mask and the visible strings use this exact geometry.
 function curtainEdge(u,state,local,side){
  const amplitude=.032*(1-state.reveal);
  const centre=.5+Math.sin(u*Math.PI*3-local*7)*amplitude+Math.sin(u*Math.PI*5+local*4)*amplitude*.35;
  return centre+side*(.008*state.charge+.57*state.reveal);
 }
 window.campaignCurtainClip=(state,local)=>{
  if(state.phase==='headline'||state.phase==='revealed')return 'none';
  const points=[];
  for(let n=0;n<=48;n++)points.push(`${(n/48*100).toFixed(2)}% ${(curtainEdge(n/48,state,local,-1)*100).toFixed(3)}%`);
  for(let n=48;n>=0;n--)points.push(`${(n/48*100).toFixed(2)}% ${(curtainEdge(n/48,state,local,1)*100).toFixed(3)}%`);
  return `polygon(${points.join(',')})`;
 };
 function transferPoint(u,time=0,phase=0){
  const envelope=Math.sin(u*Math.PI);
  const anchors=window.waveAnchors||{source:{x:593,y:181},target:{x:288,y:361}};
  return {x:anchors.source.x+(anchors.target.x-anchors.source.x)*u,y:anchors.source.y+(anchors.target.y-anchors.source.y)*u-75*envelope+envelope*(12*Math.sin(u*6*Math.PI-time*4+phase)+phase*3)};
 }
 window.waveTransferPoint=transferPoint;
 window.waveClip=progress=>{
  if(progress>=.999)return 'none';
  const p=clamp(progress),amplitude=4*Math.sin(p*Math.PI),points=['0% 0%'];
  for(let j=0;j<=16;j++){const y=j/16;points.push(`${(p*100+Math.sin(y*Math.PI*2)*amplitude).toFixed(2)}% ${(y*100).toFixed(2)}%`)}
  points.push('0% 100%');return `polygon(${points.join(',')})`;
 };
 window.renderCampaignWaves=(ad,time,index,still,scene)=>{
  const width=stage.clientWidth,height=stage.clientHeight;
  const local=still?1.25:Math.max(0,time-scene.at),t=still?1.25:time;
  const light=stage.classList.contains('light'),key=`${width}/${height}/${light}`;
  if(cacheKey!==key){cacheKey=key;canvas.width=width;canvas.height=height;gradients=[];
   for(let i=1;i<=30;i++){
    const depth=i/31,level=(.07+.26*Math.sin(Math.PI*depth)**2)*(light ? .72 : .82);
    const g=context.createLinearGradient(0,0,width,0);
    g.addColorStop(0,`rgba(${light?'23,122,145':'34,211,238'},${level*.45})`);
    g.addColorStop(.45,`rgba(${light?'33,99,115':'103,232,249'},${level})`);
    g.addColorStop(1,`rgba(${light?'105,81,175':'167,139,250'},${level*.7})`);gradients.push(g);
   }
  }
  context.clearRect(0,0,width,height);
  const gap=height/31,step=Math.max(7,width/180),travel=clamp((local-.35)/1.8);
  const pulseX=(scene.reverse?1-travel:travel)*width,pulseEnvelope=Math.sin(Math.PI*travel);
  for(let i=1;i<=30;i++){
   const depth=i/31,base=i*gap;context.beginPath();context.strokeStyle=gradients[i-1];context.lineWidth=i%6===0?1.7:1.1;
   for(let x=-step;x<=width+step;x+=step){
    const u=x/width;
    // Same broad/fine contour vocabulary as the production string field.
    const swell=Math.sin(u*2.6+depth*4.1+t*.18)*gap*.9+Math.sin(u*6.3-depth*2.2-t*.24)*gap*.25;
    const fine=Math.sin(u*22+i*.7-t*.7)*1.7;
    const pulse=Math.exp(-(((x-pulseX)/(width*.1))**2))*Math.sin((x-pulseX)*.035-local*7)*gap*.43*pulseEnvelope;
    const y=base+swell+fine+pulse;if(x===-step)context.moveTo(x,y);else context.lineTo(x,y);
   }context.stroke();
  }
  // A few brighter lower strings give the quiet lower canvas a recognisable motif.
  const ribbon=context.createLinearGradient(0,0,width,0);
  ribbon.addColorStop(0,light?'#21637300':'#22d3ee00');ribbon.addColorStop(.38,light?'#21637370':'#67e8f98a');ribbon.addColorStop(.8,light?'#6951af55':'#a78bfa78');ribbon.addColorStop(1,'#a78bfa00');
  for(let k=0;k<5;k++){context.beginPath();context.strokeStyle=ribbon;context.lineWidth=k===2?2.2:1;
   for(let x=-step;x<=width+step;x+=step){const u=x/width,y=height*.83+k*9+Math.sin(u*6.2-t*.8+k*.08)*height*.055+Math.sin(u*13+t*.42)*10;if(x===-step)context.moveTo(x,y);else context.lineTo(x,y)}context.stroke();
  }
  // Keep the copy quiet without adding visible rectangular panels.
  context.globalCompositeOperation='destination-out';
  const quiet=context.createRadialGradient(width*.36,height*.27,0,width*.36,height*.27,width*.66);
  quiet.addColorStop(0,'rgba(0,0,0,.73)');quiet.addColorStop(.55,'rgba(0,0,0,.35)');quiet.addColorStop(1,'rgba(0,0,0,0)');context.fillStyle=quiet;context.fillRect(0,0,width,height);context.globalCompositeOperation='source-over';
  const routeTime=still?1.25:local;
  svg.querySelectorAll('path').forEach((path,j)=>{let d='';for(let n=0;n<=48;n++){const p=transferPoint(n/48,routeTime,(j-1)*.9);d+=`${n?'L':'M'}${p.x.toFixed(2)} ${p.y.toFixed(2)} `}path.setAttribute('d',d)});
  svg.querySelectorAll('circle').forEach((dot,j)=>{const p=transferPoint(still ? .25+j*.26 : (local*.35+j*.31)%1,routeTime);dot.setAttribute('cx',p.x);dot.setAttribute('cy',p.y)});
  mark.querySelectorAll('path').forEach((path,j)=>{let d='';for(let x=0;x<=150;x+=3){const y=10+Math.sin(x/150*Math.PI*3-t*3+j*.5)*Math.sin(x/150*Math.PI)*(4-j);d+=`${x?'L':'M'}${x} ${y.toFixed(2)} `}path.setAttribute('d',d)});
  // Hold an oscillating horizontal seam, then open it slowly like a curtain.
  const state=window.campaignCurtain(ad,scene,index,local);
  const opacity=still?0:smooth(state.charge/.3)*(1-smooth((state.opening-.68)/.32));
  const art=document.getElementById('device-art').getBoundingClientRect(),stageBox=stage.getBoundingClientRect();
  front.setAttribute('viewBox',`0 0 ${width} ${height}`);front.style.opacity=String(opacity);front.dataset.phase=still?'still':state.phase;
  front.querySelectorAll('path').forEach((path,j)=>{
   const side=j<3?-1:1,layer=j%3-1;let d='';
   for(let x=-24;x<=width+24;x+=12){
    const u=(x-(art.left-stageBox.left))/art.width;
    const y=art.top-stageBox.top+curtainEdge(u,state,local,side)*art.height+layer*8*(1-state.reveal);
    d+=`${x===-24?'M':'L'}${x} ${y.toFixed(2)} `;
   }path.setAttribute('d',d);path.style.strokeWidth=String(layer===0?2.8:1.2);path.style.strokeOpacity=String(layer===0?.9:.42);
  });
 };
})();
