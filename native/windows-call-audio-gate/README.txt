Saiph call audio: Windows gate test
====================================

What this answers: can an app other than Phone Link put phone calls through a
Windows PC's microphone and speakers over Bluetooth? It takes about 15 minutes.
Call audio only ever travels over Bluetooth between your phone and this PC.

You need
- A Windows 11 PC WITH Bluetooth (built in, or a USB Bluetooth adapter).
- Your phone paired with that PC over Bluetooth. On the phone: Settings >
  Connections > Bluetooth > tap the gear next to the PC > keep "Phone calls" on.
- A second phone to call from. Use your own numbers. Nothing is recorded.
- To be at the PC: it asks you questions and shows two administrator prompts.

Run it
1. Unzip SaiphCallAudioGate.zip anywhere, for example to your Downloads folder.
2. Open PowerShell in that folder (Shift + right-click > Open in Terminal).
3. Run:
     powershell -NoProfile -ExecutionPolicy Bypass -File .\run-gate.ps1
   If several phones are paired, add: -Device "A55"
4. Answer y or n at each question. It asks before every step that changes the PC.
5. Send back the two files it names at the end (results\gate-....json and .md).

What it changes, and undoes
- Step 2 trusts a test certificate for 30 days (administrator prompt) and
  registers a hidden test package called "Saiph call audio gate test".
- Step 4 (only if you say y) registers that test app as the phone's hands-free
  app. Phone Link may stop handling calls for this phone until the end.
- At the end it unregisters, removes the package and removes the certificate
  (a second administrator prompt). If Phone Link calls do not work afterwards:
  Phone Link > Settings > Features > Calls, and set up calls again.
- It does not change Phone Link's settings, Bluetooth settings or Saiph.

What the results mean
- "not testable (no Bluetooth)": this PC has no Bluetooth radio.
- "not testable (phone not paired for calls)": pair the phone and keep Phone
  calls on for this PC on the phone, then run again.
- "inconclusive (no identity)": the test package did not apply. Send the files.
- Step 3 "DENIED BY SYSTEM" -> verdict "no-go (DeniedBySystem)": Windows keeps
  this API for Phone Link (an undocumented Microsoft gate). Saiph cannot offer
  call audio on Windows without Microsoft's approval.
- Step 3 "DENIED BY USER": Settings > Privacy & security > Phone calls blocks
  apps. Allow access there and run again.
- Step 3 "ALLOWED", then step 4:
  - "GO: two-way call audio through the PC": it works. Saiph can build the
    Windows version (it will need packaging with package identity).
  - "registration works but no two-way audio": registration is allowed but
    Windows does not give the audio to this app. Still a no-go.
  - "no-go (registration or connection failed)": see the error in the .md file.

Run it again at any time; each run starts clean and cleans up after itself.
To keep the test app installed for a second try, add -KeepInstalled (run once
more without it to clean up).
