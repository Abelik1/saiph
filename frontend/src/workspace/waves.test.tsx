// SPDX-License-Identifier: AGPL-3.0-or-later
/// <reference types="node" />
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { SaiphMark, WAVE_HZ, WaveField, WaveLoader, WaveProgress, startWaveTicker } from "./waves";

describe("Wave theme", () => {
  it("marks finished and current steps on the progress string", () => {
    render(<WaveProgress steps={["Connect", "Phone", "Features"]} current={1} />);
    const steps = screen.getByRole("list", { name: "Setup steps" }).querySelectorAll("li");
    expect(steps[0]).toHaveClass("done");
    expect(steps[1]).toHaveAttribute("aria-current", "step");
    expect(steps[2]).not.toHaveClass("done");
  });

  it("keeps the decoration out of the accessibility tree", () => {
    const { container } = render(<><WaveField /><SaiphMark /><WaveLoader label="Opening Saiph…" /></>);
    expect(container.querySelector(".wave-field")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByRole("img", { name: "Saiph" })).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("Opening Saiph…");
  });
  let clocks = 1e9;
  function canvasHarness() {
    const clear = vi.fn(), gradient = { addColorStop: vi.fn() };
    const context = { clearRect: clear, setTransform: vi.fn(), createLinearGradient: () => gradient,
      createRadialGradient: () => gradient, fillRect: vi.fn(), beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), stroke: vi.fn() };
    const getContext = vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(context as unknown as CanvasRenderingContext2D);
    const originalMedia = window.matchMedia;
    window.matchMedia = vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() } as unknown as MediaQueryList);
    const listen = vi.spyOn(window, "addEventListener");
    const queue: FrameRequestCallback[] = [];
    const request = vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => { queue.push(callback); return queue.length; });
    const cancel = vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => {});
    // One clock for the field and its frames, far past ripples left by earlier tests.
    const base = (clocks += 1e6), clock = vi.spyOn(performance, "now").mockReturnValue(base);
    /** Runs display frames every 16 ms of mocked time, as long as the field asks for them. */
    const run = (from: number, to: number) => {
      for (let ms = from; ms <= to && queue.length; ms += 16) { clock.mockReturnValue(base + ms); queue.splice(0).forEach((callback) => callback(base + ms)); }
      clock.mockReturnValue(base + to);
    };
    const restore = () => { getContext.mockRestore(); window.matchMedia = originalMedia; listen.mockRestore(); request.mockRestore(); cancel.mockRestore(); clock.mockRestore(); };
    return { clear, listen, queue, run, cancel, restore };
  }

  it("draws a still string field once and never animates or follows the pointer", () => {
    const harness = canvasHarness();
    const view = render(<><WaveField /><WaveProgress steps={["Connect", "Phone"]} current={1} /></>);
    expect(harness.clear).toHaveBeenCalledTimes(1);
    expect(harness.queue).toHaveLength(0);
    // Pointer movement, clicks and progress changes leave the field alone.
    for (const name of ["pointermove", "pointerdown", "click"]) window.dispatchEvent(new Event(name));
    view.rerender(<><WaveField /><WaveProgress steps={["Connect", "Phone"]} current={0} /></>);
    harness.run(0, 5000);
    expect(harness.queue).toHaveLength(0);
    expect(harness.clear).toHaveBeenCalledTimes(1);
    expect(harness.listen.mock.calls.some(([name]) => /^(pointer|mouse|touch|click)/.test(String(name)))).toBe(false);
    view.unmount();
    harness.restore();
  });

  it("redraws in the same frame after a resize, once per burst", () => {
    const harness = canvasHarness();
    const view = render(<WaveField />);
    window.dispatchEvent(new Event("resize"));
    window.dispatchEvent(new Event("resize"));
    expect(harness.queue).toHaveLength(1);
    harness.run(0, 16);
    expect(harness.clear).toHaveBeenCalledTimes(2);
    view.unmount();
    harness.restore();
  });

  it("keeps the selected-tab wave moving forever on one low-rate timer", () => {
    const motifs = readFileSync(resolve(process.cwd(), "src/design-system/motifs.css"), "utf8");
    const rule = /\.wave-underline::before\s*\{([^}]*)\}/.exec(motifs)?.[1] || "";
    // No CSS animation: it would wake the compositor on every display frame.
    expect(rule).not.toMatch(/animation\s*:/);
    expect(rule).toMatch(/transform:\s*translateX\(var\(--wave-shift/);
    // Header and footer stay unblurred: a backdrop blur is recomputed for every wave step.
    const theme = readFileSync(resolve(process.cwd(), "src/workspace/waves.css"), "utf8");
    expect(theme).not.toMatch(/backdrop-filter/);

    vi.useFakeTimers();
    const originalMedia = window.matchMedia;
    window.matchMedia = vi.fn().mockReturnValue({ matches: false } as MediaQueryList);
    try {
      const line = document.createElement("span");
      line.className = "wave-underline";
      document.body.appendChild(line);
      const release = startWaveTicker();
      const again = startWaveTicker();
      const moves = () => { const seen = new Set<string>(); let count = 0;
        for (let i = 0; i < 10; i++) { const before = line.style.getPropertyValue("--wave-shift"); vi.advanceTimersByTime(1000 / WAVE_HZ); if (line.style.getPropertyValue("--wave-shift") !== before) count++; seen.add(line.style.getPropertyValue("--wave-shift")); }
        return { count, seen: seen.size }; };
      expect(WAVE_HZ).toBeLessThanOrEqual(10);
      expect(moves()).toEqual({ count: 10, seen: 10 });
      // Still moving an hour later: the loop never runs out.
      vi.advanceTimersByTime(3600 * 1000);
      expect(moves().count).toBe(10);
      // One shared timer: releasing one user keeps it going, releasing both stops it.
      again();
      expect(moves().count).toBe(10);
      release();
      expect(moves().count).toBe(0);
      line.remove();
    } finally { vi.useRealTimers(); window.matchMedia = originalMedia; }
  });
});
