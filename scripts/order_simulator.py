"""
Simulated live order stream for demos (writes to live.order_stream only).

Examples:
    python scripts/order_simulator.py                      # steady traffic
    python scripts/order_simulator.py --incident cancel_spike --duration 120
    python scripts/order_simulator.py --rate 6 --interval 1

Open the "Live monitor" tab in the dashboard to watch it. Start steady traffic
for a few minutes first so the monitor has a baseline, then run an incident.
"""

import argparse
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.live import INCIDENTS, simulate_batch  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--rate", type=int, default=3, help="orders per tick")
    parser.add_argument("--interval", type=float, default=2.0, help="seconds per tick")
    parser.add_argument("--incident", choices=INCIDENTS, default="none")
    parser.add_argument(
        "--duration", type=int, default=0, help="stop after N seconds (0 = run until Ctrl+C)"
    )
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    started = time.monotonic()
    total = 0

    print(f"Simulating {args.rate} orders every {args.interval}s "
          f"(incident: {args.incident}). Ctrl+C to stop.")

    try:
        while True:
            total += simulate_batch(args.rate, incident=args.incident, rng=rng)
            print(f"\rorders written: {total}", end="", flush=True)

            if args.duration and time.monotonic() - started >= args.duration:
                break

            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass

    print(f"\nDone. {total} simulated orders written to live.order_stream.")


if __name__ == "__main__":
    main()
