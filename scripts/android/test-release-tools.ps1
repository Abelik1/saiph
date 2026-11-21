# SPDX-License-Identifier: GPL-3.0-only
# Real keytool with fresh synthetic material; no owner keys, account or GUI.
param([Parameter(Mandatory)][string]$JavaHome, [Parameter(Mandatory)][string]$Scratch)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'release-tools.ps1')
if (Test-Path -LiteralPath $Scratch) { throw 'Use a fresh scratch directory.' }
[void](New-Item -ItemType Directory -Path $Scratch)
$hashFixture = Join-Path $Scratch 'hash-fixture'
[IO.File]::WriteAllBytes($hashFixture,[byte[]]@())
if ((Get-AndroidReleaseSha256 $hashFixture) -ne 'E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855') { throw 'Empty-file SHA256 mismatch.' }
[IO.File]::WriteAllBytes($hashFixture,[Text.Encoding]::ASCII.GetBytes('abc'))
if ((Get-AndroidReleaseSha256 $hashFixture) -ne 'BA7816BF8F01CFEA414140DE5DAE2223B00361A396177A9CB410FF61F20015AD') { throw 'SHA256 test-vector mismatch.' }
$keytool = Join-Path $JavaHome 'bin\keytool.exe'
Add-Type -AssemblyName System.IO.Compression.FileSystem
Add-Type -AssemblyName System.IO.Compression
function New-SyntheticNativePackage($Name, $Abis=@('arm64-v8a','x86_64'), $Alignment=16384, $MissingRuntime=$false, $WrongMachine=$false, $Truncated=$false) {
    $path=Join-Path $Scratch ($Name+'.apk')
    $zip=[IO.Compression.ZipFile]::Open($path,[IO.Compression.ZipArchiveMode]::Create)
    try {
        foreach($abi in $Abis) {
            $bytes=[byte[]]::new(120)
            [Array]::Copy([byte[]]@(127,69,76,70,2,1),0,$bytes,0,6)
            [Array]::Copy([BitConverter]::GetBytes([uint16]3),0,$bytes,16,2)
            $machine=if($abi -eq 'arm64-v8a' -and -not $WrongMachine){183}else{62}
            [Array]::Copy([BitConverter]::GetBytes([uint16]$machine),0,$bytes,18,2)
            [Array]::Copy([BitConverter]::GetBytes([uint64]64),0,$bytes,32,8)
            [Array]::Copy([BitConverter]::GetBytes([uint16]56),0,$bytes,54,2)
            [Array]::Copy([BitConverter]::GetBytes([uint16]1),0,$bytes,56,2)
            [Array]::Copy([BitConverter]::GetBytes([uint32]1),0,$bytes,64,4)
            [Array]::Copy([BitConverter]::GetBytes([uint64]$Alignment),0,$bytes,112,8)
            $filename=if($MissingRuntime){'libother.so'}else{'librestic.so'}
            $stream=$zip.CreateEntry("lib/$abi/$filename").Open()
            try { $length=if($Truncated){80}else{$bytes.Length}; $stream.Write($bytes,0,$length) } finally {$stream.Dispose()}
        }
    } finally {$zip.Dispose()}
    return $path
}
$native=Get-AndroidNativeInventory (New-SyntheticNativePackage 'native-valid')
if($native.Libraries -ne 2 -or -not $native.ResticForEveryABI){throw 'Valid synthetic native package failed.'}
foreach($case in @(
    @{Name='native-32bit';Options=@{Abis=@('arm64-v8a','x86_64','armeabi-v7a')};Error='Unsupported packaged native ABI'},
    @{Name='native-missing-runtime';Options=@{MissingRuntime=$true};Error='must include the bundled restic'},
    @{Name='native-small-pages';Options=@{Alignment=4096};Error='not 16 KB aligned'},
    @{Name='native-machine';Options=@{WrongMachine=$true};Error='machine/ABI mismatch'},
    @{Name='native-truncated';Options=@{Truncated=$true};Error='Truncated ELF program headers'}
)) {
    $options=$case.Options
    $fixture=New-SyntheticNativePackage $case.Name @options
    $rejected=$false
    try {[void](Get-AndroidNativeInventory $fixture)} catch {if($_.Exception.Message -notlike "*$($case.Error)*"){throw};$rejected=$true}
    if(-not $rejected){throw "Bad native fixture accepted: $($case.Name)"}
}
$keystore = Join-Path $Scratch 'synthetic keystore.p12'
$syntheticPassword = 'Synthetic !+@#$%^&()-_123456789'
$result = Invoke-AndroidReleaseTool $keytool @('-genkeypair','-keystore',$keystore,'-alias','synthetic','-keyalg','RSA','-keysize','2048',
    '-validity','1','-dname','CN=Synthetic release test','-storepass:env','SAIPH_RELEASE_TOOL_PASSWORD','-keypass:env','SAIPH_RELEASE_TOOL_PASSWORD') @{SAIPH_RELEASE_TOOL_PASSWORD=$syntheticPassword}
if ($result.ExitCode) { throw 'Synthetic key generation failed.' }
$fingerprint = Get-AndroidSigningFingerprint $keytool $keystore 'synthetic' $syntheticPassword
if ($fingerprint -notmatch '^[A-F0-9]{2}(:[A-F0-9]{2}){31}$') { throw 'Unexpected certificate fingerprint shape.' }
$rejected = $false
try { [void](Get-AndroidSigningFingerprint $keytool $keystore 'synthetic' 'Synthetic-wrong-password') }
catch { $rejected = $true; if ($_.Exception.Message -match 'Synthetic-wrong-password') { throw 'Password leaked into an error.' } }
if (-not $rejected) { throw 'Wrong password was accepted.' }
if ([Environment]::GetEnvironmentVariable('SAIPH_RELEASE_TOOL_PASSWORD','Process')) { throw 'Password environment leaked to parent.' }

$jar = Join-Path $Scratch 'synthetic.jar'
$result = Invoke-AndroidReleaseTool (Join-Path $JavaHome 'bin\jar.exe') @('--create','--file',$jar,'-C',$Scratch,'hash-fixture')
if ($result.ExitCode) { throw 'Synthetic JAR creation failed.' }
$result = Invoke-AndroidReleaseTool (Join-Path $JavaHome 'bin\jarsigner.exe') @('-J-Duser.language=en','-keystore',$keystore,
    '-storepass:env','SAIPH_RELEASE_TOOL_PASSWORD','-keypass:env','SAIPH_RELEASE_TOOL_PASSWORD',$jar,'synthetic') @{SAIPH_RELEASE_TOOL_PASSWORD=$syntheticPassword}
if ($result.ExitCode) { throw 'Synthetic JAR signing failed.' }
$result = Invoke-AndroidReleaseTool (Join-Path $JavaHome 'bin\jarsigner.exe') @('-J-Duser.language=en','-verify','-strict',$jar)
if ($result.ExitCode -notin @(0,4) -or ($result.Out+$result.Err) -notmatch 'jar verified') { throw 'Self-signed Android-style JAR verification failed.' }
[IO.File]::WriteAllText((Join-Path $Scratch 'unsigned-entry'),'synthetic unsigned payload')
$result = Invoke-AndroidReleaseTool (Join-Path $JavaHome 'bin\jar.exe') @('--update','--file',$jar,'-C',$Scratch,'unsigned-entry')
if ($result.ExitCode) { throw 'Synthetic unsigned-entry insertion failed.' }
$result = Invoke-AndroidReleaseTool (Join-Path $JavaHome 'bin\jarsigner.exe') @('-J-Duser.language=en','-verify','-strict',$jar)
if ($result.ExitCode -in @(0,4) -or -not ($result.ExitCode -band 16)) { throw 'Strict verification accepted an unsigned JAR entry.' }

$source = Join-Path $Scratch 'public-defaults.json'
$destination = Join-Path $Scratch 'assets\hosted-defaults.json'
$defaults = @{service_url='https://cloud.example.test';issuer='https://synthetic.us.auth0.com/';audience='https://aud.example.test';android_client_id='synthetic_android';desktop_client_id='synthetic_desktop'}
$defaults | ConvertTo-Json | Set-Content -LiteralPath $source -Encoding UTF8
if (-not (Install-AndroidReleaseDefaults $source $destination)) { throw 'Fresh public asset was not placed.' }
if (Install-AndroidReleaseDefaults $source $destination) { throw 'Existing public asset was not preserved.' }
$originalHash = Get-AndroidReleaseSha256 $destination
$defaults.android_client_id = 'different_synthetic_android'
$defaults | ConvertTo-Json | Set-Content -LiteralPath $source -Encoding UTF8
$rejected = $false
try { [void](Install-AndroidReleaseDefaults $source $destination) } catch { $rejected = $true }
if (-not $rejected -or (Get-AndroidReleaseSha256 $destination) -ne $originalHash) { throw 'Conflicting public asset was replaced.' }
$defaults['private_setting'] = 'synthetic-private-value'
$defaults | ConvertTo-Json | Set-Content -LiteralPath $source -Encoding UTF8
$rejected = $false
try { [void](Install-AndroidReleaseDefaults $source (Join-Path $Scratch 'rejected\hosted-defaults.json')) } catch { $rejected = $true }
if (-not $rejected -or (Test-Path -LiteralPath (Join-Path $Scratch 'rejected'))) { throw 'Extra private field was copied.' }
Write-Output 'PASS: native ABI/runtime/ELF gates; .NET SHA256 known vectors; real keytool environment-only passwords; wrong-password rejection; fingerprint; parent environment isolation; strict JAR entry coverage; public-field whitelist and existing-asset preservation.'
