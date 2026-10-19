// SPDX-License-Identifier: AGPL-3.0-or-later
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import type { AriaRole, FormEvent, ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import { LoaderCircle, X } from "lucide-react";
import type { Features, Job, Reminder } from "./types";
import { Button, type ButtonProps } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function Markdown({ text }: { text: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown
        skipHtml
        components={{
          img: () => null,
          a: ({ children }) => <span className="source-link">{children}</span>,
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
export function Empty({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <div data-slot="empty" className="grid justify-items-center gap-2 px-5 py-12 text-center [&_svg]:mb-1 [&_svg]:text-muted-foreground">
      <h3 className="m-0 text-[15px] font-semibold text-foreground">{title}</h3>
      {children && <p className="m-0 grid max-w-[46ch] justify-items-center gap-2 text-[13px] leading-relaxed text-muted-foreground">{children}</p>}
    </div>
  );
}
export function Card({
  title,
  subtitle,
  children,
  actions,
}: {
  title?: string;
  subtitle?: string;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <section className="card">
      {(title || actions) && (
        <div className="section-head">
          <div>
            {title && <h2>{title}</h2>}
            {subtitle && <p>{subtitle}</p>}
          </div>
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}
// Older call sites name a look with a class; each maps onto a Button variant.
const legacyVariants: Record<string, Pick<ButtonProps, "variant" | "size">> = {
  primary: { variant: "default" },
  "text-button": { variant: "tonal", size: "sm" },
  "icon-button": { variant: "ghost", size: "icon-sm" },
  danger: { variant: "destructive" },
};
function variantFor(className: string): Pick<ButtonProps, "variant" | "size"> | null {
  const names = className.split(/\s+/).filter(Boolean);
  const looks = names.filter((name) => name in legacyVariants);
  // A class the design system does not know styles the button itself; leave it to that CSS.
  if (names.some((name) => !(name in legacyVariants) && name !== "selected")) return null;
  return looks.length ? legacyVariants[looks[0]] : { variant: "secondary" };
}

/** A button that runs an async action, shows that it is working and reports a failure next to itself. */
export function Action({
  run,
  children,
  className = "",
  variant,
  size,
  disabled = false,
  title,
  ariaLabel,
  role,
  ariaChecked,
}: {
  run: () => Promise<unknown>;
  children: ReactNode;
  className?: string;
  variant?: ButtonProps["variant"];
  size?: ButtonProps["size"];
  disabled?: boolean;
  title?: string;
  ariaLabel?: string;
  role?: AriaRole;
  ariaChecked?: boolean;
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const button = useRef<HTMLButtonElement>(null);
  // A switch drawn by its own stylesheet keeps that look rather than a button's.
  const look = variant ? { variant, size } : role === "switch" ? null : variantFor(className);
  const props = {
    ref: button,
    type: "button" as const,
    title,
    "aria-label": ariaLabel,
    role,
    "aria-checked": ariaChecked,
    disabled: disabled || pending,
    onClick: async () => {
      setPending(true);
      setError("");
      try {
        await run();
      } catch (error) {
        setError(String(error instanceof Error ? error.message : error));
      } finally {
        setPending(false);
      }
    },
  };
  const content = <>{pending && <LoaderCircle size={15} className="spin" />}{children}</>;
  return (
    <>
      {look
        ? <Button {...props} variant={look.variant} size={look.size} className={variant ? className : cn(/\bselected\b/.test(className) && "selected")}>{content}</Button>
        : <button {...props} className={className}>{content}</button>}
      {/* In a row of buttons the error takes its own line after the row, never between buttons. */}
      {error && (
        <span className="inline-error order-last block w-full basis-full text-[12.5px]" role="alert">
          {error}
        </span>
      )}
    </>
  );
}
export function Form({
  submit,
  children,
  className = "",
  successMessage,
}: {
  submit: () => Promise<unknown>;
  children: ReactNode;
  className?: string;
  successMessage?: string;
}) {
  const [pending, setPending] = useState(false),
    [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [dirty, setDirty] = useState(false);
  const form = useRef<HTMLFormElement>(null);
  const baseline = useRef<string>(undefined);
  const values = useCallback(() => {
    return JSON.stringify(
      Array.from(
        form.current?.querySelectorAll<
          HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement
        >("input,select,textarea") || [],
      ).map((input) => [
        input.value,
        "checked" in input ? input.checked : null,
      ]),
    );
  }, []);
  useLayoutEffect(() => {
    if (!successMessage) return;
    const current = values();
    if (baseline.current === undefined) baseline.current = current;
    const changed = baseline.current !== current;
    if (dirty !== changed) setDirty(changed);
  }, [children, successMessage, dirty, values]);
  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setSaved(false);
    setError("");
    const submitted = values();
    try {
      await submit();
      baseline.current = submitted;
      setDirty(values() !== submitted);
      setSaved(true);
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error));
    } finally {
      setPending(false);
    }
  }
  return (
    <form
      ref={form}
      className={className}
      onSubmit={onSubmit}
      onChangeCapture={() => {
        setSaved(false);
        if (successMessage) setDirty(values() !== baseline.current);
      }}
    >
      <fieldset disabled={pending}>{children}</fieldset>
      {pending && <small role="status">Saving…</small>}
      {dirty && successMessage && (
        <small className="settings-unsaved" role="status">
          Unsaved changes · choose Save to apply.
        </small>
      )}
      {saved && !dirty && successMessage && (
        <small className="settings-saved" role="status">
          {successMessage}
        </small>
      )}
      {error && (
        <p role="alert" className="inline-error">
          {error}
        </p>
      )}
    </form>
  );
}
export function Modal({
  title,
  close,
  children,
}: {
  title: string;
  close: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>("input,textarea,button")?.focus();
    return () => previous?.focus();
  }, []);
  return (
    <div className="scrim" onClick={close}>
      <section
        ref={ref}
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === "Escape") close();
          if (e.key === "Tab") {
            const nodes = Array.from(
              ref.current?.querySelectorAll<HTMLElement>(
                'button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled),[tabindex="0"]',
              ) || [],
            );
            const first = nodes[0],
              last = nodes[nodes.length - 1];
            if (e.shiftKey && document.activeElement === first) {
              e.preventDefault();
              last?.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
              e.preventDefault();
              first?.focus();
            }
          }
        }}
      >
        <div className="section-head">
          <h2>{title}</h2>
          <button
            type="button"
            className="icon-button"
            aria-label="Close dialog"
            onClick={close}
          >
            <X size={18} />
          </button>
        </div>
        {children}
      </section>
    </div>
  );
}
/** Mirrors the service: reminders for a feature switched off on this computer stay silent. */
export function featureOff(item: Reminder, features: Features) {
  if (item.kind === "break") return !features.activity_breaks;
  return (
    (item.payload.feature === "sleep_plan" ||
      item.title === "Sleep wind-down") &&
    !features.sleep_plan
  );
}
export function dateTime(value?: string | null) {
  return value
    ? new Date(value).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "Activity based";
}
export function timestamp(seconds: number | null) {
  return seconds === null
    ? "Source"
    : new Date(seconds * 1000).toISOString().slice(11, 19);
}
export function duration(seconds: number) {
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600),
    minutes = Math.floor((total % 3600) / 60),
    rest = total % 60;
  if (hours) return hours + "h " + String(minutes).padStart(2, "0") + "m";
  if (minutes) return minutes + "m " + String(rest).padStart(2, "0") + "s";
  return rest + "s";
}
export function briefDuration(seconds: number) {
  const total = Math.max(0, Math.round(seconds));
  if (total >= 86400) return Math.floor(total / 86400) + "d";
  if (total >= 3600)
    return (
      Math.floor(total / 3600) + "h " + Math.floor((total % 3600) / 60) + "m"
    );
  return total >= 60 ? Math.ceil(total / 60) + "m" : total + "s";
}
/** A once-a-second clock, so a countdown moves between desktop state pushes. */
export function useClock(active: boolean) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [active]);
  return now;
}
export function Ring({
  fraction,
  label,
  caption,
  tone = "",
}: {
  fraction: number;
  label: string;
  caption: string;
  tone?: string;
}) {
  const value = Math.max(
    0,
    Math.min(1, Number.isFinite(fraction) ? fraction : 0),
  );
  const circumference = 2 * Math.PI * 26;
  return (
    <div
      className={"progress-ring " + tone}
      role="progressbar"
      aria-label={caption}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(value * 100)}
      aria-valuetext={caption}
      title={caption}
    >
      <svg viewBox="0 0 64 64" aria-hidden="true">
        <circle className="ring-track" cx="32" cy="32" r="26" />
        <circle
          className="ring-value"
          cx="32"
          cy="32"
          r="26"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - value)}
        />
      </svg>
      <b>{label}</b>
    </div>
  );
}
function earlyWarning(item: Reminder) {
  const warn = Number(item.payload.warn_seconds) || 0;
  return warn > 0 ? " · " + warn / 60 + " min early warning" : "";
}
/** One live sentence about where a reminder currently stands. */
export function reminderStatus(item: Reminder, now: number) {
  if (item.kind === "break") {
    if (item.payload.idle_available === false)
      return "Activity detection is unavailable on this desktop. Break timer paused.";
    const idle = Number(item.payload.idle_seconds) || 0;
    const rest = Number(item.payload.break_seconds) || 0;
    if (idle >= 10)
      return (
        "Away " + duration(idle) + " of " + duration(rest) + " needed to reset"
      );
    if (item.payload.due)
      return "Break due now — you are still at the keyboard";
    const left = Math.max(
      0,
      (Number(item.payload.work_seconds) || 0) -
        (Number(item.payload.active_seconds) || 0),
    );
    return duration(left) + " of active work before your next break";
  }
  if (item.status === "paused") return "Paused" + earlyWarning(item);
  if (!item.due_at) return "Activity based" + earlyWarning(item);
  const left = (new Date(item.due_at).getTime() - now) / 1000;
  return (
    dateTime(item.due_at) +
    (left > 0 ? " · in " + duration(left) : " · due now") +
    earlyWarning(item)
  );
}
/** How much is left: measured active work for a break, wall clock for a timer. */
export function ReminderProgress({
  item,
  now,
}: {
  item: Reminder;
  now: number;
}) {
  // Every row keeps the slot so titles stay aligned, ring or no ring.
  const empty = <span className="progress-ring" aria-hidden="true" />;
  if (["completed", "cancelled"].includes(item.status)) return empty;
  const untilDue = item.due_at
    ? (new Date(item.due_at).getTime() - now) / 1000
    : 0;
  if (item.kind === "break") {
    if (item.payload.idle_available === false) return empty;
    const rest = Number(item.payload.break_seconds) || 0;
    const idle = Number(item.payload.idle_seconds) || 0;
    // Being away is the only thing that clears a break, so show that first.
    if (idle >= 10 && rest)
      return (
        <Ring
          fraction={idle / rest}
          tone="away"
          label={briefDuration(idle)}
          caption={
            "Away " +
            duration(idle) +
            " of " +
            duration(rest) +
            " needed to reset this break."
          }
        />
      );
    if (item.payload.due)
      return (
        <Ring
          fraction={1}
          tone="due"
          label="now"
          caption={"Break due. Saiph asks again in " + duration(untilDue) + "."}
        />
      );
    const work = Number(item.payload.work_seconds) || 0;
    const active = Number(item.payload.active_seconds) || 0;
    const left = Math.max(0, work - active);
    return (
      <Ring
        fraction={work ? active / work : 0}
        label={briefDuration(left)}
        caption={duration(left) + " of active work before your next break."}
      />
    );
  }
  const total = Number(item.payload.duration_seconds) || 0;
  if (item.kind !== "timer" || !total) {
    // A scheduled reminder has no span to fill, only a time left to show.
    if (!item.due_at) return empty;
    return (
      <Ring
        fraction={0}
        tone="idle"
        label={briefDuration(untilDue)}
        caption={duration(untilDue) + " until this reminder."}
      />
    );
  }
  const left = Math.max(
    0,
    item.status === "paused" ? Number(item.payload.remaining) || 0 : untilDue,
  );
  return (
    <Ring
      fraction={1 - left / total}
      tone={item.status === "paused" ? "paused" : ""}
      label={briefDuration(left)}
      caption={
        duration(left) +
        (item.status === "paused" ? " left, paused." : " left on this timer.")
      }
    />
  );
}
/** One bar per audio track, because tracks are transcribed one after another
 *  and a single overall percentage hides which voice is still being worked on. */
export function TrackProgress({ job }: { job?: Job }) {
  if (!job || job.kind !== "transcription") return null;
  const counters = job.tracks || {};
  const known = Object.keys(counters).map(Number);
  const count = Math.max(job.track_count || 0, ...known, 0);
  if (!count) return null;
  const settled = ["completed", "failed", "cancelled"].includes(job.status);
  return (
    <div className="track-progress">
      {Array.from({ length: count }, (_, index) => {
        const key = String(index + 1);
        const counter = counters[key];
        const fraction =
          job.status === "completed"
            ? 1
            : counter && counter.total
              ? Math.max(0, Math.min(1, counter.completed / counter.total))
              : 0;
        const caption = counter
          ? counter.completed + " of " + counter.total + " batches"
          : settled
            ? "Not started"
            : "Waiting its turn";
        return (
          <div className="track-progress-row" key={key}>
            <span>Track {key}</span>
            <div
              className="meter"
              role="progressbar"
              aria-label={"Track " + key + " transcription progress"}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(fraction * 100)}
              aria-valuetext={caption}
            >
              <i style={{ width: (fraction * 100).toFixed(1) + "%" }} />
            </div>
            <small>{caption}</small>
          </div>
        );
      })}
    </div>
  );
}
export const levels = ["gentle", "noticeable", "urgent"];
export const warnChoices = [0, 1, 2, 5, 10, 15, 30];
export function HeadsUp({
  value,
  change,
  label = "Early warning",
}: {
  value: number;
  change: (v: number) => void;
  label?: string;
}) {
  return (
    <label>
      {label}
      <select
        aria-label={label}
        value={value}
        onChange={(e) => change(Number(e.target.value))}
      >
        {(warnChoices.includes(value)
          ? warnChoices
          : [...warnChoices, value].sort((a, b) => a - b)
        ).map((minutes) => (
          <option key={minutes} value={minutes}>
            {minutes === 0 ? "None" : minutes + " minutes before"}
          </option>
        ))}
      </select>
    </label>
  );
}
export function Level({
  value,
  change,
  label = "Notification level",
}: {
  value: string;
  change: (v: string) => void;
  label?: string;
}) {
  return (
    <label>
      {label}
      <select
        aria-label={label}
        value={value}
        onChange={(e) => change(e.target.value)}
      >
        {levels.map((level) => (
          <option key={level}>{level}</option>
        ))}
      </select>
    </label>
  );
}

export function ago(value?: string | null, now = Date.now()) {
  if (!value) return "never";
  const seconds = (now - new Date(value).getTime()) / 1000;
  return seconds < 60 ? "just now" : briefDuration(seconds) + " ago";
}
