// SPDX-License-Identifier: AGPL-3.0-or-later
import { test } from "node:test";
import assert from "node:assert/strict";
import { connect, type Socket } from "node:net";
import { once } from "node:events";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { BinaryServer, MAX_BINARY } from "./binary.cjs";

function packet(header: object, data = Buffer.alloc(0)): Buffer {
  const json = Buffer.from(JSON.stringify({ ...header, bytes: data.length })), size = Buffer.alloc(4);
  size.writeUInt32BE(json.length);
  return Buffer.concat([size, json, data]);
}
async function connected(address: string): Promise<Socket> {
  const socket = connect(address); socket.on("error", () => {}); await once(socket, "connect"); return socket;
}
async function fixture(run: (server: BinaryServer) => Promise<void>) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "saiph-media-")), server = new BinaryServer();
  try { await server.listen(dir); await run(server); } finally { await server.close(); await fs.rm(dir, { recursive: true, force: true }); }
}
test("binary channel authenticates before accepting pictures and rejects oversized headers", async () => fixture(async server => {
  const wrong = await connected(server.address), closed = once(wrong, "close");
  wrong.write(packet({ kind: "hello", protocol: 1, role: "publish", token: "0".repeat(64) })); await closed;
  assert.equal(server.frame("screen"), undefined);
  const oversized = await connected(server.address), closed2 = once(oversized, "close");
  oversized.write(Buffer.from([0, 0, 16, 1])); await closed2;
}));
test("fragmented pictures replace latest per source; clipboard has a separate authenticated direction", async () => fixture(async server => {
  const publisher = await connected(server.address), receiver = await connected(server.address);
  publisher.write(packet({ kind: "hello", protocol: 1, role: "publish", token: server.token }));
  receiver.write(packet({ kind: "hello", protocol: 1, role: "receive", token: server.token }));
  const data = packet({ kind: "frame", source: "screen", sequence: 3 }, Buffer.from("synthetic picture"));
  const frame = once(server, "frame");
  publisher.write(data.subarray(0, 2)); publisher.write(data.subarray(2, 19)); publisher.write(data.subarray(19));
  await frame;
  assert.equal(server.frame("screen")?.toString(), "synthetic picture");
  const next = once(server, "frame"); publisher.write(packet({ kind: "frame", source: "screen", sequence: 4 }, Buffer.from("newest"))); await next;
  assert.equal(server.frame("screen")?.toString(), "newest");
  const received = once(receiver, "data"); await server.send({ kind: "clipboard.local", mime: "text/plain" }, Buffer.from("text"));
  assert.ok((await received)[0].includes(Buffer.from("text")));
  await assert.rejects(server.send({}, Buffer.alloc(MAX_BINARY + 1)), /busy/);
  const transfer = once(server, "transfer"), token = "a".repeat(32);
  publisher.write(packet({ kind: "clipboard", token, mime: "text/plain" }, Buffer.from("remote"))); await transfer;
  assert.equal((await server.take(token)).toString(), "remote");
  server.clearFrames("screen"); assert.equal(server.metadata("screen"), undefined);
}));
