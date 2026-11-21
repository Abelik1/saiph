// SPDX-License-Identifier: AGPL-3.0-or-later
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),crypto=require('node:crypto');
const {spawn,spawnSync}=require('node:child_process'),{once}=require('node:events');
const {chromium}=require('../../../frontend/node_modules/playwright');
const root=path.resolve(__dirname,'../../..'),arg=n=>{const i=process.argv.indexOf(n);return i<0?undefined:process.argv[i+1]};
const out=path.resolve(arg('--out')||'build/marketing-audience-expansion-20261019');
const manifest=JSON.parse(fs.readFileSync(path.join(__dirname,'campaign.json'),'utf8'));
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const command=(exe,args)=>{const r=spawnSync(exe,args,{windowsHide:true,encoding:'utf8'});if(r.status!==0)throw Error(r.stderr||String(r.error));return r.stdout};
function review(){
 const cards=manifest.ads.map(a=>`<article data-kind="${a.duration?'motion':'static'}"><p class="eyebrow">${esc(a.audience)}</p><h2>${esc(a.name)}</h2><p>${esc(a.format)}</p>${a.duration?`<video controls playsinline preload="none" poster="stills/${a.id}-portrait.png" src="videos/${a.id}.mp4"></video>`:`<a href="stills/${a.id}-portrait.png"><img src="stills/${a.id}-portrait.png" alt="${esc(a.name)}"></a>`}<nav><a href="stills/${a.id}-portrait.png">Portrait PNG</a><a href="stills/${a.id}-square.png">Square PNG</a><a href="stills/${a.id}-portrait.svg">Editable SVG</a>${a.duration?`<a href="videos/${a.id}.mp4">${a.duration}s MP4</a>`:''}${['beforeafter','dualos'].includes(a.design)?`<a href="loops/${a.id}.gif">GIF</a>`:''}</nav><details><summary>Copy, feature scope and test</summary><p>${esc(a.primary)}</p><p><b>Other hooks:</b> ${a.alternates.map(esc).join(' / ')}</p><p><b>Feature scope:</b> ${a.qualifier.map(esc).join(' · ')}</p><p><b>Test hypothesis:</b> ${esc(a.hypothesis)}</p><p><b>Grounding:</b> ${esc(a.source)}</p></details></article>`).join('');
 const carousels=manifest.carousels.map(c=>`<section><p class="eyebrow">FOUR-CARD CAROUSEL</p><h2>${c.id==='study'?'From class notes to your draft':'A first look at Saiph'}</h2><div class="carousel">${c.cards.map((_,i)=>`<a href="carousels/${c.id}-${i+1}.png"><img src="carousels/${c.id}-${i+1}.png" alt="${esc(c.id)} carousel card ${i+1}"></a>`).join('')}</div><p>${esc(c.caption)}</p></section>`).join('');
 return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Saiph / Eight ways into Saiph</title><style>*{box-sizing:border-box}body{margin:0;background:#0a111b;color:#e7edf4;font:17px/1.65 'Segoe UI',Arial,sans-serif}main{max-width:1300px;margin:auto;padding:65px 35px}.brand{display:flex;align-items:center;gap:15px;font-size:28px}.brand img{width:42px}h1{font-size:clamp(45px,7vw,80px);line-height:1.05;letter-spacing:-3px;max-width:950px;margin:30px 0}h2{font-size:28px;line-height:1.2;margin:12px 0}p{color:#a7b6c8;max-width:850px}.eyebrow{color:#67e8f9;font-size:12px;letter-spacing:1.5px;text-transform:uppercase}a{color:#67e8f9;text-underline-offset:4px}nav{display:flex;gap:12px 24px;flex-wrap:wrap;margin:22px 0}.grid{display:grid;grid-template-columns:1fr 1fr;gap:50px 40px}article{border-top:1px solid #2c3d50;padding-top:24px;min-width:0}article img,article video{display:block;width:100%;aspect-ratio:4/5;object-fit:contain;background:#101a27}article video{aspect-ratio:9/16;max-height:650px}summary{cursor:pointer}details p{font-size:15px}button{font:inherit;background:#122432;border:1px solid #476173;color:#e7edf4;border-radius:30px;padding:9px 22px;cursor:pointer}button[aria-pressed=true]{background:#67e8f9;color:#0a111b;border-color:#67e8f9}.filters{display:flex;gap:12px;flex-wrap:wrap;margin:40px 0 15px}section{margin-top:60px}.carousel{display:grid;grid-template-columns:repeat(4,1fr);gap:15px}.carousel img{width:100%;display:block}.note{font-size:14px}.counts{margin-bottom:30px}footer{margin-top:70px;border-top:1px solid #2c3d50;padding-top:25px}article[hidden]{display:none}@media(max-width:760px){main{padding:35px 22px}.grid{grid-template-columns:1fr;gap:30px}.carousel{grid-template-columns:1fr 1fr}h1{letter-spacing:-2px}}</style></head><body><main><div class="brand"><img src="assets/logo.svg" alt="">saiph</div><p class="eyebrow">AUDIENCE EXPANSION / 19 OCTOBER 2026</p><h1>Eight ways<br>into Saiph.</h1><p>Everyday connections, told eight different ways. A student comic, a photo story, desk notifications, a before/after loop, a mixed-computer cursor journey, a home-server blueprint, a first-look explainer and a keep-your-setup poster.</p><p class="note">8 concepts · 16 static PNGs + editable SVGs · 5 silent motion ads · 2 GIF loops · 2 four-card carousels · 3 recordable demos · 3 search-ad groups. Illustrations use synthetic content. Nothing is published.</p><nav><a href="AUDIENCE-PLAN.md">Audience and test plan</a><a href="RECORDING-SCRIPTS.md">Recordable demos</a><a href="copy.csv">Social ad copy</a><a href="search-copy.csv">Search copy</a><a href="contact-sheet.png">All eight concepts</a><a href="SOURCES.md">Sources</a></nav><div class="filters" role="group" aria-label="Filter creative format"><button data-filter="all" aria-pressed="true">All concepts</button><button data-filter="motion" aria-pressed="false">Motion</button><button data-filter="static" aria-pressed="false">Static concepts</button></div><p class="counts" aria-live="polite">8 concepts</p><div class="grid">${cards}</div>${carousels}<footer><p>Saiph beta. Android with Windows or Linux. Feature scope varies by connection mode and device. This audience expansion adds to the original ecosystem stories.</p></footer></main><script>document.querySelectorAll('[data-filter]').forEach(b=>b.addEventListener('click',()=>{let n=0;document.querySelectorAll('[data-filter]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));document.querySelectorAll('article').forEach(a=>{a.hidden=b.dataset.filter!=='all'&&a.dataset.kind!==b.dataset.filter;if(!a.hidden)n++});document.querySelector('.counts').textContent=n+' concepts'}));</script></body></html>`;
}
async function main(){
 const files=['creative.js','composition.html','campaign.json','AUDIENCE-PLAN.md','RECORDING-SCRIPTS.md','SOURCES.md','VALIDATION.md','search-copy.csv','render.cjs','results-template.csv'];
 for(const d of ['assets','stills','videos','loops','carousels','checks'])fs.mkdirSync(path.join(out,d),{recursive:true});
 if(process.argv.includes('--resume'))for(const f of files.slice(0,3))if(!fs.readFileSync(path.join(out,f)).equals(fs.readFileSync(path.join(__dirname,f))))throw Error('Visual source changed: '+f);
 for(const f of files)if(fs.existsSync(path.join(__dirname,f)))fs.copyFileSync(path.join(__dirname,f),path.join(out,f));
 fs.copyFileSync(path.join(root,'website/assets/logo.svg'),path.join(out,'assets/logo.svg'));
 fs.writeFileSync(path.join(out,'index.html'),review());
 const quote=s=>'"'+String(s).replace(/"/g,'""')+'"',fields=['creative_id','audience','format','headline','primary_text','short_caption','destination','feature_scope','test_hypothesis','source'];
 const rows=manifest.ads.map(a=>[a.id,a.audience,a.format,a.headline,a.primary,a.short,manifest.destination,a.qualifier.join('; '),a.hypothesis,a.source]);
 fs.writeFileSync(path.join(out,'copy.csv'),'\uFEFF'+[fields,...rows].map(row=>row.map(quote).join(',')).join('\r\n'));
 for(const a of manifest.ads)if(a.headline.length>40||a.short.length>80)throw Error('Copy length: '+a.id);
 if(process.argv.includes('--review-only'))return console.log('Updated audience review and document copies');
 const server=http.createServer((req,res)=>{try{const file=path.resolve(out,'.'+(decodeURIComponent(req.url.split('?')[0])==='/'?'/index.html':decodeURIComponent(req.url.split('?')[0])));if(!file.startsWith(out+path.sep))return res.writeHead(403).end();res.setHeader('Content-Type',({'.html':'text/html','.js':'application/javascript','.svg':'image/svg+xml','.png':'image/png','.mp4':'video/mp4','.gif':'image/gif'})[path.extname(file)]||'text/plain');res.end(fs.readFileSync(file))}catch{res.writeHead(404).end()}});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const url=`http://127.0.0.1:${server.address().port}`;
 const report={date:manifest.date,mode:process.argv.includes('--preflight')?'preflight':'full',layout:[],videos:[],loops:[],review:[],scope:'Synthetic marketing assets only; no product, account or physical device operated.'};
 let browser;
 try{
  browser=await chromium.launch({headless:true,executablePath:arg('--browser')||path.join(process.env.LOCALAPPDATA,'ms-playwright/chromium-1234/chrome-win64/chrome.exe'),args:['--no-first-run']});
  const context=await browser.newContext({viewport:{width:1080,height:1350},deviceScaleFactor:1}),page=await context.newPage(),cdp=await context.newCDPSession(page);
  page.on('pageerror',error=>{throw error});await page.goto(url+'/composition.html');
  async function paint(ad,t,format,still,card){const size=await page.evaluate(({ad,t,format,still,card})=>window.renderCreative(ad,t,format,still,card),{ad,t,format,still,card});await page.setViewportSize(size);await page.evaluate(()=>document.fonts.ready);return size}
  async function check(label){const errors=await page.evaluate(()=>window.checkCreative());if(errors.length)throw Error(label+': '+errors.join(', '));report.layout.push(label)}
  for(const ad of manifest.ads)for(const format of ['portrait','square']){
   await paint(ad,ad.duration||8,format,true);await check(ad.id+'/'+format);
   await page.screenshot({path:path.join(out,`stills/${ad.id}-${format}.png`)});
   fs.writeFileSync(path.join(out,`stills/${ad.id}-${format}.svg`),await page.evaluate(()=>document.querySelector('body>svg').outerHTML));
  }
  for(const carousel of manifest.carousels)for(const [i,c] of carousel.cards.entries()){
   const ad=manifest.ads.find(a=>a.id===carousel.ad);await paint(ad,8,'portrait',true,{...c,number:i+1});await check(carousel.id+'/'+(i+1));
   await page.screenshot({path:path.join(out,`carousels/${carousel.id}-${i+1}.png`)});fs.writeFileSync(path.join(out,`carousels/${carousel.id}-${i+1}.svg`),await page.evaluate(()=>document.querySelector('body>svg').outerHTML));
  }
  for(const ad of manifest.ads.filter(a=>a.duration)){
   for(const t of [0,.5,2,4,6,ad.duration-.05]){await paint(ad,t,'vertical',false);await check(ad.id+'/vertical/'+t);if(t===4)await page.screenshot({path:path.join(out,`checks/${ad.id}-motion.png`)})}
   if(process.argv.includes('--preflight'))continue;
   const file=path.join(out,`videos/${ad.id}.mp4`);let reused=false;
   if(process.argv.includes('--resume')&&fs.existsSync(file))try{const p=JSON.parse(command('ffprobe',['-v','error','-show_streams','-show_format','-of','json',file]));const s=p.streams[0];reused=s.width===1080&&s.height===1920&&s.pix_fmt==='yuv420p'&&s.avg_frame_rate==='30/1'&&Number(p.format.duration)===ad.duration}catch{}
   if(!reused){
    const encoder=spawn('ffmpeg',['-y','-hide_banner','-loglevel','error','-f','image2pipe','-vcodec','mjpeg','-framerate','30','-i','pipe:0','-an','-vf','scale=in_range=full:out_range=tv,format=yuv420p','-c:v','libx264','-preset','fast','-crf','19','-pix_fmt','yuv420p','-movflags','+faststart',file],{windowsHide:true,stdio:['pipe','ignore','pipe']});
    let errors='';encoder.stderr.on('data',b=>errors+=b);const done=once(encoder,'close');
    for(let frame=0;frame<ad.duration*30;frame++){await page.evaluate(({ad,t})=>window.renderCreative(ad,t,'vertical',false),{ad,t:frame/30});const buffer=Buffer.from((await cdp.send('Page.captureScreenshot',{format:'jpeg',quality:94,fromSurface:true,captureBeyondViewport:false,optimizeForSpeed:true})).data,'base64');if(!encoder.stdin.write(buffer))await once(encoder.stdin,'drain')}
    encoder.stdin.end();const [code]=await done;if(code!==0)throw Error(errors);
   }
   const p=JSON.parse(command('ffprobe',['-v','error','-show_streams','-show_format','-of','json',file])),s=p.streams[0];
   if(s.codec_name!=='h264'||s.pix_fmt!=='yuv420p'||s.width!==1080||s.height!==1920||s.avg_frame_rate!=='30/1'||Number(p.format.duration)!==ad.duration)throw Error('Bad export: '+ad.id);
   report.videos.push({file:'videos/'+ad.id+'.mp4',width:s.width,height:s.height,seconds:Number(p.format.duration),codec:s.codec_name,pixelFormat:s.pix_fmt,fps:s.avg_frame_rate,frames:Number(s.nb_frames)});console.log((reused?'Reused ':'Rendered ')+ad.id);
   if(['beforeafter','dualos'].includes(ad.design)){
    const gif=path.join(out,`loops/${ad.id}.gif`);command('ffmpeg',['-y','-hide_banner','-loglevel','error','-i',file,'-filter_complex','[0:v]fps=10,scale=540:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96[p];[b][p]paletteuse=dither=bayer','-loop','0',gif]);report.loops.push('loops/'+ad.id+'.gif');
   }
  }
  await page.setViewportSize({width:1600,height:1320});await page.setContent(`<html><body style="margin:0;background:#0a111b;color:#e7edf4;font:24px Segoe UI,Arial;padding:35px"><h1 style="margin:0 0 25px;font-size:38px">Saiph / Eight ways in</h1><div style="display:grid;grid-template-columns:repeat(4,1fr);gap:25px">${manifest.ads.map(a=>`<div><img style="display:block;width:100%" src="${url}/stills/${a.id}-portrait.png"><p style="font-size:19px;margin:7px 0">${esc(a.audience)}</p></div>`).join('')}</div></body></html>`);await page.evaluate(()=>Promise.all(Array.from(document.images).map(i=>i.decode())));await page.screenshot({path:path.join(out,'contact-sheet.png')});
  for(const size of [{width:1440,height:1000},{width:390,height:844}]){
   await page.setViewportSize(size);await page.goto(url);if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Review overflow');
   for(const [filter,count] of [['motion',5],['static',3],['all',8]]){await page.locator(`[data-filter="${filter}"]`).click();if(await page.locator('article:visible').count()!==count)throw Error('Review filter: '+filter)}
   await page.screenshot({path:path.join(out,`checks/review-${size.width}.png`)});report.review.push(size.width);
  }
  fs.writeFileSync(path.join(out,'checks/validation.json'),JSON.stringify(report,null,2));console.log('Audience expansion exported: '+out);
 }finally{if(browser)await browser.close();await new Promise(resolve=>server.close(resolve))}
}
main().catch(error=>{console.error(error);process.exitCode=1});
