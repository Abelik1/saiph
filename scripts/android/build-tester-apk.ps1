# SPDX-License-Identifier: AGPL-3.0-or-later
<#
.SYNOPSIS
  Build, verify and (only with -Upload) distribute an independent Saiph Android
  tester APK through Firebase App Distribution.

.DESCRIPTION
  Builds android/ with -PorionIndependent=true -PorionFirebase=true and an explicit
  version code, then verifies the APK before anything leaves this machine:

    * the whole worktree is clean and unchanged by the build; the commit is recorded
    * no google-services.json is tracked by Git, and the local one is Git-ignored
    * package, version name and version code match the request; beta is not debuggable
    * exactly one signer whose certificate SHA-256 equals -ExpectedSignerSha256
    * Firebase resources match the local google-services.json; Firebase starts,
      while push auto-init and messaging components are disabled in the APK
    * DEX and compiled resources contain none of the owner strings listed in
      -ForbiddenStringsFile (owner Hub addresses, hostnames, emails)

  Results go to a new output directory outside the repository: the APK, a Git
  archive of android/ (GPL corresponding source) and release.json with the APK
  SHA-256 and source commit. Nothing is uploaded unless -Upload is passed.

  Owner-specific values (Firebase project, tester groups, keystore, fingerprint,
  owner strings) are parameters or environment variables, never repository files.
  See docs/ANDROID_BETA_TESTING.md.

.EXAMPLE
  ./scripts/android/build-tester-apk.ps1 -VersionName 0.8.6 -VersionCode 3564000 `
    -ExpectedSignerSha256 $env:SAIPH_ANDROID_SIGNER_SHA256 `
    -GoogleServicesJson D:\private\saiph\google-services.json `
    -ForbiddenStringsFile D:\private\saiph\owner-strings.txt

  Builds and verifies only.

.EXAMPLE
  ./scripts/android/build-tester-apk.ps1 ... -Upload -TesterGroups beta-testers

  Additionally uploads the verified APK and gives the named group access.
  Add -Testers you@example.com to also give named testers access directly: a
  group with no members gives nobody access.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidatePattern('^[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?$')][string]$VersionName,
    [Parameter(Mandatory)][ValidateRange(1, 2100000000)][int]$VersionCode,
    # Certificate SHA-256 of the existing signing identity, hex with or without colons.
    [string]$ExpectedSignerSha256 = $env:SAIPH_ANDROID_SIGNER_SHA256,
    # Private Firebase configuration; copied into android/app only for this build.
    [string]$GoogleServicesJson = $env:SAIPH_ANDROID_GOOGLE_SERVICES_JSON,
    # One owner-specific string per line (# comments allowed). Required.
    [string]$ForbiddenStringsFile = $env:SAIPH_ANDROID_FORBIDDEN_STRINGS_FILE,
    # Beta supports App Distribution without debugger access. Debug remains a
    # development-only option; release does not include the tester update SDK.
    [ValidateSet('beta', 'debug')][string]$BuildType = 'beta',
    # Beta requires the existing signing identity through SAIPH_ANDROID_*.
    # Without an explicit key, debug uses the Android SDK's debug.keystore.
    [string]$KeystorePath = $env:SAIPH_ANDROID_KEYSTORE,
    [string]$KeyAlias = $env:SAIPH_ANDROID_KEY_ALIAS,
    # Highest version code already distributed; the new code must be greater.
    [int]$MinimumVersionCode = 0,
    [string]$OutputDirectory = '',
    [string]$BuildToolsVersion = '36.0.0',
    [switch]$SkipChecks,
    [switch]$Upload,
    # firebase executable/.cmd, or firebase-tools lib/bin/firebase.js (run with node).
    [string]$FirebaseCli = $env:SAIPH_FIREBASE_CLI,
    [string[]]$TesterGroups = @(),
    # Tester email addresses given access directly, e.g. the publisher's own account.
    [string[]]$Testers = @(),
    [string]$ReleaseNotesFile = '',
    # Public service/OAuth identifiers, temporarily embedded in the beta APK.
    [string]$HostedConfiguration = ''
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem
$package = 'com.orionmini.mobile'

function ConvertTo-ArgumentString([string[]]$Arguments) {
    ($Arguments | ForEach-Object {
        if ($_ -eq '') { '""' }
        elseif ($_ -notmatch '[\s"]') { $_ }
        else { '"' + (($_ -replace '(\\*)"', '$1$1\"') -replace '(\\+)$', '$1$1') + '"' }
    }) -join ' '
}

# Captures both streams without Windows PowerShell 5.1 turning native stderr into errors.
function Invoke-Captured([string]$File, [string[]]$Arguments, [string]$WorkingDirectory = '', [hashtable]$Environment = @{}) {
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $File
    $info.Arguments = ConvertTo-ArgumentString $Arguments
    $info.UseShellExecute = $false; $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true; $info.RedirectStandardError = $true
    if ($WorkingDirectory) { $info.WorkingDirectory = $WorkingDirectory }
    foreach ($key in $Environment.Keys) { $info.EnvironmentVariables[$key] = [string]$Environment[$key] }
    $process = [Diagnostics.Process]::Start($info)
    try {
        $stdout = $process.StandardOutput.ReadToEndAsync(); $stderr = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        [pscustomobject]@{ ExitCode = $process.ExitCode; Out = $stdout.Result; Err = $stderr.Result }
    } finally { $process.Dispose() }
}

function Invoke-Git([string[]]$Arguments) {
    $result = Invoke-Captured 'git' (@('-C', $repo) + $Arguments)
    if ($result.ExitCode) { throw "git $($Arguments[0]) failed." }
    return $result.Out
}

function Test-ContainsAny([byte[]]$Bytes, [string[]]$Needles) {
    $utf8 = [Text.Encoding]::UTF8.GetString($Bytes)
    # Compiled resources may hold UTF-16 strings at either byte alignment.
    $utf16 = [Text.Encoding]::Unicode.GetString($Bytes)
    $utf16Odd = if ($Bytes.Length -gt 1) { [Text.Encoding]::Unicode.GetString($Bytes, 1, $Bytes.Length - 1) } else { '' }
    foreach ($needle in $Needles) {
        foreach ($text in @($utf8, $utf16, $utf16Odd)) {
            if ($text.IndexOf($needle, [StringComparison]::OrdinalIgnoreCase) -ge 0) { return $true }
        }
    }
    return $false
}

function Read-ZipEntry($Entry) {
    $stream = $Entry.Open(); $buffer = New-Object IO.MemoryStream
    try { $stream.CopyTo($buffer); return , $buffer.ToArray() }
    finally { $stream.Dispose(); $buffer.Dispose() }
}

# ---------------------------------------------------------------- preconditions
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$android = Join-Path $repo 'android'
if (-not (Test-Path -LiteralPath (Join-Path $android 'app/build.gradle.kts'))) { throw 'Run this from the Saiph product repository.' }

$fingerprint = ($ExpectedSignerSha256 -replace '[:\s]', '').ToLowerInvariant()
if ($fingerprint -notmatch '^[0-9a-f]{64}$') { throw 'Pass -ExpectedSignerSha256 (or SAIPH_ANDROID_SIGNER_SHA256): the existing signing certificate SHA-256.' }
if ($VersionCode -le $MinimumVersionCode) { throw "Version code must be greater than $MinimumVersionCode, the highest code already distributed." }
if (-not $ForbiddenStringsFile -or -not (Test-Path -LiteralPath $ForbiddenStringsFile)) {
    throw 'Pass -ForbiddenStringsFile (or SAIPH_ANDROID_FORBIDDEN_STRINGS_FILE): a private list of owner Hub addresses, hostnames and emails that must not ship.'
}
$forbidden = @(Get-Content -LiteralPath $ForbiddenStringsFile | ForEach-Object { $_.Trim() } | Where-Object { $_ -and -not $_.StartsWith('#') })
if ($forbidden.Count -eq 0) { throw 'The forbidden strings file has no entries.' }
foreach ($group in $TesterGroups) { if ($group -notmatch '^[a-z0-9][a-z0-9-]*$') { throw 'Tester group aliases use lowercase letters, digits and hyphens.' } }
if ($TesterGroups.Count -and -not $Upload) { throw '-TesterGroups only applies with -Upload.' }
foreach ($tester in $Testers) { if ($tester -notmatch '^[^@\s,]+@[^@\s,]+\.[^@\s,]+$') { throw 'Testers are email addresses.' } }
if ($Testers.Count -and -not $Upload) { throw '-Testers only applies with -Upload.' }

$declared = [regex]::Match((Get-Content -LiteralPath (Join-Path $android 'app/build.gradle.kts') -Raw), 'versionName\s*=\s*"([^"]+)"')
if (-not $declared.Success -or $declared.Groups[1].Value -ne $VersionName) {
    throw "android/app/build.gradle.kts declares versionName '$($declared.Groups[1].Value)'. Commit the intended version name before building $VersionName."
}

if ((Invoke-Git @('status', '--porcelain')).Trim()) { throw 'Commit or stash all changes; tester builds come from a clean, recorded commit.' }
$revision = (Invoke-Git @('rev-parse', 'HEAD')).Trim()
if ($revision -notmatch '^[0-9a-f]{40}$') { throw 'Could not identify the source commit.' }

# Firebase configuration must stay private: never tracked, always ignored.
if ((Invoke-Git @('ls-files', '--', ':(glob)**/google-services.json')).Trim()) { throw 'A google-services.json is tracked by Git. Remove it from history before any build.' }
$localConfig = Join-Path $android 'app/google-services.json'
$ignored = Invoke-Captured 'git' @('-C', $repo, 'check-ignore', '-q', '--', 'android/app/google-services.json')
if ($ignored.ExitCode -ne 0) { throw 'android/app/google-services.json is not Git-ignored.' }
$placedConfig = $false
$placedHosted = $false
$hostedAsset = Join-Path $android 'app/src/beta/assets/hosted-defaults.json'
if ($GoogleServicesJson) {
    $source = (Resolve-Path -LiteralPath $GoogleServicesJson).Path
    if (Test-Path -LiteralPath $localConfig) {
        if ((Get-FileHash -LiteralPath $localConfig).Hash -ne (Get-FileHash -LiteralPath $source).Hash) { throw 'A different android/app/google-services.json already exists; remove it first.' }
    } else { Copy-Item -LiteralPath $source -Destination $localConfig; $placedConfig = $true }
} elseif (-not (Test-Path -LiteralPath $localConfig)) {
    throw 'Pass -GoogleServicesJson (or SAIPH_ANDROID_GOOGLE_SERVICES_JSON) with the private Firebase configuration.'
}

try {
    if ($HostedConfiguration) {
        if ($BuildType -ne 'beta' -or (Test-Path -LiteralPath $hostedAsset)) { throw 'Use a beta build and a fresh temporary Hosted asset.' }
        $hosted = Get-Content -LiteralPath $HostedConfiguration -Raw | ConvertFrom-Json
        $keys = @($hosted.PSObject.Properties.Name | Sort-Object)
        if (($keys -join ',') -ne 'android_client_id,audience,desktop_client_id,issuer,service_url') { throw 'Hosted defaults accept only the five public fields.' }
        foreach ($name in @('service_url','issuer','audience')) {
            $uri = [uri]$hosted.$name
            if ($uri.Scheme -ne 'https' -or $uri.UserInfo -or $uri.Query -or $uri.Fragment -or -not $uri.IsDefaultPort) { throw 'Hosted defaults require fixed HTTPS addresses.' }
        }
        if ($hosted.issuer -notmatch '^https://[a-z0-9.-]+\.auth0\.com/$' -or
            $hosted.service_url -notmatch '^https://[a-z0-9.-]+$' -or
            $hosted.android_client_id -notmatch '^[A-Za-z0-9_-]{8,128}$' -or
            $hosted.desktop_client_id -notmatch '^[A-Za-z0-9_-]{8,128}$' -or
            $hosted.android_client_id -eq $hosted.desktop_client_id -or
            (Get-Item -LiteralPath $HostedConfiguration).Length -gt 4096) { throw 'Invalid public Hosted defaults.' }
        [void](New-Item -ItemType Directory -Force -Path (Split-Path -Parent $hostedAsset))
        Copy-Item -LiteralPath $HostedConfiguration -Destination $hostedAsset
        $placedHosted = $true
    }
    $config = Get-Content -LiteralPath $localConfig -Raw | ConvertFrom-Json
    $client = @($config.client | Where-Object { $_.client_info.android_client_info.package_name -eq $package })
    if ($client.Count -ne 1) { throw "Firebase configuration must contain exactly one $package client." }
    $appId = $client[0].client_info.mobilesdk_app_id
    $project = $config.project_info.project_id
    if ($appId -notmatch '^1:[0-9]+:android:[a-fA-F0-9]+$' -or $project -notmatch '^[a-z][a-z0-9-]+$') { throw 'Invalid Firebase app/project metadata.' }

    if (-not $env:JAVA_HOME) { throw 'Set JAVA_HOME to JDK 22 (the tested Android toolchain).' }
    $java = Join-Path $env:JAVA_HOME 'bin/java.exe'
    $javaVersion = Invoke-Captured $java @('-version')
    if ($javaVersion.ExitCode -or ($javaVersion.Err + $javaVersion.Out) -notmatch 'version "22(?:\.|")') { throw 'Set JAVA_HOME to JDK 22; JDK 17 fails the inherited lint tooling.' }
    if (-not $env:ANDROID_HOME) { throw 'Set ANDROID_HOME to an Android SDK with platform 37.0, build-tools 36.0.0 and NDK 28.2.13676358.' }
    $tools = Join-Path $env:ANDROID_HOME "build-tools/$BuildToolsVersion"
    $aapt = Join-Path $tools 'aapt2.exe'
    $apksigner = Join-Path $tools 'lib/apksigner.jar'
    if (-not (Test-Path -LiteralPath $aapt) -or -not (Test-Path -LiteralPath $apksigner)) { throw "Android build-tools $BuildToolsVersion are required." }
    $native = foreach ($abi in @('arm64-v8a', 'x86_64')) {
        $library = Join-Path $android "restic-android/src/main/jniLibs/$abi/librestic.so"
        if (-not (Test-Path -LiteralPath $library)) { throw 'Generate native restic first: python android/scripts/build-restic.py --android-root android' }
        [ordered]@{ abi = $abi; sha256 = (Get-FileHash -LiteralPath $library -Algorithm SHA256).Hash.ToLowerInvariant() }
    }

    if (-not $OutputDirectory) {
        $base = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { [IO.Path]::GetTempPath() }
        $OutputDirectory = Join-Path $base "saiph-android-beta/$VersionName-$VersionCode"
    }
    $output = [IO.Path]::GetFullPath($OutputDirectory)
    if ($output.StartsWith($repo.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Keep build outputs outside the repository.' }
    if (Test-Path -LiteralPath $output) { throw 'Use a new output directory; existing artifacts are never overwritten.' }
    [void](New-Item -ItemType Directory -Path $output)

    # ------------------------------------------------------------------- build
    $variant = (Get-Culture).TextInfo.ToTitleCase($BuildType)
    $tasks = @(":app:assemble$variant")
    if (-not $SkipChecks) {
        $tasks += @(":app:testDebugUnitTest", ":core:network:testDebugUnitTest", ":restic-android:testDebugUnitTest", ":app:lint$variant")
    }
    $gradleArguments = $tasks + @("-PorionVersionCode=$VersionCode", '-PorionFirebase=true', '-PorionIndependent=true', '-PorionPush=false', '--no-configuration-cache', '--console=plain')
    $gradleEnvironment = @{}
    if ($KeystorePath) {
        if (-not $KeyAlias -or -not $env:SAIPH_ANDROID_KEYSTORE_PASSWORD -or -not $env:SAIPH_ANDROID_KEY_PASSWORD) {
            throw 'An explicit keystore needs -KeyAlias, SAIPH_ANDROID_KEYSTORE_PASSWORD and SAIPH_ANDROID_KEY_PASSWORD.'
        }
        # Match app/build.gradle.kts. Private signing values stay in the child
        # environment and never appear in Gradle command-line arguments.
        $gradleEnvironment['SAIPH_ANDROID_KEYSTORE'] = (Resolve-Path -LiteralPath $KeystorePath).Path
        $gradleEnvironment['SAIPH_ANDROID_KEYSTORE_PASSWORD'] = $env:SAIPH_ANDROID_KEYSTORE_PASSWORD
        $gradleEnvironment['SAIPH_ANDROID_KEY_ALIAS'] = $KeyAlias
        $gradleEnvironment['SAIPH_ANDROID_KEY_PASSWORD'] = $env:SAIPH_ANDROID_KEY_PASSWORD
    } elseif ($BuildType -eq 'beta') {
        throw 'Beta requires the existing signing key: pass -KeystorePath and -KeyAlias.'
    }
    Write-Output "Building $package $VersionName ($VersionCode), $BuildType, independent + Firebase, from $revision..."
    $gradle = Invoke-Captured (Join-Path $android 'gradlew.bat') $gradleArguments $android $gradleEnvironment
    Set-Content -LiteralPath (Join-Path $output 'build.log') -Value ($gradle.Out + "`n" + $gradle.Err) -Encoding utf8
    if ($gradle.ExitCode) { throw "Gradle failed; see $(Join-Path $output 'build.log')." }

    # ------------------------------------------------------------------ verify
    $apkDirectory = Join-Path $android "app/build/outputs/apk/$BuildType"
    $metadata = Get-Content -LiteralPath (Join-Path $apkDirectory 'output-metadata.json') -Raw | ConvertFrom-Json
    if ($metadata.applicationId -ne $package -or @($metadata.elements).Count -ne 1) { throw 'Unexpected APK metadata.' }
    $element = $metadata.elements[0]
    if ($element.outputFile -ne [IO.Path]::GetFileName($element.outputFile)) { throw 'Unexpected APK output path.' }
    if ([long]$element.versionCode -ne $VersionCode -or $element.versionName -ne $VersionName) { throw 'APK version does not match the request.' }
    $builtApk = Join-Path $apkDirectory $element.outputFile

    $badging = Invoke-Captured $aapt @('dump', 'badging', $builtApk)
    $expectedIdentity = "package: name='$package' versionCode='$VersionCode' versionName='$([regex]::Escape($VersionName))'"
    if ($badging.ExitCode -or $badging.Out -notmatch $expectedIdentity) { throw 'APK package/version identity verification failed.' }
    $debuggable = $badging.Out -match '(?m)^application-debuggable'
    if ($BuildType -eq 'beta' -and $debuggable) { throw 'Beta APK is debuggable; do not distribute.' }

    $signature = Invoke-Captured $java @('-jar', $apksigner, 'verify', '--print-certs', $builtApk)
    $signers = [regex]::Matches($signature.Out, 'Signer #\d+ certificate SHA-256 digest: ([a-fA-F0-9]+)')
    if ($signature.ExitCode -or $signers.Count -ne 1 -or $signers[0].Groups[1].Value.ToLowerInvariant() -ne $fingerprint) {
        throw 'APK signer does not match -ExpectedSignerSha256. Testers could not update in place; do not distribute.'
    }

    $resources = Invoke-Captured $aapt @('dump', 'resources', $builtApk)
    if ($resources.ExitCode -or $resources.Out -notmatch 'string/google_app_id' -or -not $resources.Out.Contains($appId)) {
        throw 'APK is not configured for the Firebase app in google-services.json.'
    }
    $manifest = Invoke-Captured $aapt @('dump', 'xmltree', $builtApk, '--file', 'AndroidManifest.xml')
    if ($manifest.ExitCode) { throw 'Could not read the packaged manifest.' }
    $blocks = [regex]::Matches($manifest.Out, '(?m)^[^\S\r\n]*E: (provider|service|receiver|meta-data)[^\r\n]*(?:\r?\n(?![^\S\r\n]*E: )[^\r\n]*)*')
    $componentStates = @{
        'com.google.firebase.provider.FirebaseInitProvider' = $true
        'com.orionmini.mobile.OrionMessagingService' = $false
        'com.google.firebase.iid.FirebaseInstanceIdReceiver' = $false
        'com.google.firebase.messaging.FirebaseMessagingService' = $false
    }
    foreach ($component in $componentStates.Keys) {
        $block = @($blocks | Where-Object { $_.Value -match ('A: (?:http://schemas.android.com/apk/res/android:|android:)name[^\r\n]*' + [regex]::Escape($component)) })
        $state = $componentStates[$component].ToString().ToLowerInvariant()
        if ($block.Count -ne 1 -or $block[0].Value -notmatch ('A: (?:http://schemas.android.com/apk/res/android:|android:)enabled[^\r\n]*=' + $state + '(?:\s|$)')) {
            throw "Firebase component $component does not have enabled=$state."
        }
    }
    $autoInit = @($blocks | Where-Object { $_.Value -match 'A: (?:http://schemas.android.com/apk/res/android:|android:)name[^\r\n]*firebase_messaging_auto_init_enabled' })
    if ($autoInit.Count -ne 1 -or $autoInit[0].Value -notmatch 'A: (?:http://schemas.android.com/apk/res/android:|android:)value[^\r\n]*=false(?:\s|$)') {
        throw 'Firebase Messaging auto-init is not disabled.'
    }

    # Independent tester builds must never carry an owner Hub address or identity.
    $zip = [IO.Compression.ZipFile]::OpenRead($builtApk)
    try {
        foreach ($entry in @($zip.Entries | Where-Object { $_.FullName -match '^(classes[0-9]*\.dex|resources\.arsc|AndroidManifest\.xml|assets/.*)$' })) {
            if (Test-ContainsAny (Read-ZipEntry $entry) $forbidden) { throw "APK entry $($entry.FullName) contains an owner-specific string." }
        }
    } finally { $zip.Dispose() }

    $apkName = "saiph-android-tester-$VersionName-$VersionCode.apk"
    $apk = Join-Path $output $apkName
    Copy-Item -LiteralPath $builtApk -Destination $apk

    # GPL corresponding source for exactly this commit's Android tree.
    $sourceName = "saiph-android-$VersionName-$VersionCode-source.zip"
    $sourceArchive = Join-Path $output $sourceName
    [void](Invoke-Git @('archive', '--format=zip', "--prefix=saiph-android-$VersionName/", "--output=$sourceArchive", $revision, 'android'))
    $sourceZip = [IO.Compression.ZipFile]::OpenRead($sourceArchive)
    try {
        if (@($sourceZip.Entries | Where-Object { $_.FullName -match '(^|/)(google-services\.json|local\.properties|[^/]+\.(keystore|jks)|\.env)$' })) {
            throw 'Source archive contains a private configuration file.'
        }
    } finally { $sourceZip.Dispose() }

    if ((Invoke-Git @('status', '--porcelain')).Trim() -or (Invoke-Git @('rev-parse', 'HEAD')).Trim() -ne $revision) {
        throw 'The source changed during the build; do not distribute these artifacts.'
    }

    if ($placedHosted) { Copy-Item -LiteralPath $hostedAsset -Destination (Join-Path $output 'hosted-defaults.json') }
    $receiptPath = Join-Path $output 'release.json'
    $receipt = [ordered]@{
        schema = 1; package = $package; versionName = $VersionName; versionCode = $VersionCode
        buildType = $BuildType; debuggable = [bool]$debuggable; independent = $true; firebase = $true; firebasePush = $false
        sourceCommit = $revision; apk = $apkName; apkSha256 = (Get-FileHash -LiteralPath $apk -Algorithm SHA256).Hash.ToLowerInvariant()
        signerCertificateSha256 = $fingerprint; sourceArchive = $sourceName
        sourceArchiveSha256 = (Get-FileHash -LiteralPath $sourceArchive -Algorithm SHA256).Hash.ToLowerInvariant()
        nativeRestic = @($native); firebaseAppId = $appId; firebaseProject = $project
        ownerStringScan = "passed ($($forbidden.Count) private entries)"; gradleTasks = $tasks; checksRun = (-not $SkipChecks)
        java = (($javaVersion.Err + $javaVersion.Out) -split "`r?`n")[0]; preparedAtUtc = [DateTime]::UtcNow.ToString('o')
        uploaded = $false
        hostedDefaultsSha256 = if ($placedHosted) { (Get-FileHash -LiteralPath $hostedAsset -Algorithm SHA256).Hash.ToLowerInvariant() } else { $null }
    }
    $receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $receiptPath -Encoding utf8
    Write-Output "Verified $apkName"
    Write-Output "  SHA-256: $($receipt.apkSha256)"
    Write-Output "  Source:  $revision"
    Write-Output "  Output:  $output"
    if ($debuggable) { Write-Output '  Note: debug build type (debuggable), as used by the existing tester channel.' }

    # ------------------------------------------------------------------ upload
    if (-not $Upload) { Write-Output 'Nothing was uploaded. Re-run with -Upload to distribute this build.'; return }
    if (-not $FirebaseCli) {
        $found = Get-Command firebase.cmd, firebase -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $found) { throw 'Install firebase-tools or pass -FirebaseCli.' }
        $FirebaseCli = $found.Source
    }
    $cliPath = (Resolve-Path -LiteralPath $FirebaseCli).Path
    $runner = $cliPath; $prefix = @()
    if ($cliPath -match '\.js$') {
        $runner = if ($env:SAIPH_NODE) { $env:SAIPH_NODE } else { (Get-Command node -ErrorAction Stop).Source }
        $prefix = @($cliPath)
    }
    function Invoke-Firebase([string[]]$Arguments) {
        $result = Invoke-Captured $runner ($prefix + $Arguments + @('--json', '--non-interactive')) '' @{ NO_UPDATE_NOTIFIER = '1' }
        try { $json = $result.Out | ConvertFrom-Json } catch { throw 'Firebase returned an unreadable result; its output was suppressed because it can contain account data.' }
        # Node on Windows can crash in libuv shutdown after printing a complete success result.
        $shutdownFault = $result.ExitCode -eq -1073740791 -and $result.Err -match 'UV_HANDLE_CLOSING' -and $json.status -eq 'success'
        if (($result.ExitCode -and -not $shutdownFault) -or $json.status -ne 'success') { throw 'Firebase operation failed. Check `firebase login` and project access; output suppressed.' }
        return $json.result
    }
    $apps = @(Invoke-Firebase @('apps:list', 'ANDROID', '--project', $project))
    if (-not @($apps | Where-Object { $_.appId -eq $appId -and $_.packageName -eq $package })) { throw 'The signed-in account cannot see the Firebase app from google-services.json.' }
    $notes = if ($ReleaseNotesFile) { (Resolve-Path -LiteralPath $ReleaseNotesFile).Path } else {
        $generated = Join-Path $output 'release-notes.txt'
        @(
            "Saiph $VersionName (build $VersionCode) beta tester build."
            $(if ($placedHosted) { 'Hosted beta access: activate your invitation in your Saiph account, sign in on both devices and approve your phone from your computer. No Tailscale is required.' } else { 'Independent build: pair it with an invitation from your own Saiph Hub. It contains no default Hub.' })
            "Source commit $revision. Licence: GPL-3.0-only. Ask the publisher for the matching source archive."
        ) -join "`n" | Set-Content -LiteralPath $generated -Encoding utf8
        $generated
    }
    $distribute = @('appdistribution:distribute', $apk, '--app', $appId, '--project', $project, '--release-notes-file', $notes)
    if ($TesterGroups.Count) { $distribute += @('--groups', ($TesterGroups -join ',')) }
    if ($Testers.Count) { $distribute += @('--testers', ($Testers -join ',')) }
    [void](Invoke-Firebase $distribute)
    $receipt.uploaded = $true; $receipt.uploadedAtUtc = [DateTime]::UtcNow.ToString('o'); $receipt.testerGroups = $TesterGroups
    # Only the count is kept: the release record is not a place for email addresses.
    $receipt.directTesters = $Testers.Count
    $receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $receiptPath -Encoding utf8
    if ($TesterGroups.Count -or $Testers.Count) { Write-Output "Uploaded to Firebase App Distribution for group(s): $($TesterGroups -join ', ') and $($Testers.Count) direct tester(s). A group gives access only to its current members." }
    else { Write-Output 'Uploaded to Firebase App Distribution without granting any tester access.' }
} finally {
    if ($placedHosted) { Remove-Item -LiteralPath $hostedAsset -Force }
    if ($placedConfig) { Remove-Item -LiteralPath $localConfig -Force }
}
