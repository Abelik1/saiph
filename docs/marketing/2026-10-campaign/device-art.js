// SPDX-License-Identifier: AGPL-3.0-or-later
// Reuses the website device shells. All screen content is synthetic illustration.
(() => {
 const root=document.createElement('div');root.id='device-art';
 root.setAttribute('role','img');root.setAttribute('aria-label','Illustrated Android phone and laptop sharing content');
 const shell=(kind,body)=>`<div class="dev dev-${kind}"><div class="bezel"><div class="screen">${body}</div></div>${kind==='laptop'?'<div class="base"></div>':kind==='desktop'?'<div class="neck"></div><div class="foot"></div>':''}<div class="dev-label">${kind==='laptop'?'Windows / Linux':kind==='desktop'?'Linux':'Android'}</div></div>`;
 const dots='<span class="dots"><i></i><i></i><i></i></span>';
 root.innerHTML=`<div class="art-inner">${shell('laptop',`<div class="wall w1"></div><div class="win"><div class="win-bar">${dots}<span id="art-window-title">Saiph</span></div><div class="win-body" id="art-laptop-body"></div></div><div class="taskbar"><i></i><i class="on"></i><i></i></div>`)}${shell('desktop','<div class="wall w2"></div><div class="art-peer"><img src="assets/logo.svg" alt=""><b>Linux</b><span>Your other computer</span></div>')}${shell('phone','<div class="wall w3"></div><div class="p-status"><span>9:41</span><span>5G</span></div><div class="p-app" id="art-phone-body"></div><div class="p-home-bar"></div>')}<div class="art-detail"><small id="art-detail-label"></small><b id="art-detail-text"></b></div><svg class="art-route" viewBox="0 0 720 600" aria-hidden="true"><path d="M 580 180 C 450 70 430 430 275 360"/></svg><div class="art-packet">Aa</div><div class="art-cursor">➤</div><div class="art-keyboard">${'<i></i>'.repeat(20)}</div><div class="art-feature-strip"></div></div>`;
 document.getElementById('stage').append(root);
 const note=document.createElement('div');note.id='device-art-note';note.textContent='Illustrated feature preview';document.getElementById('stage').append(note);
 const laptop=document.getElementById('art-laptop-body'),phone=document.getElementById('art-phone-body'),title=document.getElementById('art-window-title');
 const packet=root.querySelector('.art-packet'),inner=root.querySelector('.art-inner');
 const desktop=root.querySelector('.dev-desktop'),phoneShell=root.querySelector('.dev-phone'),laptopShell=root.querySelector('.dev-laptop');
 const detail=root.querySelector('.art-detail'),cursor=root.querySelector('.art-cursor'),keyboard=root.querySelector('.art-keyboard');
 let previous='';
 window.renderDevices=(ad,time,index,still,scene)=>{
  const local=Math.max(0,time-scene.at);
  const stage=document.getElementById('stage'),cinematic=stage.classList.contains('cinematic'),wide=stage.classList.contains('wide');
  const curtain=window.campaignCurtain(ad,scene,index,local),beat=curtain;
  const handoff=still?1:curtain.reveal;
  const progress=still?1:Math.max(0,Math.min(1,(local-(cinematic?beat.hold+beat.oscillate+.25:.45))/1.55));
  const arrived=progress>.88;
  const kind=scene.kind||ad.poster?.kind||'clipboard';
  if(cinematic){Object.assign(root.style,wide?{left:'130px',top:'140px',width:'1660px',height:'730px'}:{left:'130px',top:'400px',width:'820px',height:'790px'});root.style.opacity=String(still?1:curtain.phase==='headline'?.08:1);root.style.transform=still?'none':`translateY(${45*(1-handoff)}px) scale(${.91+.09*handoff})`;root.style.clipPath=still?'none':window.campaignCurtainClip(curtain,local);note.style.opacity=String(handoff)}
  else{Object.assign(root.style,{left:'',top:'',width:'',height:'',opacity:'1',transform:'none',clipPath:'none'});note.style.opacity='1'}
  const layouts={
   clipboard:[[20,525,65],[485,210,105]],notifications:[[20,555,65],[505,175,200]],photos:[[15,500,55],[480,220,100]],files:[[50,520,90],[510,175,70]],messages:[[25,540,75],[515,175,150]],calls:[[10,525,60],[455,230,75]],webcam:[[10,575,55],[525,170,200]],controls:[[185,500,60],[30,185,155]],cloud:[[15,485,45],[505,185,160]],deskflow:[[25,480,50],[505,185,160]]
  };
  const wideLayouts={
   clipboard:[[50,650,60],[820,235,85]],notifications:[[60,700,60],[865,185,190]],photos:[[45,580,80],[790,260,65]],files:[[75,650,70],[825,210,105]],messages:[[50,665,70],[835,220,100]],calls:[[45,650,65],[780,260,70]],webcam:[[40,710,60],[875,190,160]],controls:[[375,680,60],[70,230,100]],cloud:[[40,630,50],[815,225,85]],deskflow:[[40,620,60],[815,225,85]]
  };
  const baseW=wide?1120:720,baseH=wide?650:600;
  const poses=(wide?wideLayouts:layouts)[kind]||(wide?[[65,630,65],[815,225,85]]:[[45,500,55],[505,185,160]]);
  for(const [el,pose] of [[laptopShell,poses[0]],[phoneShell,poses[1]],[desktop,wide?[790,300,240]:[435,275,270]]])Object.assign(el.style,{left:pose[0]+'px',width:pose[1]+'px',bottom:pose[2]+'px',top:'auto'});
  phoneShell.style.zIndex=kind==='notifications'?'1':'4';laptopShell.style.zIndex='2';
  const secondComputer=kind==='deskflow'||kind==='cloud';
  const source=secondComputer?desktop:phoneShell;
  window.waveAnchors={source:{x:source.offsetLeft+source.offsetWidth*.5,y:baseH-parseFloat(source.style.bottom)-source.offsetHeight*.55},target:{x:laptopShell.offsetLeft+laptopShell.offsetWidth*.52,y:baseH-parseFloat(laptopShell.style.bottom)-laptopShell.offsetHeight*.52}};
  const key=ad.id+'/'+index+'/'+kind+'/'+arrived;
  root.dataset.kind=kind;
  if(key!==previous){previous=key;
   if(kind==='clipboard'){
    title.textContent='Saiph · Clipboard';
    phone.innerHTML='<h4>Notes</h4><div class="art-note selected">Coffee<br>at 10</div><div class="art-state">Text copied</div>';
    laptop.innerHTML='<div class="art-doc"><div class="art-meta">Notes on your computer</div><div id="art-typed" class="art-typed"></div><div class="art-state">Text clipboard from Android</div></div>';
   }else if(kind==='photos'||kind==='files'){
    title.textContent='Saiph · File sharing';
    phone.innerHTML=kind==='photos'?'<h4>Share photo</h4><div class="art-photo"></div><div class="art-file">desk.jpg</div><div class="art-state">Send to computer</div>':`<h4>Files</h4><div class="art-file-card">PDF<span>project.pdf</span></div><div class="art-state">${scene.reverse?'Received from PC':'Share with PC'}</div>`;
    laptop.innerHTML=`<div class="art-doc"><div class="art-meta">${scene.reverse?'Send to your phone':'Files from your phone'}</div>${kind==='photos'?'<div class="art-photo large"></div><div class="art-file">desk.jpg</div>':'<div class="art-file-card wide">PDF<span>project.pdf</span></div>'}<div class="art-state">${arrived?(scene.reverse?'Sent to Android':'Ready on your computer'):'Your file, across devices'}</div></div>`;
   }else if(kind==='notifications'){
    title.textContent='Saiph · Notifications';
    phone.innerHTML='<h4>Notification</h4><div class="art-notification phone"><small>REMINDER</small>Coffee at 10</div>';
    laptop.innerHTML=`<div class="art-doc"><div class="art-meta">From your Android</div>${arrived?'<div class="art-notification"><small>REMINDER</small>Coffee at 10</div>':'<div class="art-placeholder">Your notifications here</div>'}</div>`;
   }else if(kind==='messages'){
    title.textContent='Saiph · Texts';
    phone.innerHTML='<h4>Messages</h4><div class="art-chat incoming">Coffee at 10?</div><div class="art-chat outgoing">On my way.</div>';
    laptop.innerHTML='<div class="art-doc"><div class="art-meta">ALEX · ONE-TO-ONE TEXT</div><div class="art-chat incoming">Coffee at 10?</div><div class="art-chat outgoing" id="art-reply">On my way.</div><div class="art-state">From your phone number</div></div>';
   }else if(kind==='calls'){
    title.textContent='Saiph · Incoming call';
    phone.innerHTML='<h4>Incoming call</h4><div class="art-avatar">A</div><div class="art-caller">Alex</div><div class="art-state">Audio stays on phone</div>';
    laptop.innerHTML='<div class="art-doc"><div class="art-meta">INCOMING CALL FROM ANDROID</div><div class="art-caller">Alex</div><div class="art-call-buttons"><span>Decline</span><span>Answer</span></div><div class="art-state">Call controls on your computer</div></div>';
   }else if(kind==='webcam'){
    title.textContent='Saiph · Phone camera';
    phone.innerHTML='<h4>Camera</h4><div class="art-camera"></div><div class="art-state">USB / local Wi-Fi</div>';
    laptop.innerHTML='<div class="art-doc"><div class="art-meta">VIDEO CALL · PHONE CAMERA</div><div class="art-camera wide"></div><div class="art-state">Your phone as a webcam</div></div>';
   }else if(kind==='controls'){
    title.textContent='Saiph · Phone controls';
    phone.innerHTML='<h4>Your phone</h4><div class="art-avatar music">♪</div><div class="art-state">Music playing</div>';
    laptop.innerHTML='<div class="art-doc"><div class="art-control-row">Ringer <b>Vibrate</b></div><div class="art-control-row">Media <b>Ⅱ</b></div><div class="art-control-row">Do Not Disturb <b>On</b></div></div>';
   }else if(kind==='cloud'){
    title.textContent='Saiph · Cloud folder';
    phone.innerHTML='<h4>Saiph</h4><div class="art-note">Your phone.<br>Your devices.</div>';
    laptop.innerHTML='<div class="art-doc"><div class="art-meta">YOUR SYNCED FOLDER</div><div class="art-file-card wide">DOC<span>project-notes.docx</span></div><div class="art-state">Storage you choose</div></div>';
   }else if(kind==='deskflow'){
    title.textContent='Deskflow · Device sharing';
    phone.innerHTML='<h4>Saiph</h4>';
    laptop.innerHTML='<div class="art-doc"><div class="art-meta">WINDOWS</div><div class="art-caller">One keyboard.</div><div class="art-state">Move across both computers</div></div>';
   }else if(kind==='intro'||kind==='overview'){
    title.textContent='Saiph · Your devices';
    phone.innerHTML='<h4>Saiph</h4><img class="art-phone-logo" src="assets/logo.svg" alt=""><div class="art-state">Android</div>';
    laptop.innerHTML='<div class="art-doc"><div class="art-meta">YOUR DEVICES. CONNECTED.</div><div class="art-network"><span class="art-dot"></span>Android connected</div><div class="art-overview-features"><span>Clipboard</span><span>Notifications</span><span>Photos + files</span></div></div>';
   }else{
    title.textContent='Saiph · Your Hub';
    phone.innerHTML='<h4>Saiph</h4><div class="art-note">Your own<br>Hub</div><div class="art-state">Private network</div>';
    laptop.innerHTML=`<div class="art-doc"><div class="art-meta">SELF-HOSTED HUB</div><div class="art-network"><span class="art-dot"></span>Your own server</div><div class="art-state">${arrived?'Android + your computer':'Connecting your devices'}</div></div>`;
   }
   packet.textContent=({clipboard:'Aa',photos:'JPG',files:'PDF',notifications:'!',messages:'SMS',calls:'☎',webcam:'●',cloud:'DOC',controls:'♪'})[kind]||'↔';
  }
  const labels={intro:['YOUR DEVICES','Android + your computer'],overview:['ONE COMPANION','Your devices. Connected.'],clipboard:['TEXT CLIPBOARD','Coffee at 10'],notifications:['FROM YOUR PHONE','Coffee at 10'],photos:['PHOTO SHARING','desk.jpg'],files:['FILE SHARING','project.pdf'],messages:['TEXT FROM YOUR NUMBER','On my way.'],calls:['INCOMING CALL','Alex'],webcam:['LOCAL CAMERA','Phone camera connected'],controls:['PHONE CONTROLS','A quieter desk'],cloud:['SELF-HOSTED FOLDER','Your files, across computers'],deskflow:['DESKFLOW INTEGRATION','One keyboard. Two computers.'],hub:['SELF-HOSTED HUB','Your server. Your setup.']};
  const label=labels[kind]||labels.overview;
  document.getElementById('art-detail-label').textContent=label[0];document.getElementById('art-detail-text').textContent=label[1];
  root.querySelector('.dev-laptop .dev-label').textContent=ad.id==='04-linux-too'?'Linux':'Windows / Linux';
  const scale=Math.min(root.clientWidth/baseW,root.clientHeight/baseH);
  const drift=still?0:Math.sin(local*1.6+index)*3;
  const zoom=still?1:1.035+.035*Math.sin(local*.8);
  inner.style.width=baseW+'px';inner.style.height=baseH+'px';
  inner.style.transform=`translate(${(root.clientWidth-baseW*scale*zoom)/2+drift}px,${(root.clientHeight-baseH*scale*zoom)/2}px) scale(${scale*zoom})`;
  const route=root.querySelector('.art-route');route.style.width=baseW+'px';route.style.height=baseH+'px';route.setAttribute('viewBox',`0 0 ${baseW} ${baseH}`);
  const eased=1-Math.pow(1-progress,3);
  const travel=scene.reverse?1-eased:eased;
  const point=window.waveTransferPoint?window.waveTransferPoint(travel,still?1.25:local):{x:593-305*travel,y:181+180*travel-90*Math.sin(travel*Math.PI)};
  packet.style.transform=`translate(${point.x-packet.offsetLeft-packet.offsetWidth/2}px,${point.y-packet.offsetTop-packet.offsetHeight/2}px) scale(${1+.16*Math.sin(travel*Math.PI)})`;
  packet.style.opacity=still?'0':String(progress>0&&progress<1?1:0);
  const enter=still?1:Math.min(1,local/.7),slide=(1-enter)**3;
  laptopShell.style.transform=`translate(${-35*slide}px,${30*slide+drift}px) rotate(${-1.2*slide}deg)`;
  phoneShell.style.transform=`translate(${45*slide}px,${-20*slide-drift}px) rotate(${3*slide}deg)`;
  desktop.style.opacity=secondComputer?'1':'0';desktop.style.transform=`translateX(${(1-enter)*45}px)`;
  phoneShell.style.opacity=secondComputer?'0':'1';
  cursor.style.opacity=kind==='deskflow'?'1':'0';keyboard.style.opacity=kind==='deskflow'||kind==='messages'?'1':'0';
  if(wide){keyboard.style.left='210px';keyboard.style.bottom='5px';cursor.style.left='420px';cursor.style.top='430px'}else{keyboard.style.left='180px';keyboard.style.bottom='6px';cursor.style.left='250px';cursor.style.top='370px'}
  cursor.style.transform=`translate(${220*eased}px,${-120*eased}px)`;
  detail.style.transform=`translate(${18*slide}px,${-10*slide+drift*.5}px)`;
  detail.style.opacity=cinematic?'0':String(.85+.15*enter);
  const closing=index===ad.scenes.length-1;
  document.getElementById('cta').style.opacity=cinematic&&!closing?'0':'1';
  root.querySelector('.art-route path').style.strokeDashoffset=String(still?0:-local*24);
  const typed=document.getElementById('art-typed');if(typed)typed.textContent='Coffee at 10'.slice(0,still?12:Math.floor(Math.max(0,progress-.35)/.65*12));
  const reply=document.getElementById('art-reply');if(reply)reply.style.opacity=arrived?'1':'.12';
  const notify=laptop.querySelector('.art-notification');if(notify)notify.style.transform=`translateY(${(1-eased)*25}px)`;
  const avatar=phone.querySelector('.art-avatar');if(avatar&&kind==='calls'){const ring=still?8:8+10*Math.sin(local*4)**2;avatar.style.boxShadow=`0 0 0 ${ring}px #67e8f924,0 0 0 ${ring*1.9}px #67e8f911`}
  const photo=laptop.querySelector('.art-photo');if(photo){photo.style.transform=`translateY(${(1-eased)*12}px) scale(${.9+.1*eased})`;photo.style.opacity=String(.45+.55*eased)}
  const camera=laptop.querySelector('.art-camera');if(camera)camera.style.transform=`perspective(400px) rotateY(${still?0:Math.sin(local)*3}deg)`;
  if(kind==='controls'&&local>2.25){laptop.querySelector('.art-control-row').innerHTML='Find phone <b>Ring</b>';phone.querySelector('.art-state').textContent='Find your phone';if(avatar)avatar.style.boxShadow='0 0 0 12px #67e8f922'}
  laptop.querySelectorAll('.art-overview-features span').forEach((item,i)=>{const on=still||Math.floor(local)%3===i;item.style.background=on?'#164554':'#1e3447';item.style.borderColor=on?'#67e8f9':'#33506a'});
  const clock=scene.tag?.match(/^\d\d:\d\d/);phoneShell.querySelector('.p-status span').textContent=clock?clock[0]:'9:41';
 };
})();
