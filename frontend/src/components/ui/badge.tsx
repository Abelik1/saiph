// SPDX-License-Identifier: AGPL-3.0-or-later
import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/** A short status: a dot and a word or two. The tone says what it means, not how it looks. */
const badgeVariants = cva(
  "inline-flex w-fit shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium leading-normal before:size-1.5 before:rounded-full before:bg-current before:opacity-75 before:content-[''] [&_svg]:size-3",
  {
    variants: {
      tone: {
        default: "bg-secondary text-secondary-foreground",
        quiet: "bg-muted text-muted-foreground before:hidden",
        good: "bg-status-on-surface text-status-on",
        warn: "bg-status-warn-surface text-status-warn",
        bad: "bg-status-off-surface text-status-off",
        attention: "bg-attention-surface text-attention",
      },
    },
    defaultVariants: { tone: "default" },
  },
);

function Badge({ className, tone, ...props }: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return <span data-slot="badge" data-tone={tone || "default"} className={cn(badgeVariants({ tone }), className)} {...props} />;
}

export { Badge, badgeVariants };
