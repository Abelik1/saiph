// SPDX-License-Identifier: AGPL-3.0-or-later
import { app, BrowserWindow, dialog, ipcMain, Menu, protocol, session as electronSession } from "electron";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { APP_URL, EVENT_CHANNEL, REQUEST_CHANNEL, validateCall } from "./contract.cjs";
import { readAsset } from "./assets.cjs";
import { PythonService } from "./service.cjs";
import { BinaryServer } from "./binary.cjs";
import { NativeHost } from "./native.cjs";
import { applyWindowControl } from "./window-control.cjs";
import { missingDisplayPlatform } from "./display-platform.cjs";

const displayPlatform = missingDisplayPlatform(process.platform, process.env, process.argv);
if (displayPlatform) {
  app.relaunch({ args: [displayPlatform, ...process.argv.slice(1)] });
  app.exit(0);
}

const repo = app.isPackaged ? path.dirname(process.execPath) : path.resolve(__dirname, "../..");
const argument = process.argv.indexOf("--ui-session");
const sessionFile = argument >= 0 ? path.resolve(process.argv[argument + 1]) : undefined;
let config: Record<string, any>;
const serviceExecutable = path.join(process.resourcesPath, "service", process.platform === "win32" ? "SaiphService.exe" : "SaiphService");
if (sessionFile) {
  config = JSON.parse(fs.readFileSync(sessionFile, "utf8"));
  if (config.schema !== 1 || config.shell !== "electron" || config.status !== "starting" || !["isolated", "live"].includes(config.mode)
    || !/^[a-f0-9]{48}$/.test(config.nonce) || !path.isAbsolute(config.profile) || !path.isAbsolute(config.python)
    || !Number.isInteger(config.timeout) || config.timeout < 1 || typeof config.show !== "boolean"
    || (config.mode === "isolated" && (config.existing_profile !== false || fs.realpathSync(config.profile) !== path.join(fs.realpathSync(path.dirname(sessionFile)), "profile")))) throw new Error("Invalid desktop test session.");
} else {
  const python = app.isPackaged ? serviceExecutable : process.env.SAIPH_PYTHON;
  if (!python || !path.isAbsolute(python)) throw new Error("Run the desktop through python -m orion_mini, or its installed shortcut.");
  const args = app.isPackaged ? ["--profile-path"] : ["-m", "orion_mini.electron_launcher", "--profile-path"];
  const result = spawnSync(python, args, { cwd: repo, windowsHide: true, encoding: "utf8", timeout: 15000, env: { ...process.env, PYTHONPATH: path.join(repo, "src") } });
  if (result.status !== 0) throw new Error("The desktop profile could not be located.");
  config = { schema: 1, profile: result.stdout.trim(), mode: "live", show: true, python, fixture: "empty" };
  if (!path.isAbsolute(config.profile)) throw new Error("The desktop profile must be an absolute path.");
}
const directory = sessionFile ? path.dirname(sessionFile) : path.join(config.profile, ".electron", "run-" + randomBytes(12).toString("hex"));
fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
const source = sessionFile ? fileURLToPath(config.source_dashboard) : path.join(process.resourcesPath, "app", "frontend", "index.html");
const dashboard = !app.isPackaged && !sessionFile ? path.join(repo, "frontend/dist/index.html") : source;
const iconName = process.platform === "win32" ? "orion-mini-icon.ico" : "orion-mini-icon.png";
const icon = app.isPackaged ? path.join(repo, "_internal/assets", iconName) : path.join(repo, "assets", iconName);
const isolated = config.mode === "isolated";
app.setName("Saiph");
app.setPath("userData", sessionFile ? path.join(directory, "browser-storage") : path.join(config.profile, ".electron/browser-storage"));
app.setPath("sessionData", sessionFile ? path.join(directory, "browser-cache") : path.join(config.profile, ".electron/browser-cache"));
app.setAppUserModelId("OrionMini.Desktop");
if (sessionFile) {
  const endpoint = new URL(config.endpoint);
  if (endpoint.protocol !== "http:" || endpoint.hostname !== "127.0.0.1" || !/^\d+$/.test(endpoint.port) || endpoint.username || endpoint.password || endpoint.pathname !== "/" || endpoint.search || endpoint.hash) throw new Error("Invalid test endpoint.");
  app.commandLine.appendSwitch("remote-debugging-address", "127.0.0.1");
  app.commandLine.appendSwitch("remote-debugging-port", endpoint.port);
  app.commandLine.appendSwitch("remote-allow-origins", config.endpoint);
  if (!config.show) app.disableHardwareAcceleration();
}
protocol.registerSchemesAsPrivileged(["saiph-app", "saiph-frame", "saiph-media"].map(scheme => ({ scheme, privileges: { standard: true, secure: true, supportFetchAPI: true } })));

let window: BrowserWindow | undefined, host: NativeHost | undefined;
let closing = false, held = false;
const service = new PythonService(), binary = new BinaryServer();
binary.on("failed", () => { if (!closing) { save("failed"); app.quit(); } });
function save(status: string): void {
  config.status = status;
  if (!sessionFile) return;
  const next = { ...config, pid: process.pid, dashboard: APP_URL, status };
  fs.writeFileSync(path.join(directory, "session.tmp"), JSON.stringify(next, null, 2) + "\n");
  fs.renameSync(path.join(directory, "session.tmp"), sessionFile);
}
function announce(): void {
  if (!window || window.isDestroyed()) return;
  if (config.show && (!window.isVisible() || window.isMinimized())) { held = true; return; }
  held = false;
  window.webContents.send(EVENT_CHANNEL);
}
async function launch(args: string[]): Promise<void> {
  await service.control("launch.args", { args });
}
const ownsInstance = app.requestSingleInstanceLock();
app.on("second-instance", (_event, argv) => { host?.show(); void launch(argv.slice(app.isPackaged ? 1 : 2)).catch(() => host?.notify("Saiph", "The requested action could not finish.")); });
app.on("before-quit", event => {
  if (closing) return;
  event.preventDefault();
  closing = true;
  host?.close();
  const failed = config.status === "failed";
  void service.stop().finally(async () => {
    await binary.close();
    save(failed ? "failed" : "stopped");
    if (!sessionFile) { try { fs.unlinkSync(path.join(directory, "service.json")); fs.rmdirSync(directory); } catch {} }
    app.exit(failed ? 1 : 0);
  });
});
app.on("window-all-closed", () => { if (!host?.tray) app.quit(); });
service.on("changed", announce);
service.on("failed", () => {
  if (closing) return;
  save("failed");
  if (!isolated) dialog.showErrorBox("Saiph", "The desktop service stopped. Your profile was preserved. Reopen Saiph to reconnect.");
  app.quit();
});

function trusted(event: Electron.IpcMainInvokeEvent | Electron.IpcMainEvent): "dashboard" | "viewer" {
  if (window && event.sender === window.webContents && event.senderFrame === window.webContents.mainFrame && event.senderFrame?.url === APP_URL) return "dashboard";
  if (host?.acceptsViewer(event.sender) && event.senderFrame === event.sender.mainFrame && event.senderFrame?.url === "saiph-app://desktop/screen.html") return "viewer";
  throw new Error("Untrusted desktop caller.");
}
async function start(): Promise<void> {
  if (!ownsInstance) { app.exit(0); return; }
  await app.whenReady();
  if (!fs.statSync(dashboard).isFile()) throw new Error("Build the desktop dashboard before launching Saiph.");
  Menu.setApplicationMenu(null);
  electronSession.defaultSession.setPermissionRequestHandler((_web, _permission, callback) => callback(false));
  electronSession.defaultSession.setPermissionCheckHandler(() => false);
  electronSession.defaultSession.on("will-download", event => event.preventDefault());
  protocol.handle("saiph-app", request => readAsset(path.dirname(dashboard), request.url, request.method));
  window = new BrowserWindow({ width: 1320, height: 900, minWidth: 940, minHeight: 650, title: "Saiph", show: false, backgroundColor: "#040916", icon,
    webPreferences: { preload: path.join(__dirname, "preload.cjs"), sandbox: true, contextIsolation: true, nodeIntegration: false, webSecurity: true, backgroundThrottling: !sessionFile,
      additionalArguments: sessionFile ? [`--saiph-ui-nonce=${config.nonce}`] : [] } });
  const contents = window.webContents;
  contents.setWindowOpenHandler(() => ({ action: "deny" }));
  contents.on("will-navigate", (event, url) => { if (url !== APP_URL) event.preventDefault(); });
  contents.on("will-attach-webview", event => event.preventDefault());
  contents.on("render-process-gone", () => {
    if (closing) return;
    if (isolated) { save("failed"); app.quit(); }
    else void dialog.showMessageBox(window!, { type: "error", title: "Saiph", message: "The interface stopped responding. Reload it to reconnect to your running services.", buttons: ["Reload", "Quit"] }).then(result => result.response === 0 ? contents.reload() : app.quit());
  });
  contents.on("context-menu", (_event, params) => { if (params.isEditable) Menu.buildFromTemplate([{ role: "cut", enabled: params.editFlags.canCut }, { role: "copy", enabled: params.editFlags.canCopy }, { role: "paste", enabled: params.editFlags.canPaste }, { role: "selectAll" }]).popup({ window }); });
  await binary.listen(directory);
  host = new NativeHost(window, service, binary, isolated, path.join(__dirname, "preload.cjs"), icon, config.profile, sessionFile ? directory : undefined, config.nonce);
  await host.install();
  const hwnd = window.getNativeWindowHandle();
  const serviceConfig = path.join(directory, "service.json");
  fs.writeFileSync(serviceConfig, JSON.stringify({ schema: 1, mode: config.mode, profile: config.profile,
    desktop_pid: process.pid, desktop_executable: process.execPath, window_handle: process.platform === "win32" ? Number(hwnd.length === 8 ? hwnd.readBigUInt64LE() : hwnd.readUInt32LE()) : 0,
    binary_address: binary.address, binary_token: binary.token, fixture: config.fixture || "empty" }), { mode: 0o600 });
  await service.start(app.isPackaged ? serviceExecutable : config.python, repo, serviceConfig, config.mode, app.isPackaged);
  ipcMain.handle(REQUEST_CHANNEL, async (event, method: unknown, args: unknown) => {
    const caller = trusted(event);
    validateCall(method, args);
    if (caller === "viewer") {
      if (!["screen.status", "screen.input", "screen.stop"].includes(method)) throw new Error("This action is unavailable in the phone window.");
      if (method === "screen.status") return { ok: true, result: await service.control("screen.status") };
    }
    return service.call(method, args);
  });
  ipcMain.handle("saiph:frame-latest", event => {
    const caller = trusted(event);
    return (caller === "viewer" ? ["screen"] : ["camera", "screen"]).map(source => binary.metadata(source)).filter(Boolean);
  });
  ipcMain.on("saiph:dragging", (event, active) => { if (trusted(event) === "dashboard") contents.send("saiph:dragging", active === true); });
  ipcMain.on("saiph:files", (event, paths: unknown) => {
    if (trusted(event) !== "dashboard" || !Array.isArray(paths) || paths.length > 100 || paths.some(p => typeof p !== "string" || !path.isAbsolute(p))) return;
    const valid: string[] = [], rejected: { name: string; reason: string }[] = [];
    for (const file of paths) { try { if (fs.statSync(file).isFile()) valid.push(file); else rejected.push({ name: path.basename(file), reason: "Choose files, not folders." }); } catch { rejected.push({ name: path.basename(file), reason: "This file is unavailable." }); } }
    contents.send("saiph:dragging", false);
    contents.send("saiph:drop", { paths: valid, rejected });
  });
  const visibility = () => {
    if (!window || window.isDestroyed()) return;
    const visible = !config.show || window.isVisible() && !window.isMinimized();
    void service.control("visibility", { visible }).catch(() => {});
    if (visible && held) announce();
  };
  window.on("show", visibility); window.on("restore", visibility); window.on("hide", visibility); window.on("minimize", visibility);
  await window.loadURL(APP_URL);
  if (config.show) window.show();
  save("ready");
  if (!sessionFile) await launch(process.argv.slice(app.isPackaged ? 1 : 2));
  else {
    let lastWindowRequest = 0;
    const timer = setInterval(() => {
      try { const stop = JSON.parse(fs.readFileSync(path.join(directory, "stop-request.json"), "utf8")); if (Object.keys(stop).length === 1 && stop.nonce === config.nonce) app.quit(); } catch {}
      try { const command = JSON.parse(fs.readFileSync(path.join(directory, "window-request.json"), "utf8")); if (Number.isInteger(command.id) && command.id > lastWindowRequest && window && !window.isDestroyed()) { applyWindowControl(window, command, config.nonce); lastWindowRequest = command.id; fs.writeFileSync(path.join(directory, "window-state.json"), JSON.stringify({ id: command.id, ok: true, bounds: window.getBounds() })); } } catch {}
      try { const command = JSON.parse(fs.readFileSync(path.join(directory, "service-control.json"), "utf8")); if (command.nonce === config.nonce && command.action === "test.frame" && isolated) { fs.unlinkSync(path.join(directory, "service-control.json")); void service.control("test.frame").then(result => fs.writeFileSync(path.join(directory, "service-result.json"), JSON.stringify({ ok: true, result })), error => fs.writeFileSync(path.join(directory, "service-result.json"), JSON.stringify({ ok: false, error: error.message }))); } } catch {}
    }, 200);
    timer.unref();
    setTimeout(() => app.quit(), config.timeout * 1000).unref();
  }
}
void start().catch(() => { save("failed"); if (!isolated) dialog.showErrorBox("Saiph", "Saiph could not start. Your profile was preserved. Check the installation and reopen it."); app.quit(); });
