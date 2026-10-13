// SPDX-License-Identifier: AGPL-3.0-or-later
import "@testing-library/jest-dom/vitest"

// jsdom has no canvas; the decorative wave field simply skips drawing.
HTMLCanvasElement.prototype.getContext = (() => null) as unknown as HTMLCanvasElement["getContext"];
