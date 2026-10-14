// SPDX-License-Identifier: AGPL-3.0-or-later
import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Something you can open: a bordered row with a chevron, built on <details> so it
 * needs no script and keyboard and screen readers treat it as a disclosure. Use it
 * for options and extra detail; use Select for a choice and Tabs for places.
 */
function Disclosure({
  summary,
  icon,
  className,
  children,
  ...props
}: Omit<React.ComponentProps<"details">, "summary"> & { summary: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <details
      data-slot="disclosure"
      className={cn("group/disclosure rounded-[12px] border border-border bg-field/60 px-4 open:pb-4", className)}
      {...props}
    >
      <summary
        data-slot="disclosure-summary"
        className="flex min-h-12 cursor-pointer list-none items-center gap-2.5 py-3 text-[13.5px] font-medium text-muted-foreground outline-none transition-colors hover:text-foreground focus-visible:text-foreground group-open/disclosure:mb-3 group-open/disclosure:border-b group-open/disclosure:border-border group-open/disclosure:text-foreground [&_svg]:size-4 [&_svg]:shrink-0"
      >
        {icon}
        <span className="min-w-0 flex-1">{summary}</span>
        <span aria-hidden="true" className="disclosure-chevron" />
      </summary>
      <div className="grid gap-3 text-[13px] text-muted-foreground">{children}</div>
    </details>
  );
}

export { Disclosure };
