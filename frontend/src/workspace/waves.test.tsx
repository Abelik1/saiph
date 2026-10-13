// SPDX-License-Identifier: AGPL-3.0-or-later
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SaiphMark, WaveField, WaveLoader, WaveProgress } from "./waves";

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
});
