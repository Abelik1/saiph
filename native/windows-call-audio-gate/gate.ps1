# SPDX-License-Identifier: AGPL-3.0-or-later
# Builds the portable B2 Windows gate-test bundle on a developer PC. It changes nothing on this PC:
# the test certificate is made in memory and written to files (no certificate store), and nothing
# is installed or trusted. The owner then runs run-gate.ps1 from the bundle on a PC with Bluetooth.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\gate.ps1
#
# Needs the .NET 9 SDK and the Windows 10/11 SDK (makeappx, signtool). Output:
#   out\SaiphCallAudioGate\  (run-gate.ps1, README.txt, gate.msix, gate.cer, bin\SaiphCallAudioGate.exe)
#   out\SaiphCallAudioGate.zip
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$out = Join-Path $here 'out'
$bundle = Join-Path $out 'SaiphCallAudioGate'
$subject = 'CN=Saiph Call Audio Gate Test'
$kit = Get-ChildItem 'C:\Program Files (x86)\Windows Kits\10\bin\10.*\x64\makeappx.exe' | Sort-Object FullName | Select-Object -Last 1
if (-not $kit) { throw 'Install the Windows SDK (makeappx and signtool).' }
$tools = Split-Path $kit.FullName

Remove-Item -Recurse -Force $bundle -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force (Join-Path $bundle 'bin') | Out-Null
# Self-contained single file: the owner's PC needs no .NET runtime.
dotnet publish (Join-Path $here 'SaiphCallAudioGate.csproj') -c Release -r win-x64 --self-contained true `
  -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -o (Join-Path $bundle 'bin') | Out-Host
if ($LASTEXITCODE) { throw 'Build failed.' }
Get-ChildItem (Join-Path $bundle 'bin') -Filter *.pdb | Remove-Item

# A 30-day self-signed code-signing certificate, in memory and then files only.
$key = [System.Security.Cryptography.RSA]::Create(2048)
$request = New-Object System.Security.Cryptography.X509Certificates.CertificateRequest($subject, $key,
  [System.Security.Cryptography.HashAlgorithmName]::SHA256, [System.Security.Cryptography.RSASignaturePadding]::Pkcs1)
$usage = New-Object System.Security.Cryptography.OidCollection
[void]$usage.Add((New-Object System.Security.Cryptography.Oid '1.3.6.1.5.5.7.3.3'))
$request.CertificateExtensions.Add((New-Object System.Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension($usage, $false)))
$request.CertificateExtensions.Add((New-Object System.Security.Cryptography.X509Certificates.X509BasicConstraintsExtension($false, $false, 0, $true)))
$request.CertificateExtensions.Add((New-Object System.Security.Cryptography.X509Certificates.X509KeyUsageExtension(
  [System.Security.Cryptography.X509Certificates.X509KeyUsageFlags]::DigitalSignature, $true)))
$certificate = $request.CreateSelfSigned([DateTimeOffset]::Now.AddDays(-1), [DateTimeOffset]::Now.AddDays(30))
$password = [Guid]::NewGuid().ToString('N')
$pfx = Join-Path $out 'gate.pfx'
[IO.File]::WriteAllBytes($pfx, $certificate.Export('Pfx', $password))
[IO.File]::WriteAllBytes((Join-Path $bundle 'gate.cer'), $certificate.Export('Cert'))

$msix = Join-Path $bundle 'gate.msix'
# /nv: the manifest's executable lives in the external location, not in the package (sparse package).
# The manifest schema itself was checked with a validating pack on 18 October 2026.
& (Join-Path $tools 'makeappx.exe') pack /o /nv /d (Join-Path $here 'package') /p $msix | Out-Host
if ($LASTEXITCODE) { Remove-Item $pfx; throw 'makeappx failed.' }
& (Join-Path $tools 'signtool.exe') sign /q /fd SHA256 /f $pfx /p $password $msix | Out-Host
$signed = $LASTEXITCODE
Remove-Item $pfx   # The private key is never kept; every bundle gets its own certificate.
if ($signed) { throw 'signtool failed.' }

Copy-Item (Join-Path $here 'run-gate.ps1'), (Join-Path $here 'README.txt') $bundle
$zip = Join-Path $out 'SaiphCallAudioGate.zip'
Remove-Item $zip -ErrorAction SilentlyContinue
Compress-Archive -Path $bundle -DestinationPath $zip
"Bundle ready: $zip (certificate $($certificate.Thumbprint), valid 30 days). Nothing was installed or trusted on this PC."
