// SPDX-License-Identifier: AGPL-3.0-or-later
// Deterministic SVG artwork; synthetic screens, no generative video or device access.
(() => {
 const e=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}[c]));
 const clamp=n=>Math.max(0,Math.min(1,n)),smooth=n=>{const p=clamp(n);return p*p*(3-2*p)};
 const rect=(x,y,w,h,fill='#101d2b',stroke='#38516a',r=20)=>`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${r}" fill="${fill}" stroke="${stroke}" stroke-width="2"/>`;
 const text=(x,y,s,size=28,fill='#e7edf4',weight=500,extra='')=>`<text x="${x}" y="${y}" font-size="${size}" fill="${fill}" font-weight="${weight}" ${extra}>${e(s)}</text>`;
 const label=(x,y,s)=>text(x,y,s,21,'#95acbf',600,'letter-spacing="2"');
 const logo=(x,y,w)=>`<svg x="${x}" y="${y}" width="${w}" height="${w}" viewBox="0 0 32 32"><circle cx="16" cy="16" r="15" fill="#0f1a22" stroke="#22d3ee" stroke-opacity=".35"/><path d="M8 21 16 16 24 11" stroke="#22d3ee" stroke-opacity=".35" stroke-width="1.2"/><circle cx="8.5" cy="20.7" r="2.4" fill="#67e8f9"/><circle cx="16" cy="16" r="2.4" fill="#e7edf4"/><circle cx="23.5" cy="11.3" r="2.4" fill="#67e8f9"/></svg>`;
 const picture=(x,y,w,h)=>`<svg x="${x}" y="${y}" width="${w}" height="${h}" viewBox="0 0 400 260" preserveAspectRatio="xMidYMid slice"><rect width="400" height="260" fill="#bd977c"/><circle cx="306" cy="65" r="37" fill="#f7d8a2"/><path d="M0 200 126 50 270 260H0Z" fill="#304c60"/><path d="m65 122 61-72 76 110-68-33-22 25Z" fill="#d8e7dc"/><path d="m132 260 170-160 98 93v67Z" fill="#173c45"/><path d="M0 230Q120 170 220 235T440 220V280H0Z" fill="#6b9690"/></svg>`;
 const note=(s='Seminar notes')=>`${text(13,30,s,19,'#e7edf4',650)}${[57,81,105].map((y,i)=>`<path d="M14 ${y}h${[112,90,104][i]}" stroke="#67e8f9" stroke-width="6" stroke-linecap="round"/>`).join('')}`;
 function phone(x,y,w,body='notes',screenText='Seminar notes'){
  const screens={notes:note(screenText),photo:picture(5,35,144,200),notification:`${text(12,34,'REMINDER',13,'#67e8f9')}${rect(8,55,138,110,'#183547','#376574',10)}${text(18,86,'Review',19)}${text(18,111,'the draft.',19)}`,link:`${text(12,36,'Copied link',18,'#67e8f9')}${rect(8,58,138,100,'#183547','#376574',10)}${text(18,94,'reading list',19)}${text(18,127,'Copy',17,'#67e8f9')}`,home:`${logo(39,65,76)}${text(77,183,'Android',19,'#67e8f9',500,'text-anchor="middle"')}`};
  return `<g transform="translate(${x} ${y}) scale(${w/180})">${rect(0,0,180,340,'#101720','#3c4a5d',26)}${rect(9,11,162,318,'#0c121b','#1d2c3c',20)}<circle cx="90" cy="22" r="5" fill="#02070b"/>${text(21,36,'9:41',10)}<g transform="translate(13 45)">${screens[body]||screens.home}</g><path d="M67 315h46" stroke="#a5afbd" stroke-width="3" stroke-linecap="round"/></g>`;
 }
 function laptop(x,y,w,body='notes',title='Windows / Linux'){
  const bodies={notes:`${label(35,95,'YOUR DRAFT')}${text(35,139,'Seminar notes',29)}${[169,191,213].map((yy,i)=>`<path d="M35 ${yy}h${[220,170,200][i]}" stroke="#5c8494" stroke-width="5"/>`).join('')}`,photo:picture(24,67,372,184),notification:`${text(28,102,'Your current work',28)}${rect(118,130,270,100,'#173b4a','#67e8f9',13)}${text(134,163,'FROM YOUR ANDROID',14,'#67e8f9')}${text(134,196,'Review the draft.',24)}`,link:`${label(30,98,'PASTED ON YOUR COMPUTER')}${rect(28,123,365,76,'#173b4a','#67e8f9',10)}${text(43,170,'reading list',31)}`,home:`${logo(168,97,70)}${text(205,211,title,28,'#e7edf4',600,'text-anchor="middle"')}`};
  return `<g transform="translate(${x} ${y}) scale(${w/460})">${rect(10,0,440,286,'#182436','#435367',15)}${rect(22,13,416,260,'#0a121d','#293d53',6)}<path d="M24 48h412" stroke="#293d53"/><circle cx="39" cy="31" r="4" fill="#52738c"/><circle cx="53" cy="31" r="4" fill="#52738c"/>${text(73,37,'Saiph',17,'#a7b6c8')}${bodies[body]||bodies.home}<path d="M10 286 0 302Q225 319 460 302L450 286Z" fill="#324255" stroke="#526174"/>${text(230,348,title,23,'#a7b6c8',600,'text-anchor="middle"')}</g>`;
 }
 function route(x1,y1,x2,y2,t=1){
  const bend=Math.min(y1,y2)-60,d=`M${x1} ${y1}C${x1+40} ${bend} ${x2-40} ${bend} ${x2} ${y2}`;
  return `<path d="${d}" fill="none" stroke="#67e8f9" stroke-width="3"/><path d="${d}" fill="none" stroke="#a78bfa" stroke-width="1" transform="translate(0 9)"/><circle cx="${x1+(x2-x1)*t}" cy="${y1+(y2-y1)*t-42*Math.sin(t*Math.PI)}" r="8" fill="#b9f6ff"/>`;
 }
 function graphic(ad,t,still){
  const p=still?1:smooth((t-2)/6),end=still||t>ad.duration-2;
  if(ad.design==='comic')return [0,1,2].map(i=>{
   const active=still||Math.floor(t/3.4)>=i,ink=active?'#67e8f9':'#38516a';
   return `<g transform="translate(${i*257} 0)" opacity="${active?1:.22}">${rect(0,0,240,490,'#10202c',ink,14)}${label(20,40,['01 CAPTURE','02 CONNECT','03 CONTINUE'][i])}${i===0?phone(39,85,160,'notes'):i===1?`${rect(33,110,174,205,'#e7edf4','#67e8f9',6)}<g transform="translate(45 130)">${note()}</g>${route(80,365,170,365,p)}`:laptop(7,150,225,'notes','Your laptop')}${text(120,452,['On your phone.','Send across.','In your draft.'][i],24,'#e7edf4',600,'text-anchor="middle"')}</g>`;
  }).join('');
  if(ad.design==='photo'){
   const zoom=still?1:1.6-.6*smooth(t/6),shift=still?0:60*(1-smooth(t/6));
   return `<g transform="translate(${-shift} ${-shift*.3}) scale(${zoom})"><g opacity="${still?1:smooth(t/3)}">${phone(5,50,172,'photo')}</g>${rect(213,3,528,275,'#122434','#567483',10)}${picture(223,13,508,255)}${route(135,278,445,340,p)}<g opacity="${still?1:smooth((t-3)/3)}">${laptop(290,230,400,'photo','Your next edit starts here')}</g></g>`;
  }
  if(ad.design==='focus'){
   const q=still?1:smooth((t-2.5)/2.8),x=40+q*200,y=50+q*95;
   return `${phone(8,100,170,'notification')}${laptop(220,125,500,'home')}${route(160,190,480,290,p)}<g transform="translate(${x} ${y})">${rect(0,0,475,115,'#183a4b','#67e8f9',18)}${label(22,33,'FROM YOUR ANDROID')}${text(22,79,'Review the draft.',35)}</g>${text(480,527,'The alert comes to your screen.',26,'#e7edf4',500,'text-anchor="middle"')}`;
  }
  if(ad.design==='beforeafter'){
   const after=still||t>=3;
   return `${rect(0,0,357,500,'#14202c','#3e5066',16)}${rect(389,0,357,500,'#10323b',after?'#67e8f9':'#3e5066',16)}${label(23,40,'THE ROUND TRIP')}${label(413,40,'COPY → PASTE')}<g opacity="${after?.4:1}">${phone(36,90,113,'link')}<path d="m185 178 50-36 50 36v52H185Z" fill="#5f7084"/><path d="m185 178 50 28 50-28" stroke="#c7d4df" fill="none" stroke-width="3"/>${laptop(56,300,247,'link','')}</g>${phone(410,90,113,'link')}${route(505,230,645,325,p)}${laptop(468,300,247,'link','')}${text(178,480,'Send. Find. Open.',24,'#9bafbf',500,'text-anchor="middle"')}${text(567,480,'Keep going.',28,'#67e8f9',650,'text-anchor="middle"')}`;
  }
  if(ad.design==='dualos'){
   const cursorX=still?570:170+400*smooth((t-1)/4);
   return `${laptop(0,55,345,'home','Windows')}${laptop(400,55,345,'home','Linux')}${route(170,340,570,340,p)}<path d="m${cursorX} 207 0 48 13-12 10 22 10-5-11-21 18-2Z" fill="#e7edf4" stroke="#0a0e13" stroke-width="3"/>${rect(180,423,385,75,'#173144','#3e617a',16)}${text(372,471,'Deskflow + your Hub',28,'#67e8f9',650,'text-anchor="middle"')}`;
  }
  if(ad.design==='blueprint')return `${route(154,240,375,365,.35)}${route(600,250,375,365,.7)}${phone(60,25,145,'home')}${laptop(410,75,330,'home','')}${rect(270,330,210,160,'#132a38','#67e8f9',15)}${[365,395,425].map(yy=>`${rect(290,yy,170,19,'#264a5a','#477484',3)}<circle cx="445" cy="${yy+9}" r="4" fill="#67e8f9"/>`).join('')}${text(375,525,'YOUR HUB',29,'#67e8f9',650,'text-anchor="middle"')}${label(45,330,'YOUR PHONE')}${label(520,330,'YOUR COMPUTER')}`;
  if(ad.design==='faq')return `${laptop(8,50,355,'home','Windows')}${laptop(385,50,355,'home','Linux')}${route(190,365,560,365,.5)}${phone(295,170,170,'home')}${rect(17,435,200,74,'#123e46','#67e8f9',16)}${text(117,480,'Clipboard',28,'#e7edf4',600,'text-anchor="middle"')}${rect(528,435,220,74,'#262143','#a78bfa',16)}${text(638,480,'Photos + files',27,'#e7edf4',600,'text-anchor="middle"')}`;
  return `${laptop(0,135,520,'home')}${route(475,290,580,180,.6)}${phone(535,10,205,'home')}${text(200,90,'YOUR DEVICES.',46,'#67e8f9',750)}${text(200,145,'ONE CONNECTION.',39,'#e7edf4',650)}`;
 }
 const steps={comic:['Capture a note.','Send it across.','Continue your draft.'],photo:['Capture something.','Send it to your computer.','Keep creating.'],focus:['Your phone gets an alert.','It arrives on your computer.','Stay with your screen.'],beforeafter:['Still emailing yourself?','Copy here. Paste there.'],dualos:['Windows at one end.','Linux at the other.','One keyboard and mouse.']};
 window.renderCreative=(ad,time=0,format='portrait',still=false,card=null)=>{
  const h=format==='vertical'?1920:format==='square'?1080:1350,vertical=format==='vertical',square=format==='square';
  const x=vertical?180:100,w=vertical?720:880,brandY=vertical?250:70,titleY=vertical?365:square?167:185;
  const heroY=vertical?590:square?360:480,heroH=vertical?610:square?480:565,footerY=vertical?1290:square?900:1170;
  const light=['comic','faq'].includes(ad.design),bg=light?'#e7edf4':ad.design==='photo'?'#171323':'#0a111b',ink=light?'#102435':'#e7edf4',muted=light?'#405b6b':'#a7b6c8',accent=light?'#216373':'#67e8f9';
  const lines=card?card.lines:ad.lines,subtitle=card?card.sub:ad.sub;
  const reducedTitle=!still&&time>2&&steps[ad.design],stageIndex=ad.design==='beforeafter'?(time>=3?1:0):Math.min(2,Math.floor(time/4));
  let titleLines=reducedTitle?[steps[ad.design][stageIndex]]:lines;
  let font=reducedTitle?(vertical?55:64):(square?66:80);
  const maxChars=Math.max(...titleLines.map(s=>s.length));font=Math.min(font,w/(maxChars*.57));
  const field=Array.from({length:22},(_,i)=>{let d='';for(let xx=-30;xx<=1110;xx+=30){const yy=(i+1)*h/23+Math.sin(xx/1080*5+i*.21+time*.15)*34+Math.sin(xx/1080*12-time*.2)*8;d+=`${xx===-30?'M':'L'}${xx} ${yy.toFixed(2)} `}return `<path d="${d}" fill="none" stroke="${i%3===0?'#a78bfa':'#22d3ee'}" stroke-opacity="${light?.13:.12}"/>`}).join('');
  let art=graphic(ad,time,still);
  if(card){const mock={...ad,design:card.design||ad.design};art=graphic(mock,ad.duration||8,true)}
  const markup=`<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="1080" height="${h}" viewBox="0 0 1080 ${h}" role="img" aria-label="${e(ad.name)}" style="font-family:Segoe UI,Arial,sans-serif"><rect width="1080" height="${h}" fill="${bg}"/>${field}<g id="brand" data-safe="text">${logo(x,brandY,48)}${text(x+63,brandY+37,'saiph',40,ink,700)}${text(x+w,brandY+33,card?`${card.number} / 4`:ad.kicker,18,accent,650,'text-anchor="end" letter-spacing="2"')}</g><g id="heading" data-safe="text">${titleLines.map((s,i)=>text(x,titleY+i*font*1.08,s,font,i===titleLines.length-1?accent:ink,750,'letter-spacing="-2"')).join('')}</g><g id="subheading" data-safe="text">${(reducedTitle?[]:subtitle).map((s,i)=>text(x,titleY+(titleLines.length-1)*font*1.08+62+i*35,s,27,muted,450)).join('')}</g><rect id="hero-frame" x="${100}" y="${heroY}" width="${880}" height="${heroH}" fill="none"/><svg id="hero" overflow="hidden" x="${100}" y="${heroY}" width="${880}" height="${heroH}" viewBox="0 0 760 540">${art}</svg><g id="footer" data-safe="text">${text(x,footerY,'Explore the beta',24,muted,500)}${text(x,footerY+44,'usesaiph.com',37,ink,700)}${text(x,footerY+85,ad.qualifier[0],20,muted)}${ad.qualifier[1]?text(x,footerY+115,ad.qualifier[1],20,muted):''}</g>${text(540,vertical?1240:h-35,'Illustrated concept · synthetic content',16,muted,400,'text-anchor="middle"')}</svg>`;
  document.body.innerHTML=markup;document.body.style.margin='0';document.body.style.background=bg;
  return {width:1080,height:h};
 };
 window.checkCreative=()=>{
  const svg=document.querySelector('body>svg'),vertical=svg.height.baseVal.value===1920,errors=[];
  for(const el of document.querySelectorAll('[data-safe="text"]')){
   if(!el.childElementCount)continue;
   const b=el.getBoundingClientRect(),bounds=vertical?[180,220,900,1420]:[60,20,1020,svg.height.baseVal.value-20];
   if(b.left<bounds[0]-1||b.top<bounds[1]-1||b.right>bounds[2]+1||b.bottom>bounds[3]+1)errors.push(el.id+' outside text area');
  }
  const a=document.getElementById('heading').getBoundingClientRect(),b=document.getElementById('subheading').getBoundingClientRect(),hero=document.getElementById('hero-frame').getBoundingClientRect(),footer=document.getElementById('footer').getBoundingClientRect();
  if(b.height&&b.bottom>hero.top-15)errors.push('subtitle overlaps artwork');
  if(a.bottom>hero.top-15)errors.push('headline overlaps artwork');
  if(hero.bottom>footer.top-15)errors.push('artwork overlaps footer');
  return errors;
 };
})();
