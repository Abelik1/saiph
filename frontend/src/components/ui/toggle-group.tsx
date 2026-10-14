// SPDX-License-Identifier: AGPL-3.0-or-later
import * as React from "react";
import { ToggleGroup as ToggleGroupPrimitive } from "radix-ui";

import { cn } from "@/lib/utils";

/** A segmented control: one choice out of a few, all visible at once. */
function ToggleGroup({ className, ...props }: React.ComponentProps<typeof ToggleGroupPrimitive.Root>) {
  return (
    <ToggleGroupPrimitive.Root
      data-slot="toggle-group"
      className={cn("inline-flex w-fit items-center gap-0.5 rounded-button border border-border bg-field p-0.5", className)}
      {...props}
    />
  );
}

function ToggleGroupItem({ className, ...props }: React.ComponentProps<typeof ToggleGroupPrimitive.Item>) {
  return (
    <ToggleGroupPrimitive.Item
      data-slot="toggle-group-item"
      className={cn(
        "inline-flex h-7 cursor-pointer items-center justify-center gap-1.5 rounded-button border-0 bg-transparent px-3 text-[12.5px] font-medium text-muted-foreground outline-none transition-colors hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/35 disabled:cursor-not-allowed disabled:opacity-50 data-[state=on]:bg-secondary data-[state=on]:text-secondary-foreground data-[state=on]:shadow-[inset_0_0_0_1px_var(--secondary-border)] [&_svg]:size-3.5",
        className,
      )}
      {...props}
    />
  );
}

export { ToggleGroup, ToggleGroupItem };
