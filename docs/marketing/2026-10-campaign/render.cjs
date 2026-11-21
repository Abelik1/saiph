// SPDX-License-Identifier: AGPL-3.0-or-later
// Local, deterministic typography animation. No video generation service.
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { spawn, spawnSync } = require('node:child_process');
const { once } = require('node:events');
const { chromium } = require('../../../frontend/node_modules/playwright');

const root = path.resolve(__dirname, '../../..');
const arg = name => {const i=process.argv.indexOf(name);return i<0?undefined:process.argv[i+1];};
const out = path.resolve(arg('--out') || path.join(root,'build/marketing-campaign-20261019'));
const manifest = JSON.parse(fs.readFileSync(path.join(__dirname,'campaign.json'),'utf8'));
const fps = 30;
const htmlEscape = s => String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const cmd = (exe,args) => {const r=spawnSync(exe,args,{encoding:'utf8',windowsHide:true});if(r.status!==0)throw new Error(r.stderr||r.error||`${exe} failed`);return r.stdout;};
function makeReview() {
 const cards=manifest.ads.map(ad=>`<article><div class="media"><video controls playsinline preload="none" poster="videos/${ad.id}-poster.png" src="videos/${ad.id}-vertical.mp4"></video></div><div class="details"><p class="eyebrow">${ad.duration>=30?'32s FULL STORY / 16s QUICK CUT':ad.duration+' SECONDS'} / ${htmlEscape(ad.id)}</p><h2>${htmlEscape(ad.name)}</h2><p>${htmlEscape(ad.primary)}</p><nav><a href="videos/${ad.id}-vertical.mp4" download>${ad.duration>=30?'32s full story':'Vertical MP4'}</a>${ad.duration>=30?`<a href="videos/${ad.id}-quick.mp4" download>16s quick cut</a>`:''}<a href="stills/${ad.id}-portrait.png" download>Portrait PNG</a><a href="stills/${ad.id}-square.png" download>Square PNG</a>${['01-ecosystem-convenience','02-day-in-sync'].includes(ad.id)?`<a href="videos/${ad.id}-landscape.mp4" download>Landscape MP4</a>`:''}</nav><details><summary>Audience, copy options and test idea</summary><p><b>Audience:</b> ${htmlEscape(ad.audience)}</p><p><b>Headline:</b> ${htmlEscape(ad.headline)}</p><p><b>Other hooks:</b> ${ad.alternates.map(htmlEscape).join(' / ')}</p><p><b>Test:</b> ${htmlEscape(ad.hypothesis)}</p><p><b>Grounding:</b> ${htmlEscape(ad.source)}. Device scenes reuse the landing-page artwork styling. Screen content is synthetic illustration, with no live device demonstration or customer evidence implied.</p></details></div></article>`).join('');
 const carousel=manifest.carousel.map((_,i)=>`<a href="carousel/${i+1}.png"><img src="carousel/${i+1}.png" alt="Saiph carousel frame ${i+1}"></a>`).join('');
 return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Saiph / Your devices. Connected.</title><style>*{box-sizing:border-box}body{margin:0;background:#0a0e13;background-image:linear-gradient(#0a0e13b0,#0a0e13c0),url('assets/wave-background.png');background-attachment:fixed;background-size:cover;color:#e7edf4;font:17px/1.65 'Segoe UI',Arial,sans-serif}main{max-width:1320px;margin:auto;padding:70px 40px}header{padding-bottom:55px;border-bottom:1px solid #243142}header img{width:50px;vertical-align:middle;margin-right:14px}.eyebrow{font-size:12px;letter-spacing:2px;color:#67e8f9}h1{font-size:clamp(42px,6vw,78px);line-height:1.03;letter-spacing:-3px;max-width:900px;margin:20px 0}h2{font-size:35px;line-height:1.2;margin:14px 0}p{max-width:820px;color:#a7b6c8}a{color:#67e8f9;text-underline-offset:5px}nav{display:flex;flex-wrap:wrap;gap:12px 24px;margin:24px 0}article{display:grid;grid-template-columns:350px 1fr;gap:65px;padding:55px 0;border-bottom:1px solid #243142}.media video{display:block;width:100%;aspect-ratio:9/16;background:#131a23}.details{align-self:center}summary{cursor:pointer;color:#e7edf4}details p{font-size:15px}section{padding-top:55px}.carousel{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}.carousel img{width:100%;display:block}.loop{width:270px}.note{font-size:14px;color:#94a3b6}footer{margin-top:50px;border-top:1px solid #243142;padding-top:30px}@media(max-width:760px){main{padding:35px 22px}article{grid-template-columns:1fr;gap:25px}.media{max-width:350px}.carousel{grid-template-columns:1fr 1fr}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto}}</style></head><body><main><header><div><img src="assets/logo.svg" alt="Saiph"><span class="eyebrow">CAMPAIGN 01 / OCTOBER 2026</span></div><h1>Your devices.<br>Connected.</h1><p>Two 32-second feature stories, four short supporting ads, matching static artwork and recording scripts. The phone and computer illustrations carry the action, connected by Saiph's cyan and violet waves.</p><p class="note">Review exports. Horizontal waves oscillate across the middle, then slowly open like a curtain to reveal the enlarged devices. Saiph's cyan/violet string field connects the scenes. No AI-generated video. Beta claims require a final release check before publication.</p><nav><a href="CAMPAIGN.md">Campaign and rollout</a><a href="RECORDING-SCRIPTS.md">Recording scripts</a><a href="copy.csv">Ad copy CSV</a><a href="SOURCES.md">Sources and installed skills</a><a href="contact-sheet.png">All static concepts</a></nav></header>${cards}<section><p class="eyebrow">SWIPE FORMAT</p><h2>A clipboard carousel</h2><p>Four ordered 1080 × 1350 frames. Caption: “Copy a link on Android. Paste it on your Windows or Linux computer. Saiph connects your devices. Explore the beta at usesaiph.com.”</p><div class="carousel">${carousel}</div></section><section><p class="eyebrow">LOOP FORMAT</p><h2>A day across your devices</h2><img class="loop" src="loops/day-in-sync.gif" alt="Looping illustrated Saiph feature story"><p class="note">540 × 960 GIF. Use MP4 for feed placements that accept video. This local review does not autoplay videos.</p></section><section><p class="eyebrow">PRODUCT ARTWORK</p><h2>The app behind the message</h2><a href="stills/07-app-preview.png"><img style="max-width:600px;width:100%" src="stills/07-app-preview.png" alt="Saiph self-hosted app design preview poster"></a><p class="note">Existing repository design preview with synthetic data. Self-hosted photo browsing shown. This is not footage of a live phone.</p></section><footer><p>Saiph beta. Android with Windows/Linux. Feature availability depends on mode and device. Apple and Continuity are trademarks of Apple Inc. Microsoft and Phone Link are Microsoft trademarks. Saiph is independent and is not affiliated with or endorsed by either company.</p></footer></main></body></html>`;
}

async function main(){
 if(process.argv.includes('--resume'))for(const file of ['motion.html','device-art.css','device-art.js','wave-art.css','wave-art.js','campaign.json']){
  const existing=path.join(out,file);if(!fs.existsSync(existing))throw new Error('Missing resume source: '+file);
  const before=fs.readFileSync(existing),after=fs.readFileSync(path.join(__dirname,file));
  const visualManifest=buffer=>{const data=JSON.parse(buffer);return JSON.stringify({ads:data.ads.map(({id,theme,duration,poster,scenes})=>({id,theme,duration,poster,scenes})),carousel:data.carousel})};
  if(file==='campaign.json'?visualManifest(before)!==visualManifest(after):!before.equals(after))throw new Error('Cannot resume after visual-source changes: '+file);
 }
 for(const dir of ['assets','stills','videos','carousel','loops','checks','storyboards'])fs.mkdirSync(path.join(out,dir),{recursive:true});
 fs.copyFileSync(path.join(root,'website/assets/logo.svg'),path.join(out,'assets/logo.svg'));
 const landingCss=fs.readFileSync(path.join(root,'website/assets/site.css'),'utf8');
 const deviceStart=landingCss.indexOf('.dev {'),deviceEnd=landingCss.indexOf('.skip-link {',deviceStart);
 if(deviceStart<0||deviceEnd<0)throw new Error('Landing-page device styles not found');
 fs.writeFileSync(path.join(out,'assets/landing-devices.css'),'/* SPDX-License-Identifier: AGPL-3.0-or-later; from website/assets/site.css */\n'+landingCss.slice(deviceStart,deviceEnd));
 fs.copyFileSync(path.join(root,'docs/images/readme/desktop-photos.png'),path.join(out,'assets/desktop-photos.png'));
 for(const file of ['motion.html','device-art.css','device-art.js','wave-art.css','wave-art.js','campaign.json','CAMPAIGN.md','RECORDING-SCRIPTS.md','SOURCES.md','VALIDATION.md','results-template.csv'])fs.copyFileSync(path.join(__dirname,file),path.join(out,file));
 let review=makeReview();
 const expansion=path.join(root,'build/marketing-audience-expansion-20261019');
 if(fs.existsSync(path.join(expansion,'index.html'))){
  fs.cpSync(expansion,path.join(out,'audience-expansion'),{recursive:true});
  const banner='<aside style="padding:24px;margin:28px 0;border:1px solid #3e617a;border-radius:16px;background:#122432"><p class="eyebrow">NEW / MORE AUDIENCES, MORE FORMATS</p><h2 style="font-size:28px">Eight more ways into Saiph.</h2><p>Students, creators, everyday phone/PC users, desk workers and mixed-device enthusiasts. Comics, photo stories, notification motion, GIFs, diagrams, carousels and search copy.</p><a href="audience-expansion/index.html">Explore the new audience campaign →</a></aside>';
  review=review.replace('<nav><a href="CAMPAIGN.md">',banner+'<nav><a href="CAMPAIGN.md">');
 }
 fs.writeFileSync(path.join(out,'index.html'),review);
 const quote=s=>'"'+String(s).replace(/"/g,'""')+'"';
 const fields=['creative_id','headline','primary_text','short_caption','cta','destination','audience','grounding','test_hypothesis'];
 const rows=manifest.ads.map(a=>[a.id,a.headline,a.primary,a.short,manifest.cta,manifest.destination,a.audience,a.source,a.hypothesis]);
 fs.writeFileSync(path.join(out,'copy.csv'),'\uFEFF'+[fields,...rows].map(row=>row.map(quote).join(',')).join('\r\n'));
 for(const a of manifest.ads){if(a.headline.length>40||a.short.length>80)throw new Error(`Copy length: ${a.id}`)}
 if(process.argv.includes('--review-only')){console.log('Updated campaign review and source copies: '+out);return}
 const server=http.createServer((req,res)=>{try{const file=path.resolve(out,'.'+decodeURIComponent(req.url.split('?')[0]==='/'?'/index.html':req.url.split('?')[0]));if(!file.startsWith(out+path.sep)){res.writeHead(403).end();return}const ext=path.extname(file);res.setHeader('Content-Type',({'.html':'text/html','.css':'text/css','.js':'application/javascript','.svg':'image/svg+xml','.png':'image/png','.json':'application/json','.mp4':'video/mp4','.gif':'image/gif'})[ext]||'text/plain');res.end(fs.readFileSync(file))}catch{res.writeHead(404).end()}});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const url=`http://127.0.0.1:${server.address().port}`;
 const fallback=path.join(process.env.LOCALAPPDATA||'','ms-playwright/chromium-1234/chrome-win64/chrome.exe');
 const executablePath=arg('--browser')||(fs.existsSync(chromium.executablePath())?chromium.executablePath():fallback);
 let browser;
 const report={date:manifest.date,fps,artwork:[],videos:[],layout:[],phases:[],scope:'Campaign artwork only. No app, account or physical device operated.'};
 try{
  browser=await chromium.launch({headless:true,executablePath,args:['--no-first-run']});
  const context=await browser.newContext({viewport:{width:1080,height:1920},deviceScaleFactor:1});
  const page=await context.newPage();page.on('pageerror',e=>{throw e});
  const cdp=await context.newCDPSession(page);
  await page.goto(url+'/motion.html');
  async function setup(ad,format,poster){const size=await page.evaluate(({ad,format,poster})=>window.setup(ad,format,poster),{ad,format,poster});await page.setViewportSize({width:size[0],height:size[1]});await page.evaluate(()=>document.fonts.ready);return size}
  async function check(label){const errors=await page.evaluate(()=>window.checkLayout());if(errors.length)throw new Error(label+': '+errors.join('; '));report.layout.push(label)}
  for(const ad of manifest.ads){
   for(const [format,suffix] of [['poster','portrait'],['square','square']]){
    await setup(ad,format,ad.poster);await page.evaluate(()=>window.renderAt(1,true));await check(ad.id+'/'+format);
    const file=`stills/${ad.id}-${suffix}.png`;await page.screenshot({path:path.join(out,file)});report.artwork.push(file);
    if(ad.id===manifest.ads[0].id&&format==='poster'){
     const background=await page.evaluate(()=>document.getElementById('wave-background').toDataURL('image/png').split(',')[1]);fs.writeFileSync(path.join(out,'assets/wave-background.png'),Buffer.from(background,'base64'));
    }
   }
  }
  for(let i=0;i<manifest.carousel.length;i++){await setup(manifest.ads[1],'poster',manifest.carousel[i]);await page.evaluate(()=>window.renderAt(1,true));await check(`carousel/${i+1}`);const file=`carousel/${i+1}.png`;await page.screenshot({path:path.join(out,file)});report.artwork.push(file)}
  await page.setViewportSize({width:1080,height:1350});
  await page.setContent(`<html><body style="margin:0;background:#0a0e13;color:#e7edf4;font-family:'Segoe UI',Arial,sans-serif;padding:90px;box-sizing:border-box;height:1350px"><div style="font-size:40px;display:flex;align-items:center;gap:16px"><img src="${url}/assets/logo.svg" width="50">saiph</div><p style="color:#67e8f9;font-size:22px;letter-spacing:3px;margin-top:65px">YOUR DEVICES. CONNECTED.</p><h1 style="font-size:94px;line-height:1.04;letter-spacing:-5px;margin:25px 0 40px">Your phone.<br>Your photos.<br>Your computer.</h1><img src="${url}/assets/desktop-photos.png" style="width:900px"><p style="font-size:24px;color:#a7b6c8">Self-hosted app design preview. Synthetic data.<br>Recent-photo browsing requires a self-hosted Hub.</p><p style="font-size:29px;margin-top:35px">Explore the beta &nbsp; usesaiph.com</p><p style="font-size:23px;color:#a7b6c8">Android + Windows / Linux</p></body></html>`);
  await page.evaluate(url=>{document.body.style.padding='80px';document.body.style.backgroundImage=`url("${url}/assets/wave-background.png")`;document.body.style.backgroundSize='cover';document.querySelector('h1').style.fontSize='82px';document.querySelector('h1').style.marginBottom='30px';document.querySelector('p').style.marginTop='45px';return Promise.all(Array.from(document.images).map(i=>i.decode()))},url);
  if(await page.evaluate(()=>document.body.scrollHeight>1350))throw new Error('App poster overflow');
  await page.screenshot({path:path.join(out,'stills/07-app-preview.png')});report.artwork.push('stills/07-app-preview.png');
  await page.setViewportSize({width:1500,height:1210});
  await page.setContent(`<html><body style="margin:0;background:#10141c;padding:35px;font-family:'Segoe UI',Arial,sans-serif;color:#e7edf4"><h1 style="margin:0 0 24px">Saiph / Campaign 01</h1><div style="display:grid;grid-template-columns:repeat(3,1fr);gap:22px">${manifest.ads.map(a=>`<div><img style="width:100%;height:490px;object-fit:contain" src="${url}/stills/${a.id}-portrait.png"><p style="margin:5px">${htmlEscape(a.id)} / ${a.duration}s</p></div>`).join('')}</div></body></html>`);
  await page.evaluate(()=>Promise.all(Array.from(document.images).map(i=>i.decode())));await page.screenshot({path:path.join(out,'contact-sheet.png')});
  await page.goto(url+'/motion.html');
  if(!process.argv.includes('--stills-only')){
   for(const ad of manifest.ads){for(const format of ['vertical',...(['01-ecosystem-convenience','02-day-in-sync'].includes(ad.id)?['landscape']:[])]){
    const size=await setup(ad,format);
    for(const scene of ad.scenes){await page.evaluate(t=>window.renderAt(t,true),scene.at+1);await check(ad.id+'/'+format+'/'+scene.at);await page.screenshot({path:path.join(out,`checks/${ad.id}-${format}-${scene.at}.png`)});
     const beat=await page.evaluate(({ad,scene,index})=>window.campaignBeat(ad,scene,index),{ad,scene,index:ad.scenes.indexOf(scene)});
     const phases=[];for(const offset of [.4,beat.hold+.35,beat.hold+beat.oscillate+beat.unveil*.5,beat.hold+beat.oscillate+beat.unveil+.05]){
      phases.push(await page.evaluate(t=>{window.renderAt(t);const art=document.getElementById('device-art'),curtain=document.getElementById('wave-transition');return {text:Array.from(document.querySelectorAll('.scene')).some(e=>Number(e.style.opacity)>.6),art:Number(art.style.opacity),clip:art.style.clipPath,phase:curtain.dataset.phase,curtain:Number(curtain.style.opacity)}},scene.at+offset));
     }
     if(!phases[0].text||phases[0].art>.2||phases[1].phase!=='oscillating'||phases[1].curtain<.9||phases[1].clip==='none'||phases[2].text||phases[2].phase!=='opening'||phases[2].clip==='none'||phases[3].text||phases[3].art<.98||phases[3].clip!=='none'||phases[3].curtain!==0)throw new Error('Horizontal wave curtain failed: '+ad.id+'/'+scene.at);report.phases.push(ad.id+'/'+format+'/'+scene.at);
     if(scene===ad.scenes[0])for(const [name,offset] of [['oscillate',beat.hold+.35],['unveil',beat.hold+beat.oscillate+beat.unveil*.5]]){await page.evaluate(t=>window.renderAt(t),offset);await page.screenshot({path:path.join(out,`checks/${ad.id}-${format}-curtain-${name}.png`)})}
    }
    if(format==='vertical'){await page.evaluate(()=>window.renderAt(.48));await page.screenshot({path:path.join(out,`videos/${ad.id}-poster.png`)})}
    if(process.argv.includes('--preflight'))continue;
    const file=`videos/${ad.id}-${format}.mp4`;
    if(process.argv.includes('--resume')&&fs.existsSync(path.join(out,file))){
     try{const probe=JSON.parse(cmd('ffprobe',['-v','error','-show_streams','-show_format','-of','json',path.join(out,file)]));const v=probe.streams.find(s=>s.codec_type==='video');
      if(v.width===size[0]&&v.height===size[1]&&Number(probe.format.duration)===ad.duration&&v.pix_fmt==='yuv420p'&&v.avg_frame_rate==='30/1'){
       report.videos.push({file,width:v.width,height:v.height,seconds:Number(probe.format.duration),codec:v.codec_name,pixelFormat:v.pix_fmt,frameRate:v.avg_frame_rate,frames:Number(v.nb_frames)});console.log('Reused completed '+file);continue;
      }
     }catch{}
    }
    const encoder=spawn('ffmpeg',['-y','-hide_banner','-loglevel','error','-f','image2pipe','-vcodec','mjpeg','-framerate',String(fps),'-i','pipe:0','-an','-vf','scale=in_range=full:out_range=tv,format=yuv420p','-c:v','libx264','-preset','fast','-crf','19','-pix_fmt','yuv420p','-color_range','tv','-movflags','+faststart',path.join(out,file)],{windowsHide:true,stdio:['pipe','ignore','pipe']});
    let err='';encoder.stderr.on('data',b=>err+=b);const done=once(encoder,'close');
    let lastSample=-1,buffer;
    for(let frame=0;frame<ad.duration*fps;frame++){
     const time=frame/fps;const sceneStart=ad.scenes.filter(s=>s.at<=time).at(-1).at;
     // Render continuous camera and device motion throughout every story beat.
     const sample=time;
     if(sample!==lastSample){await page.evaluate(t=>window.renderAt(t),sample);buffer=Buffer.from((await cdp.send('Page.captureScreenshot',{format:'jpeg',quality:94,fromSurface:true,captureBeyondViewport:false,optimizeForSpeed:true})).data,'base64');lastSample=sample}
     if(!encoder.stdin.write(buffer))await once(encoder.stdin,'drain');
    }
    encoder.stdin.end();const [code]=await done;if(code!==0)throw new Error(err);
    const probe=JSON.parse(cmd('ffprobe',['-v','error','-show_streams','-show_format','-of','json',path.join(out,file)]));const stream=probe.streams.find(s=>s.codec_type==='video');
    if(stream.width!==size[0]||stream.height!==size[1]||Math.abs(Number(probe.format.duration)-ad.duration)>.05||stream.pix_fmt!=='yuv420p'||stream.avg_frame_rate!=='30/1')throw new Error('Export mismatch '+file);
    report.videos.push({file,width:stream.width,height:stream.height,seconds:Number(probe.format.duration),codec:stream.codec_name,pixelFormat:stream.pix_fmt,frameRate:stream.avg_frame_rate,frames:Number(stream.nb_frames)});
    console.log('Rendered '+file);
   }}
   if(!process.argv.includes('--preflight'))for(const ad of manifest.ads.slice(0,2)){
    const file=`videos/${ad.id}-quick.mp4`;
    cmd('ffmpeg',['-y','-hide_banner','-loglevel','error','-i',path.join(out,`videos/${ad.id}-vertical.mp4`),'-vf','setpts=0.5*PTS','-r','30','-t','16','-frames:v','480','-an','-c:v','libx264','-preset','fast','-crf','19','-pix_fmt','yuv420p','-movflags','+faststart',path.join(out,file)]);
    const probe=JSON.parse(cmd('ffprobe',['-v','error','-show_streams','-show_format','-of','json',path.join(out,file)]));const v=probe.streams.find(s=>s.codec_type==='video');
    if(Math.abs(Number(probe.format.duration)-16)>.05)throw new Error('Quick-cut duration mismatch');
    report.videos.push({file,width:v.width,height:v.height,seconds:Number(probe.format.duration),codec:v.codec_name,pixelFormat:v.pix_fmt,frameRate:v.avg_frame_rate,frames:Number(v.nb_frames)});
   }
   if(!process.argv.includes('--preflight'))cmd('ffmpeg',['-y','-hide_banner','-loglevel','error','-i',path.join(out,'videos/02-day-in-sync-vertical.mp4'),'-filter_complex','[0:v]fps=10,scale=540:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96[p];[b][p]paletteuse=dither=bayer','-loop','0',path.join(out,'loops/day-in-sync.gif')]);
  }
  if(!process.argv.includes('--stills-only')){
   for(const [i,ad] of manifest.ads.slice(0,2).entries()){
    await page.setViewportSize({width:2000,height:720});
    await page.setContent(`<html><body style="margin:0;padding:25px;background:#10141c;color:#e7edf4;font-family:'Segoe UI',Arial,sans-serif"><h1 style="font-size:30px;margin:0 0 18px">${htmlEscape(ad.name)} / 32 seconds</h1><div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px">${ad.scenes.map(s=>`<div><img style="width:100%;display:block" src="${url}/checks/${ad.id}-landscape-${s.at}.png"><p style="font-size:16px;margin:5px 0">${s.at}–${s.at+4}s / ${htmlEscape(s.kind)}</p></div>`).join('')}</div></body></html>`);
    await page.evaluate(()=>Promise.all(Array.from(document.images).map(img=>img.decode())));
    await page.screenshot({path:path.join(out,`storyboards/plot-${i===0?'a':'b'}.png`)});
   }
  }
  await page.setViewportSize({width:1440,height:1000});await page.goto(url);await page.screenshot({path:path.join(out,'checks/review-desktop.png')});
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(out,'checks/review-mobile.png')});
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw new Error('Review mobile overflow');
  fs.writeFileSync(path.join(out,'checks/validation.json'),JSON.stringify(report,null,2));
  console.log('Campaign exported: '+out);
 } finally{if(browser)await browser.close();await new Promise(resolve=>server.close(resolve))}
}
main().catch(e=>{console.error(e);process.exitCode=1});
