"""Emits three lines with a tiny delay, then exits. Used for runner tests."""
import sys
import time

for line in ("starting", "middle", "done"):
    print(line, flush=True)
    time.sleep(0.05)
sys.exit(0)
