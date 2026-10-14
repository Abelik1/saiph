// SPDX-License-Identifier: AGPL-3.0-or-later
import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { Slot } from "radix-ui";

import { cn } from "@/lib/utils";

/**
 * One button for the whole app. Pick by job, not by look:
 * - default: the one main action in a view (Saiph's string gradient).
 * - secondary: other actions that stand on their own.
 * - tonal: quiet actions inside a card or row; a soft pill, never bare text.
 * - ghost: icon-only buttons (close, media controls). Give them an aria-label.
 * - destructive: removes or stops something for good.
 * - link: inline in a sentence only.
 */
const buttonVariants = cva(
  "inline-flex shrink-0 cursor-pointer select-none items-center justify-center gap-2 whitespace-nowrap rounded-button border font-medium tracking-[-0.005em] transition-[background-color,border-color,color,box-shadow,filter] duration-150 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/35 disabled:cursor-not-allowed [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default:
          "border-transparent text-primary-foreground shadow-sm [background-image:var(--primary-gradient)] hover:brightness-110 hover:shadow-[0_0_24px_color-mix(in_srgb,var(--primary)_30%,transparent)] disabled:[background-image:none] disabled:bg-muted disabled:text-muted-foreground disabled:shadow-none disabled:brightness-100",
        secondary:
          "border-input bg-card text-foreground hover:border-secondary-border hover:bg-secondary disabled:border-border disabled:bg-transparent disabled:text-muted-foreground",
        tonal:
          "border-secondary-border bg-secondary text-secondary-foreground hover:bg-secondary-hover aria-pressed:border-primary aria-pressed:bg-primary aria-pressed:text-primary-foreground disabled:border-border disabled:bg-muted disabled:text-muted-foreground",
        ghost:
          "border-transparent bg-transparent text-muted-foreground hover:bg-secondary hover:text-foreground disabled:opacity-45 disabled:hover:bg-transparent",
        destructive:
          "border-destructive/45 bg-transparent text-destructive hover:bg-status-off-surface disabled:opacity-50",
        link: "h-auto border-transparent bg-transparent p-0 text-secondary-foreground underline-offset-4 hover:underline disabled:opacity-50",
      },
      size: {
        default: "h-10 px-[18px] text-[13.5px]",
        sm: "h-8 gap-1.5 px-[13px] text-[13px]",
        icon: "size-10 p-0",
        "icon-sm": "size-8 p-0",
      },
    },
    defaultVariants: { variant: "secondary", size: "default" },
  },
);

type ButtonProps = React.ComponentProps<"button"> & VariantProps<typeof buttonVariants> & { asChild?: boolean };

function Button({ className, variant, size, asChild = false, type, ...props }: ButtonProps) {
  const Component = asChild ? Slot.Root : "button";
  return (
    <Component
      data-slot="button"
      data-variant={variant || "secondary"}
      // A button never submits a form by accident; submit buttons say so.
      type={asChild ? undefined : type || "button"}
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  );
}

export { Button, buttonVariants };
export type { ButtonProps };
