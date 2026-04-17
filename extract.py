import argparse
import os
import re
import sys
import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

TRANSCRIPTS_DIR = Path(__file__).parent / "transcripts"
INFORMATION_DIR = Path(__file__).parent / "information"
EXTRACT_MODEL   = "claude-opus-4-6"

SYSTEM_PROMPT = """<role>
Eres un experto product manager senior, especialista en estrategia, negocios y desarrollo de productos para el mundo de logística de última milla, gig ecónomy, y applicaciones y productos tecnológicos. Actualmente, trabajas en Rappi.
</role>
<task>
A partir de las transcripciones de distintas reuniones, extraer y formular el conocimiento transmitido para ser agregado a la base de conocimiento, así como los compromisos, responsables y fechas comprometidas para ayudar a la gestión propia.
</task>
<audience>
Profesionales senior dentro de la empresa.
</audience>
<format>
Genera tu respuesta con dos secciones claramente delimitadas:

<knowledge>
[Contenido del archivo knowledge en formato markdown]
</knowledge>

<commitments>
[Contenido del archivo commitments en formato markdown]
</commitments>

El archivo knowledge debe documentar el conocimiento transmitido en la reunión: contexto, decisiones, aprendizajes, estado de iniciativas, y cualquier información relevante para la base de conocimiento.

El archivo commitments debe listar los compromisos adquiridos con: responsable, descripción del compromiso, fecha comprometida (si se menciona), y estado implícito.
</format>"""


def load_client() -> anthropic.Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)
    return anthropic.Anthropic(api_key=api_key)


def output_paths(transcript_path: Path) -> tuple[Path, Path]:
    rel = transcript_path.relative_to(TRANSCRIPTS_DIR)
    stem = rel.stem  # e.g. "2026-01-15 12-37-03"
    subdir = INFORMATION_DIR / rel.parent
    knowledge_path   = subdir / f"{stem}-knowledge.md"
    commitments_path = subdir / f"{stem}-commitments.md"
    return knowledge_path, commitments_path


def needs_processing(transcript_path: Path, force: bool = False) -> bool:
    if force:
        return True
    k, c = output_paths(transcript_path)
    return not (k.exists() and c.exists())


def parse_response(text: str) -> tuple[str, str]:
    knowledge_match   = re.search(r"<knowledge>(.*?)</knowledge>", text, re.DOTALL)
    commitments_match = re.search(r"<commitments>(.*?)</commitments>", text, re.DOTALL)

    knowledge   = knowledge_match.group(1).strip()   if knowledge_match   else text
    commitments = commitments_match.group(1).strip() if commitments_match else ""

    return knowledge, commitments


def extract(transcript_path: Path, client: anthropic.Anthropic) -> None:
    knowledge_path, commitments_path = output_paths(transcript_path)
    knowledge_path.parent.mkdir(parents=True, exist_ok=True)

    transcript_text = transcript_path.read_text(encoding="utf-8")
    date_label = transcript_path.stem  # e.g. "2026-01-15 12-37-03"

    user_message = f"Fecha de la reunión: {date_label}\n\nTranscripción:\n\n{transcript_text}"

    with client.messages.stream(
        model=EXTRACT_MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        response = stream.get_final_message()

    # Extract text content from response (skip thinking blocks)
    full_text = ""
    for block in response.content:
        if hasattr(block, "text"):
            full_text += block.text

    knowledge, commitments = parse_response(full_text)

    knowledge_path.write_text(knowledge, encoding="utf-8")
    commitments_path.write_text(commitments, encoding="utf-8")


def format_eta(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    m, s = divmod(int(seconds), 60)
    if m < 60:
        return f"{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{h}h {m}m"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="extract.py",
        description="Extract knowledge + commitments from meeting transcripts using Claude.",
        epilog=(
            "Examples:\n"
            "  python extract.py                               # all new transcripts\n"
            "  python extract.py transcripts/Team              # only that sub-directory\n"
            "  python extract.py transcripts/Team/mtg.txt      # only that one transcript\n"
            "  python extract.py transcripts/Team/mtg.txt --force  # overwrite existing outputs\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Optional .txt file(s) or sub-directory/-ies inside transcripts/ to process. "
             "Defaults to the entire transcripts/ tree.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-extract even when both -knowledge.md and -commitments.md already exist.",
    )
    return parser.parse_args()


def resolve_transcripts(paths: list[str]) -> list[Path]:
    if not paths:
        return sorted(TRANSCRIPTS_DIR.rglob("*.txt"))

    collected: set[Path] = set()
    for raw in paths:
        p = Path(raw).resolve()
        if not p.exists():
            sys.exit(f"Error: path does not exist: {raw}")
        if not p.is_relative_to(TRANSCRIPTS_DIR):
            sys.exit(f"Error: path must be inside {TRANSCRIPTS_DIR}: {raw}")
        if p.is_dir():
            collected.update(p.rglob("*.txt"))
        elif p.suffix.lower() == ".txt":
            collected.add(p)
        else:
            sys.exit(f"Error: not a .txt file or directory: {raw}")
    return sorted(collected)


def main() -> None:
    args = parse_args()
    client = load_client()

    all_transcripts = resolve_transcripts(args.paths)
    if not all_transcripts:
        print("No transcripts matched.")
        return

    to_process = [t for t in all_transcripts if needs_processing(t, args.force)]

    if not to_process:
        print("All transcripts already extracted. Nothing to do.")
        return

    skipped = len(all_transcripts) - len(to_process)
    print(f"Found {len(all_transcripts)} transcript(s). "
          f"{skipped} already done, {len(to_process)} to process.")
    if args.force:
        print("[--force] will overwrite existing knowledge/commitments files")
    print()

    times: list[float] = []

    for i, transcript in enumerate(to_process, 1):
        rel = transcript.relative_to(TRANSCRIPTS_DIR)
        print(f"[{i}/{len(to_process)}] {rel} ...", end=" ", flush=True)

        start = time.time()
        extract(transcript, client)
        elapsed = time.time() - start

        times.append(elapsed)
        avg = sum(times) / len(times)
        remaining = avg * (len(to_process) - i)

        k, c = output_paths(transcript)
        print(f"done ({elapsed:.0f}s) — ETA {format_eta(remaining)}")
        print(f"         knowledge  → {k.relative_to(Path(__file__).parent)}")
        print(f"         commitments→ {c.relative_to(Path(__file__).parent)}")

    print(f"\nDone. Processed {len(to_process)} transcript(s).")


if __name__ == "__main__":
    main()
