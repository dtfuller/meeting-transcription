"""
Build a fake repo layout under a tmp_path for filesystem tests.
"""
from pathlib import Path


def write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def build_sample_tree(root: Path) -> None:
    data = root / "data"
    transcripts = root / "transcripts"
    information = root / "information"
    to_use = root / "known-names" / "to-use"
    to_classify = root / "known-names" / "to-classify"

    # A fully-processed meeting
    (data / "multiturbo").mkdir(parents=True)
    (data / "multiturbo" / "2026-04-14 17-00-43.mov").write_bytes(b"\x00" * 16)
    write(transcripts / "multiturbo" / "2026-04-14 17-00-43.txt",
          "[00:00:00 David Fuller] hola\n[00:00:05 Darwin Henao] hola\n")
    write(information / "multiturbo" / "2026-04-14 17-00-43-knowledge.md", "# K\n")
    write(information / "multiturbo" / "2026-04-14 17-00-43-commitments.md", "# C\n")

    # A meeting with Unknown Speaker still in the transcript
    (data / "multiturbo" / "2026-04-16 17-01-16.mov").write_bytes(b"\x00" * 16)
    write(transcripts / "multiturbo" / "2026-04-16 17-01-16.txt",
          "[00:00:15 Darwin Henao] hola\n[00:01:08 Unknown Speaker 1] …\n")
    write(information / "multiturbo" / "2026-04-16 17-01-16-knowledge.md", "# K\n")
    write(information / "multiturbo" / "2026-04-16 17-01-16-commitments.md", "# C\n")

    # A meeting with no transcript yet
    (data / "check-in").mkdir(parents=True)
    (data / "check-in" / "2026-04-17 09-00-00.mov").write_bytes(b"\x00" * 16)

    # Known speakers
    to_use.mkdir(parents=True)
    (to_use / "David Fuller.mov").write_bytes(b"\x00")
    (to_use / "David Fuller - 2026-01-15.mov").write_bytes(b"\x00")
    (to_use / "Darwin Henao.mov").write_bytes(b"\x00")

    # Clips awaiting labels
    to_classify.mkdir(parents=True)
    (to_classify / "Unknown Speaker 1 - 2026-04-16 17-01-16 - 01m08s.mov").write_bytes(b"\x00")
    (to_classify / "Unknown Speaker 2 - 2026-04-16 17-01-16 - 03m22s.mov").write_bytes(b"\x00")
