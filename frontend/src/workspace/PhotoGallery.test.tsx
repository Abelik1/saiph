// SPDX-License-Identifier: AGPL-3.0-or-later
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Photos } from "./PhotoGallery";
import type { PhoneFeatureState } from "./PhoneTabs";
import type { Client } from "./types";
const photo = {
  id: "p",
  photo_id: "17",
  device_id: "phone",
  name: "Portrait.jpg",
  timestamp: 2,
  preview: "data:image/jpeg;base64,AA==",
};
const info: PhoneFeatureState = {
  photos: [
    photo,
    { ...photo, id: "l", photo_id: "18", name: "Landscape.jpg", timestamp: 1 },
  ],
  threads: [],
  messages: [],
  calls: [],
  files: [],
};
const phone = { id: "phone", online: true, capabilities: ["photos"] };
describe("Original photo interactions", () => {
  it("keeps browsing lightweight and opens a modal with original-quality actions", async () => {
    const call = vi.fn().mockResolvedValue({
      url: "file:///original.jpg",
      width: 900,
      height: 1600,
      size: 1024,
    });
    render(
      <Photos
        info={info}
        phone={phone}
        client={{ call } as unknown as Client}
      />,
    );
    const tile = screen.getByRole("button", { name: "Open Portrait.jpg" });
    fireEvent.pointerEnter(tile);
    fireEvent.focus(tile);
    expect(call).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Save photo" })).toBeNull();
    fireEvent.click(tile);
    const viewer = screen.getByRole("dialog", { name: "Portrait.jpg" });
    await waitFor(() =>
      expect(within(viewer).getByAltText("Portrait.jpg")).toHaveAttribute(
        "src",
        "file:///original.jpg",
      ),
    );
    fireEvent.load(within(viewer).getByAltText("Portrait.jpg"));
    expect(within(viewer).getByRole("status")).toHaveTextContent(
      "Original quality",
    );
    fireEvent.click(within(viewer).getByRole("button", { name: "Copy image" }));
    await waitFor(() =>
      expect(call).toHaveBeenCalledWith("phone.photo.copy", {
        device_id: "phone",
        photo_id: "17",
      }),
    );
    fireEvent.click(
      within(viewer).getByRole("button", { name: "Photo details" }),
    );
    expect(within(viewer).getByText("900 × 1600")).toBeVisible();
    fireEvent.click(
      within(viewer).getByRole("button", { name: "Close image" }),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => expect(tile).toHaveFocus());
  });
  it("replaces the browser menu and supports keyboard navigation and dismissal", async () => {
    const call = vi.fn().mockResolvedValue({ copied: true });
    render(
      <Photos
        info={info}
        phone={phone}
        client={{ call } as unknown as Client}
      />,
    );
    const tile = screen.getByRole("button", { name: "Open Portrait.jpg" });
    const event = new MouseEvent("contextmenu", {
      bubbles: true,
      cancelable: true,
      clientX: 100,
      clientY: 100,
    });
    fireEvent(tile, event);
    expect(event.defaultPrevented).toBe(true);
    const menu = screen.getByRole("menu", { name: "Photo actions" });
    expect(
      within(menu).getByRole("menuitem", { name: "Open image" }),
    ).toHaveFocus();
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(
      within(menu).getByRole("menuitem", { name: "Copy image" }),
    ).toHaveFocus();
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Copy image" }));
    await waitFor(() =>
      expect(call).toHaveBeenCalledWith("phone.photo.copy", {
        device_id: "phone",
        photo_id: "17",
      }),
    );
    fireEvent.keyDown(menu, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(tile).toHaveFocus();
  });
  it("ignores a late response after moving to the next photo", async () => {
    let resolveFirst: (value: unknown) => void = () => {};
    const call = vi.fn((_: string, args: Record<string, unknown>) =>
      args.photo_id === "17"
        ? new Promise((resolve) => {
            resolveFirst = resolve;
          })
        : Promise.resolve({
            url: "file:///landscape.jpg",
            width: 1600,
            height: 900,
            size: 512,
          }),
    );
    render(
      <Photos
        info={info}
        phone={phone}
        client={{ call } as unknown as Client}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Open Portrait.jpg" }));
    fireEvent.click(screen.getByRole("button", { name: "Next photo" }));
    resolveFirst({ url: "file:///portrait.jpg" });
    await waitFor(() =>
      expect(
        within(
          screen.getByRole("dialog", { name: "Landscape.jpg" }),
        ).getByAltText("Landscape.jpg"),
      ).toHaveAttribute("src", "file:///landscape.jpg"),
    );
  });
  it("keeps the preview and save action accessible when the original fails", async () => {
    render(
      <Photos
        info={info}
        phone={phone}
        client={
          {
            call: vi.fn().mockRejectedValue(new Error("Phone is offline")),
          } as unknown as Client
        }
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Open Portrait.jpg" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Phone is offline",
    );
    expect(
      within(screen.getByRole("dialog")).getByAltText("Portrait.jpg"),
    ).toHaveAttribute("src", photo.preview);
    expect(screen.getByRole("button", { name: "Save photo" })).toBeEnabled();
  });
  it("retries an original in place and allows a cached original save offline", async () => {
    const call = vi
      .fn()
      .mockRejectedValueOnce(new Error("Phone is offline"))
      .mockResolvedValueOnce({
        url: "file:///cached.jpg",
        width: 900,
        height: 1500,
        size: 1024,
      })
      .mockResolvedValue({ status: "saved", folder: "Downloads" });
    render(
      <Photos
        info={info}
        phone={{ ...phone, online: false }}
        client={{ call } as unknown as Client}
      />,
    );
    expect(screen.getByText(/Showing saved previews/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Open Portrait.jpg" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Phone is offline",
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry original" }));
    await waitFor(() =>
      expect(
        within(screen.getByRole("dialog")).getByAltText("Portrait.jpg"),
      ).toHaveAttribute("src", "file:///cached.jpg"),
    );
    expect(screen.queryByRole("alert")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Save photo" }));
    await waitFor(() =>
      expect(call).toHaveBeenCalledWith("phone.photo.save", {
        device_id: "phone",
        photo_id: "17",
      }),
    );
  });
  it("closes portal menus and viewers when the phone page is hidden", () => {
    const client = { call: vi.fn().mockResolvedValue({}) } as unknown as Client;
    const view = render(<Photos info={info} phone={phone} client={client} />);
    fireEvent.click(screen.getByRole("button", { name: "Open Portrait.jpg" }));
    expect(screen.getByRole("dialog")).toBeVisible();
    view.rerender(
      <Photos info={info} phone={phone} client={client} active={false} />,
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    view.rerender(<Photos info={info} phone={phone} client={client} />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
