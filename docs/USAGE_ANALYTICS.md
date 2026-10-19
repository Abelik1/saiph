# Anonymous usage statistics

Saiph's desktop and Android apps can share anonymous daily usage counts, **only
after the owner agrees**. Setup asks once with two equal choices ("Share
anonymous usage" / "Don't share"); people who set up earlier are asked once
after updating ("Ask later" asks again next launch). The choice can be changed
any time in Settings, where **See what Saiph sends** shows every batch waiting
to be sent and the last one sent. Turning it off deletes the counts on that
device. This page is the complete list of what can be sent; the apps and the
service refuse anything else, and tests check that the three lists match.

Builds without a packaged Saiph service (self-hosted and development builds)
never ask and never send.

## What a batch contains

At most one batch per device per completed day (UTC), sent within seven days:

| Field | Values |
| --- | --- |
| `schema` | `2` (apps before October 2026 send `1`, which has only the fields up to `features`) |
| `day` | The day counted, `YYYY-MM-DD` (UTC) |
| `app` | `desktop` or `android` |
| `platform` | `windows`, `linux` or `android` |
| `version` | App version, e.g. `0.1.0-beta.5` |
| `mode` | `hub`, `hosted` or `none` (how the device connects) |
| `install_age` | Days since the owner agreed: `0`, `1-6`, `7-29`, `30-89`, `90+` |
| `stage` | Setup reached: `installed`, `connected`, `phone_added`, `setup_completed` |
| `features` | Features used that day, each as a range: `1`, `2-5`, `6-20`, `21+` |
| `active_days` | How many of the 7 days ending that day Saiph was used: `1`, `2-3`, `4-6`, `7` |
| `os` | Windows or Linux family, or Android version range (see below) |
| `enabled` | Saiph switches, each `true` or `false` (see below) |
| `failures` | Failures that day by fixed reason, each as a range like `features` |
| `crashes` | Unhandled errors that day by thread kind, each as a range like `features` |

Example:

```json
{"schema": 2, "day": "2026-10-14", "app": "desktop", "platform": "windows", "version": "0.1.0-beta.5",
 "mode": "hosted", "install_age": "7-29", "stage": "phone_added",
 "features": {"clipboard_sent": "6-20", "phone_notification": "21+", "screen_messages": "1"},
 "active_days": "4-6", "os": "windows_11",
 "enabled": {"notifications": true, "messages": true, "photos": true, "apps": true, "calls": true,
             "wallpaper": false, "usb_debugging": false, "your_week": true},
 "failures": {"hosted_receive_failed": "2-5"}, "crashes": {}}
```

If the service refuses a schema 2 batch (an older service), the app sends the
same day's schema 1 fields instead.

**Never sent:** message, notification, clipboard or file content; contacts,
phone numbers or names; app names; file names; anything typed; account, device
or install identifiers; precise counts or times; error messages, stack traces,
addresses or exact operating system builds. There is no identifier, so
batches from one device cannot be linked to each other or to an account.
Retention and active-user figures come from `install_age` and the number of
batches per day, not from tracking individuals.

## Features

Desktop:

| Name | Counted when |
| --- | --- |
| `clipboard_sent` | Clipboard shared from the computer |
| `clipboard_received` | Clipboard received on the computer |
| `phone_notification` | Phone notification shown on the computer |
| `notification_action` | Phone notification answered or dismissed from the computer |
| `code_copy` | Verification code copied from a notification |
| `sms_send` | Text message sent through the phone |
| `call` | Phone call started from the computer |
| `find_phone` | Phone rung to find it |
| `file_to_phone` | File sent to the phone |
| `photo_save` | Phone photo saved |
| `photo_drag` | Phone photo dragged into another app |
| `phone_mirror` | Phone screen opened |
| `phone_camera` | Phone camera used as a webcam |
| `phone_microphone` | Phone microphone used |
| `handoff` | Link, text or file handed to another device |
| `dnd_toggle` | Do Not Disturb switched from Saiph |
| `hotspot` | Phone hotspot connection |
| `cloud_open` | Cloud folder opened |
| `hosted_file_send` | File sent with a Saiph account |
| `hosted_file_save` | File received with a Saiph account |
| `device_approved` | Device approved for a Saiph account |
| `screen_phone`, `screen_cloud`, `screen_settings` | Page opened |
| `screen_messages`, `screen_photos`, `screen_calls`, `screen_files`, `screen_apps` | Phone tab opened |

Android:

| Name | Counted when |
| --- | --- |
| `app_open` | Saiph opened |
| `clipboard_sent` | Clipboard shared from the phone |
| `clipboard_received` | Clipboard received with a Saiph account |
| `notification_shared` | Notification shared from the phone |
| `dnd_shared` | Do Not Disturb change shared from the phone |
| `hosted_file_send` | File sent with a Saiph account |
| `hosted_file_save` | File received with a Saiph account |
| `pairing_started` | Hub invitation accepted |
| `hosted_enrolled` | Saiph account device request created |
| `screen_home`, `screen_settings`, `screen_advanced`, `screen_hosted` | Screen opened |

## System, switches, failures and crashes

`os` values: `windows_10`, `windows_11`, `windows_other`, `linux_x11`,
`linux_wayland`, `linux_other` (from the display session type, never the
distribution) and, on Android, `android_8-9`, `android_10-11`, `android_12-13`,
`android_14`, `android_15+`.

`enabled`, desktop: `notifications`, `messages`, `photos`, `apps`, `calls`
(the Phone page features), `wallpaper`, `usb_debugging` and `your_week`.
Android: `notifications` (notification access granted), `clipboard`, `photos`,
`texts_and_calls`, `phone_status`, `dnd_sync`, `mobile_data` and `app_lock`.

`failures`, counted by both apps:

| Name | Counted when |
| --- | --- |
| `hosted_send_failed` | Saiph Cloud refused or could not take an encrypted message |
| `hosted_receive_failed` | Encrypted messages could not be fetched from Saiph Cloud |
| `file_send_failed` | Part of an encrypted file could not be uploaded |
| `file_receive_failed` | Part of an encrypted file could not be downloaded |
| `hub_connection_failed` | The connection to a self-hosted Hub failed or dropped |

`crashes`: `main_thread` (an unhandled error in the window or Android main
thread) and `background_thread`. Only the count is kept; the error itself is
handled exactly as before and never leaves the device.

## On the service

`POST /v1/usage` on the Saiph service accepts a batch only without an account
token, cookie, browser origin or query string, at most 4 KiB, matching the
schema above exactly, and within a service-wide rate limit. Each accepted batch
is immediately added to daily totals (installs per day by app, platform,
version, mode, install age and setup stage; installs per feature range; and,
for schema 2, installs per value of each other field, each counted on its own
and never combined with the rest of the batch). The
batch itself, network address and request headers are not stored, and the
service does not log requests. The service also keeps daily request totals by
fixed route name and status class (for example `sealed.publish` / `2xx`),
never by account, device or address. It also keeps, per day:

- **Delivery health:** how long encrypted messages waited between being sent and
  being collected (`delivery.lag`: `<1s`, `1-5s`, `5-30s`, `30s-5m`, `5m+`),
  how many expired uncollected (`delivery.expired`), and encrypted file sizes in
  ranges (`blob.size`: `<100KB`, `100KB-1MB`, `1-5MB`, `5-20MB`). Message IDs and
  send times are held in memory only until the message is collected or expires.
  A restart forgets them, so these figures undercount slightly.
- **Active accounts and devices:** the number of accounts and devices that
  completed at least one authenticated request that day. The identifiers are
  held in memory for the current day only; only the two numbers are written.
- **Download tickets by catalog name** (`download.ticket` / `windows`, `linux`,
  `android`, ...), when someone downloads from their account page.

Totals are deleted after 400 days. Administrators read them with `python -m
orion_hub.hosted_service_admin usage-report --days 30`. The report leaves out
any install group smaller than five and says how many were left out (`hidden`),
so a rare combination such as one version on one platform cannot single a
person out; `--min-cell 1` shows every group for debugging on a private
terminal. `funnel-report` adds account, device and plan totals from the account
registry (see `docs/USAGE_DATA_RECOMMENDATIONS.md`).

Website analytics are separate and described in `website/ANALYTICS.md`. Crash
reporting is not included.

## Limits

Anyone can send a well-formed batch, so totals can be inflated by abuse; they
can never reveal data about a person. Counts and stages are approximate: a
batch reports the device's current setup stage, not the stage on that day.

## Your week (never sent)

The desktop Phone page has a **Your week** panel: what you did with Saiph in the
last seven days, which page you opened most, your busiest day, and the people you
texted most. It is worked out on the computer when the panel is opened, from
local counts kept for 14 days and from text messages already synced for the
Phone page. No list of people is stored, and none of it is part of the anonymous
batches above, which use separate, coarser counts. It is on by default because
nothing leaves the computer; Settings → General turns it off, which deletes its
counts, and the panel can clear the current week.
