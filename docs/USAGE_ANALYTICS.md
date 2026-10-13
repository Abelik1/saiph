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
| `schema` | `1` |
| `day` | The day counted, `YYYY-MM-DD` (UTC) |
| `app` | `desktop` or `android` |
| `platform` | `windows`, `linux` or `android` |
| `version` | App version, e.g. `0.1.0-beta.5` |
| `mode` | `hub`, `hosted` or `none` (how the device connects) |
| `install_age` | Days since the owner agreed: `0`, `1-6`, `7-29`, `30-89`, `90+` |
| `stage` | Setup reached: `installed`, `connected`, `phone_added`, `setup_completed` |
| `features` | Features used that day, each as a range: `1`, `2-5`, `6-20`, `21+` |

Example:

```json
{"schema": 1, "day": "2026-10-14", "app": "desktop", "platform": "windows", "version": "0.1.0-beta.5",
 "mode": "hosted", "install_age": "7-29", "stage": "phone_added",
 "features": {"clipboard_sent": "6-20", "phone_notification": "21+", "screen_messages": "1"}}
```

**Never sent:** message, notification, clipboard or file content; contacts,
phone numbers or names; app names; file names; anything typed; account, device
or install identifiers; precise counts or times. There is no identifier, so
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

## On the service

`POST /v1/usage` on the Saiph service accepts a batch only without an account
token, cookie, browser origin or query string, at most 4 KiB, matching the
schema above exactly, and within a service-wide rate limit. Each accepted batch
is immediately added to daily totals (installs per day by app, platform,
version, mode, install age and setup stage; installs per feature range). The
batch itself, network address and request headers are not stored, and the
service does not log requests. The service also keeps daily request totals by
fixed route name and status class (for example `sealed.publish` / `2xx`),
never by account, device or address. Totals are deleted after 400 days.
Administrators read them with `python -m orion_hub.hosted_service_admin
usage-report --days 30`.

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
