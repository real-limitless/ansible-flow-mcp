"""Sleep time for spoke join retries.

attempt 0 waits 1 second. Later attempts wait a random value from 1 second
through a ceiling that doubles up to 60 seconds.
"""

from __future__ import annotations

import random
import sys

CAP = 60


def backoff_seconds(attempt: int, *, cap: int = CAP, rng: random.Random | None = None) -> int:
    step = min(16, max(0, int(attempt)))
    ceiling = max(1, min(cap, 2**step))
    picker = rng if rng is not None else random
    return picker.randint(1, ceiling)


def main() -> None:
    raw = sys.argv[1] if len(sys.argv) > 1 else "0"
    print(backoff_seconds(int(raw)))


if __name__ == "__main__":
    main()
