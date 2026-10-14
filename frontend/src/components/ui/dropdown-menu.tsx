// SPDX-License-Identifier: AGPL-3.0-or-later
import * as React from "react";
import { DropdownMenu as MenuPrimitive } from "radix-ui";
import { Check } from "lucide-react";

import { cn } from "@/lib/utils";

/** A menu of actions or a choice that scopes a whole view, such as which device a page shows. */
function DropdownMenu(props: React.ComponentProps<typeof MenuPrimitive.Root>) {
  return <MenuPrimitive.Root data-slot="dropdown-menu" {...props} />;
}

function DropdownMenuTrigger(props: React.ComponentProps<typeof MenuPrimitive.Trigger>) {
  return <MenuPrimitive.Trigger data-slot="dropdown-menu-trigger" {...props} />;
}

function DropdownMenuContent({ className, sideOffset = 6, align = "start", ...props }: React.ComponentProps<typeof MenuPrimitive.Content>) {
  return (
    <MenuPrimitive.Portal>
      <MenuPrimitive.Content
        data-slot="dropdown-menu-content"
        sideOffset={sideOffset}
        align={align}
        className={cn("z-50 min-w-56 overflow-hidden rounded-field border border-border bg-popover p-1 text-popover-foreground shadow-[var(--shadow-md)]", className)}
        {...props}
      />
    </MenuPrimitive.Portal>
  );
}

const itemClass =
  "relative flex cursor-pointer select-none items-center gap-2.5 rounded-[7px] px-2.5 py-2 text-[13px] outline-none data-[disabled]:pointer-events-none data-[disabled]:opacity-50 data-[highlighted]:bg-secondary data-[highlighted]:text-foreground [&_svg]:size-4 [&_svg]:shrink-0";

function DropdownMenuItem({ className, ...props }: React.ComponentProps<typeof MenuPrimitive.Item>) {
  return <MenuPrimitive.Item data-slot="dropdown-menu-item" className={cn(itemClass, className)} {...props} />;
}

function DropdownMenuRadioGroup(props: React.ComponentProps<typeof MenuPrimitive.RadioGroup>) {
  return <MenuPrimitive.RadioGroup data-slot="dropdown-menu-radio-group" {...props} />;
}

function DropdownMenuRadioItem({ className, children, ...props }: React.ComponentProps<typeof MenuPrimitive.RadioItem>) {
  return (
    <MenuPrimitive.RadioItem data-slot="dropdown-menu-radio-item" className={cn(itemClass, "pr-8", className)} {...props}>
      {children}
      <span className="absolute right-2.5 flex size-4 items-center justify-center">
        <MenuPrimitive.ItemIndicator><Check className="text-primary" /></MenuPrimitive.ItemIndicator>
      </span>
    </MenuPrimitive.RadioItem>
  );
}

function DropdownMenuLabel({ className, ...props }: React.ComponentProps<typeof MenuPrimitive.Label>) {
  return <MenuPrimitive.Label data-slot="dropdown-menu-label" className={cn("px-2.5 py-1.5 text-[12px] font-medium text-muted-foreground", className)} {...props} />;
}

function DropdownMenuSeparator({ className, ...props }: React.ComponentProps<typeof MenuPrimitive.Separator>) {
  return <MenuPrimitive.Separator data-slot="dropdown-menu-separator" className={cn("-mx-1 my-1 h-px bg-border", className)} {...props} />;
}

export { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuSeparator, DropdownMenuTrigger };
