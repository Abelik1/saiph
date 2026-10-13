// SPDX-License-Identifier: AGPL-3.0-or-later
import "@testing-library/jest-dom/vitest"

// jsdom does not implement the native dialog top layer.
HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
