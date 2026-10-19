// SPDX-License-Identifier: AGPL-3.0-or-later
import { BookOpen, MessageSquarePlus } from "lucide-react";
import type { Client } from "./types";
import { Action } from "./ui";
import { PreferenceCard as Card } from "./PreferenceCard";
import { Disclosure } from "@/components/ui/disclosure";

/** Short fixes per area; the same topics are in docs/USER_GUIDE.md under "Troubleshooting and privacy". */
export const topics: [string, string[]][] = [
  ["General", [
    "Open Saiph on your phone and check that it says Connected. With Saiph Cloud, both devices must be signed in to the same account.",
    "On the phone, let Saiph run in the background: Android Settings → Apps → Saiph → Battery → Unrestricted.",
    "If Sync over mobile data is off, the phone pauses until it is on Wi-Fi.",
    "Use Refresh next to the phone's name to ask it for its latest status.",
  ]],
  ["Apps", [
    "Phone apps open through the phone's wireless or USB debugging. Pair it once in Settings → Advanced.",
    "Some apps block screen capture; they show a black window.",
  ]],
  ["Calls", [
    "In Saiph on your phone, turn on Texts and calls and allow the phone permissions it asks for.",
    "Call audio stays on your phone or its headset; answer, decline and dialling work from this computer.",
    "Turn on Calls in Settings → Phone on this computer.",
  ]],
  ["Messages", [
    "Turn on Texts and calls in Saiph on your phone and allow SMS access.",
    "Group replies and MMS pictures need an up-to-date Saiph on your phone, with Saiph Cloud or a Saiph Hub.",
    "A conversation that is missing usually arrives after a minute; reopen the Messages tab to check again.",
  ]],
  ["Notifications", [
    "In Saiph on your phone, tap Allow notifications and turn on notification access for Saiph.",
    "Music controls use the same access.",
    "Turn on Notifications in Settings → Phone on this computer.",
  ]],
  ["Phone screen", [
    "Choose Mirror screen on the Phone page. Keep both devices on the same Wi-Fi; no cable or install is needed.",
    "On your phone, tap Allow, confirm it's you and choose Start now. Your screen opens in its own window here.",
  ]],
  ["Photos", [
    "In Saiph on your phone, allow the photo gallery and choose which photos Android lets Saiph see.",
    "Only recent photos are shown. Save one to keep a full-size copy on this computer.",
    "Turn on Photos in Settings → Phone on this computer.",
  ]],
];

/** Phone Link's Help & feedback: feedback goes to the public issue tracker; fixes are short and local. */
export function HelpFeedback({ client }: { client: Client }) {
  return <div className="columns">
    <Card title="Send feedback" subtitle="Tell us what worked, what didn't and what you'd like next.">
      <p>Opens a new issue on Saiph's public GitHub page in your browser. Don't include phone numbers, messages, codes or passwords.</p>
      <Action variant="default" run={() => client.call("help.open", { link: "feedback" })}><MessageSquarePlus />Send feedback</Action>
    </Card>
    <Card title="Troubleshooting" subtitle="Quick fixes for each part of Saiph.">
      <div className="grid gap-2">
        {topics.map(([title, steps]) => <Disclosure key={title} summary={title}>
          <ul className="m-0 grid gap-1.5 pl-5 text-[13px] leading-relaxed text-muted-foreground">{steps.map((step) => <li key={step}>{step}</li>)}</ul>
        </Disclosure>)}
      </div>
      <Action variant="secondary" run={() => client.call("help.open", { link: "guide" })}><BookOpen />Read the full guide</Action>
    </Card>
  </div>;
}
