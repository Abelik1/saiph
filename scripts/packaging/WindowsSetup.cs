// SPDX-License-Identifier: AGPL-3.0-or-later
// Native per-user preview installer. Uses the .NET Framework shipped on Windows.
// No administrator elevation, credential inputs, network downloads or shell scripts.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Text;
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
    static bool silent, isolated, uninstall, noStartup, noLaunch, noSendTo;
    // Set only by the options page: an explicit untick also removes the owned integration.
    static bool removeStartup;
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
                    case "--no-send-to": noSendTo = true; break;
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
            if (!uninstall) { RunWizard(); return 0; }
            RunRemoval(); return 0;
        } catch (Exception failure) { Console.Error.WriteLine("Saiph installer failed: " + phase + "; " + failure.GetType().Name + "; " + failure.HResult); if (!silent) MessageBox.Show("Saiph could not complete installation. No user data was removed.", "Saiph"); return 1; }
    }

    static WaveSurface surface;
    static void Progress(string message) { Progress(message, -1); }
    // The wizard installs on a worker thread so its animation keeps running;
    // the uninstall window still installs on the UI thread and pumps messages.
    static void Progress(string message, double fraction) {
        if (status == null) return;
        Action update = delegate { status.Text = message; if (fraction >= 0 && surface != null) surface.Progress = fraction; };
        if (!status.InvokeRequired) { update(); Application.DoEvents(); return; }
        try { status.BeginInvoke(update); } catch (InvalidOperationException) { } // Window already gone; progress is cosmetic.
    }
    static string LockName() {
        using (var hash = SHA256.Create()) {
            string key = WindowsIdentity.GetCurrent().User.Value + "\n" + destination.ToUpperInvariant();
            return @"Global\OrionSetup-" + BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(key))).Replace("-", "");
        }
    }
    // Confirm → Removing → Removed, in the same look as the setup wizard.
    static void RunRemoval() {
        var window = new Form { Text = "Remove Saiph", ClientSize = new Size(640, 340), StartPosition = FormStartPosition.CenterScreen,
                                FormBorderStyle = FormBorderStyle.FixedDialog, MaximizeBox = false, Font = new Font("Segoe UI", 10),
                                BackColor = WaveSurface.Footer };
        window.HandleCreated += delegate { WaveSurface.DarkTitleBar(window.Handle); };
        surface = new WaveSurface { Bounds = new Rectangle(0, 0, 640, 268), Hero = true, Heading = "Remove Saiph",
            Body = "Saiph's files will be removed. Your settings, paired device keys, notes and Cloud files will be retained." };
        status = new Label { Left = 24, Top = 282, Width = 340, Height = 48, Text = "Internal preview · publisher signing and clean-device acceptance pending.",
                             BackColor = WaveSurface.Footer, ForeColor = WaveSurface.Muted, Font = new Font("Segoe UI", 9) };
        var action = WaveSurface.Button("Remove Saiph", 452, 286, true);
        action.Width = 164;
        bool removing = false, removed = false;
        // Removal runs on its own thread; the window cannot close until it ends.
        window.FormClosing += (sender, e) => { if (removing) e.Cancel = true; };
        action.Click += delegate {
            if (removed) { window.Close(); return; }
            removing = true; action.Enabled = false; status.Text = "";
            surface.Heading = "Removing Saiph…"; surface.Working = true; surface.Invalidate();
            var worker = new Thread(delegate() {
                bool done = false;
                try { Perform(); done = true; } catch { }
                window.BeginInvoke((Action)delegate {
                    removing = false; surface.Working = false; action.Enabled = true;
                    if (done) {
                        removed = true; action.Text = "Close"; surface.Heading = "Saiph removed"; surface.Body = "Saiph removed. Your data is retained."; surface.Celebrate();
                    } else {
                        surface.Heading = "Remove Saiph";
                        status.Text = "Saiph could not be removed. Your settings and data were retained.";
                    }
                    surface.AccessibleName = surface.Heading; surface.AccessibleDescription = surface.Body; surface.Invalidate();
                });
            });
            // COM shell links are read on this thread.
            worker.SetApartmentState(ApartmentState.STA);
            worker.Start();
        };
        surface.AccessibleName = surface.Heading; surface.AccessibleDescription = surface.Body;
        foreach (Control control in new Control[] { surface, status, action }) window.Controls.Add(control);
        Application.Run(window);
    }

    // Welcome → Options → Installing → Done. Options map onto the same flags as silent mode.
    static void RunWizard() {
        var window = new Form { Text = "Saiph setup", ClientSize = new Size(640, 420), StartPosition = FormStartPosition.CenterScreen,
                                FormBorderStyle = FormBorderStyle.FixedDialog, MaximizeBox = false, Font = new Font("Segoe UI", 10),
                                BackColor = WaveSurface.Footer };
        window.HandleCreated += delegate { WaveSurface.DarkTitleBar(window.Handle); };
        surface = new WaveSurface { Bounds = new Rectangle(0, 0, 640, 348) };
        bool upgrade = File.Exists(Path.Combine(destination, "orion-install.json"));
        bool startupNow = false;
        try { using (var key = Registry.CurrentUser.OpenSubKey(RunKey)) startupNow = key != null && key.GetValue("OrionMini") != null; } catch { }
        var startup = WaveSurface.Option("Start Saiph when I sign in", 146, !upgrade || startupNow);
        var sendTo = WaveSurface.Option("Add \"Saiph (phone)\" to the Send to menu in File Explorer", 178, !upgrade || File.Exists(SendToShortcut));
        var launch = WaveSurface.Option("Open Saiph when setup finishes", 210, !noLaunch);
        var location = new Label { Left = 46, Top = 252, Width = 548, Height = 44, Text = "Installs for your Windows account only, in " + destination,
                                   BackColor = WaveSurface.Card, ForeColor = WaveSurface.Muted, Font = new Font("Segoe UI", 9) };
        status = new Label { Left = 24, Top = 362, Width = 340, Height = 48, Text = "Internal preview · publisher signing and clean-device acceptance pending.",
                             BackColor = WaveSurface.Footer, ForeColor = WaveSurface.Muted, Font = new Font("Segoe UI", 9) };
        var back = WaveSurface.Button("Back", 372, 366, false);
        var next = WaveSurface.Button("Next", 500, 366, true);
        int page = 0;
        bool installing = false;
        Action show = delegate {
            surface.Heading = page == 0 ? (upgrade ? "Update Saiph" : "Install Saiph") : page == 1 ? "Choose options" : page == 2 ? "Installing…" : "Saiph is ready";
            surface.Body = page == 0 ? "Saiph connects your Android phone and your computers. Your existing settings and device pairing are kept."
                + " After setup, Saiph's guide helps you sign in and add your phone."
                : page == 2 ? "Installing Saiph. This takes a moment." : page == 3 ? "Saiph is installed. Open it from the Start menu any time." : "";
            surface.ShowCard = page == 1; surface.Hero = page == 0;
            startup.Visible = sendTo.Visible = launch.Visible = location.Visible = page == 1;
            back.Visible = page == 1; next.Enabled = page != 2;
            next.Text = page == 1 ? (upgrade ? "Update" : "Install") : page == 3 ? "Finish" : "Next";
            surface.AccessibleName = surface.Heading; surface.AccessibleDescription = surface.Body;
            surface.Invalidate();
        };
        back.Click += delegate { page = 0; show(); };
        // Installation runs on its own thread; the window cannot close until it ends.
        window.FormClosing += (sender, e) => { if (installing) e.Cancel = true; };
        next.Click += delegate {
            if (page == 0) { page = 1; show(); return; }
            if (page == 3) { window.Close(); return; }
            noStartup = removeStartup = !startup.Checked; noSendTo = !sendTo.Checked; noLaunch = !launch.Checked;
            page = 2; installing = true; status.Text = ""; surface.Progress = 0.02; surface.Working = true; show();
            var worker = new Thread(delegate() {
                bool done = false;
                try { Perform(); done = true; } catch { }
                window.BeginInvoke((Action)delegate {
                    installing = false; surface.Working = false;
                    if (done) { page = 3; status.Text = ""; surface.Progress = 1; surface.Celebrate(); }
                    else { page = 1; surface.Progress = -1; status.Text = "The installation could not finish. Your existing release and data were retained."; }
                    show();
                });
            });
            // COM shell links are created on this thread.
            worker.SetApartmentState(ApartmentState.STA);
            worker.Start();
        };
        foreach (Control control in new Control[] { startup, sendTo, launch, location }) surface.Controls.Add(control);
        foreach (Control control in new Control[] { surface, status, back, next }) window.Controls.Add(control);
        show(); Application.Run(window);
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
                    if (++number % 40 == 0) Progress("Installing Saiph · " + number + " of " + manifest.files.Length + " files", 0.92 * number / manifest.files.Length);
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
    // Explorer's Send to menu: Windows appends the selected files after this fixed argument.
    static string SendToShortcut { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.SendTo), "Saiph (phone).lnk"); } }
    const string SendFilesArgument = "--send-files";
    static bool OwnShortcut(string path, List<string> targets, string arguments = "") {
        try { CheckParents(path, destination); return File.Exists(path) && Shortcut.Owned(path, targets, arguments); }
        catch { return false; }
    }
    static void PreflightIntegration(List<string> targets) {
        CheckParents(MenuShortcut, destination);
        if (Directory.Exists(MenuShortcut) || (File.Exists(MenuShortcut) && !OwnShortcut(MenuShortcut, targets))) throw new InvalidDataException();
        CheckParents(SendToShortcut, destination);
        if (Directory.Exists(SendToShortcut) || (File.Exists(SendToShortcut) && !OwnShortcut(SendToShortcut, targets, SendFilesArgument))) throw new InvalidDataException();
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
        if (noSendTo) { if (OwnShortcut(SendToShortcut, targets, SendFilesArgument)) File.Delete(SendToShortcut); }
        else { Directory.CreateDirectory(Path.GetDirectoryName(SendToShortcut)); Shortcut.Create(SendToShortcut, exe, icon, "OrionMini.Desktop", SendFilesArgument); }
        // Only remove the old label when its target proves installer ownership.
        if (OwnShortcut(LegacyMenuShortcut, targets)) File.Delete(LegacyMenuShortcut);
        using (var key = Registry.CurrentUser.CreateSubKey(RunKey)) {
            // Existing opt-out is retained on upgrade. The app's own setting remains authoritative.
            if (!noStartup && (first || key.GetValue("OrionMini") != null)) key.SetValue("OrionMini", "\"" + exe + "\"");
            // An explicit untick in the options page removes only Saiph's own entry.
            if (removeStartup) { object value = key.GetValue("OrionMini", null, RegistryValueOptions.DoNotExpandEnvironmentNames); if (IntegrationPolicy.OwnRun(value, targets)) key.DeleteValue("OrionMini"); }
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
            if (OwnShortcut(SendToShortcut, targets, SendFilesArgument)) File.Delete(SendToShortcut);
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

// Saiph's look for the setup window: deep blue, with strings that ripple like
// plucked guitar strings. Purely visual; it never touches installation state.
sealed class WaveSurface : Control {
    public static readonly Color Footer = Color.FromArgb(5, 11, 26), Card = Color.FromArgb(11, 22, 46), Muted = Color.FromArgb(143, 163, 191);
    static readonly Color Cyan = Color.FromArgb(34, 211, 238), Light = Color.FromArgb(103, 232, 249), Violet = Color.FromArgb(167, 139, 250);
    public string Heading = "", Body = "";
    public bool ShowCard, Hero, Working;
    public double Progress = -1; // Below zero hides the progress string.
    readonly Stopwatch clock = Stopwatch.StartNew();
    readonly System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer { Interval = 16 };
    readonly List<double[]> plucks = new List<double[]>(); // x, y, strength, start
    readonly Font headingFont = new Font("Segoe UI Semilight", 21), bodyFont = new Font("Segoe UI", 10), brandFont = new Font("Segoe UI Semibold", 15);
    double shown, knot, last;
    const int Strings = 24, BarLeft = 40, BarRight = 600, BarY = 236, HeroX = 520, HeroY = 190;

    public WaveSurface() {
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
        AccessibleRole = AccessibleRole.StaticText;
        timer.Tick += delegate { Invalidate(); };
        if (AnimationsEnabled()) timer.Start();
    }
    protected override void Dispose(bool disposing) {
        if (disposing) { timer.Dispose(); headingFont.Dispose(); bodyFont.Dispose(); brandFont.Dispose(); }
        base.Dispose(disposing);
    }

    [DllImport("user32.dll")] static extern bool SystemParametersInfo(uint action, uint parameter, ref bool value, uint flags);
    [DllImport("dwmapi.dll")] static extern int DwmSetWindowAttribute(IntPtr window, int attribute, ref int value, int size);
    // Honour Windows' "Animation effects" setting.
    static bool AnimationsEnabled() { bool on = true; try { SystemParametersInfo(0x1042, 0, ref on, 0); } catch { } return on; }
    public static void DarkTitleBar(IntPtr handle) { int on = 1; try { DwmSetWindowAttribute(handle, 20, ref on, 4); } catch { } }

    public static CheckBox Option(string text, int top, bool on) {
        return new CheckBox { Left = 44, Top = top, Width = 552, Height = 28, Text = text, Checked = on, Visible = false,
                              FlatStyle = FlatStyle.Flat, BackColor = Card, ForeColor = Color.FromArgb(227, 238, 251) };
    }
    public static Button Button(string text, int left, int top, bool primary) {
        var button = new Button { Left = left, Top = top, Width = 116, Height = 36, Text = text, FlatStyle = FlatStyle.Flat, Cursor = Cursors.Hand,
                                  BackColor = primary ? Cyan : Color.FromArgb(18, 33, 62), ForeColor = primary ? Color.FromArgb(4, 16, 31) : Color.FromArgb(227, 238, 251),
                                  Font = new Font("Segoe UI Semibold", 10) };
        button.FlatAppearance.BorderColor = primary ? Cyan : Color.FromArgb(34, 55, 92);
        button.FlatAppearance.MouseOverBackColor = primary ? Light : Color.FromArgb(28, 50, 90);
        // Flat buttons keep their colour when disabled; dim them so busy states read clearly.
        Color back = button.BackColor, border = button.FlatAppearance.BorderColor;
        button.EnabledChanged += delegate {
            button.BackColor = button.Enabled ? back : Color.FromArgb(22, 38, 66);
            button.FlatAppearance.BorderColor = button.Enabled ? border : Color.FromArgb(34, 55, 92);
        };
        return button;
    }

    double Seconds { get { return clock.Elapsed.TotalSeconds; } }
    void Pluck(double x, double y, double strength) { plucks.Add(new double[] { x, y, strength, Seconds }); if (plucks.Count > 16) plucks.RemoveAt(0); }
    // Ripples run out along the finished string, or from the mark.
    public void Celebrate() {
        if (Progress < 0) { Pluck(HeroX, HeroY, 1.4); return; }
        for (int i = 0; i < 5; i++) Pluck(BarLeft + i * (BarRight - BarLeft) / 4.0, BarY, 1.2);
    }

    protected override void OnPaint(PaintEventArgs e) {
        var g = e.Graphics; g.SmoothingMode = SmoothingMode.AntiAlias; g.TextRenderingHint = TextRenderingHint.ClearTypeGridFit;
        double t = Seconds, elapsed = Math.Min(0.1, t - last); last = t;
        int width = ClientSize.Width, height = ClientSize.Height;
        using (var background = new LinearGradientBrush(new Rectangle(0, 0, width, height + 1), Color.FromArgb(10, 24, 52), Color.FromArgb(4, 9, 23), 90f))
            g.FillRectangle(background, 0, 0, width, height);
        Glow(g, width * 0.12f, -40, 300, Cyan, 34);
        Glow(g, width * 0.95f, height + 30, 280, Violet, 30);

        // Progress and the "working" knot ease toward their targets.
        if (Progress < 0) shown = 0; else shown += (Progress - shown) * Math.Min(1, elapsed * 4);
        knot += ((Working ? 1 : 0) - knot) * Math.Min(1, elapsed * 3);
        // The working knot rings at the progress head, or around the large mark.
        double headX = Progress >= 0 ? BarLeft + (BarRight - BarLeft) * shown : HeroX, headY = Progress >= 0 ? BarY : HeroY;
        plucks.RemoveAll(p => t - p[3] > 4);

        float gap = height / (float)(Strings + 1);
        var points = new PointF[width / 5 + 3];
        for (int i = 1; i <= Strings; i++) {
            double baseY = i * gap, depth = i / (double)(Strings + 1);
            int alpha = (int)(255 * (0.06 + 0.24 * Math.Pow(Math.Sin(Math.PI * depth), 2)));
            for (int n = 0; n < points.Length; n++) {
                double x = n * 5 - 5, u = x / width;
                double y = baseY + Math.Sin(u * 2.6 + depth * 4.1 + t * 0.12) * gap * 0.9 + Math.Sin(u * 6.3 - depth * 2.2 - t * 0.21) * gap * 0.25
                         + Math.Sin(u * 22 - t * 0.9 + i * 0.7) * 1.2;
                foreach (var p in plucks) {
                    double age = t - p[3], dx = x - p[0], dy = baseY - p[1];
                    double front = Math.Abs(dx) - age * 420;
                    y += Math.Sin(dx * 0.05 - age * 18) * 14 * p[2] * Math.Exp(-dy * dy / (2 * 80.0 * 80.0)) * Math.Exp(-front * front / 7000) * Math.Exp(-age * 1.3);
                }
                if (knot > 0.01) {
                    double dx = x - headX, dy = baseY - headY;
                    // Around the large mark the knot is wider, so it reads without a progress string.
                    double spread = Progress >= 0 ? 70 : 105, swing = Progress >= 0 ? 6 : 9;
                    double near = Math.Exp(-dx * dx / (2 * spread * spread)) * Math.Exp(-dy * dy / (2 * 90.0 * 90.0));
                    y -= dy * 0.35 * near * knot;
                    y += Math.Sin(t * 17 + i * 1.9 + dx * 0.06) * swing * near * knot;
                }
                points[n] = new PointF((float)x, (float)y);
            }
            using (var brush = new LinearGradientBrush(new PointF(0, 0), new PointF(width, 1), Color.FromArgb(alpha / 3, Cyan), Color.FromArgb(alpha / 2, Violet)))
            using (var pen = new Pen(brush, 1f)) {
                brush.InterpolationColors = new ColorBlend { Positions = new[] { 0f, 0.45f, 1f }, Colors = new[] { Color.FromArgb(alpha / 3, Cyan), Color.FromArgb(alpha, Light), Color.FromArgb(alpha / 2, Violet) } };
                pen.Brush = brush;
                g.DrawLines(pen, points);
            }
        }

        Mark(g, 26, 20, 36, t);
        using (var brand = new SolidBrush(Color.FromArgb(220, 240, 250))) g.DrawString("saiph", brandFont, brand, 68, 24);
        using (var white = new SolidBrush(Color.FromArgb(240, 246, 252))) g.DrawString(Heading, headingFont, white, 26, 74);
        if (Body.Length > 0) using (var muted = new SolidBrush(Color.FromArgb(185, 203, 226)))
            g.DrawString(Body, bodyFont, muted, new RectangleF(29, 124, Hero ? 400 : 580, 90));
        if (Hero) { Glow(g, HeroX, HeroY, 90, Light, 40); Mark(g, HeroX - 68, HeroY - 68, 136, t); }
        if (ShowCard) {
            using (var path = Rounded(new RectangleF(24, 124, 592, 184), 16))
            using (var fill = new SolidBrush(Card)) using (var edge = new Pen(Color.FromArgb(60, Light), 1f)) { g.FillPath(fill, path); g.DrawPath(edge, path); }
        }
        if (Progress >= 0) ProgressString(g, t);
    }

    // The progress bar is a string: the finished stretch carries a travelling wave.
    void ProgressString(Graphics g, double t) {
        float head = (float)(BarLeft + (BarRight - BarLeft) * shown);
        using (var rest = new Pen(Color.FromArgb(50, Light), 1f) { DashPattern = new[] { 2f, 5f } }) g.DrawLine(rest, head, BarY, BarRight, BarY);
        int count = Math.Max(2, (int)((head - BarLeft) / 3) + 1);
        var wave = new PointF[count];
        double ring = 1 + 2.5 * knot;
        for (int n = 0; n < count; n++) {
            float x = BarLeft + (head - BarLeft) * n / (count - 1);
            // Fixed at both ends, like a string held at the nut and at the fret.
            double envelope = Math.Min(1, 3 * Math.Sin(Math.PI * n / (count - 1)));
            wave[n] = new PointF(x, (float)(BarY + Math.Sin((x - BarLeft) / 40.0 * Math.PI * 2 - t * 9) * 3.2 * ring * envelope));
        }
        using (var brush = new LinearGradientBrush(new PointF(BarLeft, 0), new PointF(BarRight + 1, 0), Cyan, Violet))
        using (var pen = new Pen(brush, 2.2f))
        using (var halo = new Pen(Color.FromArgb(40, Light), 7f)) { g.DrawLines(halo, wave); g.DrawLines(pen, wave); }
        Glow(g, head, BarY, 26 + (float)(6 * Math.Sin(t * 5)), Light, 90);
        Star(g, new PointF(head, BarY), 5, Color.FromArgb(242, 248, 255));
        Star(g, new PointF(BarLeft, BarY), 4, Light);
        using (var caption = new SolidBrush(Muted))
            g.DrawString(shown >= 0.995 ? "Done" : (int)(shown * 100) + "%", bodyFont, caption, BarLeft - 3, BarY + 18);
    }

    // Saiph's mark: three stars joined by a vibrating string held at the middle star.
    static void Mark(Graphics g, float left, float top, float size, double t) {
        float k = size / 40f;
        Func<float, float, PointF> at = (x, y) => new PointF(left + x * k, top + y * k);
        double a = 4.2 * Math.Cos(t * Math.PI * 2 / 1.1), echo = -2.6 * Math.Cos(t * Math.PI * 2 / 1.6);
        Glow(g, left + 20 * k, top + 20 * k, (float)((10.5 + 1.8 * Math.Sin(t * 2)) * k), Light, 110);
        using (var faint = new Pen(Color.FromArgb(90, Light), 0.9f * k)) Strand(g, faint, at, echo);
        using (var brush = new LinearGradientBrush(at(8, 29), at(32.5f, 10.5f), Cyan, Violet))
        using (var pen = new Pen(brush, 1.6f * k) { StartCap = LineCap.Round, EndCap = LineCap.Round }) Strand(g, pen, at, a);
        Star(g, at(8, 29), 2.6f * k, Light); Star(g, at(20, 20), 3f * k, Color.FromArgb(242, 248, 255)); Star(g, at(32, 11), 2.6f * k, Color.FromArgb(185, 166, 251));
    }
    static void Strand(Graphics g, Pen pen, Func<float, float, PointF> at, double a) {
        // Two quadratic halves, swinging in opposite directions about the middle star.
        Half(g, pen, at(8, 29), at((float)(14 + 0.55 * a), (float)(24.5 + 0.83 * a)), at(20, 20));
        Half(g, pen, at(20, 20), at((float)(26 - 0.55 * a), (float)(15.5 - 0.83 * a)), at(32, 11));
    }
    static void Half(Graphics g, Pen pen, PointF from, PointF control, PointF to) {
        g.DrawBezier(pen, from, new PointF(from.X + (control.X - from.X) * 2 / 3, from.Y + (control.Y - from.Y) * 2 / 3),
                     new PointF(to.X + (control.X - to.X) * 2 / 3, to.Y + (control.Y - to.Y) * 2 / 3), to);
    }
    static void Star(Graphics g, PointF centre, float radius, Color color) {
        using (var brush = new SolidBrush(color)) g.FillEllipse(brush, centre.X - radius, centre.Y - radius, radius * 2, radius * 2);
    }
    static void Glow(Graphics g, float x, float y, float radius, Color color, int alpha) {
        if (radius <= 1) return;
        using (var path = new GraphicsPath()) {
            path.AddEllipse(x - radius, y - radius, radius * 2, radius * 2);
            using (var brush = new PathGradientBrush(path) { CenterColor = Color.FromArgb(alpha, color), SurroundColors = new[] { Color.FromArgb(0, color) } })
                g.FillPath(brush, path);
        }
    }
    static GraphicsPath Rounded(RectangleF box, float radius) {
        var path = new GraphicsPath(); float d = radius * 2;
        path.AddArc(box.Left, box.Top, d, d, 180, 90); path.AddArc(box.Right - d, box.Top, d, d, 270, 90);
        path.AddArc(box.Right - d, box.Bottom - d, d, d, 0, 90); path.AddArc(box.Left, box.Bottom - d, d, d, 90, 90);
        path.CloseFigure(); return path;
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
    public static bool Owned(string path, IEnumerable<string> targets, string expectedArguments = "") {
        object item = new ShellLink();
        try {
            ((System.Runtime.InteropServices.ComTypes.IPersistFile)item).Load(path, 0);
            var target = new StringBuilder(32768); var arguments = new StringBuilder(32768);
            ((Link)item).GetPath(target, target.Capacity, IntPtr.Zero, 4); // SLGP_RAWPATH; never resolve or launch.
            ((Link)item).GetArguments(arguments, arguments.Capacity);
            return arguments.ToString() == expectedArguments && targets.Any(exe => String.Equals(target.ToString(), exe, StringComparison.OrdinalIgnoreCase));
        } finally { Marshal.FinalReleaseComObject(item); }
    }
    public static void Create(string path, string executable, string icon, string identity, string arguments = "") {
        object item = new ShellLink();
        try {
            var link = (Link)item; link.SetPath(executable); link.SetWorkingDirectory(Path.GetDirectoryName(executable)); link.SetIconLocation(icon, 0);
            if (arguments.Length > 0) link.SetArguments(arguments);
            var store = (Store)item; var key = new Key { format = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), id = 5 };
            var value = new Value { type = 31, text = Marshal.StringToCoTaskMemUni(identity) };
            try { store.SetValue(ref key, ref value); store.Commit(); } finally { Marshal.FreeCoTaskMem(value.text); }
            ((System.Runtime.InteropServices.ComTypes.IPersistFile)item).Save(path, true);
        } finally { Marshal.FinalReleaseComObject(item); }
    }
}
