// SPDX-License-Identifier: AGPL-3.0-or-later
import "@testing-library/jest-dom/vitest"

// jsdom has no canvas; the decorative wave field simply skips drawing.
HTMLCanvasElement.prototype.getContext = (() => null) as unknown as HTMLCanvasElement["getContext"];

// jsdom does not implement the native dialog top layer.
HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
