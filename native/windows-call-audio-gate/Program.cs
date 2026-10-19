// SPDX-License-Identifier: AGPL-3.0-or-later
// B2 Windows gate test (docs/CALL_AUDIO.md, docs/research/CALL_AUDIO_SPIKE.md section 7).
// Records exactly what Windows answers when an app with package identity and the restricted
// phoneLineTransportManagement capability asks to become a phone's Bluetooth hands-free app.
//
//   probe       read-only: identity, Bluetooth radios, hands-free transport devices, call state
//   access      PhoneLineTransportDevice.RequestAccessAsync (no registration change)
//   register    RegisterApp (may take the phone's registration from Phone Link)
//   connect     ConnectAsync (opens the HFP service-level connection)
//   watch N     report call and audio-routing changes for N seconds (place a call meanwhile)
//   unregister  UnregisterApp (undo register)
//
// Options: --device <part of the device name>, --out <file.json>. Every run prints one JSON report.
// Call audio is Bluetooth only; nothing here uses the network.
using System.Text.Json;
using Windows.ApplicationModel.Calls;
using Windows.Devices.Enumeration;
using Windows.Devices.Radios;

var mode = args.Length > 0 ? args[0] : "probe";
string? Option(string name) { var i = Array.IndexOf(args, name); return i >= 0 && i + 1 < args.Length ? args[i + 1] : null; }
var report = new Dictionary<string, object?> { ["mode"] = mode, ["at"] = DateTimeOffset.Now.ToString("o"),
    ["os"] = Environment.OSVersion.VersionString };

try { report["identity"] = Windows.ApplicationModel.Package.Current.Id.FamilyName; }
catch (Exception error) { report["identity"] = null; report["identity_error"] = Describe(error); }

try
{
    var radios = await Radio.GetRadiosAsync();
    report["radios"] = radios.Select(r => new { kind = r.Kind.ToString(), state = r.State.ToString(), name = r.Name }).ToList();
}
catch (Exception error) { report["radios_error"] = Describe(error); }

var devices = new List<(DeviceInformation Info, PhoneLineTransportDevice? Device)>();
try
{
    var selector = PhoneLineTransportDevice.GetDeviceSelector();
    report["selector"] = selector;
    foreach (var info in await DeviceInformation.FindAllAsync(selector))
    {
        PhoneLineTransportDevice? device = null;
        try { device = PhoneLineTransportDevice.FromId(info.Id); } catch (Exception error) { report["from_id_error"] = Describe(error); }
        devices.Add((info, device));
    }
    report["devices"] = devices.Select(d => Describe(d.Info, d.Device)).ToList();
}
catch (Exception error) { report["devices_error"] = Describe(error); }

try { report["call"] = new { active = PhoneCallManager.IsCallActive, incoming = PhoneCallManager.IsCallIncoming }; }
catch (Exception error) { report["call_error"] = Describe(error); }

if (mode != "probe")
{
    var wanted = Option("--device");
    var chosen = devices.FirstOrDefault(d => d.Device is not null && (wanted is null || d.Info.Name.Contains(wanted, StringComparison.OrdinalIgnoreCase)));
    if (chosen.Device is null)
        report["result"] = devices.Count == 0
            ? "no hands-free transport device: pair the phone over Bluetooth first (this needs a Bluetooth radio)"
            : "no device matched --device";
    else
    {
        report["device"] = chosen.Info.Name;
        var device = chosen.Device;
        try
        {
            switch (mode)
            {
                case "access":
                    report["result"] = (await device.RequestAccessAsync()).ToString();
                    break;
                case "register":
                    report["access"] = (await device.RequestAccessAsync()).ToString();
                    device.RegisterApp();
                    report["result"] = new { registered = device.IsRegistered() };
                    break;
                case "connect":
                    report["result"] = new { connected = await device.ConnectAsync() };
                    break;
                case "watch":
                    var seconds = args.Length > 1 && int.TryParse(args[1], out var s) ? Math.Clamp(s, 5, 600) : 120;
                    var events = new List<object>();
                    void Note(string what) { lock (events) events.Add(new { at = DateTimeOffset.Now.ToString("o"), what,
                        active = Safe(() => PhoneCallManager.IsCallActive), incoming = Safe(() => PhoneCallManager.IsCallIncoming),
                        routing = Safe(() => device.AudioRoutingStatus.ToString()) }); }
                    PhoneCallManager.CallStateChanged += (_, _) => Note("call state changed");
                    device.AudioRoutingStatusChanged += (_, _) => Note("audio routing changed");
                    device.InBandRingingEnabledChanged += (_, _) => Note("in-band ringing changed");
                    Note("watching");
                    await Task.Delay(TimeSpan.FromSeconds(seconds));
                    Note("done");
                    report["result"] = events;
                    break;
                case "unregister":
                    device.UnregisterApp();
                    report["result"] = new { registered = device.IsRegistered() };
                    break;
                default:
                    report["result"] = "unknown mode";
                    break;
            }
        }
        catch (Exception error) { report["result"] = null; report["error"] = Describe(error); }
        report["after"] = Describe(chosen.Info, device);
    }
}

var json = JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true });
Console.WriteLine(json);
var output = Option("--out");
if (output is not null) File.WriteAllText(output, json);
return 0;

static object Describe(object value, PhoneLineTransportDevice? device = null) => value switch
{
    Exception error => new { type = error.GetType().Name, hresult = $"0x{error.HResult:X8}", message = error.Message },
    DeviceInformation info => new
    {
        name = info.Name, id = info.Id, enabled = info.IsEnabled,
        transport = Safe(() => device?.Transport.ToString()),
        registered = Safe(() => device?.IsRegistered()),
        routing = Safe(() => device?.AudioRoutingStatus.ToString()),
        in_band_ringing = Safe(() => device?.InBandRingingEnabled),
    },
    _ => value.ToString() ?? "",
};

static object? Safe<T>(Func<T> read)
{
    try { return read(); }
    catch (Exception error) { return $"error 0x{error.HResult:X8}: {error.Message}"; }
}
