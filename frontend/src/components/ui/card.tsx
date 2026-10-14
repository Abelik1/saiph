// SPDX-License-Identifier: AGPL-3.0-or-later
import * as React from "react";

import { cn } from "@/lib/utils";

/** A surface over the strings. Slightly see-through, never blurred: blur over a moving field repaints every frame. */
function Card({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card"
      className={cn("flex flex-col gap-4 rounded-card border border-border bg-card/90 py-5 text-card-foreground shadow-sm", className)}
      {...props}
    />
  );
}

function CardHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-header"
      className={cn("grid auto-rows-min items-start gap-1 px-5 has-data-[slot=card-action]:grid-cols-[1fr_auto]", className)}
      {...props}
    />
  );
}

function CardTitle({ className, ...props }: React.ComponentProps<"h2">) {
  return <h2 data-slot="card-title" className={cn("m-0 text-[15px] font-semibold leading-snug tracking-[-0.01em]", className)} {...props} />;
}

function CardDescription({ className, ...props }: React.ComponentProps<"p">) {
  return <p data-slot="card-description" className={cn("m-0 text-[13px] leading-normal text-muted-foreground", className)} {...props} />;
}

function CardAction({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="card-action" className={cn("col-start-2 row-span-2 row-start-1 flex items-center gap-2 self-start justify-self-end", className)} {...props} />;
}

function CardContent({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="card-content" className={cn("px-5", className)} {...props} />;
}

function CardFooter({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="card-footer" className={cn("flex flex-wrap items-center gap-2 px-5", className)} {...props} />;
}

export { Card, CardHeader, CardFooter, CardTitle, CardAction, CardDescription, CardContent };
