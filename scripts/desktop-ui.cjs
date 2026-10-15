// SPDX-License-Identifier: AGPL-3.0-or-later
// Controls only an explicitly launched desktop-ui.py session, through the real DOM.
const fs = require("node:fs");
const path = require("node:path");
const { parseArgs } = require("node:util");
const { pathToFileURL } = require("node:url");

function readSession(file) {
  const session = JSON.parse(fs.readFileSync(file, "utf8"));
  const endpoint = new URL(session.endpoint);
  if (session.schema !== 1 || session.status !== "ready" || !Number.isInteger(session.pid)
    || !/^[a-f0-9]{48}$/.test(session.nonce) || !["isolated", "live"].includes(session.mode)
    || endpoint.protocol !== "http:" || endpoint.hostname !== "127.0.0.1" || !endpoint.port
    || endpoint.username || endpoint.password || endpoint.pathname !== "/" || endpoint.search || endpoint.hash
    || new URL(session.dashboard).protocol !== "file:") {
    throw new Error("Not a ready local Saiph UI test session. Launch scripts/desktop-ui.py first.");
  }
  return session;
}

async function connectDesktop(file) {
  const session = readSession(file);
  const playwright = require(process.env.SAIPH_UI_PLAYWRIGHT_PATH || path.resolve(__dirname, "../frontend/node_modules/@playwright/test"));
  const browser = await playwright.chromium.connectOverCDP(session.endpoint, { noDefaults: true, timeout: 15000 });
  try {
    const candidates = browser.contexts().flatMap(context => context.pages()).filter(page => page.url() === session.dashboard);
    for (const page of candidates) {
      if (await page.evaluate(() => window.__saiphUISession) === session.nonce) {
        page.setDefaultTimeout(15000);
        return { browser, page, session, expect: playwright.expect };
      }
    }
    throw new Error("The debug endpoint belongs to another window; no action was performed.");
  } catch (error) {
    await browser.close(); // Disconnect CDP without closing the native app.
    throw error;
  }
}

function target(page, values) {
  if (values.label !== undefined) return page.getByLabel(values.label, { exact: true });
  if (values.role && values.name !== undefined) return page.getByRole(values.role, { name: values.name, exact: true });
  throw new Error("Choose --label or --role with --name, using names from snapshot.");
}

async function main(args = process.argv.slice(2)) {
  const { values, positionals } = parseArgs({ args, allowPositionals: true, options: {
    session: { type: "string" }, role: { type: "string" }, name: { type: "string" },
    label: { type: "string" }, value: { type: "string" }, key: { type: "string" },
    output: { type: "string" }, script: { type: "string" }, help: { type: "boolean" },
  } });
  if (values.help) {
    console.log("node scripts/desktop-ui.cjs --session <session.json> snapshot|click|fill|check|uncheck|select|press|screenshot|run|stop\n"
      + "Targets: --role button --name Settings, or --label 'Computer name'.\n"
      + "fill/select: --value; press: --key; screenshot: --output; run: --script <flow.cjs>.\n"
      + "A flow exports async ({ page, expect, session }) => { ... }; the caller disconnects afterward.");
    return;
  }
  const command = positionals[0];
  if (!values.session || positionals.length !== 1 || !["snapshot", "click", "fill", "check", "uncheck", "select", "press", "screenshot", "run", "stop"].includes(command)) {
    throw new Error("Provide --session <session.json> and one supported command; use --help.");
  }
  const connection = await connectDesktop(values.session);
  const { page } = connection;
  try {
    switch (command) {
      case "snapshot": console.log(await page.locator("body").ariaSnapshot()); break;
      case "click": await target(page, values).click(); break;
      case "fill":
        if (values.value === undefined) throw new Error("fill requires --value");
        await target(page, values).fill(values.value); break;
      case "check": await target(page, values).check(); break;
      case "uncheck": await target(page, values).uncheck(); break;
      case "select":
        if (values.value === undefined) throw new Error("select requires --value");
        await target(page, values).selectOption(values.value); break;
      case "press":
        if (!values.key) throw new Error("press requires --key");
        await page.keyboard.press(values.key); break;
      case "screenshot":
        if (!values.output) throw new Error("screenshot requires --output");
        fs.mkdirSync(path.dirname(path.resolve(values.output)), { recursive: true });
        await page.screenshot({ path: values.output }); break;
      case "run": {
        if (!values.script) throw new Error("run requires --script");
        const flow = (await import(pathToFileURL(path.resolve(values.script)).href)).default;
        if (typeof flow !== "function") throw new Error("The flow must export a function.");
        await flow(connection); break;
      }
      case "stop":
        fs.writeFileSync(path.join(path.dirname(path.resolve(values.session)), "stop-request.json"), JSON.stringify({ nonce: connection.session.nonce }));
        break;
    }
  } finally {
    await connection.browser.close();
  }
}

module.exports = { connectDesktop, readSession, main };
if (require.main === module) main().catch(error => { console.error(error.message); process.exitCode = 1; });
