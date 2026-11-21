# SPDX-License-Identifier: GPL-3.0-only
# Build the two public Android releases (docs/ANDROID_DISTRIBUTION.md). Run it yourself:
#
#   powershell -ExecutionPolicy Bypass -File scripts\android\build-release.ps1 -VersionName 1.0.0 -VersionCode 100 -AccountOrigin https://account.example.test
#
# It builds, from this checkout:
#   1. the website download: the "direct" APK, signed with the app signing key;
#   2. the Google Play upload: the "play" app bundle (.aab), signed with the upload key.
# Passwords are asked for here and live only in this process; nothing is written to disk
# except the two outputs, their SHA-256 sums and each signer's certificate fingerprint.
param(
    [Parameter(Mandatory)] [string]$VersionName,
    [Parameter(Mandatory)] [int]$VersionCode,
    [Parameter(Mandatory)] [string]$AccountOrigin,
    [string]$HostedConfiguration = '',
    [switch]$PasswordDialog,
    [string]$SigningKeystore = 'E:\Saiph-private\saiph-app-signing.jks',
    [string]$SigningAlias = 'saiph',
    [string]$UploadKeystore = 'E:\Saiph-private\saiph-play-upload.jks',
    [string]$UploadAlias = 'upload',
    [string]$Output = 'E:\Saiph-private\android-releases',
    [switch]$SkipChecks
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$android = Join-Path $repo 'android'
. (Join-Path $PSScriptRoot 'release-tools.ps1')
$placedHosted = $false
$previousJavaOptions = $env:JAVA_TOOL_OPTIONS
$hostedAsset = Join-Path $android 'app\src\beta\assets\hosted-defaults.json'
function Stop-Release($why) { Write-Host "`nSTOPPED: $why" -ForegroundColor Red; exit 1 }
function Step($text) { Write-Host "`n== $text ==" -ForegroundColor Cyan }

try {
Step 'Checking tools and keys'
$accountUri = [uri]$AccountOrigin
if ($accountUri.Scheme -ne 'https' -or $accountUri.Authority -ne $accountUri.Host -or
    $accountUri.UserInfo -or $accountUri.Query -or $accountUri.Fragment -or $AccountOrigin -ne "https://$($accountUri.Host)") {
    Stop-Release 'AccountOrigin must be the canonical HTTPS account-site origin, without a trailing slash.'
}
$placedHosted = Install-AndroidReleaseDefaults $HostedConfiguration $hostedAsset
$hosted = Get-Content -LiteralPath $hostedAsset -Raw | ConvertFrom-Json
if (((@($hosted.PSObject.Properties.Name | Sort-Object)) -join ',') -ne 'android_client_id,audience,desktop_client_id,issuer,service_url' -or
    (Get-Item -LiteralPath $hostedAsset).Length -gt 4096) { Stop-Release 'Invalid public Hosted defaults.' }
foreach ($name in @('service_url','audience','issuer')) {
    $uri = [uri]$hosted.$name
    if (-not $uri.IsAbsoluteUri -or $uri.Scheme -ne 'https' -or $uri.UserInfo -or $uri.Query -or $uri.Fragment -or -not $uri.IsDefaultPort) { Stop-Release 'Hosted defaults require fixed HTTPS addresses.' }
}
if ($hosted.issuer -notmatch '^https://[a-z0-9.-]+\.auth0\.com/$' -or
    $hosted.android_client_id -notmatch '^[A-Za-z0-9_-]{8,128}$' -or
    $hosted.desktop_client_id -notmatch '^[A-Za-z0-9_-]{8,128}$' -or
    $hosted.android_client_id -eq $hosted.desktop_client_id) { Stop-Release 'Invalid public Hosted sign-in settings.' }
if ($VersionName -notmatch '^\d+\.\d+\.\d+$') { Stop-Release 'VersionName must look like 1.0.0' }
if ($VersionCode -lt 1) { Stop-Release 'VersionCode must be a positive whole number, higher than any release before it' }
$sourceCommit = (& git -C $repo rev-parse HEAD).Trim()
if ($LASTEXITCODE -or (& git -C $repo status --porcelain --untracked-files=normal)) { Stop-Release 'Build a clean committed worktree so the signed files have an exact source revision.' }
if (-not $env:JAVA_HOME -or -not (Test-Path (Join-Path $env:JAVA_HOME 'bin\java.exe'))) {
    if (Test-Path 'C:\Program Files\Java\jdk-22') { $env:JAVA_HOME = 'C:\Program Files\Java\jdk-22' } else { Stop-Release 'Set JAVA_HOME to JDK 22.' }
}
if (-not $env:ANDROID_HOME) {
    # The SDK Claude installed lives in the Claude app's virtualized AppData; a normal terminal sees it there.
    $virtual = Join-Path $env:LOCALAPPDATA 'Packages\Claude_pzs8sxrjxfjjc\LocalCache\Local\Android\Sdk'
    $env:ANDROID_HOME = if (Test-Path $virtual) { $virtual } else { Join-Path $env:LOCALAPPDATA 'Android\Sdk' }
}
if (-not (Test-Path (Join-Path $env:ANDROID_HOME 'build-tools'))) { Stop-Release "No Android SDK at $env:ANDROID_HOME" }
foreach ($abi in 'arm64-v8a', 'x86_64') {
    if (-not (Test-Path (Join-Path $android "restic-android\src\main\jniLibs\$abi\librestic.so"))) {
        Stop-Release "Build restic first (restic-android/UPSTREAM.md), or copy restic-android\src\main\jniLibs from a checkout that has it."
    }
}
foreach ($keystore in $SigningKeystore, $UploadKeystore) {
    if (-not (Test-Path $keystore)) { Stop-Release "No keystore at $keystore. Create it with the keytool command in the launch guide." }
}
# The version name is committed with the code it describes, as for tester builds.
$declared = [regex]::Match((Get-Content -Raw (Join-Path $android 'app\build.gradle.kts')), 'versionName = "([^"]+)"')
if ($declared.Groups[1].Value -ne $VersionName) { Stop-Release "android/app/build.gradle.kts declares versionName '$($declared.Groups[1].Value)'. Commit $VersionName there first." }
$keytool = Join-Path $env:JAVA_HOME 'bin\keytool.exe'
$java = Join-Path $env:JAVA_HOME 'bin\java.exe'
$jarsigner = Join-Path $env:JAVA_HOME 'bin\jarsigner.exe'
$tools = Join-Path $env:ANDROID_HOME 'build-tools\36.0.0'
if (-not (Test-Path -LiteralPath (Join-Path $tools 'lib\apksigner.jar')) -or -not (Test-Path -LiteralPath (Join-Path $tools 'aapt2.exe')) -or
    -not (Test-Path -LiteralPath (Join-Path $tools 'zipalign.exe'))) { Stop-Release 'Android build-tools 36.0.0 are required for signature, package and alignment verification.' }
$isolated = Join-Path $repo 'build\android-release'
foreach ($setting in @(@{Name='GRADLE_USER_HOME';Path='gradle-home'},@{Name='ANDROID_USER_HOME';Path='android-user'})) {
    if (-not [Environment]::GetEnvironmentVariable($setting.Name,'Process')) { [Environment]::SetEnvironmentVariable($setting.Name,(Join-Path $isolated $setting.Path),'Process') }
}
$tempDirectory = Join-Path $isolated 'tmp'
[void](New-Item -ItemType Directory -Force -Path $tempDirectory)
$env:JAVA_TOOL_OPTIONS = ($previousJavaOptions + ' -Djava.io.tmpdir="' + $tempDirectory + '"').Trim()
$release = Join-Path $Output "$VersionName-$VersionCode"
if (Test-Path $release) { Stop-Release "$release already exists; use a new version code." }

function Build($task, $keystore, $alias, $password) {
    $env:SAIPH_ANDROID_KEYSTORE = $keystore; $env:SAIPH_ANDROID_KEY_ALIAS = $alias
    $env:SAIPH_ANDROID_KEYSTORE_PASSWORD = $password; $env:SAIPH_ANDROID_KEY_PASSWORD = $password
    try {
        $tasks = @($task)
        if (-not $SkipChecks) { $tasks += @(':app:testDirectDebugUnitTest', ':app:testPlayDebugUnitTest', ':core:network:testDebugUnitTest') }
        & (Join-Path $android 'gradlew.bat') -p $android @tasks "-PorionVersionCode=$VersionCode" `
            "-PorionAccountOrigin=$AccountOrigin" `
            "-Djava.io.tmpdir=$tempDirectory" `
            -PorionFirebase=false -PorionIndependent=true --no-configuration-cache --no-daemon --console=plain --max-workers=3
        if ($LASTEXITCODE) { Stop-Release "Gradle failed on $task" }
    } finally {
        Remove-Item Env:SAIPH_ANDROID_KEYSTORE_PASSWORD, Env:SAIPH_ANDROID_KEY_PASSWORD -ErrorAction SilentlyContinue
    }
}
function Fingerprint($keystore, $alias, $password) {
    Get-AndroidSigningFingerprint $keytool $keystore $alias $password
}

Step "Website download (direct APK), signed with $SigningKeystore"
$signingPassword = Read-AndroidReleasePassword 'App signing key password' ([bool]$PasswordDialog)
$signingFingerprint = Fingerprint $SigningKeystore $SigningAlias $signingPassword
if (-not $signingFingerprint) { Stop-Release 'Wrong app signing password or alias.' }
Build ':app:assembleDirectRelease' $SigningKeystore $SigningAlias $signingPassword
$signingPassword = $null

Step "Google Play upload (play bundle), signed with $UploadKeystore"
$uploadPassword = Read-AndroidReleasePassword 'Upload key password' ([bool]$PasswordDialog)
$uploadFingerprint = Fingerprint $UploadKeystore $UploadAlias $uploadPassword
if (-not $uploadFingerprint) { Stop-Release 'Wrong upload key password or alias.' }
Build ':app:bundlePlayRelease' $UploadKeystore $UploadAlias $uploadPassword
$uploadPassword = $null

Step 'Verifying signatures and package identity'
$builtApk = Join-Path $android 'app\build\outputs\apk\direct\release\app-direct-release.apk'
$builtAab = Join-Path $android 'app\build\outputs\bundle\playRelease\app-play-release.aab'
$apkSignature = Invoke-AndroidReleaseTool $java @('-jar',(Join-Path $tools 'lib\apksigner.jar'),'verify','--print-certs',$builtApk)
$apkSigners = @([regex]::Matches($apkSignature.Out,'Signer #\d+ certificate SHA-256 digest:\s*([a-fA-F0-9]{64})'))
if ($apkSignature.ExitCode -or $apkSigners.Count -ne 1 -or $apkSigners[0].Groups[1].Value -ne $signingFingerprint.Replace(':','').ToLowerInvariant()) { Stop-Release 'The APK signature does not match the app signing certificate.' }
$aabSignature = Invoke-AndroidReleaseTool $jarsigner @('-J-Duser.language=en','-verify','-strict',$builtAab)
$aabCertificate = Invoke-AndroidReleaseTool $keytool @('-J-Duser.language=en','-printcert','-jarfile',$builtAab)
$aabFingerprints = @([regex]::Matches($aabCertificate.Out,'SHA256:\s*([0-9A-Fa-f:]{95})') | ForEach-Object { $_.Groups[1].Value.ToUpperInvariant() } | Select-Object -Unique)
if ($aabSignature.ExitCode -notin @(0,4) -or ($aabSignature.Out + $aabSignature.Err) -notmatch 'jar verified' -or
    $aabCertificate.ExitCode -or $aabFingerprints.Count -ne 1 -or $aabFingerprints[0] -ne $uploadFingerprint) { Stop-Release 'The Play bundle signature or entry coverage does not match the upload certificate.' }
# Strict exit 4 permits the expected self-signed Android certificate. Other
# failure bits (including unsigned entries) are rejected.
$badging = Invoke-AndroidReleaseTool (Join-Path $tools 'aapt2.exe') @('dump','badging',$builtApk)
if ($badging.ExitCode -or $badging.Out -notmatch "package: name='com.orionmini.mobile.unlocked' versionCode='$VersionCode' versionName='$([regex]::Escape($VersionName))'" -or $badging.Out -match 'application-debuggable') { Stop-Release 'The APK package/version/debug state does not match the release.' }
$nativeApk = Get-AndroidNativeInventory $builtApk
$nativeAab = Get-AndroidNativeInventory $builtAab
$alignment = Invoke-AndroidReleaseTool (Join-Path $tools 'zipalign.exe') @('-c','-P','16','4',$builtApk)
if ($alignment.ExitCode) { Stop-Release 'APK ZIP alignment verification failed.' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$expectedDefaults = Get-AndroidReleaseSha256 $hostedAsset
foreach ($bundle in @(@{Path=$builtApk;Entry='assets/hosted-defaults.json'},@{Path=$builtAab;Entry='base/assets/hosted-defaults.json'})) {
    $zip = [IO.Compression.ZipFile]::OpenRead($bundle.Path)
    try {
        $entry = $zip.GetEntry($bundle.Entry)
        if (-not $entry) { Stop-Release 'A release is missing its public Hosted defaults.' }
        $stream = $entry.Open(); $digest = [Security.Cryptography.SHA256]::Create()
        try { $actual = ([BitConverter]::ToString($digest.ComputeHash($stream))).Replace('-','') }
        finally { $stream.Dispose(); $digest.Dispose() }
        if ($actual -ne $expectedDefaults) { Stop-Release 'The packaged public Hosted defaults do not match the reviewed build input.' }
    } finally { $zip.Dispose() }
}
if ((& git -C $repo rev-parse HEAD).Trim() -ne $sourceCommit -or (& git -C $repo status --porcelain --untracked-files=normal)) { Stop-Release 'The source changed during the build; no release receipt was issued.' }

Step "Saving to $release"
[void](New-Item -ItemType Directory -Path $release)
$apk = Join-Path $release "Saiph-$VersionName.apk"
$aab = Join-Path $release "Saiph-$VersionName-play.aab"
Copy-Item -LiteralPath $builtApk -Destination $apk
Copy-Item -LiteralPath $builtAab -Destination $aab
$receipt = [ordered]@{
    versionName = $VersionName; versionCode = $VersionCode
    sourceCommit = $sourceCommit; uncommitted = $false
    accountOrigin = $AccountOrigin
    hostedDefaultsSha256 = (Get-AndroidReleaseSha256 $hostedAsset).ToLowerInvariant()
    apk = (Split-Path $apk -Leaf); apkSha256 = (Get-AndroidReleaseSha256 $apk).ToLowerInvariant()
    aab = (Split-Path $aab -Leaf); aabSha256 = (Get-AndroidReleaseSha256 $aab).ToLowerInvariant()
    appSigningCertificateSha256 = $signingFingerprint; uploadCertificateSha256 = $uploadFingerprint
    signatureVerification = 'APK apksigner, AAB jarsigner and upload certificate verified'
    packageVerification = 'APK package, version and release state verified; both Hosted assets match'
    nativeApk = $nativeApk; nativeAab = $nativeAab
    zipAlignmentVerification = 'zipalign -c -P 16 4 passed'
    checksRun = -not [bool]$SkipChecks
}
$receipt | ConvertTo-Json -Depth 6 | Set-Content -Encoding utf8 (Join-Path $release 'release.json')
# Saiph (Google Play) and Saiph Unlocked (website) are both signed by this app signing key.
$assetlinks = @('com.orionmini.mobile', 'com.orionmini.mobile.unlocked' | ForEach-Object { @{relation=@('delegate_permission/common.handle_all_urls');target=@{namespace='android_app';package_name=$_;sha256_cert_fingerprints=@($signingFingerprint)}} })
ConvertTo-Json -InputObject $assetlinks -Depth 6 | Set-Content -Encoding utf8 (Join-Path $release 'assetlinks.json')
Write-Host "`nDone." -ForegroundColor Green
Write-Host "  Website APK : $apk"
Write-Host "  Play bundle : $aab  (upload this in Play Console)"
Write-Host "  App signing certificate SHA-256: $signingFingerprint"
if ($receipt.uncommitted) { Write-Host '  Note: the checkout had uncommitted changes; release from a clean commit.' -ForegroundColor Yellow }
} finally {
    $signingPassword = $null; $uploadPassword = $null
    if ($null -eq $previousJavaOptions) { Remove-Item Env:JAVA_TOOL_OPTIONS -ErrorAction SilentlyContinue }
    else { $env:JAVA_TOOL_OPTIONS = $previousJavaOptions }
    if ($placedHosted -and (Test-Path -LiteralPath $hostedAsset)) { Remove-Item -LiteralPath $hostedAsset }
}
