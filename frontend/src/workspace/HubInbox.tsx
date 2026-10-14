// SPDX-License-Identifier: AGPL-3.0-or-later
import { CalendarPlus, Check, X } from "lucide-react";
import type { Client, HubItem, ProposedEvent, State } from "./types";
import { Action, ago } from "./ui";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Disclosure } from "@/components/ui/disclosure";
import { Eyebrow, Item, ItemContent, ItemDescription, ItemMedia, ItemTitle } from "@/components/ui/item";

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

// Where a suggestion came from, in words rather than service names.
const sources: Record<string, string> = { "phone-action": "Phone action" };
function sourceLabel(source: string) {
  // Calendar helpers name themselves "calendar-…"; any of them is a calendar suggestion.
  return sources[source] || (source.startsWith("calendar") ? "Calendar suggestion" : source.replaceAll("-", " "));
}

function Row({ item, client }: { item: HubItem; client: Client }) {
  const decide = (decision: string) =>
    client.call("hub.decide", { id: item.id, decision });
  return (
    <div data-kind={item.kind} data-status={item.status} className="grid gap-2 rounded-[12px] border border-border bg-field/50 p-3.5">
      <div className="flex items-center gap-2">
        <Eyebrow className="min-w-0 flex-1 truncate">{sourceLabel(item.source)}</Eyebrow>
        <small className="shrink-0 text-[11px] text-muted-foreground">{ago(item.created_at)}</small>
      </div>
      <b className="text-[13.5px] font-semibold leading-snug">{item.title}</b>
      {item.body && <p className="m-0 text-[12.5px] leading-relaxed text-muted-foreground">{item.body}</p>}
      {item.proposal?.review && <div className="grid gap-1 rounded-[10px] bg-muted/60 p-2.5 text-[12.5px] [&_p]:m-0">
        <p><b>{item.proposal.review.operation}</b> · {item.proposal.review.phone}</p>
        {item.proposal.review.recipients && <p>To: {item.proposal.review.recipients.join(", ")}</p>}
        {item.proposal.review.app && <p>{item.proposal.review.app} · {item.proposal.review.title}</p>}
        {item.proposal.review.text && <blockquote className="m-0 border-l-2 border-secondary-border pl-2.5 text-muted-foreground" style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere"}}>{item.proposal.review.text}</blockquote>}
      </div>}
      {(item.proposal?.events || []).map((event, n) => (
        <Item key={n} variant="muted" size="sm">
          <ItemMedia className="size-8"><CalendarPlus /></ItemMedia>
          <ItemContent>
            <ItemTitle>{event.title}</ItemTitle>
            <ItemDescription>
              {eventWhen(event)}
              {event.reminders.length > 0 &&
                " · reminder " + event.reminders.map(reminderLabel).join(", ")}
            </ItemDescription>
          </ItemContent>
        </Item>
      ))}
      {item.status === "new" ? (
        <div className="flex flex-wrap gap-1.5 pt-0.5">
          {item.kind === "proposal" ? (
            <>
              <Action variant="tonal" size="sm" run={() => decide("accept")}>
                <Check /> {item.proposal?.action ? "Accept" : "Add to calendar"}
              </Action>
              <Action variant="secondary" size="sm" run={() => decide("dismiss")}>
                <X /> Dismiss
              </Action>
            </>
          ) : (
            <Action variant="tonal" size="sm" run={() => decide("done")}>
              <Check /> Clear
            </Action>
          )}
        </div>
      ) : (
        <small className="text-[12px] text-muted-foreground">{status(item)}</small>
      )}
    </div>
  );
}

function split(items: HubItem[]) {
  const open = items.filter(
    (i) => i.status === "new" || (i.status === "accepted" && i.result),
  );
  const waiting = items.filter((i) => i.status === "accepted" && !i.result);
  const recent = items
    .filter((i) => !open.includes(i) && !waiting.includes(i))
    .slice(0, 4);
  return { current: [...open, ...waiting], recent };
}

/** Whether Saiph Hub has anything for the owner to decide or check right now. */
export function hubHasCurrent(state: State) {
  return split(state.hub_inbox?.items || []).current.length > 0;
}

/** Hub suggestions as a section of another list, such as the Phone page's notifications. */
export function HubSuggestions({ state, client }: { state: State; client: Client }) {
  const { synced_at, error } = state.hub_inbox;
  const { current, recent } = split(state.hub_inbox.items);
  if (!current.length && !recent.length && !error) return null;
  return (
    <section aria-label="From Saiph Hub" className="grid gap-2.5">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="m-0 text-[12.5px] font-semibold text-muted-foreground">Suggestions from Saiph Hub</h3>
        <small className="text-[12px] text-muted-foreground">{synced_at ? ago(synced_at) : ""}</small>
      </div>
      {error && <p className="m-0 text-[12.5px] text-muted-foreground">Saiph will check for new items automatically.</p>}
      {current.map((item) => <Row key={item.id} item={item} client={client} />)}
      {recent.length > 0 && (
        <Disclosure summary="Recently decided">
          {recent.map((item) => <Row key={item.id} item={item} client={client} />)}
        </Disclosure>
      )}
    </section>
  );
}

/** Saiph Hub's inbox: the same notices and calendar suggestions the phone shows.
 * Deciding here decides everywhere; the first decision on any device wins. */
export function HubInbox({ state, client }: { state: State; client: Client }) {
  const { synced_at, error } = state.hub_inbox;
  const { current, recent } = split(state.hub_inbox.items);
  return (
    <Card className="gap-3">
      <CardHeader>
        <CardTitle>From Saiph Hub</CardTitle>
        <CardAction><small className="text-[12px] text-muted-foreground">{synced_at ? ago(synced_at) : "Updates automatically"}</small></CardAction>
      </CardHeader>
      <CardContent className="grid gap-2.5">
        {error && <p className="m-0 text-[12.5px] text-muted-foreground">Saiph will check for new items automatically.</p>}
        {current.length ? (
          current.map((item) => <Row key={item.id} item={item} client={client} />)
        ) : (
          <p className="m-0 py-2 text-center text-[13px] text-muted-foreground">Nothing waiting for you</p>
        )}
        {recent.length > 0 && (
          <Disclosure summary="Recently decided">
            {recent.map((item) => <Row key={item.id} item={item} client={client} />)}
          </Disclosure>
        )}
      </CardContent>
    </Card>
  );
}
