import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT            = Path(__file__).parent
DATA_DIR        = ROOT / "data"
TRANSCRIPTS_DIR = ROOT / "transcripts"
TRANSCRIBE_PY   = ROOT / "transcribe.py"
EXTRACT_PY      = ROOT / "extract.py"


def resolve_videos(paths: list[str]) -> list[Path]:
    if not paths:
        return sorted(DATA_DIR.rglob("*.mov"))

    collected: set[Path] = set()
    for raw in paths:
        p = Path(raw).resolve()
        if not p.exists():
            sys.exit(f"Error: path does not exist: {raw}")
        if not p.is_relative_to(DATA_DIR):
            sys.exit(f"Error: path must be inside {DATA_DIR}: {raw}")
        if p.is_dir():
            collected.update(p.rglob("*.mov"))
        elif p.suffix.lower() == ".mov":
            collected.add(p)
        else:
            sys.exit(f"Error: not a .mov file or directory: {raw}")
    return sorted(collected)


def transcript_path_for(video: Path) -> Path:
    return TRANSCRIPTS_DIR / video.relative_to(DATA_DIR).with_suffix(".txt")


def hash_file(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(cmd: list[str]) -> int:
    print(f"\n$ {' '.join(cmd)}\n", flush=True)
    return subprocess.run(cmd, check=False).returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="process.py",
        description="End-to-end pipeline: transcribe.py then extract.py. "
                    "By default processes only new recordings. With --reclassify, "
                    "re-processes videos whose transcripts still contain 'Unknown Speaker' "
                    "and re-extracts only those transcripts whose content actually changed.",
        epilog=(
            "Examples:\n"
            "  python process.py                          # new recordings across data/\n"
            "  python process.py data/Team                # new recordings under data/Team/\n"
            "  python process.py data/Team/mtg.mov        # one specific video\n"
            "  python process.py --reclassify             # retry all Unknown-Speaker transcripts\n"
            "  python process.py data/Team --reclassify   # retry Unknown-Speaker transcripts under data/Team\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Optional .mov file(s) or sub-directory/-ies inside data/. "
             "Defaults to the entire data/ tree.",
    )
    parser.add_argument(
        "--reclassify",
        action="store_true",
        help="Re-process videos whose transcript still contains 'Unknown Speaker', "
             "then re-extract only those whose transcript content actually changed.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    py = sys.executable

    videos = resolve_videos(args.paths)
    if not videos:
        print("No .mov files matched.")
        return

    if not args.reclassify:
        rc_t = run([py, str(TRANSCRIBE_PY), *args.paths])
        rc_e = run([py, str(EXTRACT_PY)])
        sys.exit(max(rc_t, rc_e))

    before: dict[Path, str | None] = {
        transcript_path_for(v): hash_file(transcript_path_for(v)) for v in videos
    }

    rc_t = run([py, str(TRANSCRIBE_PY), "--reclassify", *args.paths])

    changed = [
        tp for tp, h_before in before.items()
        if (h_after := hash_file(tp)) is not None and h_after != h_before
    ]

    if not changed:
        print("\nNo transcripts changed; nothing to re-extract.")
        sys.exit(rc_t)

    print(f"\n{len(changed)} transcript(s) changed — re-extracting:")
    for tp in changed:
        print(f"  {tp.relative_to(ROOT)}")

    rc_e = run([py, str(EXTRACT_PY), "--force", *(str(p) for p in changed)])
    sys.exit(max(rc_t, rc_e))


if __name__ == "__main__":
    main()
