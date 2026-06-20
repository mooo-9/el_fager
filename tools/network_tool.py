"""
Network status and diagnostics for El Fager.

Check connectivity, WiFi info, ping hosts, run speed tests, get IP addresses.
Uses stdlib socket/subprocess for most checks; speedtest-cli for speed test.
"""


def check_internet() -> str:
    """Fast check: can we reach the internet? DNS test to 8.8.8.8:53."""
    try:
        import socket
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        return "Internet: connected."
    except OSError:
        return "Internet: NOT connected. No route to 8.8.8.8:53."
    except Exception as e:
        return f"[check_internet failed: {e}]"


def get_network_status() -> str:
    """Current network info: IP, WiFi SSID, signal, gateway."""
    try:
        import socket
        import subprocess

        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)

        lines = [f"Host: {hostname}", f"Local IP: {local_ip}"]

        # WiFi info via netsh (Windows)
        try:
            result = subprocess.run(
                ["netsh", "wlan", "show", "interfaces"],
                capture_output=True, text=True, timeout=5
            )
            out = result.stdout
            ssid = ""
            signal = ""
            for line in out.splitlines():
                stripped = line.strip()
                if stripped.startswith("SSID") and "BSSID" not in stripped and not ssid:
                    ssid = stripped.split(":", 1)[-1].strip()
                elif stripped.startswith("Signal"):
                    signal = stripped.split(":", 1)[-1].strip()
            if ssid:
                lines.append(f"WiFi SSID: {ssid}")
            if signal:
                lines.append(f"Signal: {signal}")
            if not ssid:
                lines.append("WiFi: not connected (may be on Ethernet)")
        except Exception:
            lines.append("WiFi info: unavailable")

        # Default gateway via route print
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 "(Get-NetRoute -DestinationPrefix '0.0.0.0/0' | Sort-Object -Property RouteMetric | Select-Object -First 1).NextHop"],
                capture_output=True, text=True, timeout=5
            )
            gw = result.stdout.strip()
            if gw:
                lines.append(f"Gateway: {gw}")
        except Exception:
            pass

        return "\n".join(lines)
    except Exception as e:
        return f"[get_network_status failed: {e}]"


def ping(host: str, count: int = 4) -> str:
    """Ping a host and return average latency and packet loss."""
    try:
        import subprocess
        result = subprocess.run(
            ["ping", "-n", str(count), host],
            capture_output=True, text=True, timeout=30
        )
        out = result.stdout
        # Parse Windows ping output
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        stats_line = ""
        avg_line = ""
        for line in lines:
            if "packets: sent" in line.lower() or "lost" in line.lower():
                stats_line = line
            if "average" in line.lower() or "minimum" in line.lower():
                avg_line = line
        summary = []
        if stats_line:
            summary.append(stats_line)
        if avg_line:
            summary.append(avg_line)
        if not summary:
            return f"Ping {host}: no response (host unreachable or blocked)."
        return f"Ping {host} ({count} packets):\n" + "\n".join(summary)
    except subprocess.TimeoutExpired:
        return f"[ping timed out after 30s pinging {host}]"
    except Exception as e:
        return f"[ping failed: {e}]"


def internet_speed() -> str:
    """Download and upload speed via speedtest-cli. Takes ~10 seconds."""
    try:
        import speedtest
        st = speedtest.Speedtest()
        st.get_best_server()
        download_mbps = st.download() / 1_000_000
        upload_mbps = st.upload() / 1_000_000
        server = st.results.server
        server_name = f"{server.get('name', '?')}, {server.get('country', '?')}"
        ping_ms = st.results.ping
        return (
            f"Speed test results (server: {server_name}):\n"
            f"  Download: {download_mbps:.1f} Mbps\n"
            f"  Upload:   {upload_mbps:.1f} Mbps\n"
            f"  Ping:     {ping_ms:.0f} ms"
        )
    except Exception as e:
        return f"[internet_speed failed: {e}]"


def get_local_ip() -> str:
    """Local IPv4 address of this machine."""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        return f"Local IP: {ip}"
    except Exception as e:
        return f"[get_local_ip failed: {e}]"


def get_public_ip() -> str:
    """External/public IPv4 address via ipify.org."""
    try:
        import urllib.request
        with urllib.request.urlopen("https://api.ipify.org", timeout=5) as resp:
            ip = resp.read().decode().strip()
        return f"Public IP: {ip}"
    except Exception as e:
        return f"[get_public_ip failed: {e}]"
