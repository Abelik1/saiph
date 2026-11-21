# SPDX-License-Identifier: GPL-3.0-only
# Local release helpers. Passwords never appear in command-line arguments or files.
function Get-AndroidReleaseSha256([string]$Path) {
    # Get-FileHash may be absent in a standalone Windows PowerShell host whose
    # module path was inherited from PowerShell 7. Use the built-in .NET API.
    $stream = [IO.File]::OpenRead($Path)
    $digest = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($digest.ComputeHash($stream))).Replace('-','') }
    finally { $stream.Dispose(); $digest.Dispose() }
}

function Get-AndroidNativeInventory([string]$Path) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $expected = @('arm64-v8a','x86_64')
    $zip = [IO.Compression.ZipFile]::OpenRead($Path)
    try {
        $entries = @($zip.Entries | Where-Object { $_.FullName -match '(^|/)lib/[^/]+/[^/]+\.so$' })
        $runtimes = @(); $abis = @()
        foreach ($entry in $entries) {
            $abi = ($entry.FullName -split '/')[-2]
            if ($abi -notin $expected) { throw "Unsupported packaged native ABI: $abi" }
            $abis += $abi
            if ($entry.Name -eq 'librestic.so') { $runtimes += $abi }
            $reader = [IO.BinaryReader]::new($entry.Open())
            try {
                $header = $reader.ReadBytes(64)
                if ($header.Length -ne 64 -or [BitConverter]::ToString($header,0,6) -ne '7F-45-4C-46-02-01' -or
                    [BitConverter]::ToUInt16($header,16) -ne 3) { throw "Expected a little-endian ELF64 DYN binary: $($entry.FullName)" }
                $machine = if ($abi -eq 'arm64-v8a') { 183 } else { 62 }
                if ([BitConverter]::ToUInt16($header,18) -ne $machine) { throw "Native machine/ABI mismatch: $($entry.FullName)" }
                $offset = [BitConverter]::ToUInt64($header,32)
                $size = [BitConverter]::ToUInt16($header,54)
                $count = [BitConverter]::ToUInt16($header,56)
                if ($offset -lt 64 -or $offset -gt 1048576 -or $size -ne 56 -or $count -lt 1 -or $count -gt 128) { throw "Invalid ELF program headers: $($entry.FullName)" }
                if ($reader.ReadBytes([int]$offset-64).Length -ne ($offset-64)) { throw 'Truncated ELF header padding.' }
                $programs = $reader.ReadBytes($size*$count)
                if ($programs.Length -ne ($size*$count)) { throw 'Truncated ELF program headers.' }
                $loads = 0
                for ($index=0; $index -lt $count; $index++) {
                    $start = $index*$size
                    if ([BitConverter]::ToUInt32($programs,$start) -ne 1) { continue }
                    $loads++
                    $alignment = [BitConverter]::ToUInt64($programs,$start+48)
                    $fileOffset = [BitConverter]::ToUInt64($programs,$start+8)
                    $address = [BitConverter]::ToUInt64($programs,$start+16)
                    if ($alignment -lt 16384 -or ($alignment -band ($alignment-1)) -ne 0 -or
                        ($fileOffset % $alignment) -ne ($address % $alignment)) { throw "Native LOAD segment is not 16 KB aligned: $($entry.FullName)" }
                }
                if (-not $loads) { throw "Native binary has no LOAD segments: $($entry.FullName)" }
            } finally { $reader.Dispose() }
        }
        $actual = @($abis | Sort-Object -Unique)
        if (($actual -join ',') -ne ($expected -join ',') -or
            (@($runtimes | Sort-Object -Unique) -join ',') -ne ($expected -join ',')) { throw 'Both supported ABIs must include the bundled restic runtime.' }
        [pscustomobject]@{ABIs=$actual;Libraries=$entries.Count;ElfLoadAlignment='at least 16 KB';ResticForEveryABI=$true}
    } finally { $zip.Dispose() }
}

function Invoke-AndroidReleaseTool([string]$File, [string[]]$Arguments, [hashtable]$Environment = @{}) {
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $File
    $start.Arguments = ($Arguments | ForEach-Object {
        if ($_ -match '["\r\n]') { throw 'Unexpected release-tool argument.' }
        '"' + ($_ -replace '(\\+)$', '$1$1') + '"'
    }) -join ' '
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    foreach ($name in $Environment.Keys) { $start.EnvironmentVariables[$name] = [string]$Environment[$name] }
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $start
    try {
        [void]$process.Start()
        foreach ($name in $Environment.Keys) { $start.EnvironmentVariables.Remove($name) }
        $process.StandardInput.Close()
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        [pscustomobject]@{ExitCode=$process.ExitCode;Out=$stdout.GetAwaiter().GetResult();Err=$stderr.GetAwaiter().GetResult()}
    } finally {
        foreach ($name in $Environment.Keys) { $start.EnvironmentVariables.Remove($name) }
        $process.Dispose()
    }
}

function Get-AndroidSigningFingerprint([string]$Keytool, [string]$Keystore, [string]$Alias, [string]$Password) {
    $result = Invoke-AndroidReleaseTool $Keytool @('-J-Duser.language=en','-list','-v','-keystore',$Keystore,'-alias',$Alias,
        '-storepass:env','SAIPH_RELEASE_TOOL_PASSWORD') @{SAIPH_RELEASE_TOOL_PASSWORD=$Password}
    if ($result.ExitCode) { throw 'Cannot unlock the signing key. Check the password and alias; no key was changed.' }
    $fingerprint = [regex]::Match($result.Out + $result.Err, 'SHA256:\s*([0-9A-Fa-f:]{95})')
    if (-not $fingerprint.Success) { throw 'The keystore did not return a SHA-256 certificate fingerprint.' }
    return $fingerprint.Groups[1].Value.ToUpperInvariant()
}

function Read-AndroidReleasePassword([string]$Prompt, [bool]$Dialog = $false) {
    if (-not $Dialog) {
        $secure = Read-Host $Prompt -AsSecureString
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer); $secure.Dispose() }
    }
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $form = [Windows.Forms.Form]::new()
    $form.Text = 'Saiph Android release - unlock existing key'
    $form.ClientSize = [Drawing.Size]::new(540,190)
    $form.StartPosition = 'CenterScreen'
    $form.TopMost = $true
    $form.FormBorderStyle = 'FixedDialog'
    $form.MaximizeBox = $false; $form.MinimizeBox = $false
    $form.Font = [Drawing.Font]::new('Segoe UI',10)
    $label = [Windows.Forms.Label]::new(); $label.Text = $Prompt + ".`r`nEnter the password you saved when creating this key."; $label.SetBounds(20,15,500,48); $form.Controls.Add($label)
    $passwordBox = [Windows.Forms.TextBox]::new(); $passwordBox.UseSystemPasswordChar = $true; $passwordBox.SetBounds(20,76,500,28); $form.Controls.Add($passwordBox)
    $ok = [Windows.Forms.Button]::new(); $ok.Text = 'Unlock and build'; $ok.SetBounds(245,133,155,36); $form.Controls.Add($ok)
    $cancel = [Windows.Forms.Button]::new(); $cancel.Text = 'Cancel'; $cancel.SetBounds(410,133,110,36); $cancel.DialogResult = 'Cancel'; $form.Controls.Add($cancel)
    $form.AcceptButton = $ok; $form.CancelButton = $cancel
    $form.Add_Shown({ $form.Activate(); $passwordBox.Focus() })
    $ok.Add_Click({ if ($passwordBox.Text.Length -gt 0) { $form.DialogResult = 'OK'; $form.Close() } })
    try {
        if ($form.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) { throw 'Release cancelled; existing keys are unchanged.' }
        return $passwordBox.Text
    } finally { $passwordBox.Clear(); $form.Dispose() }
}

function Install-AndroidReleaseDefaults([string]$Source, [string]$Destination) {
    if (-not $Source) {
        if (-not (Test-Path -LiteralPath $Destination)) { throw 'Supply -HostedConfiguration with the five public Hosted fields.' }
        $Source = $Destination
    }
    $info = Get-Item -LiteralPath $Source
    if ($info.Length -gt 4096) { throw 'Public Hosted defaults exceed 4096 bytes.' }
    $defaults = Get-Content -LiteralPath $Source -Raw | ConvertFrom-Json
    if ((@($defaults.PSObject.Properties.Name | Sort-Object) -join ',') -ne 'android_client_id,audience,desktop_client_id,issuer,service_url') { throw 'Hosted defaults accept only the five public fields.' }
    foreach ($property in $defaults.PSObject.Properties) { if ($property.Value -isnot [string] -or $property.Value -match '[\x00-\x20\\]') { throw 'Public Hosted fields must be nonempty strings without whitespace or backslashes.' } }
    foreach ($name in @('service_url','issuer','audience')) {
        $uri = [uri]$defaults.$name
        if (-not $uri.IsAbsoluteUri -or $uri.Scheme -ne 'https' -or $uri.UserInfo -or $uri.Query -or $uri.Fragment -or -not $uri.IsDefaultPort) { throw 'Hosted defaults require fixed HTTPS addresses.' }
    }
    $origin = [uri]$defaults.service_url
    if ($origin.AbsolutePath -ne '/' -or $defaults.issuer -notmatch '^https://[a-z0-9.-]+\.auth0\.com/$' -or
        $defaults.android_client_id -notmatch '^[A-Za-z0-9_-]{8,128}$' -or $defaults.desktop_client_id -notmatch '^[A-Za-z0-9_-]{8,128}$' -or
        $defaults.android_client_id -eq $defaults.desktop_client_id) { throw 'Invalid public Hosted sign-in fields.' }
    if (Test-Path -LiteralPath $Destination) {
        if ((Get-AndroidReleaseSha256 $Source) -ne (Get-AndroidReleaseSha256 $Destination)) { throw 'An existing Hosted asset differs; it was preserved.' }
        return $false
    }
    [void](New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination))
    Copy-Item -LiteralPath $Source -Destination $Destination
    return $true
}
