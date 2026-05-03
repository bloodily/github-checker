import json
import os
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

USERNAMES_FILE = os.environ.get("USERNAMES_FILE", "usernames.txt")
RESULTS_FILE = os.environ.get("RESULTS_FILE", "results.json")
PROXIES_FILE = os.environ.get("PROXIES_FILE", "proxies.txt")
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", 20))
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", 10))
API_VERSION = os.environ.get("GITHUB_API_VERSION", "2022-11-28")
USER_AGENT = os.environ.get("USER_AGENT", "github-username-checker")

ENDPOINT_TEMPLATE = "https://api.github.com/users/{username}"
PERMANENT_CODES = {422}
BASE_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": API_VERSION,
    "User-Agent": USER_AGENT,
}
if GITHUB_TOKEN:
    BASE_HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"


def load_proxies(filepath: str) -> list:
    """Returns [None] (runner IP) + list of proxy dicts."""
    proxies = [None]
    if not os.path.exists(filepath):
        print("No proxies file found — running on runner IP only.", flush=True)
        return proxies
    with open(filepath) as f:
        lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    for line in lines:
        proxies.append({"http": line, "https": line})
    print(f"Loaded {len(proxies) - 1} proxies (+ runner IP).", flush=True)
    return proxies


class ProxyPool:
    """Thread-safe round-robin proxy pool with per-proxy cooldown tracking."""

    def __init__(self, proxies: list):
        self.proxies = proxies
        self.lock = threading.Lock()
        self.index = 0
        self.available_at = [0.0] * len(proxies)

    def get(self) -> tuple[int, dict | None]:
        """Returns (proxy_index, proxy) for the next available proxy."""
        with self.lock:
            now = time.time()
            for _ in range(len(self.proxies)):
                idx = self.index % len(self.proxies)
                self.index += 1
                if self.available_at[idx] <= now:
                    return idx, self.proxies[idx]

            idx = min(range(len(self.proxies)), key=lambda i: self.available_at[i])
            wait = max(0.0, self.available_at[idx] - now)
            if wait > 0:
                print(f"  All proxies cooling down. Waiting {wait:.1f}s...", flush=True)
                time.sleep(wait)
            return idx, self.proxies[idx]

    def mark_unavailable(self, idx: int, retry_after: float):
        with self.lock:
            self.available_at[idx] = max(self.available_at[idx], time.time() + retry_after)
            print(f"  Cooling down {self.label(idx)} for {retry_after:.0f}s", flush=True)

    def label(self, idx: int) -> str:
        if self.proxies[idx] is None:
            return "runner IP"
        return list(self.proxies[idx].values())[0]


def parse_retry_after(response: requests.Response) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return max(1.0, float(retry_after))
        except ValueError:
            pass

    reset_at = response.headers.get("X-RateLimit-Reset")
    if reset_at:
        try:
            return max(1.0, float(reset_at) - time.time())
        except ValueError:
            pass

    return 60.0


def check_username(username: str, pool: ProxyPool) -> dict:
    url = ENDPOINT_TEMPLATE.format(username=username)

    for _attempt in range(1, 6):
        idx, proxy = pool.get()
        try:
            response = requests.get(
                url,
                headers=BASE_HEADERS,
                proxies=proxy,
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code == 200:
                return {"username": username, "available": False, "status": "ok"}

            if response.status_code == 404:
                return {"username": username, "available": True, "status": "ok"}

            if response.status_code in {403, 429}:
                retry_after = parse_retry_after(response)
                pool.mark_unavailable(idx, retry_after)
                continue

            if response.status_code in PERMANENT_CODES:
                return {"username": username, "available": None, "status": f"permanent_{response.status_code}"}

            print(f"  [{username}] unexpected {response.status_code}", flush=True)
            return {"username": username, "available": None, "status": f"error_{response.status_code}"}

        except (requests.exceptions.Timeout, requests.exceptions.ProxyError, requests.exceptions.ConnectionError):
            pool.mark_unavailable(idx, 5)
        except requests.exceptions.RequestException as e:
            print(f"  [{username}] request error: {e}", flush=True)
            return {"username": username, "available": None, "status": "transient_request_error"}

    return {"username": username, "available": None, "status": "transient_max_retries"}


def load_usernames(filepath: str) -> list[str]:
    with open(filepath, "r") as f:
        return [line.strip() for line in f if line.strip()]


def load_existing_results() -> dict:
    if not os.path.exists(RESULTS_FILE):
        return {"available": [], "taken": [], "errored": []}
    with open(RESULTS_FILE) as f:
        return json.load(f)


def save_results(available: list, taken: list, errored: list):
    final_results = {"available": available, "taken": taken, "errored": errored}
    with open(RESULTS_FILE, "w") as f:
        json.dump(final_results, f, indent=2)
    print(f"Results saved to {RESULTS_FILE}", flush=True)


def main():
    proxies = load_proxies(PROXIES_FILE)
    pool = ProxyPool(proxies)

    usernames = load_usernames(USERNAMES_FILE)
    print(f"Checking {len(usernames)} GitHub usernames with {MAX_WORKERS} workers...", flush=True)
    if GITHUB_TOKEN:
        print("Authenticated GitHub API requests enabled.", flush=True)
    else:
        print("No GITHUB_TOKEN/GH_TOKEN set — using unauthenticated GitHub API requests.", flush=True)

    results = load_existing_results()
    available = results.get("available", [])
    taken = results.get("taken", [])
    errored = results.get("errored", [])

    lock = threading.Lock()
    batch_available = []
    interrupted = threading.Event()

    def handle_signal(signum, frame):
        del signum, frame
        print("\nInterrupted — saving partial results...", flush=True)
        interrupted.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(check_username, u, pool): u for u in usernames}
        for future in as_completed(futures):
            if interrupted.is_set():
                executor.shutdown(wait=False, cancel_futures=True)
                break

            username = futures[future]
            result = future.result()

            with lock:
                if result["available"] is True:
                    available.append(username)
                    batch_available.append(username)
                    print(f"  AVAILABLE  {username}", flush=True)
                elif result["available"] is False:
                    taken.append(username)
                    print(f"  TAKEN      {username}", flush=True)
                elif "transient" in result["status"]:
                    print(f"  RETRYABLE  {username} ({result['status']})", flush=True)
                else:
                    errored.append(username)
                    print(f"  ERRORED    {username} ({result['status']})", flush=True)

    print(f"\n{'=' * 40}", flush=True)
    print(f"Available : {len(batch_available)} — {', '.join(batch_available) or 'none'}", flush=True)
    print(f"Taken     : {len(taken)}", flush=True)
    print(f"Errored   : {len(errored)}", flush=True)

    save_results(available, taken, errored)


if __name__ == "__main__":
    main()
