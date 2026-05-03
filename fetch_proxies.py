import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

PROXIES_FILE = os.environ.get("PROXIES_FILE", "proxies.txt")
TEST_URL = "https://api.github.com/users/octocat"
TIMEOUT = 3
MAX_WORKERS = 200
REQUEST_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "github-username-checker-proxy-validator",
}

# ---------------------------------------------------------------------------
# Source definitions
# ---------------------------------------------------------------------------

# proxyscrape: returns plain "ip:port" lines, one per protocol fetch
PROXYSCRAPE_SOURCES = [
    ("http",   "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all"),
    ("socks4", "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks4&timeout=10000&country=all&anonymity=all"),
    ("socks5", "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks5&timeout=10000&country=all&anonymity=all"),
]

# proxifly (via jsDelivr CDN): returns "protocol://ip:port" lines
PROXIFLY_SOURCES = [
    ("http",   "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/http/data.txt"),
    ("socks4", "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/socks4/data.txt"),
    ("socks5", "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/socks5/data.txt"),
]

# geonode: public JSON API, paginates at 500/page
GEONODE_API = "https://proxylist.geonode.com/api/proxy-list"
GEONODE_PARAMS = {
    "limit": 500,
    "sort_by": "lastChecked",
    "sort_type": "desc",
}

# monosans: smaller checked protocol lists
MONOSANS_SOURCES = [
    ("http",   "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt"),
    ("socks4", "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks4.txt"),
    ("socks5", "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt"),
]

# ClearProxy: use GitHub-specific checked lists
CLEARPROXY_SOURCES = [
    ("http",   "https://raw.githubusercontent.com/ClearProxy/checked-proxy-list/main/custom/github/http.txt"),
    ("socks4", "https://raw.githubusercontent.com/ClearProxy/checked-proxy-list/main/custom/github/socks4.txt"),
    ("socks5", "https://raw.githubusercontent.com/ClearProxy/checked-proxy-list/main/custom/github/socks5.txt"),
]

# GoekhanDev: top-level raw protocol lists
GOEKHANDEV_SOURCES = [
    ("http",   "https://raw.githubusercontent.com/GoekhanDev/free-proxy-list/main/http.txt"),
    ("socks4", "https://raw.githubusercontent.com/GoekhanDev/free-proxy-list/main/socks4.txt"),
    ("socks5", "https://raw.githubusercontent.com/GoekhanDev/free-proxy-list/main/socks5.txt"),
]

# iplocate: verified protocol lists
IPLOCATE_SOURCES = [
    ("http",   "https://raw.githubusercontent.com/iplocate/free-proxy-list/main/protocols/http.txt"),
    ("socks4", "https://raw.githubusercontent.com/iplocate/free-proxy-list/main/protocols/socks4.txt"),
    ("socks5", "https://raw.githubusercontent.com/iplocate/free-proxy-list/main/protocols/socks5.txt"),
]


# ---------------------------------------------------------------------------
# Fetchers — each returns a list of (protocol, "ip:port") tuples
# ---------------------------------------------------------------------------

def _fetch_proxyscrape() -> list[tuple[str, str]]:
    results = []
    print("Fetching proxyscrape...", flush=True)
    for protocol, url in PROXYSCRAPE_SOURCES:
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            entries = [line.strip() for line in r.text.splitlines() if line.strip()]
            print(f"  proxyscrape {protocol}: {len(entries)}", flush=True)
            results.extend((protocol, e) for e in entries)
        except Exception as exc:
            print(f"  ⚠️  proxyscrape {protocol}: {exc}", flush=True)
    return results


def _fetch_proxifly() -> list[tuple[str, str]]:
    results = []
    print("Fetching proxifly (jsDelivr CDN)...", flush=True)
    for protocol, url in PROXIFLY_SOURCES:
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            entries = []
            for line in r.text.splitlines():
                line = line.strip()
                if not line:
                    continue
                if "://" in line:
                    line = line.split("://", 1)[1]
                entries.append(line)
            print(f"  proxifly {protocol}: {len(entries)}", flush=True)
            results.extend((protocol, e) for e in entries)
        except Exception as exc:
            print(f"  ⚠️  proxifly {protocol}: {exc}", flush=True)
    return results


def _fetch_geonode() -> list[tuple[str, str]]:
    results = []
    print("Fetching geonode API...", flush=True)
    page = 1
    while True:
        try:
            params = {**GEONODE_PARAMS, "page": page}
            r = requests.get(GEONODE_API, params=params, timeout=15)
            r.raise_for_status()
            data = r.json()
            proxies = data.get("data", [])
            if not proxies:
                break
            for p in proxies:
                ip = p.get("ip", "").strip()
                port = str(p.get("port", "")).strip()
                protocols = p.get("protocols", [])
                if not ip or not port or not protocols:
                    continue
                for proto in protocols:
                    proto = proto.lower()
                    if proto in ("http", "https", "socks4", "socks5"):
                        norm = "http" if proto == "https" else proto
                        results.append((norm, f"{ip}:{port}"))
            print(f"  geonode page {page}: {len(proxies)} entries", flush=True)
            total = data.get("total", 0)
            if page * GEONODE_PARAMS["limit"] >= total:
                break
            page += 1
        except Exception as exc:
            print(f"  ⚠️  geonode page {page}: {exc}", flush=True)
            break
    print(f"  geonode total collected: {len(results)}", flush=True)
    return results


def _fetch_monosans() -> list[tuple[str, str]]:
    results = []
    print("Fetching monosans...", flush=True)
    for protocol, url in MONOSANS_SOURCES:
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            entries = [line.strip() for line in r.text.splitlines() if line.strip()]
            print(f"  monosans {protocol}: {len(entries)}", flush=True)
            results.extend((protocol, e) for e in entries)
        except Exception as exc:
            print(f"  ⚠️  monosans {protocol}: {exc}", flush=True)
    return results


def _fetch_clearproxy() -> list[tuple[str, str]]:
    results = []
    print("Fetching ClearProxy...", flush=True)
    for protocol, url in CLEARPROXY_SOURCES:
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            entries = [line.strip() for line in r.text.splitlines() if line.strip()]
            print(f"  ClearProxy {protocol}: {len(entries)}", flush=True)
            results.extend((protocol, e) for e in entries)
        except Exception as exc:
            print(f"  ⚠️  ClearProxy {protocol}: {exc}", flush=True)
    return results


def _fetch_goekhandev() -> list[tuple[str, str]]:
    results = []
    print("Fetching GoekhanDev...", flush=True)
    for protocol, url in GOEKHANDEV_SOURCES:
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            entries = [line.strip() for line in r.text.splitlines() if line.strip()]
            print(f"  GoekhanDev {protocol}: {len(entries)}", flush=True)
            results.extend((protocol, e) for e in entries)
        except Exception as exc:
            print(f"  ⚠️  GoekhanDev {protocol}: {exc}", flush=True)
    return results


def _fetch_iplocate() -> list[tuple[str, str]]:
    results = []
    print("Fetching iplocate...", flush=True)
    for protocol, url in IPLOCATE_SOURCES:
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            entries = [line.strip() for line in r.text.splitlines() if line.strip()]
            print(f"  iplocate {protocol}: {len(entries)}", flush=True)
            results.extend((protocol, e) for e in entries)
        except Exception as exc:
            print(f"  ⚠️  iplocate {protocol}: {exc}", flush=True)
    return results


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def fetch_proxy_list() -> list[tuple[str, str]]:
    """Fetch from all sources and return deduped (protocol, ip:port) tuples."""
    raw: list[tuple[str, str]] = []
    raw.extend(_fetch_proxyscrape())
    raw.extend(_fetch_proxifly())
    raw.extend(_fetch_geonode())
    raw.extend(_fetch_monosans())
    raw.extend(_fetch_clearproxy())
    raw.extend(_fetch_goekhandev())
    raw.extend(_fetch_iplocate())

    print(f"\nRaw total before dedup: {len(raw)}", flush=True)

    seen: set[tuple[str, str]] = set()
    unique: list[tuple[str, str]] = []
    for item in raw:
        if item not in seen:
            seen.add(item)
            unique.append(item)

    removed = len(raw) - len(unique)
    print(f"Duplicates removed: {removed}", flush=True)
    print(f"Unique proxies to validate: {len(unique)}", flush=True)
    return unique


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_proxy(protocol: str, proxy_str: str) -> str | None:
    if protocol == "http":
        proxy_url = f"http://{proxy_str}"
    elif protocol == "socks4":
        proxy_url = f"socks4://{proxy_str}"
    elif protocol == "socks5":
        proxy_url = f"socks5://{proxy_str}"
    else:
        return None

    proxies = {"http": proxy_url, "https": proxy_url}
    try:
        response = requests.get(
            TEST_URL,
            proxies=proxies,
            timeout=TIMEOUT,
            headers=REQUEST_HEADERS,
        )
        if response.status_code in (200, 403, 429):
            return proxy_url
    except Exception:
        pass
    return None


def validate_proxies(proxy_list: list[tuple[str, str]]) -> list[str]:
    print(f"\nValidating {len(proxy_list)} proxies ({MAX_WORKERS} threads, {TIMEOUT}s timeout)...", flush=True)
    live = []
    completed = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(test_proxy, protocol, p): (protocol, p) for protocol, p in proxy_list}
        for future in as_completed(futures):
            completed += 1
            result = future.result()
            if result:
                live.append(result)
                print(f"  ✅ {result} ({len(live)} live, {completed}/{len(proxy_list)} checked)", flush=True)
            elif completed % 500 == 0:
                print(f"  ... {completed}/{len(proxy_list)} checked, {len(live)} live so far", flush=True)

    return live


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    proxy_list = fetch_proxy_list()
    live_proxies = validate_proxies(proxy_list)

    print(f"\n{'='*40}", flush=True)
    print(f"Live proxies: {len(live_proxies)}/{len(proxy_list)}", flush=True)

    if not live_proxies:
        print("⚠️  No live proxies found — checker will run on runner IP only.", flush=True)
    else:
        with open(PROXIES_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(live_proxies) + "\n")
        print(f"Written {len(live_proxies)} proxies to {PROXIES_FILE}", flush=True)


if __name__ == "__main__":
    main()
