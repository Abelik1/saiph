// SPDX-License-Identifier: AGPL-3.0-or-later
// Native per-user preview installer. Uses the .NET Framework shipped on Windows.
// No administrator elevation, credential inputs, network downloads or shell scripts.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Threading;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Win32;

public sealed class FileItem { public string path; public long bytes; public string sha256; }
public sealed class Package { public string format; public int schema; public string version; public string platform; public string profile; public long build; public string entrypoint; public string release_state; public string license_inventory; public FileItem[] files; }
public sealed class Installation { public string format = "orion-desktop-install"; public int schema = 1; public string root; public string current; public bool isolated; public bool removed; public List<string> versions = new List<string>(); }

public static class Setup {
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 32 * 1024 * 1024 };
    static readonly Regex Version = new Regex(@"^[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?$");
    static readonly Regex Hash = new Regex("^[a-f0-9]{64}$");
    const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
    const string UninstallKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\OrionMini";
    const string EnrollmentExtension = @"Software\Classes\.orion-enrollment";
    const string EnrollmentClass = @"Software\Classes\Orion.Enrollment";
    static bool silent, isolated, uninstall, noStartup, noLaunch;
    static string destination;
    static Label status;
    static string phase = "arguments";

    [STAThread] public static int Main(string[] arguments) {
        try {
            for (int i = 0; i < arguments.Length; i++) {
                switch (arguments[i]) {
                    case "--silent": silent = true; break;
                    case "--isolated": isolated = true; break;
                    case "--uninstall": uninstall = true; break;
                    case "--no-startup": noStartup = true; break;
                    case "--no-launch": noLaunch = true; break;
                    case "--destination": destination = arguments[++i]; break;
                    default: throw new InvalidDataException();
                }
            }
            if (destination == null) destination = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "OrionMini");
            destination = Path.GetFullPath(destination).TrimEnd(Path.DirectorySeparatorChar);
            if (!isolated && destination != Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "OrionMini"))
                throw new InvalidDataException(); // Arbitrary paths are accepted only in explicit no-integration test mode.
            if (silent) { Perform(); return 0; }
            Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
            var window = new Form { Text = "Saiph", ClientSize = new Size(570, 285), StartPosition = FormStartPosition.CenterScreen,
                                    FormBorderStyle = FormBorderStyle.FixedDialog, MaximizeBox = false, Font = new Font("Segoe UI", 10) };
            window.Controls.Add(new Label { Left = 28, Top = 24, Width = 500, Height = 34, Text = uninstall ? "Remove Saiph" : "Install Saiph", Font = new Font("Segoe UI", 19) });
            window.Controls.Add(new Label { Left = 30, Top = 78, Width = 505, Height = 70,
                Text = uninstall ? "Saiph's files will be removed. Your settings, paired device keys, notes and Cloud files will be retained."
                                 : "Saiph installs for your Windows account. Your existing settings and device pairing are preserved. Supporting components are guided in Saiph setup." });
            status = new Label { Left = 30, Top = 155, Width = 505, Height = 55, Text = "Internal preview · publisher signing and clean-device acceptance pending." };
            var action = new Button { Left = 355, Top = 225, Width = 180, Height = 36, Text = uninstall ? "Remove Saiph" : "Install Saiph" };
            action.Click += delegate {
                if (action.Text == "Close") { window.Close(); return; }
                action.Enabled = false;
                try { Perform(); status.Text = uninstall ? "Saiph removed. Your data is retained." : "Saiph is installed. Open it from the Start menu."; action.Text = "Close"; action.Enabled = true; }
                catch { status.Text = "The installation could not finish. Your existing release and data were retained."; action.Enabled = true; }
            };
            window.Controls.Add(action); Application.Run(window); return 0;
        } catch (Exception failure) { Console.Error.WriteLine("Saiph installer failed: " + phase + "; " + failure.GetType().Name + "; " + failure.HResult); if (!silent) MessageBox.Show("Saiph could not complete installation. No user data was removed.", "Saiph"); return 1; }
    }

    static void Progress(string message) { if (status != null) { status.Text = message; Application.DoEvents(); } }
    static string LockName() {
        using (var hash = SHA256.Create()) {
            string key = WindowsIdentity.GetCurrent().User.Value + "\n" + destination.ToUpperInvariant();
            return @"Global\OrionSetup-" + BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(key))).Replace("-", "");
        }
    }
    static void Perform() {
        phase = "installation-lock";
        using (var mutex = new Mutex(false, LockName())) {
            bool acquired = false;
            try {
                try { acquired = mutex.WaitOne(0); }
                catch (AbandonedMutexException) { acquired = true; }
                if (!acquired) throw new IOException("Another Saiph installation is running.");
                if (uninstall) Remove(); else Install();
            } finally { if (acquired) mutex.ReleaseMutex(); }
        }
    }
    static void RetryOwnedRename(Action operation) {
        for (int attempt = 0; ; attempt++) {
            try { operation(); return; }
            catch (IOException) { if (attempt >= 39) throw; System.Threading.Thread.Sleep(100); }
        }
    }
    static string Under(string root, string relative) {
        if (String.IsNullOrEmpty(relative) || relative.Contains('\\') || relative.Contains(':') || relative.Contains('\n') || relative.Contains('\r') || relative.Contains('\0') || relative.StartsWith("/") || relative.Split('/').Any(p => p == "" || p == "." || p == "..")) throw new InvalidDataException();
        string full = Path.GetFullPath(Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar)));
        if (!full.StartsWith(Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException();
        CheckParents(full, root); return full;
    }
    static void CheckParents(string path, string root) {
        var directory = new DirectoryInfo(Directory.Exists(path) ? path : Path.GetDirectoryName(path));
        while (directory != null) {
            if (directory.Exists && (directory.Attributes & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException();
            directory = directory.Parent;
        }
        if (File.Exists(path) && (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException();
    }
    // Authenticode appends the certificate table after the payload trailer. The
    // builder 8-byte aligns the unsigned file so signing adds no padding; the
    // table must end the file exactly, otherwise the file is rejected.
    static long PayloadEnd(FileStream file) {
        var header = new byte[4096];
        file.Seek(0, SeekOrigin.Begin);
        int read = file.Read(header, 0, header.Length);
        if (read < 0x40 || header[0] != 'M' || header[1] != 'Z') throw new InvalidDataException();
        int pe = BitConverter.ToInt32(header, 0x3C);
        if (pe < 0x40 || pe + 24 + 2 > read || BitConverter.ToUInt32(header, pe) != 0x00004550) throw new InvalidDataException();
        int optional = pe + 24, magic = BitConverter.ToUInt16(header, optional);
        int directories = optional + (magic == 0x20b ? 112 : magic == 0x10b ? 96 : -1);
        if (directories < optional || directories + 5 * 8 > read) throw new InvalidDataException();
        long tableOffset = BitConverter.ToUInt32(header, directories + 4 * 8), tableSize = BitConverter.ToUInt32(header, directories + 4 * 8 + 4);
        if (tableSize == 0) return file.Length;
        if (tableOffset <= 0 || tableOffset + tableSize != file.Length) throw new InvalidDataException();
        return tableOffset;
    }
    static string SHA(string path) { using (var hash = SHA256.Create()) using (var input = File.OpenRead(path)) return BitConverter.ToString(hash.ComputeHash(input)).Replace("-", "").ToLowerInvariant(); }
    static string Marker { get { return Path.Combine(destination, "orion-install.json"); } }
    static Installation Existing() {
        if (!Directory.Exists(destination)) return null;
        CheckParents(destination, destination);
        if (!File.Exists(Marker)) { if (Directory.EnumerateFileSystemEntries(destination).Any()) throw new InvalidDataException(); return null; }
        var installation = Json.Deserialize<Installation>(File.ReadAllText(Marker));
        if (installation.format != "orion-desktop-install" || installation.schema != 1 || installation.root != destination || installation.isolated != isolated || !Version.IsMatch(installation.current) || installation.versions.Any(v => !Version.IsMatch(v))) throw new InvalidDataException();
        return installation;
    }

    static void Install() {
        phase = "existing-install";
        Installation old = Existing();
        var integration = OwnedExecutables(old);
        if (!isolated) { phase = "integration-preflight"; PreflightIntegration(integration); }
        string source = Assembly.GetExecutingAssembly().Location;
        long payloadLength, offset;
        using (var file = File.OpenRead(source)) {
            phase = "payload";
            long end = PayloadEnd(file);
            if (end < 16) throw new InvalidDataException();
            file.Seek(end - 16, SeekOrigin.Begin); byte[] tail = new byte[16]; if (file.Read(tail, 0, tail.Length) != 16) throw new InvalidDataException();
            if (Encoding.ASCII.GetString(tail, 8, 8) != "ORIONZIP") throw new InvalidDataException();
            payloadLength = BitConverter.ToInt64(tail, 0); offset = end - 16 - payloadLength;
            if (payloadLength <= 0 || offset <= 0) throw new InvalidDataException();
        }
        Directory.CreateDirectory(destination);
        string stage = Path.Combine(destination, "staging-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(stage);
        bool activated = false;
        try {
            Package manifest;
            using (var file = File.OpenRead(source)) using (var slice = new Slice(file, offset, payloadLength)) using (var zip = new ZipArchive(slice, ZipArchiveMode.Read)) {
                phase = "manifest";
                foreach (var entry in zip.Entries) Under(stage, entry.FullName); // Validate every path before any extraction.
                var member = zip.GetEntry("package-manifest.json"); if (member == null || member.Length > 32 * 1024 * 1024) throw new InvalidDataException();
                using (var input = new StreamReader(member.Open())) manifest = Json.Deserialize<Package>(input.ReadToEnd());
                if (manifest.format != "orion-desktop-package" || manifest.schema != 1 || manifest.platform != "windows-x86_64" || !Version.IsMatch(manifest.version) || manifest.entrypoint != "app/OrionMini.exe" || manifest.files == null || manifest.files.Length > 30000) throw new InvalidDataException();
                var known = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "package-manifest.json" };
                long bytes = 0;
                foreach (var item in manifest.files) {
                    Under(stage, item.path); if (!known.Add(item.path) || !Hash.IsMatch(item.sha256) || item.bytes < 0) throw new InvalidDataException();
                    bytes = checked(bytes + item.bytes);
                }
                if (bytes > 16L * 1024 * 1024 * 1024 || zip.Entries.Count != known.Count || zip.Entries.Any(e => !known.Contains(e.FullName))) throw new InvalidDataException();
                var drive = new DriveInfo(Path.GetPathRoot(destination)); if (drive.AvailableFreeSpace < bytes + 256L * 1024 * 1024) throw new IOException();
                int number = 0;
                phase = "extract-and-hash";
                foreach (var item in manifest.files) {
                    var entry = zip.GetEntry(item.path); if (entry == null || entry.Length != item.bytes) throw new InvalidDataException();
                    string target = Under(stage, item.path); Directory.CreateDirectory(Path.GetDirectoryName(target));
                    using (var input = entry.Open()) using (var output = File.Create(target)) input.CopyTo(output);
                    if (SHA(target) != item.sha256) throw new InvalidDataException();
                    if (++number % 80 == 0) Progress("Installing Saiph · " + number + " of " + manifest.files.Length + " files");
                }
                File.WriteAllText(Path.Combine(stage, "package-manifest.json"), Json.Serialize(manifest));
            }
            string release = Under(destination, "releases/" + manifest.version);
            phase = "release-activation";
            if (Directory.Exists(release)) throw new IOException(); // Never overwrite loaded DLLs or an existing release.
            Directory.CreateDirectory(Path.GetDirectoryName(release)); RetryOwnedRename(() => Directory.Move(stage, release));
            var next = old == null ? new Installation { root = destination, isolated = isolated } : Json.Deserialize<Installation>(Json.Serialize(old));
            next.current = manifest.version; if (!next.versions.Contains(manifest.version)) next.versions.Add(manifest.version);
            next.removed = false;
            // Prepare the small uninstaller before changing startup/menu/current release.
            phase = "uninstall-staging";
            using (var input = File.OpenRead(source)) using (var output = File.Create(Path.Combine(destination, "Uninstall.exe.new"))) {
                byte[] buffer = new byte[65536]; long left = offset; while (left > 0) { int count = input.Read(buffer, 0, (int)Math.Min(left, buffer.Length)); if (count == 0) throw new EndOfStreamException(); output.Write(buffer, 0, count); left -= count; }
            }
            // Integration follows complete extraction. The current marker is the final commit point.
            if (!isolated) {
                integration.Add(Path.Combine(release, "app", "OrionMini.exe"));
                Integrate(release, old == null, integration);
            }
            phase = "current-marker";
            string temporary = Marker + ".new"; File.WriteAllText(temporary, Json.Serialize(next));
            RetryOwnedRename(() => { if (File.Exists(Marker)) File.Replace(temporary, Marker, Marker + ".previous"); else File.Move(temporary, Marker); });
            activated = true;
            string uninstallFile = Path.Combine(destination, "Uninstall.exe");
            phase = "uninstall-activation";
            RetryOwnedRename(() => { if (File.Exists(uninstallFile)) File.Replace(uninstallFile + ".new", uninstallFile, null); else File.Move(uninstallFile + ".new", uninstallFile); });
            if (!isolated && !noLaunch) Process.Start(new ProcessStartInfo(Under(release, manifest.entrypoint)) { WorkingDirectory = Path.Combine(release, "app"), UseShellExecute = true });
        } catch {
            if (!activated && !isolated && old != null && !old.removed) {
                // Restore shortcuts/launch target to the previous complete release.
                // The data root and previous release were never overwritten.
                Integrate(Under(destination, "releases/" + old.current), false, integration);
            }
            throw;
        } finally {
            // Only the random staging directory created by this invocation is removable.
            if (Directory.Exists(stage)) { CheckParents(stage, destination); Directory.Delete(stage, true); }
            if (!activated) Progress("Installation was not activated. Existing Saiph data and release remain available.");
        }
    }

    static List<string> OwnedExecutables(Installation installation) {
        var targets = new List<string>();
        if (installation == null) return targets;
        foreach (string version in installation.versions) {
            string release = Under(destination, "releases/" + version);
            string path = Under(release, "package-manifest.json");
            if (!File.Exists(path)) throw new InvalidDataException();
            var manifest = Json.Deserialize<Package>(File.ReadAllText(path));
            if (manifest.format != "orion-desktop-package" || manifest.schema != 1 || manifest.version != version || manifest.platform != "windows-x86_64" || manifest.entrypoint != "app/OrionMini.exe" || manifest.files == null) throw new InvalidDataException();
            var executable = manifest.files.SingleOrDefault(item => item.path == manifest.entrypoint);
            string target = Under(release, manifest.entrypoint);
            // Removed or locally changed releases confer no ownership of external entries.
            if (executable != null && Hash.IsMatch(executable.sha256) && File.Exists(target) && new FileInfo(target).Length == executable.bytes && SHA(target) == executable.sha256) targets.Add(target);
        }
        return targets;
    }
    static Dictionary<string, object> ReadTree(string path) {
        using (var key = Registry.CurrentUser.OpenSubKey(path)) {
            if (key == null) return null;
            var values = new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase);
            ReadTree(key, "", values); return values;
        }
    }
    static Dictionary<string, object> TryReadTree(string path) {
        try { return ReadTree(path); } catch { return null; }
    }
    static void ReadTree(RegistryKey key, string path, Dictionary<string, object> values) {
        if (values.Count > 100 || path.Length > 200) throw new InvalidDataException();
        values.Add(path + "/", true);
        foreach (string name in key.GetValueNames()) values.Add(path + ":" + name, key.GetValue(name, null, RegistryValueOptions.DoNotExpandEnvironmentNames));
        foreach (string name in key.GetSubKeyNames()) using (var child = key.OpenSubKey(name)) ReadTree(child, path + "/" + name, values);
    }
    static string MenuShortcut { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), "Saiph", "Saiph.lnk"); } }
    static string LegacyMenuShortcut { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), "Orion", "Orion.lnk"); } }
    static bool OwnShortcut(string path, List<string> targets) {
        try { CheckParents(path, destination); return File.Exists(path) && Shortcut.Owned(path, targets); }
        catch { return false; }
    }
    static void PreflightIntegration(List<string> targets) {
        CheckParents(MenuShortcut, destination);
        if (Directory.Exists(MenuShortcut) || (File.Exists(MenuShortcut) && !OwnShortcut(MenuShortcut, targets))) throw new InvalidDataException();
        using (var key = Registry.CurrentUser.OpenSubKey(RunKey)) {
            object value = key == null ? null : key.GetValue("OrionMini", null, RegistryValueOptions.DoNotExpandEnvironmentNames);
            if (value != null && !IntegrationPolicy.OwnRun(value, targets)) throw new InvalidDataException();
        }
        var uninstallValues = ReadTree(UninstallKey);
        if (uninstallValues != null && !IntegrationPolicy.OwnUninstall(uninstallValues, destination)) throw new InvalidDataException();
        var extension = ReadTree(EnrollmentExtension);
        var command = ReadTree(EnrollmentClass);
        // A bare extension owned by another application is never overwritten.
        if (extension != null && (command == null || !IntegrationPolicy.Matches(extension, IntegrationPolicy.Extension()))) throw new InvalidDataException();
        if (command != null && !targets.Any(exe => IntegrationPolicy.Matches(command, IntegrationPolicy.Enrollment(exe)))) throw new InvalidDataException();
    }
    static void Integrate(string release, bool first, List<string> targets) {
        // Check again immediately before integration, including on rollback.
        PreflightIntegration(targets);
        string exe = Path.Combine(release, "app", "OrionMini.exe"); string icon = Path.Combine(release, "app", "_internal", "assets", "orion-mini-icon.ico");
        string menu = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), "Saiph"); Directory.CreateDirectory(menu);
        Shortcut.Create(MenuShortcut, exe, icon, "OrionMini.Desktop");
        // Only remove the old label when its target proves installer ownership.
        if (OwnShortcut(LegacyMenuShortcut, targets)) File.Delete(LegacyMenuShortcut);
        using (var key = Registry.CurrentUser.CreateSubKey(RunKey)) {
            // Existing opt-out is retained on upgrade. The app's own setting remains authoritative.
            if (!noStartup && (first || key.GetValue("OrionMini") != null)) key.SetValue("OrionMini", "\"" + exe + "\"");
        }
        using (var key = Registry.CurrentUser.CreateSubKey(UninstallKey)) {
            key.SetValue("DisplayName", "Saiph"); key.SetValue("InstallLocation", destination); key.SetValue("Publisher", "Saiph local preview");
            key.SetValue("UninstallString", "\"" + Path.Combine(destination, "Uninstall.exe") + "\" --uninstall --no-launch");
            key.SetValue("NoModify", 1); key.SetValue("NoRepair", 1);
        }
        using (var extension = Registry.CurrentUser.CreateSubKey(EnrollmentExtension)) extension.SetValue("", "Orion.Enrollment");
        using (var command = Registry.CurrentUser.CreateSubKey(EnrollmentClass + @"\shell\open\command")) command.SetValue("", "\"" + exe + "\" --enrollment \"%1\"");
    }

    static void Remove() {
        phase = "uninstall";
        var installation = Existing(); if (installation == null) throw new InvalidDataException();
        var targets = OwnedExecutables(installation);
        var retained = new List<string>();
        foreach (string version in installation.versions) {
            string release = Under(destination, "releases/" + version);
            string manifestFile = Under(release, "package-manifest.json"); if (!File.Exists(manifestFile)) throw new InvalidDataException();
            var manifest = Json.Deserialize<Package>(File.ReadAllText(manifestFile));
            if (manifest.format != "orion-desktop-package" || manifest.version != version || manifest.files == null) throw new InvalidDataException();
            // Preflight all paths first; do not recursively remove arbitrary files added by a user.
            foreach (var item in manifest.files) Under(release, item.path);
            var directories = new List<string>();
            var pending = new Stack<string>(); pending.Push(release);
            while (pending.Count > 0) {
                foreach (string child in Directory.GetDirectories(pending.Pop())) {
                    CheckParents(child, release); directories.Add(child); pending.Push(child);
                }
            }
            foreach (var item in manifest.files) { string path = Under(release, item.path); if (File.Exists(path) && SHA(path) == item.sha256) File.Delete(path); }
            bool userFilesRemain = Directory.GetFiles(release, "*", SearchOption.AllDirectories).Any(path => path != manifestFile);
            if (!userFilesRemain) File.Delete(manifestFile);
            foreach (string directory in directories.OrderByDescending(d => d.Length)) { CheckParents(directory, release); if (!Directory.EnumerateFileSystemEntries(directory).Any()) Directory.Delete(directory); }
            if (!Directory.EnumerateFileSystemEntries(release).Any()) Directory.Delete(release);
            else retained.Add(version);
        }
        if (!isolated) {
            if (OwnShortcut(MenuShortcut, targets)) File.Delete(MenuShortcut);
            if (OwnShortcut(LegacyMenuShortcut, targets)) File.Delete(LegacyMenuShortcut);
            using (var key = Registry.CurrentUser.OpenSubKey(RunKey, true)) { object value = key == null ? null : key.GetValue("OrionMini", null, RegistryValueOptions.DoNotExpandEnvironmentNames); if (IntegrationPolicy.OwnRun(value, targets)) key.DeleteValue("OrionMini"); }
            if (IntegrationPolicy.OwnUninstall(TryReadTree(UninstallKey), destination)) Registry.CurrentUser.DeleteSubKeyTree(UninstallKey, false);
            var command = TryReadTree(EnrollmentClass);
            if (targets.Any(exe => IntegrationPolicy.Matches(command, IntegrationPolicy.Enrollment(exe)))) {
                Registry.CurrentUser.DeleteSubKeyTree(EnrollmentClass, false);
                if (IntegrationPolicy.Matches(TryReadTree(EnrollmentExtension), IntegrationPolicy.Extension())) Registry.CurrentUser.DeleteSubKeyTree(EnrollmentExtension, false);
            }
        }
        installation.versions = retained; installation.removed = true;
        File.WriteAllText(Marker, Json.Serialize(installation));
        if (File.Exists(Marker + ".previous")) File.Delete(Marker + ".previous");
        // Uninstall.exe may be the running file. Retain the small stub; never delete outside owned releases.
    }
}

// Pure policy: tests can inject registry snapshots without changing HKCU.
public static class IntegrationPolicy {
    public static bool OwnRun(object value, IEnumerable<string> targets) {
        string command = value as string;
        return command != null && targets.Any(exe => String.Equals(command, "\"" + exe + "\"", StringComparison.OrdinalIgnoreCase));
    }
    public static bool Matches(Dictionary<string, object> actual, Dictionary<string, object> expected) {
        if (actual == null || actual.Count != expected.Count) return false;
        foreach (var entry in expected) {
            object value; if (!actual.TryGetValue(entry.Key, out value)) return false;
            if (entry.Value is string) { if (!(value is string) || !String.Equals((string)value, (string)entry.Value, StringComparison.OrdinalIgnoreCase)) return false; }
            else if (!Object.Equals(value, entry.Value)) return false;
        }
        return true;
    }
    public static bool OwnUninstall(Dictionary<string, object> actual, string root) {
        return Matches(actual, Uninstall(root)) || Matches(actual, Uninstall(root, true));
    }
    public static Dictionary<string, object> Uninstall(string root, bool legacy = false) {
        return new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase) {
            {"/", true}, {":DisplayName", legacy ? "Orion" : "Saiph"}, {":InstallLocation", root}, {":Publisher", legacy ? "Orion local preview" : "Saiph local preview"},
            {":UninstallString", "\"" + Path.Combine(root, "Uninstall.exe") + "\" --uninstall --no-launch"}, {":NoModify", 1}, {":NoRepair", 1}
        };
    }
    public static Dictionary<string, object> Extension() {
        return new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase) {{"/", true}, {":", "Orion.Enrollment"}};
    }
    public static Dictionary<string, object> Enrollment(string exe) {
        return new Dictionary<string, object>(StringComparer.OrdinalIgnoreCase) {
            {"/", true}, {"/shell/", true}, {"/shell/open/", true}, {"/shell/open/command/", true},
            {"/shell/open/command:", "\"" + exe + "\" --enrollment \"%1\""}
        };
    }
}

sealed class Slice : Stream {
    readonly Stream source; readonly long start, length; long position;
    public Slice(Stream source, long start, long length) { this.source = source; this.start = start; this.length = length; }
    public override int Read(byte[] buffer, int offset, int count) { source.Position = start + position; int read = source.Read(buffer, offset, (int)Math.Min(count, length - position)); position += read; return read; }
    public override long Seek(long offset, SeekOrigin origin) { long next = origin == SeekOrigin.Begin ? offset : origin == SeekOrigin.Current ? position + offset : length + offset; if (next < 0 || next > length) throw new IOException(); position = next; return position; }
    public override bool CanRead { get { return true; } } public override bool CanSeek { get { return true; } } public override bool CanWrite { get { return false; } }
    public override long Length { get { return length; } } public override long Position { get { return position; } set { Seek(value, SeekOrigin.Begin); } }
    public override void Flush() {} public override void SetLength(long value) { throw new NotSupportedException(); } public override void Write(byte[] b, int o, int c) { throw new NotSupportedException(); }
}

static class Shortcut {
    [ComImport, Guid("00021401-0000-0000-C000-000000000046")] class ShellLink {}
    [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("000214F9-0000-0000-C000-000000000046")]
    interface Link {
        void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder a, int b, IntPtr c, int d); void GetIDList(out IntPtr a); void SetIDList(IntPtr a);
        void GetDescription(IntPtr a, int b); void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string a);
        void GetWorkingDirectory(IntPtr a, int b); void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string a);
        void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder a, int b); void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string a);
        void GetHotkey(out short a); void SetHotkey(short a); void GetShowCmd(out int a); void SetShowCmd(int a);
        void GetIconLocation(IntPtr a, int b, out int c); void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string a, int b);
        void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string a, int b); void Resolve(IntPtr a, int b);
        void SetPath([MarshalAs(UnmanagedType.LPWStr)] string a);
    }
    [StructLayout(LayoutKind.Sequential)] struct Key { public Guid format; public uint id; }
    [StructLayout(LayoutKind.Explicit, Size=24)] struct Value { [FieldOffset(0)] public ushort type; [FieldOffset(8)] public IntPtr text; }
    [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")]
    interface Store { void GetCount(out uint a); void GetAt(uint a, out Key b); void GetValue(ref Key a, out Value b); void SetValue(ref Key a, ref Value b); void Commit(); }
    public static bool Owned(string path, IEnumerable<string> targets) {
        object item = new ShellLink();
        try {
            ((System.Runtime.InteropServices.ComTypes.IPersistFile)item).Load(path, 0);
            var target = new StringBuilder(32768); var arguments = new StringBuilder(32768);
            ((Link)item).GetPath(target, target.Capacity, IntPtr.Zero, 4); // SLGP_RAWPATH; never resolve or launch.
            ((Link)item).GetArguments(arguments, arguments.Capacity);
            return arguments.Length == 0 && targets.Any(exe => String.Equals(target.ToString(), exe, StringComparison.OrdinalIgnoreCase));
        } finally { Marshal.FinalReleaseComObject(item); }
    }
    public static void Create(string path, string executable, string icon, string identity) {
        object item = new ShellLink();
        try {
            var link = (Link)item; link.SetPath(executable); link.SetWorkingDirectory(Path.GetDirectoryName(executable)); link.SetIconLocation(icon, 0);
            var store = (Store)item; var key = new Key { format = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), id = 5 };
            var value = new Value { type = 31, text = Marshal.StringToCoTaskMemUni(identity) };
            try { store.SetValue(ref key, ref value); store.Commit(); } finally { Marshal.FreeCoTaskMem(value.text); }
            ((System.Runtime.InteropServices.ComTypes.IPersistFile)item).Save(path, true);
        } finally { Marshal.FinalReleaseComObject(item); }
    }
}
