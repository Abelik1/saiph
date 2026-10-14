// SPDX-License-Identifier: AGPL-3.0-or-later
/// <reference types="node" />
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

// The design system rule from docs/DESKTOP_DESIGN_SYSTEM.md: a colour is written
// once, in a token file, and everything else reads a role. These tests keep it true.

// Vitest runs from frontend/.
const src = resolve(process.cwd(), "src");

/** Files allowed to state colours outright. */
const tokenFiles = new Set(["design-system/families.css", "design-system/tokens.css"]);

/**
 * Colours that are not interface. Adding a file here needs the same kind of argument.
 * - PairingQr: a QR code is black on white in every theme, or phone cameras cannot read it.
 * - preview/fixture: synthetic photo thumbnails for the design preview, not shipped.
 */
const exempt = new Set(["workspace/PairingQr.tsx", "preview/fixture.ts"]);

/**
 * Stylesheets from before the design system, kept in the "legacy" cascade layer
 * until their pages are rebuilt from src/components/ui. Each may only lose literals:
 * lower the number when you move rules onto roles, and delete the line when it
 * reaches zero. Never raise one.
 */
const legacy: Record<string, number> = {
  "workspace/workspace.css": 273,
  "workspace/waves.css": 60,
  "workspace/link.css": 41,
  "workspace/PhotoGallery.css": 24,
  "workspace/SettingsLayout.css": 24,
  "workspace/PhoneTabs.css": 1,
};

const hex = /(?<![\w&%-])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b/g;
const functional = /\b(?:rgba?|hsla?|oklch|oklab|lab|lch)\(\s*[\d.]+[^()]*\)/g;
const named = /:\s*[^;{}]*?\b(white|black)\b(?!-)/g;
// Tailwind's own palette (bg-slate-800, text-white …) bypasses the roles.
const palette = /(?<![\w-])(?:[a-z-]+:)*(?:bg|text|border(?:-[trblxy])?|ring|ring-offset|outline|fill|stroke|from|via|to|shadow|decoration|accent|caret|divide|placeholder)-(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d{2,3}(?![\w-])|(?<![\w-])(?:[a-z-]+:)*(?:bg|text|border|fill|stroke)-(?:white|black)(?![\w-])/g;

function stripComments(source: string, css: boolean) {
  const withoutBlocks = source.replace(/\/\*[\s\S]*?\*\//g, "");
  return css ? withoutBlocks : withoutBlocks.replace(/^\s*\/\/.*$/gm, "");
}

/** Every colour literal in a stylesheet or module, after comments are removed. */
export function colourLiterals(source: string, kind: "css" | "ts"): string[] {
  const text = stripComments(source, kind === "css");
  const found = [...text.matchAll(hex), ...text.matchAll(functional)].map((match) => match[0]);
  if (kind === "css") {
    for (const match of text.matchAll(named)) if (!/url\(/.test(match[0])) found.push(match[1]);
  } else {
    found.push(...[...text.matchAll(palette)].map((match) => match[0]));
  }
  return found;
}

function walk(directory: string): string[] {
  return readdirSync(directory).flatMap((name: string) => {
    const path = join(directory, name);
    if (statSync(path).isDirectory()) return walk(path);
    return /\.(css|tsx?)$/.test(name) && !/\.(test|spec)\.tsx?$/.test(name) && name !== "test-setup.ts" ? [path] : [];
  });
}

function files() {
  return walk(src).map((path) => ({ file: relative(src, path).split("\\").join("/"), source: readFileSync(path, "utf8") }));
}

describe("design tokens", () => {
  it("finds literals, including ones planted in a component", () => {
    expect(colourLiterals(".x { color: #22d3ee; background: rgba(0, 0, 0, .4); border-color: white }", "css")).toEqual(["#22d3ee", "rgba(0, 0, 0, .4)", "white"]);
    expect(colourLiterals('<div className="bg-slate-800 hover:text-white" style={{ color: "#fff" }} />', "ts")).toEqual(["#fff", "bg-slate-800", "hover:text-white"]);
    expect(colourLiterals('<div className="bg-card text-muted-foreground border-border/60 bg-white-ish" />', "ts")).toEqual([]);
    expect(colourLiterals("mask: url(\"data:image/svg+xml,%3Cpath stroke='black'/%3E\")", "css")).toEqual([]);
  });

  it("keeps colours in the token files", () => {
    const problems: string[] = [];
    for (const { file, source } of files()) {
      if (tokenFiles.has(file) || exempt.has(file) || file in legacy) continue;
      for (const literal of colourLiterals(source, file.endsWith(".css") ? "css" : "ts")) problems.push(`${file}: ${literal}`);
    }
    expect(problems).toEqual([]);
  });

  it("only ever removes literals from the legacy stylesheets", () => {
    const counts = Object.fromEntries(files().filter(({ file }) => file in legacy).map(({ file, source }) => [file, colourLiterals(source, "css").length]));
    for (const [file, ceiling] of Object.entries(legacy)) expect(counts[file] ?? 0, `${file} gained colour literals; read a role from tokens.css`).toBeLessThanOrEqual(ceiling);
  });

  it("reads colour families only in the token file", () => {
    const readers = files().filter(({ file, source }) => !tokenFiles.has(file) && /var\(--(?:hue|sat)-/.test(stripComments(source, true))).map(({ file }) => file);
    expect(readers).toEqual([]);
  });

  it("defines every role that Tailwind exposes", () => {
    const tokens = readFileSync(join(src, "design-system/tokens.css"), "utf8");
    const index = readFileSync(join(src, "index.css"), "utf8");
    const exposed = [...index.matchAll(/--color-[\w-]+:\s*var\((--[\w-]+)\)/g)].map((match) => match[1]);
    expect(exposed.length).toBeGreaterThan(20);
    for (const role of exposed) expect(tokens, `${role} is exposed to Tailwind but not defined`).toMatch(new RegExp(`\\n\\s*${role}:`));
  });
});
