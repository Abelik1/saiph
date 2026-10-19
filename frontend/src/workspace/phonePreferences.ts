// SPDX-License-Identifier: AGPL-3.0-or-later
import type { PhonePreferences, State } from "./types";

export const phoneFeatures = ["notifications", "messages", "photos", "apps", "calls"] as const;
export type PhoneFeature = (typeof phoneFeatures)[number];
export type EffectivePreferences = { features: Record<PhoneFeature, boolean>; wallpaper: boolean; audio_player: boolean; badges: boolean; recent: boolean; usb_debugging: boolean };

/** Defaults match src/orion_mini/phone_settings.py: everything on except the wallpaper and the USB debugging mode. */
export function phonePreferences(settings?: State["settings"]): EffectivePreferences {
  const saved: PhonePreferences = settings?.link?.phone || {};
  const features = Object.fromEntries(phoneFeatures.map((name) => [name, saved.features?.[name] !== false])) as Record<PhoneFeature, boolean>;
  return { features, wallpaper: saved.wallpaper === true, audio_player: saved.audio_player !== false, badges: saved.badges !== false, recent: saved.recent !== false,
    usb_debugging: saved.usb_debugging === true };
}

/** Phone tabs that a turned-off feature hides. */
export function hiddenTabs(preferences: EffectivePreferences): string[] {
  const tabs: [PhoneFeature, string][] = [["messages", "Messages"], ["photos", "Photos"], ["calls", "Calls"], ["apps", "Apps"]];
  return tabs.filter(([feature]) => !preferences.features[feature]).map(([, tab]) => tab);
}
