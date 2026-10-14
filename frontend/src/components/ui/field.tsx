// SPDX-License-Identifier: AGPL-3.0-or-later
import * as React from "react";
import { Label as LabelPrimitive } from "radix-ui";

import { cn } from "@/lib/utils";

function Label({ className, ...props }: React.ComponentProps<typeof LabelPrimitive.Root>) {
  return (
    <LabelPrimitive.Root
      data-slot="label"
      className={cn("flex select-none items-center gap-2 text-[12px] font-medium text-muted-foreground peer-disabled:opacity-50", className)}
      {...props}
    />
  );
}

/**
 * A label, its control and an optional hint, stacked. Pass the control's id as
 * `htmlFor` so the label names it.
 */
function Field({
  label,
  htmlFor,
  hint,
  className,
  children,
}: {
  label: React.ReactNode;
  htmlFor: string;
  hint?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div data-slot="field" className={cn("grid gap-1.5", className)}>
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {hint && <p className="m-0 text-[12px] leading-normal text-muted-foreground">{hint}</p>}
    </div>
  );
}

export { Field, Label };
