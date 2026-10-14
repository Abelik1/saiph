// SPDX-License-Identifier: AGPL-3.0-or-later
import { useId, useState } from "react";
import type { Client } from "./types";
import { Action } from "./ui";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";

/** Android wireless debugging on the local Wi-Fi: no cable, Hub or Tailscale. */
export function WirelessDebugging({
  client,
  onConnected,
}: {
  client: Client;
  onConnected?: () => Promise<unknown> | void;
}) {
  const id = useId();
  const [pairAddress, setPairAddress] = useState("");
  const [code, setCode] = useState("");
  const [address, setAddress] = useState("");
  const [notice, setNotice] = useState("");
  return (
    <div className="grid gap-3 text-[12.5px] leading-relaxed text-muted-foreground">
      <p className="m-0">
        Your phone and this computer must be on the same Wi‑Fi. On the phone,
        open Settings → Developer options → Wireless debugging and turn it on.
      </p>
      <p className="m-0">
        <b className="text-foreground">First time only:</b> tap “Pair device with pairing code” on the
        phone and enter what it shows here.
      </p>
      <Field label="Pairing IP address and port" htmlFor={id + "-pair"}>
        <Input
          id={id + "-pair"}
          value={pairAddress}
          placeholder="192.168.1.20:37123"
          autoComplete="off"
          spellCheck={false}
          onChange={(event) => setPairAddress(event.target.value)}
        />
      </Field>
      <Field label="Wi‑Fi pairing code" htmlFor={id + "-code"}>
        <Input
          id={id + "-code"}
          value={code}
          placeholder="123456"
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={7}
          onChange={(event) => setCode(event.target.value)}
        />
      </Field>
      <Action
        variant="tonal"
        size="sm"
        disabled={!pairAddress.trim() || !code.trim()}
        run={async () => {
          setNotice("");
          await client.call("camera.pair", {
            address: pairAddress.trim(),
            code: code.trim(),
          });
          setCode("");
          setNotice(
            "Paired. Now connect with the address at the top of the Wireless debugging screen.",
          );
        }}
      >
        Pair this computer
      </Action>
      <p className="m-0">
        <b className="text-foreground">Each time:</b> enter the IP address and port shown at the top of the
        Wireless debugging screen. It changes when the phone restarts or
        reconnects to Wi‑Fi.
      </p>
      <Field label="Phone IP address and port" htmlFor={id + "-address"}>
        <Input
          id={id + "-address"}
          value={address}
          placeholder="192.168.1.20:41234"
          autoComplete="off"
          spellCheck={false}
          onChange={(event) => setAddress(event.target.value)}
        />
      </Field>
      <Action
        variant="tonal"
        size="sm"
        disabled={!address.trim()}
        run={async () => {
          setNotice("");
          await client.call("camera.connect", { address: address.trim() });
          setNotice("Connected over Wi‑Fi.");
          await onConnected?.();
        }}
      >
        Connect over Wi‑Fi
      </Action>
      {notice && (
        <p className="m-0" role="status">
          {notice}
        </p>
      )}
    </div>
  );
}
