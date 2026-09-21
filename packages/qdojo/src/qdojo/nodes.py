"""Find live Qubic nodes without being told one.

Bootstrap from a few known public nodes, ask them for their peer lists, probe
everything in parallel with a short timeout, and keep the nodes whose tick
agrees with the best. A node that answers slowly or from the past is worse
than none: a stale tick means a stale balance and a missed window.
"""
import concurrent.futures as cf
import json
import os
import re
import subprocess
import time

from .chain import parse

BOOTSTRAP = ["82.197.173.130", "157.180.10.49", "45.152.160.100", "45.152.160.226"]
PORT = 21841
AGREE_WITHIN = 20      # ticks behind the best a node may be and still count as live
MAX_PROBE = 40
IP_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


def parse_node_list(text: str) -> list[str]:
    return [l.strip() for l in text.splitlines() if IP_RE.match(l.strip())]


def native_probe(timeout: float = 6.0):
    """A prober that speaks the node protocol: ip[:port] -> (tick or None, peers).

    The peer list costs nothing extra: a node volunteers it the moment the
    socket opens, which is the same list `qubic-cli -getnodeiplist` asks for.
    So one connection answers both halves, and discovery needs no binary.
    Peers come back as bare IPs; an explicit `--node IP:PORT` keeps its port.
    """
    from .qubic.node import Node, NodeError

    def probe(ip: str):
        host, _, port = ip.partition(":")
        try:
            with Node(host, int(port or PORT), timeout) as n:
                peers = n.public_peers()
                return n.tick_info()["tick"], [p for p in peers if IP_RE.match(p)]
        except (NodeError, ValueError, OSError):
            return None, []
    return probe


def cli_probe(binary: str, timeout: float = 6.0):
    """A prober built on qubic-cli: ip -> (tick or None, peer list).

    Kept for `--chain cli`. `native_probe` is the default and needs no binary.
    """
    def probe(ip: str):
        base = [binary, "-nodeip", ip, "-nodeport", str(PORT)]
        try:
            out = subprocess.run(base + ["-getcurrenttick"], capture_output=True, text=True, timeout=timeout).stdout
        except (subprocess.TimeoutExpired, OSError):
            return None, []
        tick = parse.current_tick(out)
        peers = []
        if tick:
            try:
                peers = parse_node_list(subprocess.run(base + ["-getnodeiplist"], capture_output=True, text=True,
                                                       timeout=timeout).stdout)
            except (subprocess.TimeoutExpired, OSError):
                pass
        return tick, peers
    return probe


def discover(probe, seeds=None, max_probe: int = MAX_PROBE, workers: int = 12) -> list[dict]:
    """Nodes sorted best first: [{ip, tick, lag}], only those within AGREE_WITHIN of the best tick."""
    seeds = list(seeds or BOOTSTRAP)
    results: dict[str, int | None] = {}
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        first = dict(zip(seeds, ex.map(probe, seeds)))
        candidates = []
        for ip, (tick, peers) in first.items():
            results[ip] = tick
            candidates += [p for p in peers if p not in results and p not in candidates]
        candidates = candidates[: max(0, max_probe - len(results))]
        for ip, (tick, _) in zip(candidates, ex.map(probe, candidates)):
            results[ip] = tick
    live = {ip: t for ip, t in results.items() if t}
    if not live:
        return []
    best = max(live.values())
    good = [{"ip": ip, "tick": t, "lag": best - t} for ip, t in live.items() if best - t <= AGREE_WITHIN]
    return sorted(good, key=lambda d: (d["lag"], d["ip"]))


def cache_path(state_dir: str) -> str:
    return os.path.join(state_dir, "nodes.json")


def save(state_dir: str, nodes: list[dict]) -> None:
    os.makedirs(state_dir, mode=0o700, exist_ok=True)
    with open(cache_path(state_dir), "w", encoding="utf-8") as f:
        json.dump({"found_at": int(time.time()), "nodes": nodes}, f, indent=2)


def load(state_dir: str, max_age: float = 6 * 3600) -> list[dict]:
    try:
        with open(cache_path(state_dir), encoding="utf-8") as f:
            d = json.load(f)
    except (FileNotFoundError, ValueError):
        return []
    if time.time() - d.get("found_at", 0) > max_age:
        return []
    return d.get("nodes", [])


def best_node(state_dir: str, probe, force: bool = False) -> str:
    """The best known node IP, discovering (and caching) when the cache is cold."""
    nodes = [] if force else load(state_dir)
    if not nodes:
        nodes = discover(probe)
        if not nodes:
            raise RuntimeError("no live Qubic node found; pass --node explicitly")
        save(state_dir, nodes)
    return nodes[0]["ip"]
