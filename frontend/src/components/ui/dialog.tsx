// SPDX-License-Identifier: AGPL-3.0-or-later
import * as React from "react";
import { Dialog as DialogPrimitive } from "radix-ui";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";

function Dialog(props: React.ComponentProps<typeof DialogPrimitive.Root>) {
  return <DialogPrimitive.Root data-slot="dialog" {...props} />;
}

function DialogTrigger(props: React.ComponentProps<typeof DialogPrimitive.Trigger>) {
  return <DialogPrimitive.Trigger data-slot="dialog-trigger" {...props} />;
}

/** A focused task over the page. Esc and the close button always leave it. */
function DialogContent({ className, children, ...props }: React.ComponentProps<typeof DialogPrimitive.Content>) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay data-slot="dialog-overlay" className="fixed inset-0 z-40 bg-background/70" />
      <DialogPrimitive.Content
        data-slot="dialog-content"
        className={cn(
          "fixed top-1/2 left-1/2 z-50 grid max-h-[calc(100dvh-48px)] w-[min(560px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 gap-4 overflow-y-auto rounded-card border border-border bg-popover p-6 text-popover-foreground shadow-[var(--shadow-lg)] outline-none",
          className,
        )}
        {...props}
      >
        {children}
        <DialogPrimitive.Close
          aria-label="Close dialog"
          className="absolute top-4 right-4 inline-flex size-8 cursor-pointer items-center justify-center rounded-button border-0 bg-transparent text-muted-foreground outline-none transition-colors hover:bg-secondary hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/35 [&_svg]:size-4"
        >
          <X />
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

function DialogHeader({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="dialog-header" className={cn("grid gap-1 pr-10", className)} {...props} />;
}

function DialogTitle({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Title>) {
  return <DialogPrimitive.Title data-slot="dialog-title" className={cn("m-0 text-[17px] font-semibold tracking-[-0.02em]", className)} {...props} />;
}

function DialogDescription({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Description>) {
  return <DialogPrimitive.Description data-slot="dialog-description" className={cn("m-0 text-[13px] leading-relaxed text-muted-foreground", className)} {...props} />;
}

export { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger };
