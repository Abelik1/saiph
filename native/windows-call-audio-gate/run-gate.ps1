# SPDX-License-Identifier: AGPL-3.0-or-later
# Saiph B2 Windows gate test, in one step. Run it on a Windows 11 PC that HAS Bluetooth, with the
# phone paired over Bluetooth and "Phone calls" turned on for this PC on the phone.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\run-gate.ps1
#
# It asks before every step that changes the PC, and undoes everything at the end:
#   1. read-only checks (no change)
#   2. trust a 30-day test certificate (one admin prompt) and register a test package for this user
#   3. ask Windows for hands-free access: the gate itself
#   4. optional: register as the phone's hands-free app, connect, and watch one real call
#   5. unregister, remove the package and the certificate (one admin prompt)
# Results go to results\gate-<time>.json and results\gate-<time>.md; send both back.
# Call audio stays on Bluetooth between the phone and this PC. Nothing is sent over the network.
param([string]$Device = '', [switch]$KeepInstalled)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$exe = Join-Path $here 'bin\SaiphCallAudioGate.exe'
$msix = Join-Path $here 'gate.msix'
$cer = Join-Path $here 'gate.cer'
$name = 'Saiph.CallAudioGate'
$results = Join-Path $here 'results'
New-Item -ItemType Directory -Force $results | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$log = [ordered]@{ started = (Get-Date).ToString('o'); steps = [ordered]@{}; answers = [ordered]@{}; verdict = '' }

function Save {
  $log | ConvertTo-Json -Depth 12 | Set-Content -Encoding UTF8 (Join-Path $results "gate-$stamp.json")
  $lines = @("# Saiph call audio gate test, $stamp", '', "Verdict: **$($log.verdict)**", '')
  foreach ($key in $log.steps.Keys) { $lines += "- $key : $($log.steps[$key].meaning)" }
  foreach ($key in $log.answers.Keys) { $lines += "- $key : $($log.answers[$key])" }
  $lines | Set-Content -Encoding UTF8 (Join-Path $results "gate-$stamp.md")
}
function Harness([string[]]$Arguments) {
  $file = Join-Path $results ("step-" + $Arguments[0] + "-$stamp.json")
  & $exe @Arguments --out $file | Out-Null
  Get-Content -Raw $file | ConvertFrom-Json
}
function Ask([string]$Question) {
  do { $answer = (Read-Host "$Question [y/n]").Trim().ToLower() } while ($answer -notin @('y', 'n'))
  $answer -eq 'y'
}
function Record([string]$Step, $Report, [string]$Meaning) {
  $log.steps[$Step] = [ordered]@{ meaning = $Meaning; report = $Report }
  Write-Host ""; Write-Host "[$Step] $Meaning" -ForegroundColor Cyan
  Save
}
function Elevated([string]$Command) {
  $process = Start-Process powershell -Verb RunAs -Wait -PassThru -ArgumentList @('-NoProfile', '-Command', $Command)
  if ($process.ExitCode) { throw "The administrator step failed (exit $($process.ExitCode))." }
}
function Cleanup {
  if ($KeepInstalled) { Write-Host 'Left installed because of -KeepInstalled. Run .\run-gate.ps1 again without it to clean up.'; return }
  try { if (Get-AppxPackage $name) { & $exe unregister @deviceArgs --out (Join-Path $results "step-unregister-$stamp.json") | Out-Null } } catch { }
  Get-AppxPackage $name | Remove-AppxPackage
  $thumbprint = (New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($cer)).Thumbprint
  if (Get-ChildItem Cert:\LocalMachine\TrustedPeople | Where-Object Thumbprint -eq $thumbprint) {
    Write-Host 'Removing the test certificate needs one more administrator prompt.'
    Elevated "Get-ChildItem Cert:\LocalMachine\TrustedPeople | Where-Object Thumbprint -eq '$thumbprint' | Remove-Item"
  }
  $log.steps['cleanup'] = [ordered]@{ meaning = 'Test package and certificate removed.'; report = $null }
  Save
}
$deviceArgs = @(); if ($Device) { $deviceArgs = @('--device', $Device) }

Write-Host 'Saiph call audio gate test. Read the README first; answer y/n at each prompt.' -ForegroundColor Yellow

# 1. Read-only checks.
$probe = Harness (@('probe') + $deviceArgs)
$bluetooth = @($probe.radios | Where-Object { $_.kind -eq 'Bluetooth' })
$log.windows = $probe.os
if (-not $bluetooth) {
  Record 'probe' $probe 'No Bluetooth radio on this PC. Nothing can be tested here; use a PC with Bluetooth or add a USB Bluetooth adapter.'
  $log.verdict = 'not testable (no Bluetooth)'; Save; exit 1
}
if (-not @($probe.devices).Count) {
  Record 'probe' $probe ('Bluetooth is ' + $bluetooth[0].state + ' but no phone offers phone calls to this PC. Pair the phone, keep "Phone calls" on for this PC on the phone, then run again.')
  $log.verdict = 'not testable (phone not paired for calls)'; Save; exit 1
}
Record 'probe' $probe ("Bluetooth radio found; hands-free phone(s): " + (($probe.devices | ForEach-Object { $_.name }) -join ', ') + '. Without package identity, as expected.')

# 2. Package identity (changes the PC until cleanup).
if (-not (Ask 'Step 2 trusts a 30-day test certificate (administrator prompt) and registers a test package for your account. Continue?')) {
  $log.verdict = 'stopped by owner before installing'; Save; exit 0
}
try {
  if (-not (Get-AppxPackage $name)) {
    Elevated "Import-Certificate -FilePath '$cer' -CertStoreLocation Cert:\LocalMachine\TrustedPeople | Out-Null"
    Add-AppxPackage -Path $msix -ExternalLocation (Join-Path $here 'bin')
  }
  $identity = Harness (@('probe') + $deviceArgs)
  if (-not $identity.identity) {
    Record 'identity' $identity 'The package registered but the harness did not run with its identity. The test is inconclusive; send the results back.'
    $log.verdict = 'inconclusive (no identity)'; exit 1
  }
  Record 'identity' $identity "Running with package identity $($identity.identity) and the phoneLineTransportManagement capability."

  # 3. The gate.
  $access = Harness (@('access') + $deviceArgs)
  $meaning = switch ($access.result) {
    'Allowed'        { 'ALLOWED: Windows lets a sideloaded app with this capability use the hands-free API. Continue to step 4.' }
    'DeniedBySystem' { 'DENIED BY SYSTEM: Windows refuses this app. This is the Limited Access Feature / Phone Link gate; no-go without Microsoft.' }
    'DeniedByUser'   { 'DENIED BY USER: Settings > Privacy & security > Phone calls blocks apps. Allow it there and run again.' }
    default          { "UNEXPECTED: $($access.result) $($access.error.message) (HRESULT $($access.error.hresult)). Send the results back." }
  }
  Record 'access' $access $meaning
  if ($access.result -ne 'Allowed') { $log.verdict = "no-go ($($access.result))"; exit 0 }

  # 4. Registration, connection and one real call.
  if (Ask 'Step 4 registers this test app as the phone''s hands-free app (Phone Link may lose calls for this phone until cleanup) and connects. Continue?') {
    $register = Harness (@('register') + $deviceArgs)
    Record 'register' $register $(if ($register.result.registered) { 'Registered.' } else { "Not registered: $($register.error.message) (HRESULT $($register.error.hresult))." })
    $connect = Harness (@('connect') + $deviceArgs)
    Record 'connect' $connect $(if ($connect.result.connected) { 'Connected (hands-free service-level connection open).' } else { "Did not connect: $($connect.error.message) (HRESULT $($connect.error.hresult))." })
    if ($register.result.registered -and $connect.result.connected) {
      Write-Host ''
      Write-Host 'Now call this phone from another phone and ANSWER ON THE PHONE. Talk for about 30 seconds, then hang up.' -ForegroundColor Yellow
      Write-Host 'Watching for 120 seconds...'
      $watch = Harness (@('watch', '120') + $deviceArgs)
      $routing = @($watch.result | ForEach-Object { $_.routing } | Where-Object { $_ }) -join ' -> '
      Record 'watch' $watch "Audio routing seen: $routing"
      $log.answers['caller heard through PC speakers'] = Ask 'Did you hear the caller through this PC''s speakers?'
      $log.answers['caller heard PC microphone'] = Ask 'Did the caller hear you through this PC''s microphone?'
      $log.answers['no manual switching needed'] = Ask 'Did the audio come to the PC without switching anything on the phone?'
      $both = $log.answers['caller heard through PC speakers'] -and $log.answers['caller heard PC microphone']
      $log.verdict = $(if ($both) { 'GO: two-way call audio through the PC' } else { 'registration works but no two-way audio (no-go)' })
    } else { $log.verdict = 'no-go (registration or connection failed)' }
  } else { $log.verdict = 'access allowed; registration not tried' }
}
finally {
  Save
  Cleanup
  Write-Host ''
  Write-Host "Verdict: $($log.verdict)" -ForegroundColor Green
  Write-Host "Send back: $results\gate-$stamp.json and gate-$stamp.md"
  Write-Host 'If Phone Link calls do not work for this phone afterwards: Phone Link > Settings > Features > Calls, set it up again.'
}
