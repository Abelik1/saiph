// SPDX-License-Identifier: AGPL-3.0-or-later
import * as React from "react";
import { Switch as SwitchPrimitive } from "radix-ui";

import { cn } from "@/lib/utils";

function Switch({ className, ...props }: React.ComponentProps<typeof SwitchPrimitive.Root>) {
  return (
    <SwitchPrimitive.Root
      data-slot="switch"
      className={cn(
        "peer inline-flex h-[22px] w-[38px] shrink-0 cursor-pointer items-center rounded-full border border-input bg-muted p-0 outline-none transition-colors focus-visible:ring-[3px] focus-visible:ring-ring/35 disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:border-transparent data-[state=checked]:bg-primary",
        className,
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb
        data-slot="switch-thumb"
        className="pointer-events-none block size-4 translate-x-[2px] rounded-full bg-foreground shadow-sm transition-transform data-[state=checked]:translate-x-[18px] data-[state=checked]:bg-primary-foreground"
      />
    </SwitchPrimitive.Root>
  );
}

export { Switch };
