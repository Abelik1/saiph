// SPDX-License-Identifier: AGPL-3.0-or-later
// Saiph local network relay (SaiphNetwork.exe).
//
// Windows Firewall allows or blocks inbound connections by the full path of the
// listening program. Each Saiph update installs a new versioned folder, so a rule
// the owner allowed for releases\<old>\app\saiph.exe no longer matches and the
// phone camera, phone screen and local file transfers were blocked again after
// every update. The installer keeps this small relay at one fixed path,
// %LOCALAPPDATA%\Programs\OrionMini\SaiphNetwork.exe, so Windows asks once and the
// answer keeps applying.
//
// The app listens on 127.0.0.1 only and starts the relay per session:
//   SaiphNetwork.exe --target <loopback port> --parent <app process id>
// The relay listens on all IPv4 interfaces on a free port, prints "PORT <n>" on
// standard output, and copies bytes between each accepted connection and
// 127.0.0.1:<target>. It never reads or changes the traffic (TLS stays end to end
// between the devices) and exits when the app exits or closes standard input.
// "--bind loopback" (tests only) listens on 127.0.0.1, which Windows Firewall never asks about.
using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Threading;

[assembly: AssemblyTitle("Saiph local network")]
[assembly: AssemblyDescription("Lets your phone and computers reach Saiph on your Wi-Fi")]
[assembly: AssemblyProduct("Saiph")]
[assembly: AssemblyCopyright("Saiph contributors, AGPL-3.0-or-later")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

public static class Relay {
    const int MaxConnections = 16;
    static int open;

    public static int Main(string[] arguments) {
        int target = 0, parent = 0;
        try {
            bool loopback = arguments.Length == 6 && arguments[4] == "--bind" && arguments[5] == "loopback";
            if ((arguments.Length != 4 && !loopback) || arguments[0] != "--target" || arguments[2] != "--parent"
                || !int.TryParse(arguments[1], out target) || target < 1 || target > 65535
                || !int.TryParse(arguments[3], out parent) || parent <= 0) return 2;
            Process app = Process.GetProcessById(parent);
            var listener = new TcpListener(loopback ? IPAddress.Loopback : IPAddress.Any, 0);
            listener.Start(8);
            Console.Out.WriteLine("PORT " + ((IPEndPoint)listener.LocalEndpoint).Port);
            Console.Out.Flush();
            // Exit with the app, or as soon as it closes our standard input.
            new Thread(() => { try { app.WaitForExit(); } catch { } Environment.Exit(0); }) { IsBackground = true }.Start();
            new Thread(() => { try { while (Console.In.Read() >= 0) { } } catch { } Environment.Exit(0); }) { IsBackground = true }.Start();
            while (true) {
                TcpClient client = listener.AcceptTcpClient();
                if (Interlocked.Increment(ref open) > MaxConnections) { Interlocked.Decrement(ref open); client.Close(); continue; }
                new Thread(() => Forward(client, target)) { IsBackground = true }.Start();
            }
        } catch (Exception failure) {
            Console.Error.WriteLine("Saiph local network relay stopped: " + failure.GetType().Name);
            return 1;
        }
    }

    static void Forward(TcpClient client, int target) {
        TcpClient upstream = null;
        try {
            client.NoDelay = true;
            upstream = new TcpClient();
            upstream.NoDelay = true;
            upstream.Connect(IPAddress.Loopback, target);
            NetworkStream inbound = client.GetStream(), outbound = upstream.GetStream();
            var back = new Thread(() => Copy(outbound, inbound, client, upstream)) { IsBackground = true };
            back.Start();
            Copy(inbound, outbound, client, upstream);
            back.Join();
        } catch {
        } finally {
            try { client.Close(); } catch { }
            if (upstream != null) try { upstream.Close(); } catch { }
            Interlocked.Decrement(ref open);
        }
    }

    // One direction; when either side ends, both sockets close so the other direction ends too.
    static void Copy(Stream from, Stream to, TcpClient a, TcpClient b) {
        byte[] buffer = new byte[65536];
        try {
            int count;
            while ((count = from.Read(buffer, 0, buffer.Length)) > 0) to.Write(buffer, 0, count);
        } catch {
        } finally {
            try { a.Client.Shutdown(SocketShutdown.Both); } catch { }
            try { b.Client.Shutdown(SocketShutdown.Both); } catch { }
        }
    }
}
