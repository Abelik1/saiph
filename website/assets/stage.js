// SPDX-License-Identifier: AGPL-3.0-or-later
// Device animatics: scripted scenes played across a laptop, desktop and phone.
(function () {
  const root = document.querySelector("[data-stage]");
  if (!root) return;

  const inner = root.querySelector(".stage-inner");
  const caption = document.querySelector("[data-stage-caption]");
  const tabs = Array.from(document.querySelectorAll("[data-scene]"));
  const pauseBtn = document.querySelector("[data-stage-pause]");
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const screens = {};
  for (const key of ["laptop", "desktop", "phone"]) {
    const dev = inner.querySelector(".dev-" + key);
    screens[key] = { dev, screen: dev.querySelector(".screen"), body: dev.querySelector(".scr-body"), layer: dev.querySelector(".layer") };
  }

  const h = (html) => {
    const t = document.createElement("template");
    t.innerHTML = html.trim();
    return t.content.firstElementChild;
  };

  // ---------- building blocks ----------
  const status = () => `<div class="p-status"><span>9:41</span><span>5G ▮▮▮</span></div><div class="p-home-bar"></div>`;
  const taskbar = (on) => `<div class="taskbar"><i></i><i class="${on ? "on" : ""}"></i><i></i><i></i><em class="clock">18:42</em></div>`;
  const orionWin = (tab, body, cls = "") => `
    <div class="win"><div class="win-bar"><span class="dots"><i></i><i></i><i></i></span>Saiph
      <span class="tabs">${["Phone", "Cloud", "Settings"].map((t) => `<span class="${t === tab ? "on" : ""}">${t}</span>`).join("")}</span>
    </div><div class="win-body ${cls}">${body}</div></div>`;
  const plainWin = (title, body, cls = "") => `
    <div class="win"><div class="win-bar"><span class="dots"><i></i><i></i><i></i></span>${title}</div>
    <div class="win-body ${cls}">${body}</div></div>`;
  const computer = (wall, win, orionOn = true) => `<div class="wall ${wall}"></div>${win || ""}${taskbar(orionOn)}`;
  const phoneLock = () => `<div class="wall w3"></div>${status()}<div class="p-lock"><b>9:41</b><span>Saturday 10 October</span></div>`;
  const phoneApp = (title, body) => `<div class="p-app"><h4>${title}</h4>${body}</div>${status()}`;
  const phoneSummary = () => `
    <div class="main"><div class="panel-title">Your phone</div>
      <div class="phone-card"><div class="ph"></div><div><b>Galaxy A55</b><span>● Connected privately</span></div></div>
      <div class="stat-row"><div><b>82%</b>Battery</div><div><b>3</b>Alerts</div><div><b>2</b>Unread texts</div></div>
    </div>`;
  const toast = ({ title, body, av = "a1", initial, actions = ["Reply", "Dismiss"], reply = false }) => h(`
    <div class="toast"><div class="t-head"><span class="logo"></span>Saiph · from your phone</div>
      <div class="t-main"><div class="av ${av}">${initial || title[0]}</div><div><b>${title}</b><span class="t-text">${body}</span></div></div>
      <div class="t-actions">${actions.map((a) => `<span>${a}</span>`).join("")}</div>
      ${reply ? `<div class="t-reply compose"><span class="txt" data-ph="Reply…"></span><span class="send"></span></div>` : ""}
    </div>`);
  const notif = ({ app, title, body, av = "a1" }) => h(`
    <div class="notif"><div class="av ${av}">${title[0]}</div><div><div class="meta">${app} · now</div><b>${title}</b><div class="n-body">${body}</div></div></div>`);

  // ---------- scene runtime ----------
  let runId = 0;
  let paused = false;
  let current = 0;
  class Abort extends Error {}

  function ctx(id) {
    const live = () => { if (id !== runId) throw new Abort(); };
    return {
      set(dev, html) { screens[dev].body.innerHTML = html; screens[dev].layer.innerHTML = ""; },
      add(dev, el, where = "layer") { screens[dev][where === "layer" ? "layer" : "body"].appendChild(el); return el; },
      q(dev, sel) { return screens[dev].screen.querySelector(sel); },
      say(text) {
        if (!caption) return;
        caption.classList.add("fade");
        setTimeout(() => { if (id === runId) { caption.textContent = text; caption.classList.remove("fade"); } }, reduced ? 0 : 180);
      },
      async wait(ms) {
        live();
        if (!reduced) await new Promise((r) => setTimeout(r, ms));
        while (paused && id === runId) await new Promise((r) => setTimeout(r, 120));
        live();
      },
      async type(el, text, speed = 42) {
        if (reduced) { el.textContent = text; return; }
        for (const ch of text) { live(); el.textContent += ch; await this.wait(speed); }
      },
      async press(el) { el.classList.add("pressed"); await this.wait(180); el.classList.remove("pressed"); },
      async beam(from, to, count = 1) {
        live();
        if (reduced) return;
        const box = inner.getBoundingClientRect();
        const centre = (k) => {
          const r = screens[k].screen.getBoundingClientRect();
          return [r.left - box.left + r.width / 2, r.top - box.top + r.height / 2];
        };
        const [x1, y1] = centre(from);
        const [x2, y2] = centre(to);
        const lift = Math.min(box.height * 0.28, Math.abs(x2 - x1) * 0.35 + 30);
        const mx = (x1 + x2) / 2, my = Math.min(y1, y2) - lift;
        const svg = h(`<svg class="beam-trail" viewBox="0 0 ${box.width} ${box.height}"><path d="M${x1},${y1} Q${mx},${my} ${x2},${y2}"/></svg>`);
        inner.appendChild(svg);
        const path = svg.querySelector("path");
        const len = path.getTotalLength();
        const frames = [];
        for (let i = 0; i <= 24; i++) {
          const p = path.getPointAtLength((len * i) / 24);
          frames.push({ left: p.x + "px", top: p.y + "px", opacity: i === 0 || i === 24 ? 0.4 : 1 });
        }
        const runs = [];
        for (let i = 0; i < count; i++) {
          const dot = h(`<div class="beam"></div>`);
          inner.appendChild(dot);
          const anim = dot.animate(frames, { duration: 750, delay: i * 220, easing: "cubic-bezier(.45,0,.25,1)", fill: "both" });
          runs.push(anim.finished.then(() => dot.remove(), () => dot.remove()));
        }
        await Promise.all(runs);
        setTimeout(() => svg.remove(), 900);
        live();
      },
    };
  }

  function clearStage() {
    inner.querySelectorAll(".beam, .beam-trail").forEach((n) => n.remove());
  }

  // ---------- scenes ----------
  const scenes = {
    async notifications(c) {
      c.set("phone", phoneLock());
      c.set("laptop", computer("w1", plainWin("Essay draft.docx", `<div class="doc"><span class="line" style="width:90%"></span><span class="line" style="width:75%"></span><span class="line" style="width:84%"></span><span class="line" style="width:60%"></span></div>`)));
      c.set("desktop", computer("w2", orionWin("Phone", phoneSummary())));
      c.say("A message lands on your phone…");
      await c.wait(700);
      const n = c.add("phone", notif({ app: "Messages", title: "Sam", body: "Are we still on for 7?" }));
      await c.wait(1100);
      c.say("…and appears on every computer you've paired.");
      await Promise.all([c.beam("phone", "laptop"), c.beam("phone", "desktop")]);
      const tl = c.add("laptop", toast({ title: "Sam", body: "Are we still on for 7?" }));
      const td = c.add("desktop", toast({ title: "Sam", body: "Are we still on for 7?", reply: true }));
      await c.wait(1300);
      c.say("Reply from your desktop keyboard…");
      await c.press(td.querySelector(".t-actions span"));
      td.classList.add("replying");
      await c.wait(300);
      await c.type(td.querySelector(".txt"), "Yes! See you there");
      await c.wait(350);
      await c.press(td.querySelector(".send"));
      await c.beam("desktop", "phone");
      n.querySelector(".n-body").textContent = "You replied: Yes! See you there";
      n.classList.add("done");
      tl.classList.add("out");
      td.classList.add("out");
      c.say("…it's sent from your phone, and the alert clears everywhere.");
      await c.wait(2600);
    },

    async clipboard(c) {
      c.set("laptop", computer("w1", plainWin("Notes", `<div class="doc"><p>Flat viewing, Saturday</p><p><span class="sel">Door code 4471, flat 3B</span></p><p>Bring ID + deposit</p><span class="line" style="width:70%"></span></div>`)));
      c.set("desktop", computer("w2", orionWin("Phone", `<div class="main"><div class="panel-title">Shared clipboard</div><div class="clip">
        <div class="ci">https://maps.app/x7Qk2<small>from Phone · 2 min ago</small></div>
        <div class="ci">Invoice #2231<small>from Desktop · 1 h ago</small></div></div></div>`)));
      c.set("phone", phoneApp(`<span class="av a1">S</span>Sam`, `<div class="thread"><div class="bub in">What's the door code again?</div></div>
        <div class="compose"><span class="txt" data-ph="Message"></span><span class="send"></span></div>`));
      c.say("Copy something on your laptop…");
      await c.wait(900);
      c.q("laptop", ".sel").classList.add("on");
      await c.wait(500);
      c.add("laptop", h(`<div class="keycap">Ctrl + C</div>`));
      await c.wait(700);
      c.say("…and it's on your phone and desktop clipboards too.");
      await Promise.all([c.beam("laptop", "phone"), c.beam("laptop", "desktop")]);
      c.q("desktop", ".clip").prepend(h(`<div class="ci new">Door code 4471, flat 3B<small>from Laptop · just now</small></div>`));
      const chip = h(`<div class="chip">Paste from Laptop</div>`);
      c.q("phone", ".thread").after(chip);
      await c.wait(1200);
      c.say("Paste it anywhere. No more emailing yourself.");
      await c.press(chip);
      chip.remove();
      c.q("phone", ".txt").textContent = "Door code 4471, flat 3B";
      await c.wait(700);
      await c.press(c.q("phone", ".send"));
      c.q("phone", ".txt").textContent = "";
      c.q("phone", ".thread").appendChild(h(`<div class="bub out">Door code 4471, flat 3B</div>`));
      await c.wait(2400);
    },

    async messages(c) {
      const convo = (av, name, text, on) => `<div class="item ${on ? "on" : ""}"><div class="av ${av}">${name[0]}</div><div><b>${name}</b><span>${text}</span></div></div>`;
      c.set("desktop", computer("w2", orionWin("Phone", `
        <div class="side"><div class="panel-title">Messages</div>${convo("a2", "Mum", "Did you get home ok?", true)}${convo("a1", "Sam", "See you at 7")}${convo("a3", "Dentist", "Reminder: Tue 10:30")}</div>
        <div class="main"><div class="thread"><div class="bub in">Did you get home ok?</div></div>
          <div class="compose"><span class="txt" data-ph="Text message"></span><span class="send"></span></div></div>`)));
      c.set("phone", phoneApp(`<span class="av a2">M</span>Mum`, `<div class="thread"><div class="bub in">Did you get home ok?</div></div>
        <div class="compose"><span class="txt" data-ph="Message"></span><span class="send"></span></div>`));
      c.set("laptop", computer("w1", plainWin("Lecture slides", `<div class="doc"><span class="line" style="width:60%;height:1em"></span><span class="line" style="width:88%"></span><span class="line" style="width:80%"></span><span class="line" style="width:68%"></span></div>`)));
      c.say("Read and answer your texts with a real keyboard.");
      await c.wait(1100);
      await c.type(c.q("desktop", ".txt"), "Home now, thanks! Call you tomorrow");
      await c.wait(300);
      await c.press(c.q("desktop", ".send"));
      c.q("desktop", ".txt").textContent = "";
      const mine = h(`<div class="bub out">Home now, thanks! Call you tomorrow<small>Sending via phone…</small></div>`);
      c.q("desktop", ".thread").appendChild(mine);
      await c.beam("desktop", "phone");
      c.q("phone", ".thread").appendChild(h(`<div class="bub out">Home now, thanks! Call you tomorrow</div>`));
      mine.querySelector("small").textContent = "Sent";
      c.say("It goes out from your phone, with your own number.");
      await c.wait(2800);
    },

    async calls(c) {
      c.set("phone", `<div class="call"><div class="av a1 ring">S</div><b>Sam</b><span>Mobile · incoming call</span><div class="btns"><i class="r"></i><i class="g"></i></div></div>${status()}`);
      c.set("laptop", computer("w1", plainWin("Spreadsheet", `<div class="doc"><span class="line" style="width:95%"></span><span class="line" style="width:95%"></span><span class="line" style="width:95%"></span><span class="line" style="width:95%"></span></div>`)));
      c.set("desktop", computer("w2", orionWin("Phone", phoneSummary())));
      c.say("Your phone rings in the other room…");
      await c.wait(1000);
      await Promise.all([c.beam("phone", "laptop"), c.beam("phone", "desktop")]);
      const tl = c.add("laptop", toast({ title: "Sam", body: "Incoming call", actions: ["Answer", "Decline"] }));
      const td = c.add("desktop", toast({ title: "Sam", body: "Incoming call", actions: ["Answer", "Decline"] }));
      tl.querySelector(".t-actions span").classList.add("ok");
      td.querySelector(".t-actions span").classList.add("ok");
      tl.querySelectorAll(".t-actions span")[1].classList.add("bad");
      td.querySelectorAll(".t-actions span")[1].classList.add("bad");
      c.say("…you see who it is on whichever screen is in front of you.");
      await c.wait(1600);
      await c.press(tl.querySelector(".t-actions span"));
      await c.beam("laptop", "phone");
      const call = c.q("phone", ".call");
      call.classList.add("live");
      call.querySelector(".ring").classList.remove("ring");
      const label = call.querySelector("span");
      td.classList.add("out");
      tl.querySelector(".t-text").textContent = "On call · 00:00";
      tl.querySelector(".t-actions").innerHTML = `<span>Mute</span><span class="bad">End call</span>`;
      c.say("Answer or decline from your computer.");
      for (let s = 0; s < 5; s++) {
        label.textContent = "Connected · 00:0" + s;
        tl.querySelector(".t-text").textContent = "On call · 00:0" + s;
        await c.wait(650);
      }
    },

    async files(c) {
      c.set("phone", `<div class="viewfinder"><div class="shutter"></div></div>${status()}`);
      c.set("laptop", computer("w1", orionWin("Phone", `<div class="main"><div class="panel-title">Recent photos</div><div class="photos"><i class="p1"></i><i class="p2"></i><i class="p3"></i><i class="p4"></i><i class="p5"></i></div></div>`)));
      c.set("desktop", computer("w2", orionWin("Phone", `<div class="main" style="flex:0 0 30%;align-items:center;justify-content:center"><div class="file"><i></i>Boarding pass.pdf</div></div>
        <div class="dropzone">Drop files here to send them to your phone</div>`)));
      c.say("Take a photo on your phone…");
      await c.wait(1000);
      await c.press(c.q("phone", ".shutter"));
      c.add("phone", h(`<div class="flash"></div>`));
      await c.wait(500);
      await c.beam("phone", "laptop");
      c.q("laptop", ".photos").prepend(h(`<i class="new"></i>`));
      c.q("laptop", ".photos i:last-child").remove();
      c.say("…it's already in Recent photos on your laptop.");
      await c.wait(1800);
      c.say("Send a file the other way: drop it on Saiph…");
      const file = c.q("desktop", ".file");
      const zone = c.q("desktop", ".dropzone");
      const fr = file.getBoundingClientRect(), zr = zone.getBoundingClientRect();
      file.style.transform = `translate(${zr.left + zr.width / 2 - (fr.left + fr.width / 2)}px, ${zr.top + zr.height / 2 - (fr.top + fr.height / 2)}px)`;
      await c.wait(600);
      zone.classList.add("hot");
      await c.wait(500);
      file.style.opacity = "0";
      zone.textContent = "Sending Boarding pass.pdf…";
      await c.beam("desktop", "phone");
      zone.textContent = "Sent to Galaxy A55";
      c.add("phone", notif({ app: "Saiph", title: "Boarding pass.pdf", body: "Received from Desktop · Tap to open", av: "a4" }));
      c.say("…and it lands on your phone over your private connection.");
      await c.wait(2600);
    },

    async webcam(c) {
      c.set("desktop", computer("w2", plainWin("Weekly sync · video call", `<div class="vgrid">
        <div class="vtile"><div class="av a2">P</div><em>Priya</em></div>
        <div class="vtile me"><div class="live"></div><span class="off">Camera off</span><em>You</em></div></div>`), false));
      c.set("phone", phoneApp("Saiph Camera", `<div class="opt">Use as webcam for<b>Desktop</b></div><div class="opt">Lens<b>Rear</b></div><div class="opt">Quality<b>1080p</b></div><div class="big-btn">Start</div>`));
      c.set("laptop", computer("w1", ""));
      c.say("Need a better webcam? Use the one in your pocket.");
      await c.wait(1500);
      const btn = c.q("phone", ".big-btn");
      await c.press(btn);
      c.set("phone", `<div class="viewfinder"></div><div class="rec">Live to Desktop</div>${status()}`);
      await c.beam("phone", "desktop", 3);
      c.q("desktop", ".vtile.me").classList.add("on");
      c.say("It starts only when you press Start and stops the moment you disconnect.");
      await c.beam("phone", "desktop", 3);
      await c.beam("phone", "desktop", 3);
      await c.wait(1200);
    },

    async cloud(c) {
      const f = (name, cls = "") => `<div class="file ${cls}"><i></i>${name}</div>`;
      const folder = (extra = "") => plainWin("Saiph Cloud", `<div class="fm">${f("Lab report.pdf")}${f("Budget.docx", "docx")}${f("Tickets.pdf")}${extra}</div>`);
      c.set("laptop", computer("w1", folder()));
      c.set("desktop", computer("w2", folder()));
      c.set("phone", phoneLock());
      c.say("Optional Cloud: save into your Saiph folder on the laptop…");
      await c.wait(1100);
      const nf = h(`<div class="file docx new"><i></i>Thesis v4.docx<em class="badge sync"></em></div>`);
      c.q("laptop", ".fm").appendChild(nf);
      await c.wait(900);
      await c.beam("laptop", "desktop", 2);
      nf.querySelector(".badge").className = "badge done";
      c.q("desktop", ".fm").appendChild(h(`<div class="file docx new"><i></i>Thesis v4.docx<em class="badge done"></em></div>`));
      c.say("…and it's on your desktop, synced through storage you control.");
      await c.wait(2800);
    },
  };

  const order = tabs.map((t) => t.dataset.scene);

  async function play(index, auto) {
    current = (index + order.length) % order.length;
    const id = ++runId;
    clearStage();
    tabs.forEach((t, i) => t.setAttribute("aria-selected", String(i === current)));
    const label = tabs[current].dataset.label;
    if (label) inner.setAttribute("aria-label", label);
    try {
      await scenes[order[current]](ctx(id));
      if (reduced) return;
      await ctx(id).wait(700);
      play(current + 1, true);
    } catch (e) {
      if (!(e instanceof Abort)) throw e;
    }
  }

  tabs.forEach((t, i) => t.addEventListener("click", () => {
    play(i);
    if (t.closest(".feature-cards")) root.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "center" });
  }));
  document.querySelectorAll("[data-goto-scene]").forEach((b) => b.addEventListener("click", () => {
    const i = order.indexOf(b.dataset.gotoScene);
    if (i >= 0) { play(i); root.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "center" }); }
  }));

  if (pauseBtn) {
    const icons = {
      pause: `<svg viewBox="0 0 14 14" fill="currentColor"><rect x="2" y="1" width="3.5" height="12" rx="1"/><rect x="8.5" y="1" width="3.5" height="12" rx="1"/></svg>`,
      play: `<svg viewBox="0 0 14 14" fill="currentColor"><path d="M3 1.5v11l9-5.5z"/></svg>`,
    };
    pauseBtn.innerHTML = icons.pause;
    pauseBtn.addEventListener("click", () => {
      paused = !paused;
      pauseBtn.innerHTML = paused ? icons.play : icons.pause;
      pauseBtn.setAttribute("aria-label", paused ? "Play animation" : "Pause animation");
      inner.querySelectorAll("*").forEach((n) => n.getAnimations().forEach((a) => (paused ? a.pause() : a.play())));
    });
    if (reduced) pauseBtn.hidden = true;
  }

  // Start when visible; pause off-screen so it doesn't burn CPU.
  let started = false;
  new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (e.isIntersecting && !started) { started = true; play(0); }
    }
  }, { threshold: 0.15 }).observe(root);
})();
