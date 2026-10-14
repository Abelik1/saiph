// SPDX-License-Identifier: AGPL-3.0-or-later
import * as React from "react";

import { cn } from "@/lib/utils";

const fieldClass =
  "w-full min-w-0 rounded-field border border-input bg-field px-3 text-[13px] text-foreground outline-none transition-[border-color,box-shadow] placeholder:text-muted-foreground hover:border-secondary-border focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/20 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive";

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return <input data-slot="input" type={type} className={cn(fieldClass, "h-10 py-2", className)} {...props} />;
}

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return <textarea data-slot="textarea" className={cn(fieldClass, "min-h-24 resize-y py-2.5 leading-relaxed", className)} {...props} />;
}

export { Input, Textarea, fieldClass };
