# SPDX-License-Identifier: GPL-3.0-only
# Save the two Android release key passwords once, so build-release.ps1 stops asking. Run it yourself:
#
#   powershell -ExecutionPolicy Bypass -File scripts\android\save-release-passwords.ps1
#
# Each password is checked against its keystore first, so a typo is never saved. The file is written
# with Export-Clixml, which encrypts each password with Windows DPAPI: only this Windows user on this
# PC can read it back. Delete the file to go back to typing the passwords.
param(
    [string]$SigningKeystore = 'E:\Saiph-private\saiph-app-signing.jks',
    [string]$SigningAlias = 'saiph',
    [string]$UploadKeystore = 'E:\Saiph-private\saiph-play-upload.jks',
    [string]$UploadAlias = 'upload',
    [string]$Path = 'E:\Saiph-private\android-release-passwords.clixml'
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'release-tools.ps1')
if (-not $env:JAVA_HOME) { throw 'JAVA_HOME is not set; it is needed to check the passwords with keytool.' }
$keytool = Join-Path $env:JAVA_HOME 'bin\keytool.exe'
if (-not (Test-Path -LiteralPath $keytool)) { throw "keytool was not found at $keytool." }

function Read-Checked([string]$Prompt, [string]$Keystore, [string]$Alias) {
    if (-not (Test-Path -LiteralPath $Keystore)) { throw "Keystore not found: $Keystore" }
    $secure = Read-Host $Prompt -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
        $fingerprint = try { Get-AndroidSigningFingerprint $keytool $Keystore $Alias $plain } catch { $null }
        if (-not $fingerprint) { throw "That password does not open $Keystore (alias $Alias). Nothing was saved." }
    } finally { $plain = $null; [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    return $secure
}

$saved = @{
    signing = Read-Checked 'App signing key password' $SigningKeystore $SigningAlias
    upload  = Read-Checked 'Upload key password' $UploadKeystore $UploadAlias
}
$saved | Export-Clixml -LiteralPath $Path -Force
Write-Host "Saved both passwords to $Path (encrypted for this Windows user on this PC)." -ForegroundColor Green
Write-Host 'build-release.ps1 now uses them. Delete that file to be asked again.'
