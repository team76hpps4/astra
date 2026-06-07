#!/usr/bin/env python3
import subprocess
import sys
import time
import argparse
import csv
import re
from collections import defaultdict, deque
from pathlib import Path

def flow_key(src_ip, src_port, dst_ip, dst_port):
    """4-tuple to identify a TCP direction."""
    return (src_ip, src_port, dst_ip, dst_port)

def extract_client_mac(ip_address, arp_cache):
    """
    Lookup MAC address from IP using ARP cache.
    Returns MAC address or None if not found.
    """
    return arp_cache.get(ip_address)

def update_arp_cache():
    """
    Read system ARP table and return {ip: mac} mapping.
    Works on OpenWrt and standard Linux.
    """
    arp_cache = {}
    try:
        result = subprocess.run(
            ['ip', 'neigh', 'show'],
            capture_output=True,
            text=True,
            timeout=2
        )
        for line in result.stdout.splitlines():
            match = re.search(r'(\d+\.\d+\.\d+\.\d+)\s+.*lladdr\s+([0-9a-f:]{17})', line, re.IGNORECASE)
            if match:
                ip, mac = match.groups()
                arp_cache[ip] = mac.lower()
    except Exception:
        try:
            result = subprocess.run(
                ['arp', '-n'],
                capture_output=True,
                text=True,
                timeout=2
            )
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 3 and re.match(r'\d+\.\d+\.\d+\.\d+', parts[0]):
                    ip = parts[0]
                    mac = parts[2]
                    if re.match(r'[0-9a-f:]{17}', mac, re.IGNORECASE):
                        arp_cache[ip] = mac.lower()
        except Exception:
            pass
    
    return arp_cache

def parse_tcpdump_line(line):
    """
    Parse a tcpdump line of the form:

    1764611714.186027 IP 192.168.1.229.41432 > 142.251.12.84.443: Flags [.],
        seq 1:1401, ack 1, win 128, options [...], length 1400
    """
    line = line.strip()
    if not line:
        return None

    parts = line.split()
    if len(parts) < 5:
        return None

    try:
        ts = float(parts[0])
    except ValueError:
        return None

    if parts[1] != "IP":
        return None

    try:
        src = parts[2]             
        direction = parts[3]       
        dst = parts[4]             

        if direction != '>':
            return None
        if dst.endswith(':'):
            dst = dst[:-1]

        src_ip, src_port = src.rsplit('.', 1)
        dst_ip, dst_port = dst.rsplit('.', 1)
        src_port = int(src_port)
        dst_port = int(dst_port)
    except Exception:
        return None

    rest = " ".join(parts[5:])

    seq_start = None
    seq_end = None
    ack = None
    length = 0

    idx = rest.rfind("length ")
    if idx != -1:
        try:
            length_str = rest[idx + len("length "):].split()[0]
            length = int(length_str)
        except Exception:
            length = 0

    if "seq " in rest:
        try:
            seg = rest.split("seq ", 1)[1].split(',', 1)[0].strip()
            if ':' in seg:
                a, b = seg.split(':', 1)
                seq_start = int(a)
                seq_end = int(b)
            else:
                seq_start = int(seg)
                if length > 0:
                    seq_end = seq_start + length
        except Exception:
            seq_start = None
            seq_end = None

    if " ack " in rest:
        try:
            seg = rest.split(" ack ", 1)[1].split(',', 1)[0].strip()
            ack = int(seg)
        except Exception:
            ack = None

    if seq_start is not None and seq_end is None and length > 0:
        seq_end = seq_start + length

    return {
        "ts": ts,
        "src_ip": src_ip,
        "src_port": src_port,
        "dst_ip": dst_ip,
        "dst_port": dst_port,
        "seq_start": seq_start,
        "seq_end": seq_end,
        "ack": ack,
        "length": length,
    }

def rtt_monitor(iface, bpf_filter, min_length=1, verbose=True, debug=False, csv_output=None):
    """
    Run tcpdump on iface with given BPF filter, estimate RTTs
    by matching data packets with their ACKs.
    """
    cmd = [
        "tcpdump",
        "-nn",
        "-tt",
        "-l",
        "-s", "96",
        "-i", iface,
        bpf_filter,
    ]

    print("Running:", " ".join(cmd), file=sys.stderr, flush=True)
    
    if csv_output:
        print(f"Writing RTT data to: {csv_output}", file=sys.stderr, flush=True)

    outstanding = defaultdict(deque)
    
    arp_cache = {}
    last_arp_update = 0

    csv_file = None
    csv_writer = None
    if csv_output:
        try:
            csv_file = open(csv_output, 'a', newline='')
            csv_writer = csv.writer(csv_file)
            if Path(csv_output).stat().st_size == 0:
                csv_writer.writerow(['timestamp', 'client_mac', 'rtt_ms', 'flow_info'])
                csv_file.flush()
        except Exception as e:
            print(f"Error opening CSV file {csv_output}: {e}", file=sys.stderr)
            csv_file = None
            csv_writer = None

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )

    try:
        for line in proc.stdout:
            info = parse_tcpdump_line(line)

            if info is None:
                if debug:
                    sys.stderr.write("SKIP: " + line)
                continue

            ts = info["ts"]
            length = info["length"]
            seq_end = info["seq_end"]
            ack = info["ack"]

            src_ip = info["src_ip"]
            dst_ip = info["dst_ip"]
            src_port = info["src_port"]
            dst_port = info["dst_port"]

            fwd = flow_key(src_ip, src_port, dst_ip, dst_port)
            rev = flow_key(dst_ip, dst_port, src_ip, src_port)

            if time.time() - last_arp_update > 10:
                arp_cache = update_arp_cache()
                last_arp_update = time.time()
                if debug:
                    print(f"ARP cache updated: {len(arp_cache)} entries", file=sys.stderr)

            if debug:
                sys.stderr.write(f"PARSED: {info}\n")

            if length >= min_length and seq_end is not None:
                outstanding[fwd].append((seq_end, ts))

            if ack is not None:
                dq = outstanding[rev]
                rtt_sample = None
                while dq and dq[0][0] <= ack:
                    _, s_ts = dq.popleft()
                    rtt_sample = ts - s_ts

                if rtt_sample is not None:
                    rtt_ms = rtt_sample * 1000
                    
                    client_mac = extract_client_mac(rev[0], arp_cache) or \
                                 extract_client_mac(rev[2], arp_cache) or \
                                 "unknown"
                    
                    flow_info = f"{rev[0]}:{rev[1]}->{rev[2]}:{rev[3]}"
                    
                    if csv_writer:
                        try:
                            csv_writer.writerow([ts, client_mac, f"{rtt_ms:.2f}", flow_info])
                            csv_file.flush()
                        except Exception as e:
                            print(f"Error writing to CSV: {e}", file=sys.stderr)
                    
                    if verbose:
                        sys.stdout.write(
                            f"{time.strftime('%H:%M:%S', time.localtime(ts))} "
                            f"MAC={client_mac} "
                            f"RTT={rtt_ms:.2f}ms "
                            f"{flow_info}\n"
                        )
                        sys.stdout.flush()

    except KeyboardInterrupt:
        print("\nStopped by user.", file=sys.stderr)
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
        
        if csv_file:
            csv_file.close()
            print(f"CSV file closed: {csv_output}", file=sys.stderr)

def main():
    parser = argparse.ArgumentParser(description="Passive TCP RTT monitor with CSV output for BandSteeringManager.")
    parser.add_argument(
        "-i", "--interface",
        required=True,
        help="Interface (e.g. br-lan, wlan0, phy0-ap0)"
    )
    parser.add_argument(
        "-f", "--filter",
        default="tcp",
        help="BPF filter to pass to tcpdump (default: 'tcp')"
    )
    parser.add_argument(
        "--min-length",
        type=int,
        default=1,
        help="Minimum TCP payload length to track (default: 1 byte)"
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Quiet mode (no RTT prints to stdout)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Debug parsing (prints skipped/parsed packets to stderr)"
    )
    parser.add_argument(
        "-o", "--output",
        default="./rtt_stats.csv",
        help="CSV output file for BandSteeringManager (default: /tmp/rtt_stats.csv)"
    )

    args = parser.parse_args()

    rtt_monitor(
        iface=args.interface,
        bpf_filter=args.filter,
        min_length=args.min_length,
        verbose=not args.quiet,
        debug=args.debug,
        csv_output=args.output
    )


if __name__ == "__main__":
    main()
