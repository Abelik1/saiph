// SPDX-License-Identifier: AGPL-3.0-or-later
import { useId, useState } from "react";
import type { Client, State } from "./types";
import { Action, Form } from "./ui";
import { PreferenceCard as Card } from "./PreferenceCard";
import { ContinuitySettings } from "./ContinuitySettings";
import { Updates } from "./Updates";
import { CameraSettings } from "./CameraSettings";
import { MicrophoneSettings } from "./PhoneMicrophone";
import { HostedSettings } from "./HostedSettings";
import { DeskflowSettings } from "./DeskflowSettings";
import { HotspotSettings } from "./HotspotSettings";
import { RemoteSettings } from "./RemoteSettings";
import { BluetoothLockSettings } from "./BluetoothLockSettings";
import { PhoneSettings, UsbDebuggingSettings } from "./PhoneSettings";
import { HelpFeedback } from "./HelpFeedback";
import { SettingsLayout } from "./SettingsLayout";
import { RetainedView } from "./Navigation";
import { useSettingsNavigation, useSettingsSection } from "./settingsNavigation";
import { Button } from "@/components/ui/button";
import { Disclosure } from "@/components/ui/disclosure";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { UsageSettings, YourWeekSettings } from "./UsageSharing";
import { YourWeek } from "./YourWeek";

export function WorkspaceModule({
  installed = false,
}: {
  installed?: boolean;
}) {
  return (
    <Card title="Workspace" subtitle="Optional projects, calendar and assistant tools.">
      <p className="muted">
        {installed
          ? "The Workspace edition is installed on this computer."
          : "Available separately. Saiph Link works on its own."}
      </p>
    </Card>
  );
}

export function Settings({ state, client, openSetup }: { state: State; client: Client; openSetup?: () => void }) {
  const { connectPhone } = useSettingsNavigation();
  // Once a phone is connected, adding another lives in the Phone tab's header.
  const hasPhone = Boolean(state.phone?.devices.some((device) => device.hosted || device.capabilities.includes("battery")));
  const [tab, setTab] = useSettingsSection("General" as string);
  const [name, setName] = useState(state.settings.machine?.name || "");
  const [hub, setHub] = useState(state.settings.hub?.base_url || ""),
    [code, setCode] = useState("");
  const [notice, setNotice] = useState("");
  const hubIds = useId();
  const hubForm = (
    <Form
      className="grid gap-4"
      submit={async () => {
        await client.call("hub.pair", {
          base_url: hub,
          code,
          name: state.settings.machine?.name || "Saiph desktop",
        });
        setCode("");
        setNotice("This computer is paired.");
      }}
    >
      <Field label="Hub address" htmlFor={hubIds + "-address"}>
        <Input id={hubIds + "-address"} aria-label="Saiph Hub address" type="url" required value={hub} onChange={(event) => setHub(event.target.value)} />
      </Field>
      <Field label="One-time pairing code" htmlFor={hubIds + "-code"}>
        <Input id={hubIds + "-code"} aria-label="Saiph Hub pairing code" required value={code} inputMode="numeric" maxLength={8} onChange={(event) => setCode(event.target.value)} />
      </Field>
      <Button type="submit" variant="secondary" className="justify-self-start">Pair desktop</Button>
    </Form>
  );
  return (
    <SettingsLayout
      tabs={["General", "Connections", "Phone", "Devices", "Updates", "Advanced", "Help"]}
      selected={tab}
      onSelect={(value) => {
        setTab(value);
        setNotice("");
      }}
    >
      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
      )}
      <RetainedView active={tab === "General"}>
        {() => (
          <div className="columns general-preferences">
            {connectPhone && !hasPhone && <Card title="Connect your phone" subtitle="Sign in, scan a QR code and approve your phone from the Phone tab.">
              <Button variant="default" onClick={connectPhone}>Connect a phone</Button>
            </Card>}
            <div className="grid gap-5">
              <Card title="This computer">
                <Form
                  successMessage="Computer preferences saved."
                  submit={async () => {
                    await client.call("settings.save", {
                      machine: { ...state.settings.machine, name },
                    });
                  }}
                >
                  <label>
                    Computer name
                    <input
                      value={name}
                      maxLength={40}
                      required
                      onChange={(event) => setName(event.target.value)}
                    />
                  </label>
                  <Button type="submit" className="justify-self-start">Save this computer</Button>
                </Form>
              </Card>
            </div>
            <Card title="Startup">
              <div className="list-row">
                <div className="grow">
                  <b>Start when I sign in</b>
                  <small>Open Saiph automatically after signing in.</small>
                </div>
                <Action
                  role="switch"
                  ariaChecked={state.settings.start_with_windows}
                  ariaLabel="Start when I sign in"
                  run={() =>
                    client.call("settings.save", {
                      start_with_windows: !state.settings.start_with_windows,
                    })
                  }
                >
                  <span className="settings-switch-thumb" />
                </Action>
              </div>
              <div className="list-row">
                <div className="grow">
                  <b>Close to the system tray</b>
                  <small>
                    Keep Saiph available while its window is closed.
                  </small>
                </div>
                <Action
                  role="switch"
                  ariaChecked={state.settings.close_to_tray}
                  ariaLabel="Close to the system tray"
                  run={() =>
                    client.call("settings.save", {
                      close_to_tray: !state.settings.close_to_tray,
                    })
                  }
                >
                  <span className="settings-switch-thumb" />
                </Action>
              </div>
            </Card>
            <div className="grid gap-5">
              <WorkspaceModule installed={state.modules?.workspace?.installed} />
              {openSetup && (
                <Card title="Setup guide" subtitle="Review features and preferences.">
                  <div><Button variant="secondary" onClick={openSetup}>Run the setup guide</Button></div>
                </Card>
              )}
              <YourWeekSettings enabled={state.insights?.enabled} client={client} />
              <YourWeek enabled={state.insights?.enabled} client={client} />
              <UsageSettings usage={state.usage} client={client} />
            </div>
          </div>
        )}
      </RetainedView>
      <RetainedView active={tab === "Phone"}>
        {() => <PhoneSettings state={state} client={client} openTab={(value) => { setTab(value); setNotice(""); }} />}
      </RetainedView>
      <RetainedView active={tab === "Help"}>
        {() => <HelpFeedback client={client} />}
      </RetainedView>
      <RetainedView active={tab === "Updates"}>
        {() => <Updates client={client} status={state.update_status} cloud={state.hosted?.enabled} update={state.app_update} />}
      </RetainedView>
      <RetainedView active={tab === "Connections"}>
        {() => (
          <div className="columns">
            <HostedSettings hosted={state.hosted} client={client} />
            <ContinuitySettings
              platform={state.platform}
              settings={state.settings}
              backup={state.backup_status}
              client={client}
              workspace={false}
            />
            <HotspotSettings hotspot={state.hotspot} client={client} />
            {/* Saiph accounts are the default: a server you run yourself stays folded away until it is paired. */}
            {state.settings.hub?.paired
              ? <Card title="Self-hosted Hub" subtitle="This computer connects through a Saiph Hub server you manage.">
                  <p role="status">This computer is paired with your Hub.</p>
                  <Disclosure summary="Pair with a different Hub">{hubForm}</Disclosure>
                  {state.phone?.error && <p className="inline-error">{state.phone.error}</p>}
                </Card>
              : <Disclosure summary="Self-hosted Hub">
                  <p className="m-0">Connect through a Saiph Hub server you manage instead of a Saiph account. Use the invitation from your server.</p>
                  {hubForm}
                  {state.phone?.error && <p className="inline-error">{state.phone.error}</p>}
                </Disclosure>}
          </div>
        )}
      </RetainedView>
      <RetainedView active={tab === "Devices"}>
        {() => (
          <div className="columns">
            <CameraSettings
              platform={state.platform}
              settings={state.settings}
              camera={state.camera}
              client={client}
            />
            <MicrophoneSettings
              platform={state.platform}
              settings={state.settings}
              microphone={state.microphone}
              client={client}
            />
            <RemoteSettings remote={state.remote} state={state} client={client} />
            <BluetoothLockSettings status={state.bt_lock} client={client} />
          </div>
        )}
      </RetainedView>
      <RetainedView active={tab === "Advanced"}>
        {() => (
          <div className="grid gap-5">
            <DeskflowSettings
              settings={state.settings}
              error={state.deskflow?.error}
              status={state.deskflow}
              client={client}
              defaultEnabled={false}
            />
            <UsbDebuggingSettings state={state} client={client} />
          </div>
        )}
      </RetainedView>
    </SettingsLayout>
  );
}
