# SPDX-License-Identifier: AGPL-3.0-or-later
"""Measure what decorative motion costs inside Qt WebEngine, one variant at a time.

Each variant is a small synthetic page shaped like the desktop header (translucent
bar over a full-window string canvas, a selected-tab wave). It is loaded into a real
QWebEngineView and the CPU time of this process plus its QtWebEngineProcess
children is sampled. No profile, account, device or installed app is involved.

    python scripts/measure-render-cost.py                 # offscreen, all variants
    python scripts/measure-render-cost.py --show          # visible window, GPU as normal
    python scripts/measure-render-cost.py --variant old-wave --variant stepped-wave

Results are synthetic: offscreen rendering is software-only, so absolute numbers
differ from an installed app on real hardware. Compare variants within one run.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

WAVE = ("url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='6' viewBox='0 0 12 6'%3E"
        "%3Cpath d='M0 3 Q3 0 6 3 T12 3' fill='none' stroke='black' stroke-width='1.6'/%3E%3C/svg%3E\")")
FADE = "linear-gradient(90deg, transparent, #000 35%, #000 65%, transparent)"

# The previous selected-tab wave: a moving child under a masked parent, 60 Hz.
OLD_WAVE = f"""
.wave {{ position:absolute; left:50%; bottom:5px; width:40px; height:8px; margin-left:-20px; overflow:hidden; contain:paint;
  -webkit-mask:{FADE}; mask:{FADE}; }}
.wave::before {{ content:""; position:absolute; inset:0 -12px 0 0; background:#67e8f9;
  -webkit-mask:{WAVE} repeat-x 0 50% / 12px 6px; mask:{WAVE} repeat-x 0 50% / 12px 6px;
  animation: slide 1.2s linear infinite; }}
@keyframes slide {{ to {{ transform: translateX(-12px); }} }}
"""
# One element, both masks on it, the wave mask stepping 12 times per 0.8 s (15 Hz).
STEPPED_WAVE = f"""
.wave {{ position:absolute; left:50%; bottom:5px; width:40px; height:8px; margin-left:-20px; background:#67e8f9;
  -webkit-mask:{FADE}, {WAVE} repeat-x 0 50% / 12px 6px; -webkit-mask-composite: source-in;
  mask:{FADE}, {WAVE} repeat-x 0 50% / 12px 6px; mask-composite: intersect;
  animation: slide 0.8s steps(12) infinite; }}
@keyframes slide {{ to {{ -webkit-mask-position: 0 0, -12px 50%; mask-position: 0 0, -12px 50%; }} }}
"""
# Same element, stepped transform of a pre-faded strip (compositor animation).
STEPPED_TRANSFORM = OLD_WAVE.replace("animation: slide 1.2s linear infinite", "animation: slide 0.8s steps(12) infinite")

# The wave strip moved by a 15 Hz timer: no running CSS animation, so no 60 Hz ticks.
TIMER_WAVE = OLD_WAVE.replace("animation: slide 1.2s linear infinite;", "transform: translateX(var(--shift, 0px));")
TIMER_SCRIPT = """<script>let k=0;setInterval(()=>{k=(k+1)%12;document.documentElement.style.setProperty('--shift',-k+'px')},1000/15);</script>"""

CANVAS_LOOP = """
<script>
const c=document.querySelector('canvas'),x=c.getContext('2d');let last=0;
function frame(t){ if(t-last>=1000/15){ last=t; x.clearRect(0,0,c.width,c.height); x.strokeStyle='rgba(103,232,249,.25)';
  for(let i=1;i<=30;i++){ x.beginPath(); for(let p=-6;p<=c.width+6;p+=6){ const y=i*c.height/31+Math.sin(p/c.width*2.6+i*0.13+t/8000)*18+Math.sin(p/c.width*22-t/1100+i*.7)*1.2;
    p===-6?x.moveTo(p,y):x.lineTo(p,y);} x.stroke(); } } requestAnimationFrame(frame); }
requestAnimationFrame(frame);
</script>"""
CANVAS_STATIC = CANVAS_LOOP.replace("requestAnimationFrame(frame); }\nrequestAnimationFrame(frame);", "}\nframe(1000);")

VARIANTS = {
    "idle": {"css": "", "canvas": CANVAS_STATIC, "blur": False, "waves": 0},
    "old-canvas": {"css": "", "canvas": CANVAS_LOOP, "blur": True, "waves": 0},
    "old-wave": {"css": OLD_WAVE, "canvas": CANVAS_STATIC, "blur": True, "waves": 2},
    "old-all": {"css": OLD_WAVE, "canvas": CANVAS_LOOP, "blur": True, "waves": 2},
    "stepped-transform": {"css": STEPPED_TRANSFORM, "canvas": CANVAS_STATIC, "blur": False, "waves": 2},
    "stepped-wave": {"css": STEPPED_WAVE, "canvas": CANVAS_STATIC, "blur": False, "waves": 2},
    "stepped-wave-blur": {"css": STEPPED_WAVE, "canvas": CANVAS_STATIC, "blur": True, "waves": 2},
    "old-wave-no-blur": {"css": OLD_WAVE, "canvas": CANVAS_STATIC, "blur": False, "waves": 2},
    "stepped-transform-blur": {"css": STEPPED_TRANSFORM, "canvas": CANVAS_STATIC, "blur": True, "waves": 2},
    "stepped-no-fade": {"css": STEPPED_TRANSFORM.replace(f"-webkit-mask:{FADE}; mask:{FADE};", ""), "canvas": CANVAS_STATIC, "blur": False, "waves": 2},
    "timer-wave": {"css": TIMER_WAVE, "canvas": CANVAS_STATIC + TIMER_SCRIPT, "blur": False, "waves": 2},
    "stepped-transform-10hz": {"css": STEPPED_TRANSFORM.replace("0.8s steps(12)", "1.2s steps(12)"), "canvas": CANVAS_STATIC, "blur": False, "waves": 2},
}


def page(variant: dict) -> str:
    blur = "backdrop-filter: blur(14px);" if variant["blur"] else ""
    waves = "".join(f'<span class="tab">Tab {n}<span class="wave"></span></span>' for n in range(variant["waves"]))
    return f"""<!doctype html><html><head><style>
html,body {{ margin:0; height:100%; background:#050b1a; color:#e9fbff; font:13px sans-serif; overflow:hidden; }}
canvas {{ position:fixed; inset:0; width:100%; height:100%; }}
header {{ position:relative; height:64px; display:flex; gap:24px; align-items:stretch; padding:0 32px; background:rgba(5,11,26,.72); {blur} }}
.tab {{ position:relative; display:flex; align-items:center; padding:0 14px; }}
{variant["css"]}
</style></head><body><canvas width="1300" height="860"></canvas><header>{waves}</header>{variant["canvas"]}</body></html>"""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--variant", action="append", choices=sorted(VARIANTS))
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--warmup", type=float, default=3)
    parser.add_argument("--show", action="store_true", help="Visible window with the platform's normal rendering.")
    options = parser.parse_args(argv)
    if not options.show:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    import psutil
    from PySide6.QtCore import QEventLoop, QTimer, QUrl
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication

    app = QApplication(["Saiph render cost"])
    view = QWebEngineView()
    view.resize(1300, 860)
    view.show()
    me = psutil.Process()

    def wait(seconds):
        loop = QEventLoop()
        QTimer.singleShot(int(seconds * 1000), loop.quit)
        loop.exec()

    def cpu():
        total = 0.0
        for process in [me, *me.children(recursive=True)]:
            try:
                times = process.cpu_times()
                total += times.user + times.system
            except psutil.Error:
                pass
        return total

    results = {}
    for name in options.variant or list(VARIANTS):
        view.setHtml(page(VARIANTS[name]), QUrl("about:blank"))
        wait(options.warmup)
        start, began = cpu(), time.perf_counter()
        wait(options.seconds)
        results[name] = round(100 * (cpu() - start) / (time.perf_counter() - began), 1)
        print(f"{name:20s} {results[name]:6.1f} % of one core", flush=True)
    print(json.dumps({"rendering": "visible" if options.show else "offscreen", "seconds": options.seconds, "cpu_percent": results}))
    view.close()
    app.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
