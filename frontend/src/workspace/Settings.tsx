// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from "react";
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
import { SettingsLayout } from "./SettingsLayout";
import { RetainedView } from "./Navigation";
import { useSettingsNavigation, useSettingsSection } from "./settingsNavigation";
import { Button } from "@/components/ui/button";
import { Disclosure } from "@/components/ui/disclosure";
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
  return (
    <SettingsLayout
      tabs={["General", "Connections", "Devices", "Updates", "Advanced"]}
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
      <RetainedView active={tab === "Updates"}>
        {() => <Updates client={client} status={state.update_status} />}
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
            <Disclosure summary="Self-hosted Hub" open={state.settings.hub?.paired || undefined}>
            <Card title="Saiph Hub" subtitle="Connect through a server you manage.">
              <p role="status">{state.settings.hub?.paired ? "This computer is paired." : "Use your server invitation to connect."}</p>
              <Disclosure summary="Pair using a code" open={!state.settings.hub?.paired}>
              <Form
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
                <label>
                  Hub address
                  <input
                    aria-label="Saiph Hub address"
                    type="url" required
                    value={hub}
                    onChange={(event) => setHub(event.target.value)}
                  />
                </label>
                <label>
                  One-time pairing code
                  <input
                    aria-label="Saiph Hub pairing code"
                    required
                    value={code}
                    inputMode="numeric"
                    maxLength={8}
                    onChange={(event) => setCode(event.target.value)}
                  />
                </label>
                <Button type="submit" variant="secondary" className="justify-self-start">Pair desktop</Button>
              </Form>
              </Disclosure>
              {state.phone?.error && (
                <p className="inline-error">{state.phone.error}</p>
              )}
            </Card>
            </Disclosure>
            <HotspotSettings hotspot={state.hotspot} client={client} />
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
          <DeskflowSettings
            settings={state.settings}
            error={state.deskflow?.error}
            status={state.deskflow}
            client={client}
            defaultEnabled={false}
          />
        )}
      </RetainedView>
    </SettingsLayout>
  );
}
