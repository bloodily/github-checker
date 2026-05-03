import json
import itertools
import os
import string

RESULTS_FILE = os.environ.get("RESULTS_FILE", "results.json")
OUTPUT_FILE = os.environ.get("USERNAMES_FILE", "usernames.txt")
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", 100))

CHARSET = string.ascii_lowercase + string.digits + "-"

def load_checked() -> set[str]:
    """Load all previously checked usernames from results.json."""
    if not os.path.exists(RESULTS_FILE):
        return set()
    with open(RESULTS_FILE) as f:
        data = json.load(f)
    checked = set()
    for key in ("available", "taken", "errored"):
        checked.update(data.get(key, []))
    return checked


def is_valid(username: str) -> bool:
    """GitHub username rules: 1-39 chars, letters/digits/hyphens, no leading/trailing or consecutive hyphens."""
    if not (3 <= len(username) <= 4):
        return False
    if username.startswith("-") or username.endswith("-"):
        return False
    if "--" in username:
        return False
    return True


def all_combinations() -> list[str]:
    combos = []
    for length in (1, 2, 3, 4):
        for combo in itertools.product(CHARSET, repeat=length):
            username = "".join(combo)
            if is_valid(username):
                combos.append(username)
    return combos


def generate_batch(checked: set[str], batch_size: int) -> list[str]:
    all_names = all_combinations()
    unchecked = [u for u in all_names if u not in checked]
    print(f"Total valid combinations : {len(all_names):,}")
    print(f"Already checked          : {len(checked):,}")
    print(f"Remaining                : {len(unchecked):,}")

    if not unchecked:
        print("All combinations have been checked!")
        return []

    # Prioritize shorter usernames first
    unchecked.sort(key=lambda u: (len(u), u))
    return unchecked[:batch_size]


def main():
    checked = load_checked()
    batch = generate_batch(checked, BATCH_SIZE)

    if not batch:
        print("Nothing new to check.")
        return

    with open(OUTPUT_FILE, "w") as f:
        f.write("\n".join(batch) + "\n")

    print(f"\nWrote {len(batch)} usernames to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
