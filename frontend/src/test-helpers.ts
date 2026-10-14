// SPDX-License-Identifier: AGPL-3.0-or-later
// Interactions for design-system components that jsdom cannot drive with a plain click.
import { fireEvent, screen } from "@testing-library/react";

/** Opens a tab: Radix tabs activate on mouse down, as a pointer does. */
export function openTab(name: string) {
  fireEvent.mouseDown(screen.getByRole("tab", { name }), { button: 0 });
}

/** Chooses an option from a Select, the way a keyboard user does. */
export function chooseOption(label: string | RegExp, option: string) {
  const trigger = screen.getByRole("combobox", { name: label });
  fireEvent.keyDown(trigger, { key: "Enter" });
  const item = screen.getByRole("option", { name: option });
  fireEvent.keyDown(item, { key: "Enter" });
}

/** Chooses an item from a dropdown menu opened from the keyboard. */
export function chooseMenuItem(trigger: string | RegExp, item: string | RegExp) {
  fireEvent.keyDown(screen.getByRole("button", { name: trigger }), { key: "Enter" });
  fireEvent.click(screen.getByRole("menuitemradio", { name: item }));
}
