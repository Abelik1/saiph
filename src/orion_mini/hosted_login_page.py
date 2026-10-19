# SPDX-License-Identifier: AGPL-3.0-or-later
"""Static, self-contained browser handoff. Never interpolate callback data."""
import base64
import hashlib


STYLE = """
:root{color-scheme:dark;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#080e17;color:#eef4fa}
*{box-sizing:border-box}body{margin:0;min-height:100vh;min-height:100svh;display:grid;place-items:center;padding:32px 20px;background:radial-gradient(ellipse at 50% 20%,#17333d66,transparent 65%)}
main{width:100%;max-width:480px;padding:42px 36px 32px;border:1px solid #263442;border-radius:24px;background:#101923;box-shadow:0 24px 100px #0005;text-align:center}
.brand{display:flex;align-items:center;justify-content:center;gap:9px;margin-bottom:36px;font-size:18px;font-weight:650;letter-spacing:-.4px}.brand svg{width:26px;height:26px;color:#35cad6}
.status{display:grid;place-items:center;width:64px;height:64px;border:1px solid #2c6970;border-radius:50%;margin:0 auto 22px;background:#15383d;color:#67e0d7}.status svg{width:30px;height:30px}
h1{margin:0 0 12px;font-size:30px;line-height:1.2;letter-spacing:-1px;font-weight:650}p{margin:0 auto;color:#a8b9c8;font-size:15px;line-height:1.65;max-width:340px}
button{display:block;width:100%;margin-top:30px;border:0;border-radius:999px;padding:14px 20px;background:#35cad6;color:#08171d;font-family:inherit;font-size:15px;font-weight:600;line-height:1.2;cursor:pointer}button:hover{background:#75e1e8}button:focus-visible{outline:3px solid #eef4fa;outline-offset:4px}
.hint{margin-top:22px;font-size:13px;min-height:42px;color:#8295a6}.error .status{color:#f5bc83;border-color:#775637;background:#34291e}.error h1{font-size:27px}
@media(max-width:420px){main{padding:32px 24px 24px}h1{font-size:27px}.brand{margin-bottom:28px}}
@media(prefers-color-scheme:light){:root{color-scheme:light;background:#f3f7fa;color:#172a37}body{background:radial-gradient(ellipse at 50% 20%,#bfeef066,transparent 65%)}main{background:#fff;border-color:#d9e3e9;box-shadow:0 24px 100px #183c4d0c}p{color:#516778}.hint{color:#647b8c}.status{background:#e4f8f5;border-color:#b8e5dd;color:#16877d}.error .status{background:#fff2e2;border-color:#edd4b5;color:#996329}button:focus-visible{outline-color:#172a37}}
""".strip()

CLEAR_QUERY = "history.replaceState(null,'',location.pathname);"
SUCCESS_SCRIPT = CLEAR_QUERY + """
function closeTab(){window.close();}
document.getElementById('close-tab').addEventListener('click',function(){
 closeTab();document.getElementById('hint').textContent='Your browser kept this tab open. You can close it using the tab’s close button.';
});
closeTab();setTimeout(closeTab,500);
"""


def _hash(value):
    return base64.b64encode(hashlib.sha256(value.encode()).digest()).decode()


def login_page(success):
    script = SUCCESS_SCRIPT if success else CLEAR_QUERY
    title = "You’re signed in" if success else "Sign-in didn’t finish"
    message = ("Your connection is ready. Return to Saiph to continue." if success
               else "Return to Saiph and try signing in again. Your device approval is kept.")
    icon = ('<path d="m6 15 6 6L25 8"/>' if success
            else '<path d="M15 7v10m0 6v.1"/>')
    action = ('<button id="close-tab" type="button">Close this tab</button>' if success else '')
    hint = "You can safely close this tab." if success else "You can close this tab and try again in the app."
    html = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{title} · Saiph</title><style>{STYLE}</style></head>'
            f'<body><main class="{"success" if success else "error"}">'
            '<div class="brand"><svg viewBox="0 0 28 28" fill="none" aria-hidden="true">'
            '<path d="m14 2 3.5 8.5L26 14l-8.5 3.5L14 26l-3.5-8.5L2 14l8.5-3.5Z" stroke="currentColor" stroke-width="1.8"/></svg>Saiph</div>'
            '<div class="status"><svg viewBox="0 0 30 30" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            f'{icon}</svg></div><h1>{title}.</h1><p>{message}</p>{action}'
            f'<p class="hint" id="hint" role="status">{hint}</p></main><script>{script}</script></body></html>')
    policy = (f"default-src 'none'; script-src 'sha256-{_hash(script)}'; style-src 'sha256-{_hash(STYLE)}'; "
              "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
    return html.encode(), policy
