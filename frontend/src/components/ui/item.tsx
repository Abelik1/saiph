// SPDX-License-Identifier: AGPL-3.0-or-later
import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/**
 * One row in a list or a setting: optional media on the left, a title and a line
 * of detail, and its actions on the right. Every list in the app uses this shape.
 */
const itemVariants = cva("group/item flex min-w-0 items-center gap-3 rounded-[12px] text-[13px] transition-colors", {
  variants: {
    variant: {
      default: "bg-transparent",
      outline: "border border-border bg-field/50",
      muted: "bg-muted/50",
    },
    size: {
      default: "px-4 py-3",
      sm: "px-3 py-2",
      flush: "p-0",
    },
  },
  defaultVariants: { variant: "default", size: "default" },
});

function Item({ className, variant, size, ...props }: React.ComponentProps<"div"> & VariantProps<typeof itemVariants>) {
  return <div data-slot="item" className={cn(itemVariants({ variant, size }), className)} {...props} />;
}

function ItemMedia({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="item-media"
      className={cn("flex size-9 shrink-0 items-center justify-center self-start rounded-[10px] bg-secondary text-secondary-foreground [&_svg]:size-[18px]", className)}
      {...props}
    />
  );
}

function ItemContent({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="item-content" className={cn("grid min-w-0 flex-1 gap-0.5", className)} {...props} />;
}

function ItemTitle({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="item-title" className={cn("min-w-0 truncate text-[13.5px] font-medium leading-snug text-foreground", className)} {...props} />;
}

function ItemDescription({ className, ...props }: React.ComponentProps<"p">) {
  return <p data-slot="item-description" className={cn("m-0 min-w-0 text-[12.5px] leading-normal text-muted-foreground", className)} {...props} />;
}

function ItemActions({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="item-actions" className={cn("flex shrink-0 items-center gap-1.5", className)} {...props} />;
}

/** A small uppercase label above a group of rows or controls. */
function Eyebrow({ className, ...props }: React.ComponentProps<"p">) {
  return <p data-slot="eyebrow" className={cn("m-0 text-[12px] font-medium uppercase tracking-[0.06em] text-muted-foreground", className)} {...props} />;
}

export { Item, ItemMedia, ItemContent, ItemTitle, ItemDescription, ItemActions, Eyebrow };
