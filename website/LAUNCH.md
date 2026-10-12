# Launch preparation and acceptance

Source preparation does not publish source, create installers, configure a mail
provider or open paid Hosted. Keep both repositories private until the owner
explicitly requests publication. Use only the Saiph website project; preserve
the personal CV apex/www and unrelated infrastructure.

## Download acceptance

1. Select a reviewed clean source revision and fixed version tag. Complete the
   platform, signing, licence, upgrade/rollback and independent review gates in
   `docs/RELEASE_STATUS.md`. Unsigned CI packages are development artifacts.
2. Produce Windows, Linux, Android and self-hosted Hub packages from that revision.
   Finalize signatures before recording checksums. Preserve Android's existing
   signing identity and application/data/pairing compatibility.
3. Use `release-checksums.py` to record final bytes and full source commit. Verify
   again after downloading the actual release. Record signing checks separately;
   SHA-256 and GitHub digests establish byte integrity, not publisher identity.
4. With explicit publication authorization, publish the approved source and
   versioned release with all packages, SHA256SUMS and release-source.json.
   Fetch its actual REST metadata and files. Use `prepare-website-downloads.py`
   with an exact four-platform filename map; never manufacture asset links.
5. Build public-fields-only settings. Confirm every link succeeds without private
   GitHub authentication and the downloaded bytes/signatures match review. Record
   actual results. Enable links only for those accepted assets.

There is no approved public release yet. The builder's launch mode additionally
requires all four packages and the configured waitlist. Preview mode can serve
truthful informational pages without opening collection or paid subscriptions.

## Controller contact and deferred support email

Support email setup is deferred. No public controller contact has been confirmed;
do not advertise `support@usesaiph.com` or a personal forwarding destination.
Keep `privacy.contactEmail` empty, privacy status draft and `waitlistUrl` empty.
A working public controller contact for withdrawal and deletion requests is
required before email collection can open; a support mailbox is not required if
the owner confirms another appropriate public controller contact.

Suggested privacy contact: `privacy@usesaiph.com`, separate from the deferred
support mailbox. This is a proposal only, not a configured or verified address.
The owner must set up the alias/mailbox, verify receipt from a separate address,
and confirm who handles withdrawal/deletion requests before it appears in public
settings or the notice. Keep `contactEmail` empty until then.

Confirm the contact's delivery and actual mail-provider processing/retention
before publishing it. Do not send email or change DNS/provider settings as part
of source preparation.

## Email launch updates

Tally form `https://tally.so/r/gDy42K` is published. The owner reports a required
email field and required unchecked consent checkbox with this exact text:

> I agree to receive the Saiph launch announcement and occasional launch updates by email. I can unsubscribe or ask for my email to be deleted at any time.

The form has a hidden `consent_version` field, partial submissions disabled and
no respondent confirmation email. It is **single opt-in**, with no second email
confirmation step. Do not describe it as double opt-in. The only allowed signup
URL is `https://tally.so/r/gDy42K?consent_version=NOTICE_VERSION`, where the
parameter exactly matches `waitlist.noticeVersion`. Unknown, duplicate or
mismatched query parameters and other form URLs are rejected. The preparation
version `2026-10-11` must be reviewed with the final notice before activation.

The source settings record the form's reported controls but leave signup off.
Before enabling it, confirm:

- The required email/consent fields, hidden version value and complete submission
  record. Use the exact same text for `waitlistNotice` and `waitlist.consentText`.
  Do not import account or support contacts. Partial submissions stay off.
- A public controller withdrawal/deletion contact, concrete active-list retention,
  deletion/export steps and cleanup responsibility. No active-list retention
  interval has been approved. Tally's backup deletion window is not that policy.
- The separate campaign sender, unsubscribe in every update, suppression after
  withdrawal and retention for the minimum suppression record. Tally collecting a
  form response does not create an email campaign or unsubscribe system.
- Email open/click tracking disabled in the eventual sender, verified from a
  delivered test message. Keep `trackingDisabled` false until verified. No
  respondent confirmation email is sent by this form.
- Actual integrations, the DPA and international-transfer safeguards. Tally's
  optional form email notifications use SendGrid in the US; respondent
  confirmation being off does not establish that owner notifications are off.
  Confirm owner notifications and any exports/integrations before activation.

Verified from Tally's own [privacy policy](https://tally.so/help/privacy-policy)
and [GDPR/subprocessor page](https://tally.so/help/gdpr) on 11 October 2026:
Tally is processor for form responses, while the creator controls their retention.
Form data is stored in Europe; Google Cloud hosting/storage is listed in Belgium.
Optional form-email notifications use US SendGrid, so storage region does not
establish EU-only processing. Tally describes deleted form-data backup removal within 90 days and a manual
Trash-emptying control. Verify actual deletion behavior; do not infer immediate
purge of every backup from emptying Trash. This does not set Saiph's retention.

Use only owner-authorized test addresses for eventual signup, duplicates,
unsubscribe, deletion/export and a synthetic update. No form submissions, emails,
provider configuration, activation or broadcasts are part of this source change.

## Privacy and final configuration

The owner approved the controller identity: Alexander Belik, operating as
Abelik1, Ireland. The GitHub display name can remain Abelik1. Identity approval
alone does not approve the complete notice or attest email delivery.

Complete the template's public privacy fields with verified hosting retention,
locations/transfers and contact-email processing (mail providers including the
private inbox provider, purposes/bases, retention and safeguards). Keep the actual
personal destination private. Review the website delivery/security legitimate
interests assessment and the email-update consent scope. Describe actual data,
recipients, retention, rights and withdrawal; include the controller contact and
supervisory-authority route. Set privacy status to approved only after those facts
and the working contact are reviewed. Add the signup provider's precise facts
before collection. The account/Auth0/billing service needs its own notice.

References used for preparation, not a compliance certification:

- [Irish DPC privacy-policy guidance](https://dataprotection.ie/en/faqs/responsibilities-data-controllers/how-do-i-make-privacy-policy)
- [Irish DPC electronic direct marketing](https://www.dataprotection.ie/en/organisations/rules-electronic-and-direct-marketing)
- [Irish DPC complaints](https://dataprotection.ie/en/individuals/exercising-your-rights/complaints-handling-investigations-and-enforcement-individuals)

## Preview, activation and rollback

Build only the explicit static allowlist with `build-website.py`. Review the
manifest hashes and desktop/mobile browser behavior. Use the existing protected
Saiph Vercel preview before activating the corresponding public configuration.
No token, private environment, inbox destination, provider export or Git history
belongs in the deployment. Preserve the existing security headers; the site
needs no embedded forms or application cookies. Optional cookie-free public
pageview analytics stays off until the separate [activation checks](ANALYTICS.md)
are complete; preserve the same-origin script/connect security policy.

Confirm all public pages, privacy/consent links, exact release files, HTTPS and
actual signup lifecycle after activation. Keep the CV unchanged. Record the
source commit, settings/manifest hashes, target and actual verification separately
from planned steps. To rollback, restore the earlier recorded Saiph deployment
only; disable signup/broken downloads immediately. Removing a signup link does
not remove existing provider data or unsubscribe people: perform the documented
provider deletion/suppression steps as well. Paid Hosted, company/payment/legal,
physical acceptance and independent review remain separate gates.

## Legal/privacy preparation bundle

Draft website/account privacy, Hosted terms, refund/withdrawal and contact pages
are prepared. Read [the legal review record](../docs/LEGAL_PRIVACY.md) and the proposed
retention schedule before approving any public collection or paid service. The
public contact and provider/retention facts remain unconfirmed. The draft pages
and passing source checks do not establish legal or Stripe approval.
