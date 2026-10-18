// SPDX-License-Identifier: AGPL-3.0-or-later
import type { ReactNode } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/** Consistent heading, description and control spacing for preferences and Cloud. */
export function PreferenceCard({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return <Card>
    <CardHeader><CardTitle>{title}</CardTitle>{subtitle && <CardDescription>{subtitle}</CardDescription>}</CardHeader>
    <CardContent className="grid gap-4 [&>button]:justify-self-start [&>p]:m-0 [&>p]:text-sm [&>p]:leading-relaxed [&>p]:text-muted-foreground">{children}</CardContent>
  </Card>;
}
