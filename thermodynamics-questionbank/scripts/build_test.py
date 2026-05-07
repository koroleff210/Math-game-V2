from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
EXPORT_DIR = ROOT / "exports"
HTML_DIR = EXPORT_DIR / "html"
MANIFEST_DIR = EXPORT_DIR / "manifests"
QUESTIONS_JSON = DATA_DIR / "questions.json"
SOURCE_DIR = ROOT.parent
CONFIG_PATH = ROOT / "bank_config.json"
CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
SOURCE_ASSETS = SOURCE_DIR / CONFIG["source_assets_dir"]
KATEX_CSS = SOURCE_ASSETS / "katex.min.css"
ASSET_PATTERN = re.escape(f"./{CONFIG['source_assets_dir']}/")
PREP_PAPERS_DIR = SOURCE_DIR / "Prep papers"

DIFFICULTY_ICON_MAP = {
    "1-plane-15E688-18px.png": "simple.png",
    "2-planes-00BBAF-18px.png": "standard.png",
    "3-planes-3F63E0-18px.png": "hard.png",
    "4-planed-442B7E-18px.png": "very hard.png",
    "5-planes-3B1E54-18px.png": "very hard.png",
}

BROWSERS = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
]


def find_browser() -> Path:
    for browser in BROWSERS:
        if browser.exists():
            return browser
    raise SystemExit("No supported browser found for HTML-to-PDF printing.")


def file_uri(path: Path) -> str:
    return path.resolve().as_uri()


def asset_uri(name: str) -> str:
    return file_uri(SOURCE_ASSETS / name)


def prep_asset_uri(name: str) -> str:
    return file_uri(PREP_PAPERS_DIR / name)


def replace_difficulty_badges(html: str) -> str:
    pattern = re.compile(
        r'<picture[^>]*>.*?<img[^>]+src="' + ASSET_PATTERN + r'([^"]+)"[^>]*>.*?</picture>',
        flags=re.I | re.S,
    )

    def repl(match: re.Match[str]) -> str:
        replacement = DIFFICULTY_ICON_MAP.get(match.group(1))
        if not replacement:
            return match.group(0)
        return f'<img class="difficulty-badge" src="{prep_asset_uri(replacement)}" alt="{replacement}">'

    return pattern.sub(repl, html)


def localize_assets(html: str) -> str:
    def repl(match: re.Match[str]) -> str:
        return asset_uri(match.group(1))

    html = replace_difficulty_badges(html)
    return re.sub(rf"{ASSET_PATTERN}([^\"')\s]+)", repl, html)


def load_questions() -> list[dict]:
    return json.loads(QUESTIONS_JSON.read_text(encoding="utf-8"))


def get_questions_by_ids(ids: list[str]) -> list[dict]:
    question_map = {q["id"]: q for q in load_questions()}
    missing = [qid for qid in ids if qid not in question_map]
    if missing:
        raise SystemExit(f"Unknown question IDs: {', '.join(missing)}")
    return [question_map[qid] for qid in ids]


def wrap_document(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <link rel="stylesheet" href="{file_uri(KATEX_CSS)}">
  <style>
    @page {{
      size: A4;
      margin: 12mm 13mm 12mm 13mm;
    }}

    :root {{
      --ink: #18232d;
      --muted: #62707d;
      --rule: #d9e1ea;
      --accent: #144b73;
      --soft: #f7fafc;
    }}

    * {{
      box-sizing: border-box;
    }}

    html, body {{
      margin: 0;
      padding: 0;
      color: var(--ink);
      font-family: "Segoe UI", Arial, sans-serif;
      font-size: 11.2pt;
      line-height: 1.34;
      background: white;
    }}

    .question,
    .section-break {{
      break-before: page;
      page-break-before: always;
      min-height: 262mm;
    }}

    .question:first-of-type,
    .section-break:first-of-type {{
      break-before: auto;
      page-break-before: auto;
    }}

    .question-header {{
      display: flex;
      align-items: center;
      gap: 4mm;
      margin: 0 0 5mm 0;
      padding-bottom: 3mm;
      border-bottom: 1px solid var(--rule);
    }}

    .question-title {{
      margin: 0;
      color: var(--accent);
      font-size: 16pt;
      font-weight: 700;
      letter-spacing: 0.01em;
    }}

    .difficulty-badge {{
      width: 12mm;
      height: 12mm;
      min-width: 12mm;
      min-height: 12mm;
      margin: 0;
      object-fit: contain;
    }}

    .section-break {{
      display: flex;
      align-items: center;
      justify-content: center;
    }}

    .section-card {{
      width: 100%;
      border: 2px solid #dce6ef;
      border-radius: 18px;
      padding: 14mm 10mm;
      text-align: center;
      background: linear-gradient(180deg, #f9fbfe 0%, #ffffff 100%);
    }}

    .section-card h2 {{
      margin: 0 0 3mm 0;
      font-size: 22pt;
      color: var(--accent);
    }}

    .section-card p {{
      margin: 0;
      color: var(--muted);
      font-size: 11pt;
    }}

    p {{
      margin: 0 0 3.2mm 0;
    }}

    img {{
      display: block;
      max-width: min(100%, 145mm);
      width: auto;
      height: auto;
      max-height: 82mm;
      margin: 3.2mm auto;
      object-fit: contain;
      page-break-inside: avoid;
    }}

    picture {{
      display: block;
      width: 100%;
    }}

    table {{
      width: auto;
      max-width: 100%;
      border-collapse: collapse;
      margin: 3.2mm auto;
      font-size: 9.4pt;
    }}

    td, th {{
      border: 1px solid #6b7785;
      padding: 2.4mm 2.6mm;
      vertical-align: top;
    }}

    ol, ul {{
      margin: 3mm 0 3mm 0;
      padding-left: 0;
    }}

    li {{
      margin: 0 0 2mm 0;
    }}

    .mcq ol {{
      list-style: none;
    }}

    .mcq ol li {{
      padding: 3.2mm 4mm;
      border: 1px solid #d0d8e2;
      border-radius: 10px;
      background: var(--soft);
    }}

    .mcq table {{
      width: 100%;
      max-width: 160mm;
      font-size: 9.4pt;
    }}

    .subpart {{
      margin: 0 0 5mm 0;
      padding-bottom: 4mm;
      border-bottom: 1px dashed #e2e8ef;
    }}

    .subpart:last-child {{
      border-bottom: none;
      padding-bottom: 0;
    }}

    .subpart-label {{
      margin: 0 0 2mm 0;
      font-size: 10pt;
      font-weight: 700;
      color: var(--muted);
    }}

    .answer-inline {{
      font-size: 12pt;
      font-weight: 700;
      color: var(--accent);
    }}

    .video-ref {{
      margin-top: 1.5mm;
      font-size: 8.8pt;
      color: var(--muted);
      word-break: break-all;
    }}

    h4 {{
      display: none;
    }}

    .question.structured p[style*="text-align: right"] {{
      color: var(--muted);
      font-size: 9.3pt;
    }}

    .et_pb_toggle,
    .fluid-width-video-wrapper,
    iframe {{
      display: none !important;
    }}
  </style>
</head>
<body>
{body}
</body>
</html>
"""


def strip_original_header(body_html: str) -> tuple[str, str]:
    badge_match = re.search(r'<img class="difficulty-badge" src="[^"]+" alt="[^"]+">', body_html, flags=re.I)
    badge_html = badge_match.group(0) if badge_match else ""
    body_html = re.sub(
        r'<div class="et_pb_text_inner"><h4>Question\s+\d+&nbsp;.*?</h4></div>',
        "",
        body_html,
        count=1,
        flags=re.I | re.S,
    )
    return badge_html, body_html


def question_block(question: dict, display_number: int) -> str:
    body = localize_assets(question["question_html"])
    badge_html, body = strip_original_header(body)
    kind_class = "mcq" if question["type"] == "mcq" else "structured"
    return f"""
<section class="question {kind_class}">
  <div class="question-header">
    <div class="question-title">Question {display_number}</div>
    {badge_html}
  </div>
  {body}
</section>
"""


def answer_block(question: dict, display_number: int) -> str:
    if question["type"] == "mcq":
        inner = f'<p class="answer-inline">Correct answer: {question["answer"]}</p>'
    else:
        chunks = []
        for subpart in question["subparts"]:
            answer_html = localize_assets(subpart["answer_html"])
            video = f'<div class="video-ref">Video: {subpart["video_solution"]}</div>' if subpart.get("video_solution") else ""
            chunks.append(
                f"""
<div class="subpart">
  <div class="subpart-label">{subpart['label']}</div>
  {answer_html}
  {video}
</div>
"""
            )
        inner = "\n".join(chunks)
    return f"""
<section class="question structured">
  <div class="question-header">
    <div class="question-title">Question {display_number}</div>
  </div>
  {inner}
</section>
"""


def section_break(title: str, subtitle: str) -> str:
    return f"""
<section class="section-break">
  <div class="section-card">
    <h2>{title}</h2>
    <p>{subtitle}</p>
  </div>
</section>
"""


def print_to_pdf(browser: Path, html_path: Path, pdf_path: Path) -> None:
    cmd = [
        str(browser),
        "--headless=new",
        "--disable-gpu",
        "--allow-file-access-from-files",
        "--print-to-pdf-no-header",
        "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_path}",
        file_uri(html_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"Build browser-rendered PDFs from the {CONFIG.get('title', ROOT.name)}.")
    parser.add_argument("--ids", nargs="+", required=True, help="Question IDs such as P1-Q03 P1-Q11 P2-Q04")
    parser.add_argument("--name", required=True, help="Output name prefix, for example sample_test")
    parser.add_argument("--title", default=f"{CONFIG.get('title', ROOT.name)} Custom Test", help="Internal title only")
    parser.add_argument("--output-dir", default=str(EXPORT_DIR), help="Directory where PDFs should be written")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    browser = find_browser()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)

    questions = get_questions_by_ids(args.ids)
    mcq_questions = [q for q in questions if q["paper"] == "Paper 1"]
    structured_questions = [q for q in questions if q["paper"] == "Paper 2"]

    question_sections = []
    if mcq_questions:
        question_sections.append(section_break("Multiple Choice", "Paper 1"))
        for i, q in enumerate(mcq_questions, start=1):
            question_sections.append(question_block(q, i))
    if structured_questions:
        question_sections.append(section_break("Structured Questions", "Paper 2"))
        for i, q in enumerate(structured_questions, start=1):
            question_sections.append(question_block(q, i))

    answer_sections = []
    if mcq_questions:
        answer_sections.append(section_break("Multiple Choice Answers", "Paper 1"))
        for i, q in enumerate(mcq_questions, start=1):
            answer_sections.append(answer_block(q, i))
    if structured_questions:
        answer_sections.append(section_break("Structured Answers", "Paper 2"))
        for i, q in enumerate(structured_questions, start=1):
            answer_sections.append(answer_block(q, i))

    question_html_path = HTML_DIR / f"{args.name}_questions.html"
    answer_html_path = HTML_DIR / f"{args.name}_answers.html"
    question_pdf = output_dir / f"{args.name}_questions.pdf"
    answer_pdf = output_dir / f"{args.name}_answers.pdf"
    manifest = MANIFEST_DIR / f"{args.name}.json"

    question_html_path.write_text(wrap_document(args.title, "\n".join(question_sections)), encoding="utf-8")
    answer_html_path.write_text(wrap_document(f"{args.title} - Answers", "\n".join(answer_sections)), encoding="utf-8")

    print_to_pdf(browser, question_html_path, question_pdf)
    print_to_pdf(browser, answer_html_path, answer_pdf)

    manifest.write_text(
        json.dumps(
            {
                "name": args.name,
                "title": args.title,
                "ids": args.ids,
                "browser": str(browser),
                "question_html": str(question_html_path),
                "answer_html": str(answer_html_path),
                "question_pdf": str(question_pdf),
                "answer_pdf": str(answer_pdf),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(json.dumps({"question_pdf": str(question_pdf), "answer_pdf": str(answer_pdf)}, indent=2))


if __name__ == "__main__":
    main()
