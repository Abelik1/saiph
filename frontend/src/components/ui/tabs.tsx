// SPDX-License-Identifier: AGPL-3.0-or-later
import * as React from "react";
import { Tabs as TabsPrimitive } from "radix-ui";

import { cn } from "@/lib/utils";

function Tabs({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Root>) {
  return <TabsPrimitive.Root data-slot="tabs" className={cn("flex flex-col", className)} {...props} />;
}

function TabsList({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      className={cn("flex min-h-14 items-stretch gap-1 border-b border-border px-4", className)}
      {...props}
    />
  );
}

/** The selected tab carries a short ringing string instead of a flat bar. */
function TabsTrigger({ className, children, ...props }: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      data-slot="tabs-trigger"
      className={cn(
        "group relative inline-flex cursor-pointer items-center gap-2 rounded-field border-0 bg-transparent px-3 text-[13px] font-medium text-muted-foreground outline-none transition-colors hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/35 disabled:pointer-events-none disabled:opacity-50 data-[state=active]:text-foreground [&_svg]:size-[17px] [&_svg]:shrink-0",
        className,
      )}
      {...props}
    >
      {children}
      <span aria-hidden="true" className="wave-underline hidden group-data-[state=active]:block" />
    </TabsPrimitive.Trigger>
  );
}

function TabsContent({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Content>) {
  return <TabsPrimitive.Content data-slot="tabs-content" className={cn("outline-none", className)} {...props} />;
}

export { Tabs, TabsList, TabsTrigger, TabsContent };
