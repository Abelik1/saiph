// SPDX-License-Identifier: AGPL-3.0-or-later
// Inline scripts for the /buy and /trial pages, run with the per-request CSP nonce.
// Google Analytics only after the visitor's Accept on usesaiph.com (basic
// consent mode: the tag is never loaded otherwise). Page address without query.
export const GA_SCRIPT = `(function(){var d=JSON.parse(document.getElementById("buy-analytics").textContent);
window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}
gtag("consent","default",{ad_storage:"denied",ad_user_data:"denied",ad_personalization:"denied",analytics_storage:"denied"});
gtag("consent","update",{analytics_storage:"granted"});
gtag("js",new Date());gtag("set",{allow_google_signals:false,allow_ad_personalization_signals:false});
gtag("config",d.id,{cookie_domain:"usesaiph.com",cookie_expires:15724800,page_location:location.origin+location.pathname,send_page_view:false});
var s=document.createElement("script");s.async=true;s.src="https://www.googletagmanager.com/gtag/js?id="+encodeURIComponent(d.id);document.head.appendChild(s);
window.saiphBuyEvent=function(done){var p={};for(var k in d.params)p[k]=d.params[k];if(done){p.event_callback=done;p.event_timeout=800;}gtag("event",d.event,p);};
if(!document.getElementById("handoff-form"))window.saiphBuyEvent();})();`;
// Signed in: continue (to Stripe, or start the trial) without another click; the button stays for no-JS.
// The address becomes /account first, so Back from Stripe does not loop here.
export const HANDOFF_SCRIPT = `(function(){var f=document.getElementById("handoff-form");if(!f)return;var sent=false;
function go(){if(sent)return;sent=true;try{history.replaceState(null,"","/account");}catch(e){}f.submit();}
if(window.saiphBuyEvent){window.saiphBuyEvent(go);setTimeout(go,1000);}else go();})();`;
