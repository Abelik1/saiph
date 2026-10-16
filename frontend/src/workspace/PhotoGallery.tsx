// SPDX-License-Identifier: AGPL-3.0-or-later
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  ChevronLeft,
  ChevronRight,
  Copy,
  Download,
  Image,
  Info,
  LoaderCircle,
  Maximize2,
  MoreHorizontal,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import type { Client } from "./types";
import type { PhoneFeatureState, PhonePhoto, PhotoSave } from "./PhoneTabs";
import { Action, Empty } from "./ui";

type PhoneDevice = { id: string; hosted?: boolean; online: boolean; capabilities: string[] };
type Original = { url: string; width: number; height: number; size: number };
function SavePhoto({
  photo,
  phone,
  client,
  recorded,
  menuItem = false,
}: {
  photo: PhonePhoto;
  phone: PhoneDevice;
  client: Client;
  recorded?: PhotoSave;
  menuItem?: boolean;
}) {
  // The call result shows at once; a newer recorded state (e.g. the download finishing) then takes over.
  const [pending, setPending] = useState(false);
  const [local, setLocal] = useState<{ result: PhotoSave; seen?: string }>();
  const recordedAt = useRef(recorded?.updated_at);
  useEffect(() => {
    recordedAt.current = recorded?.updated_at;
  }, [recorded?.updated_at]);
  const shown = pending
    ? { status: "saving" as const }
    : local && local.seen === recorded?.updated_at
      ? local.result
      : recorded;
  const save = async () => {
    setPending(true);
    try {
      const result = await client.call<PhotoSave>("phone.photo.save", {
        device_id: phone.id,
        photo_id: photo.photo_id,
      });
      setLocal({
        result: result?.status ? result : { status: "saving" },
        seen: recordedAt.current,
      });
    } catch (error) {
      setLocal({
        result: {
          status: "failed",
          error: String(error instanceof Error ? error.message : error),
        },
        seen: recordedAt.current,
      });
    } finally {
      setPending(false);
    }
  };
  if (shown?.status === "saved")
    return (
      <div className="phone-photo-save">
        <small role="status" title={shown.path || undefined}>
          {shown.existing ? "Already saved to " : "Saved to "}
          {shown.folder || "Downloads → Orion"}
        </small>
        {shown.file_id && (
          <Action
            role={menuItem ? "menuitem" : undefined}
            className={menuItem ? "photo-menu-item" : "text-button"}
            run={() => client.call("phone.file.open", { id: shown.file_id })}
          >
            Show in folder
          </Action>
        )}
      </div>
    );
  const saving = shown?.status === "saving";
  return (
    <div className="phone-photo-save">
      <button
        type="button"
        role={menuItem ? "menuitem" : undefined}
        className={menuItem ? "photo-menu-item" : "text-button"}
        disabled={saving}
        onClick={() => void save()}
      >
        {saving ? (
          <LoaderCircle size={15} className="spin" />
        ) : (
          <Download size={16} />
        )}
        {saving ? "Saving…" : "Save photo"}
      </button>
      {saving && (
        <small role="status">Saving the original from your phone…</small>
      )}
      {shown?.status === "failed" && (
        <small className="inline-error" role="alert">
          {shown.error || "The photo could not be saved. Try again."}
        </small>
      )}
    </div>
  );
}
function CopyPhoto({
  photo,
  client,
  menuItem = false,
}: {
  photo: PhonePhoto;
  client: Client;
  menuItem?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  return (
    <Action
      role={menuItem ? "menuitem" : undefined}
      // In the menu every item shares the menu's look; in the viewer it is a quiet pill.
      className={menuItem ? "photo-menu-item" : "text-button"}
      run={async () => {
        setCopied(false);
        await client.call("phone.photo.copy", {
          device_id: photo.device_id,
          photo_id: photo.photo_id,
        });
        setCopied(true);
      }}
    >
      <Copy size={16} />
      {copied ? "Copied original" : "Copy photo"}
    </Action>
  );
}

function PhotoViewer({
  photo,
  phone,
  client,
  recorded,
  onClose,
  onStep,
  position,
}: {
  photo: PhonePhoto;
  phone: PhoneDevice;
  client: Client;
  recorded?: PhotoSave;
  onClose: () => void;
  onStep: (step: number) => void;
  position: string;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [original, setOriginal] = useState<Original>();
  const [loaded, setLoaded] = useState(false),
    [error, setError] = useState("");
  const [zoomed, setZoomed] = useState(false),
    [details, setDetails] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);
  useEffect(() => {
    let active = true;
    client
      .call<Original>("phone.photo.view", {
        device_id: photo.device_id,
        photo_id: photo.photo_id,
      })
      .then((value) => {
        if (active) setOriginal(value);
      })
      .catch((error) => {
        if (active)
          setError(error instanceof Error ? error.message : String(error));
      });
    return () => {
      active = false;
    };
  }, [client, photo.device_id, photo.photo_id, attempt]);
  return createPortal(
    <dialog
      ref={dialog}
      className="photo-viewer"
      onContextMenu={(event) => event.preventDefault()}
      aria-label={photo.name}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onKeyDown={(event) => {
        if (event.key === "ArrowLeft") onStep(-1);
        if (event.key === "ArrowRight") onStep(1);
      }}
    >
      <header className="photo-viewer-toolbar">
        <div className="photo-viewer-title">
          <strong>{photo.name}</strong>
          <small>{position}</small>
        </div>
        <div className="photo-viewer-actions">
          <CopyPhoto photo={photo} client={client} />
          <SavePhoto
            photo={photo}
            phone={phone}
            client={client}
            recorded={recorded}
          />
          <button
            aria-label={zoomed ? "Fit image" : "Zoom to actual size"}
            disabled={!loaded}
            onClick={() => setZoomed(!zoomed)}
          >
            {zoomed ? <ZoomOut size={18} /> : <ZoomIn size={18} />}
          </button>
          <button
            aria-label="Photo details"
            aria-pressed={details}
            onClick={() => setDetails(!details)}
          >
            <Info size={18} />
          </button>
          <button aria-label="Close image" onClick={onClose}>
            <X size={21} />
          </button>
        </div>
      </header>
      <div
        className={"photo-viewer-stage" + (zoomed ? " zoomed" : "")}
        tabIndex={0}
        aria-label="Image preview"
      >
        <img
          key={attempt}
          src={original?.url || photo.preview}
          alt={photo.name}
          onLoad={(event) => {
            if (
              original &&
              event.currentTarget.getAttribute("src") === original.url
            ) {
              setLoaded(true);
              setError("");
            }
          }}
          onError={() =>
            setError(
              "The image could not be displayed. You can still save the original.",
            )
          }
        />
      </div>
      <button
        className="photo-previous"
        aria-label="Previous photo"
        onClick={() => onStep(-1)}
      >
        <ChevronLeft />
      </button>
      <button
        className="photo-next"
        aria-label="Next photo"
        onClick={() => onStep(1)}
      >
        <ChevronRight />
      </button>
      {details && (
        <aside className="photo-details">
          <h2>Photo details</h2>
          <dl>
            <dt>File name</dt>
            <dd>{photo.name}</dd>
            <dt>Added on phone</dt>
            <dd>{new Date(photo.timestamp).toLocaleString()}</dd>
            {original && (
              <>
                <dt>Dimensions</dt>
                <dd>
                  {original.width} × {original.height}
                </dd>
                <dt>File size</dt>
                <dd>{(original.size / 1024 / 1024).toFixed(2)} MB</dd>
              </>
            )}
          </dl>
        </aside>
      )}
      <footer className="photo-viewer-footer">
        {error ? (
          <span>
            <span role="alert">{error}</span>{" "}
            <button
              type="button"
              onClick={() => {
                setError("");
                setOriginal(undefined);
                setLoaded(false);
                setZoomed(false);
                setAttempt((value) => value + 1);
              }}
            >
              Retry original
            </button>
          </span>
        ) : (
          <span role="status">
            {loaded ? (
              "Original quality"
            ) : (
              <>
                <LoaderCircle size={14} className="spin" />
                Loading original…
              </>
            )}
          </span>
        )}
        <span>← → Browse · Esc Close</span>
      </footer>
    </dialog>,
    document.body,
  );
}

function PhotoMenu({
  photo,
  phone,
  client,
  recorded,
  point,
  onOpen,
  onClose,
}: {
  photo: PhonePhoto;
  phone: PhoneDevice;
  client: Client;
  recorded?: PhotoSave;
  point: { x: number; y: number };
  onOpen: () => void;
  onClose: () => void;
}) {
  const menu = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    menu.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const dismiss = (event: PointerEvent) => {
      if (!menu.current?.contains(event.target as Node)) onClose();
    };
    document.addEventListener("pointerdown", dismiss);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      previous?.focus();
    };
  }, [onClose]);
  return createPortal(
    <div
      ref={menu}
      role="menu"
      aria-label="Photo actions"
      className="photo-context-menu"
      style={{
        left: Math.max(8, Math.min(point.x, window.innerWidth - 280)),
        top: Math.max(8, Math.min(point.y, window.innerHeight - 310)),
      }}
      onKeyDown={(event) => {
        if (["Escape", "Tab"].includes(event.key)) {
          event.preventDefault();
          onClose();
        }
        if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
          event.preventDefault();
          const buttons = Array.from(
            menu.current?.querySelectorAll<HTMLButtonElement>(
              "button:not(:disabled)",
            ) || [],
          );
          const index = buttons.indexOf(
            document.activeElement as HTMLButtonElement,
          );
          buttons[
            event.key === "Home"
              ? 0
              : event.key === "End"
                ? buttons.length - 1
                : (index +
                    (event.key === "ArrowDown" ? 1 : -1) +
                    buttons.length) %
                  buttons.length
          ]?.focus();
        }
      }}
    >
      <div className="photo-menu-heading">
        <strong>{photo.name}</strong>
        <small>{new Date(photo.timestamp).toLocaleDateString()}</small>
      </div>
      <button role="menuitem" className="photo-menu-item" onClick={onOpen}>
        <Maximize2 size={16} />
        Open photo
      </button>
      <div role="group">
        <CopyPhoto photo={photo} client={client} menuItem />
      </div>
      <div role="group">
        <SavePhoto
          photo={photo}
          phone={phone}
          client={client}
          recorded={recorded}
          menuItem
        />
      </div>
    </div>,
    document.body,
  );
}

export function Photos({
  info,
  phone,
  client,
  active = true,
}: {
  info: PhoneFeatureState;
  phone?: PhoneDevice;
  client: Client;
  active?: boolean;
}) {
  const [status, setStatus] = useState("");
  const [selected, setSelected] = useState<string>();
  const [menu, setMenu] = useState<{
    photo: PhonePhoto;
    x: number;
    y: number;
  }>();
  const tiles = useRef(new Map<string, HTMLButtonElement>());
  const closeMenu = useCallback(() => setMenu(undefined), []);
  const [view, setView] = useState({ active, device: phone?.id });
  if (view.active !== active || view.device !== phone?.id) {
    setView({ active, device: phone?.id });
    setSelected(undefined);
    setMenu(undefined);
  }
  if (!phone?.capabilities.includes("photos"))
    return (
      <Empty title="Photos permission">
        {phone?.hosted ? "On your phone, tap Allow photo gallery. Your recent photos appear here after Android access is granted."
          : "Allow photos in Saiph on your phone. Your recent photos then appear automatically."}
      </Empty>
    );
  const rows = info.photos
    .filter((p) => p.device_id === phone.id)
    .sort((a, b) => b.timestamp - a.timestamp);
  const current = rows.findIndex((photo) => photo.id === selected),
    photo = rows[current];
  const recorded = (photo: PhonePhoto) =>
    info.photo_saves?.find(
      (s) => s.device_id === phone.id && s.photo_id === String(photo.photo_id),
    );
  return rows.length ? (
    <>
      <p className="muted">
        {phone.online
          ? `${rows.length} recent ${rows.length === 1 ? "photo" : "photos"}`
          : "Showing saved previews. Originals already loaded on this computer are available offline; reconnect your phone to download others."}
      </p>
      {status && <p role="status">{status}</p>}
      <div className="phone-photo-grid">
        {rows.map((photo) => (
          <article key={photo.id}>
            <button
              ref={(node) => {
                if (node) tiles.current.set(photo.id, node);
                else tiles.current.delete(photo.id);
              }}
              className="phone-photo-image"
              aria-label={"Open " + photo.name}
              draggable={phone.online}
              onClick={() => setSelected(photo.id)}
              onContextMenu={(event) => {
                event.preventDefault();
                event.currentTarget.focus();
                setMenu({ photo, x: event.clientX, y: event.clientY });
              }}
              onDragStart={(event) => {
                event.preventDefault();
                setStatus(
                  "Preparing the original photo… Keep holding to drag it.",
                );
                void client
                  .call<{ dragged?: boolean; ready?: boolean }>(
                    "phone.photo.drag",
                    { device_id: phone.id, photo_id: photo.photo_id },
                  )
                  .then((result) =>
                    setStatus(
                      result.dragged
                        ? ""
                        : result.ready
                          ? "Photo ready. Drag it to another app."
                          : "The original is downloading. Drag it again when it is ready.",
                    ),
                  )
                  .catch((error) => setStatus(String(error)));
              }}
            >
              {photo.preview ? (
                <img
                  src={photo.preview}
                  alt={photo.name}
                  loading="lazy"
                  draggable={false}
                />
              ) : (
                <Image size={30} aria-label="Photo preview loading" />
              )}
              <span className="photo-open-hint">
                <Maximize2 size={18} />
              </span>
            </button>
              <button
                className="photo-tile-menu"
                aria-label={"Actions for " + photo.name}
                aria-haspopup="menu"
                onClick={(event) => {
                  const bounds = event.currentTarget.getBoundingClientRect();
                  setMenu({
                    photo,
                    x: bounds.right - 264,
                    y: bounds.bottom + 4,
                  });
                }}
              >
                <MoreHorizontal size={18} />
              </button>
          </article>
        ))}
      </div>
      {active && menu && (
        <PhotoMenu
          photo={menu.photo}
          phone={phone}
          client={client}
          recorded={recorded(menu.photo)}
          point={menu}
          onClose={closeMenu}
          onOpen={() => {
            setSelected(menu.photo.id);
            setMenu(undefined);
          }}
        />
      )}
      {active && photo && (
        <PhotoViewer
          key={photo.id}
          photo={photo}
          phone={phone}
          client={client}
          recorded={recorded(photo)}
          position={`${current + 1} of ${rows.length}`}
          onClose={() => {
            setSelected(undefined);
            requestAnimationFrame(() => tiles.current.get(photo.id)?.focus());
          }}
          onStep={(step) =>
            setSelected(rows[(current + step + rows.length) % rows.length].id)
          }
        />
      )}
    </>
  ) : (
    <Empty
      title={
        phone.online
          ? "Your recent photos appear here"
          : "No saved photo previews"
      }
    >
      {phone.online
        ? "Saiph is reading the photos your phone allows it to share."
        : "Reconnect your phone to load recent photos."}
    </Empty>
  );
}
