// SPDX-License-Identifier: AGPL-3.0-or-later
import { Check, X } from "lucide-react";
import type { Client, HubItem, ProposedEvent, State } from "./types";
import { ago } from "./ui";
import { Action, Card, Empty } from "./ui";

/** "2 weeks before", "1 day before", "at the start". */
export function reminderLabel(minutes: number) {
  if (minutes === 0) return "at the start";
  const units: [number, string][] = [
    [10080, "week"],
    [1440, "day"],
    [60, "hour"],
    [1, "minute"],
  ];
  const [size, name] = units.find(([size]) => minutes % size === 0)!;
  const count = minutes / size;
  return `${count} ${name}${count === 1 ? "" : "s"} before`;
}

export function eventWhen(event: ProposedEvent) {
  const date = event.all_day
    ? new Date(event.start.slice(0, 10) + "T00:00")
    : new Date(event.start);
  const day = date.toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
  return event.all_day
    ? day
    : `${day} ${date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`;
}

function status(item: HubItem) {
  if (item.proposal?.action && item.status === "applied") return "Approved · queued for phone";
  const by = item.decided_by ? ` on ${item.decided_by}` : "";
  if (item.status === "accepted")
    return item.result
      ? `Accepted${by}. Not added yet: ${item.result}`
      : `Accepted${by}. The calendar scout adds it on its next run.`;
  if (item.status === "applied")
    return "In your calendar" + (item.result ? ` · ${item.result}` : "");
  if (item.status === "dismissed") return `Dismissed${by}`;
  if (item.status === "done") return `Cleared${by}`;
  return "";
}

function Row({ item, client }: { item: HubItem; client: Client }) {
  const decide = (decision: string) =>
    client.call("hub.decide", { id: item.id, decision });
  return (
    <div className={"hub-item " + item.kind + " " + item.status}>
      <div className="hub-item-head">
        <span className="eyebrow">
          {item.source.replaceAll("-", " ").toUpperCase()}
        </span>
        <small>{ago(item.created_at)}</small>
      </div>
      <b>{item.title}</b>
      {item.body && <p>{item.body}</p>}
      {item.proposal?.review && <div className="hub-action-review">
        <p><b>{item.proposal.review.operation}</b> · {item.proposal.review.phone}</p>
        {item.proposal.review.recipients && <p>To: {item.proposal.review.recipients.join(", ")}</p>}
        {item.proposal.review.app && <p>{item.proposal.review.app} · {item.proposal.review.title}</p>}
        {item.proposal.review.text && <blockquote style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere"}}>{item.proposal.review.text}</blockquote>}
      </div>}
      {(item.proposal?.events || []).map((event, n) => (
        <div className="hub-event" key={n}>
          <span className="calendar-swatch kind-deadline" />
          <span>
            <b>{event.title}</b>
            <small>
              {eventWhen(event)}
              {event.reminders.length > 0 &&
                " · reminder " + event.reminders.map(reminderLabel).join(", ")}
            </small>
          </span>
        </div>
      ))}
      {item.status === "new" ? (
        <div className="button-row">
          {item.kind === "proposal" ? (
            <>
              <Action className="primary" run={() => decide("accept")}>
                <Check size={15} /> {item.proposal?.action ? "Accept" : "Add to calendar"}
              </Action>
              <Action run={() => decide("dismiss")}>
                <X size={15} /> Dismiss
              </Action>
            </>
          ) : (
            <Action run={() => decide("done")}>
              <Check size={15} /> Clear
            </Action>
          )}
        </div>
      ) : (
        <small className="hub-status">{status(item)}</small>
      )}
    </div>
  );
}

/** Saiph Hub's inbox: the same notices and calendar suggestions the phone shows.
 * Deciding here decides everywhere; the first decision on any device wins. */
export function HubInbox({ state, client }: { state: State; client: Client }) {
  const { items, synced_at, error } = state.hub_inbox;
  const open = items.filter(
    (i) => i.status === "new" || (i.status === "accepted" && i.result),
  );
  const waiting = items.filter((i) => i.status === "accepted" && !i.result);
  const recent = items
    .filter((i) => !open.includes(i) && !waiting.includes(i))
    .slice(0, 4);
  return (
    <Card
      title="From Saiph Hub"
      actions={
        <small>{synced_at ? ago(synced_at) : "Updates automatically"}</small>
      }
    >
      {error && <p className="muted">Saiph will check for new items automatically.</p>}
      {open.length || waiting.length ? (
        [...open, ...waiting].map((item) => (
          <Row key={item.id} item={item} client={client} />
        ))
      ) : (
        <Empty title="Nothing waiting for you" />
      )}
      {recent.length > 0 && (
        <details className="quiet-details">
          <summary>Recently decided</summary>
          {recent.map((item) => (
            <Row key={item.id} item={item} client={client} />
          ))}
        </details>
      )}
    </Card>
  );
}
