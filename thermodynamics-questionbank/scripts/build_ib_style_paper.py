from __future__ import annotations

import json
import html as html_lib
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT.parent
EXPORT_DIR = ROOT / "exports"
DATA_DIR = ROOT / "data"
KATEX_CSS = (BASE / "IB Physics - Questionbank - Thermodynamics - Paper Plainz_files" / "katex.min.css").read_text(encoding="utf-8", errors="replace")

P1_SELECTION = [
    "P1-Q01",
    "P1-Q03",
    "P1-Q04",
    "P1-Q05",
    "P1-Q06",
    "P1-Q07",
    "P1-Q08",
    "P1-Q09",
    "P1-Q10",
    "P1-Q11",
    "P1-Q13",
    "P1-Q14",
    "P1-Q15",
    "P1-Q16",
    "P1-Q17",
    "P1-Q25",
]

P2_SELECTION = [
    {"level": 3, "id": "P2-Q01"},
    {"level": 1, "id": "P2-Q03"},
]

BROWSERS = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
]


def file_uri(path: Path) -> str:
    return path.resolve().as_uri()


def find_browser() -> Path:
    for browser in BROWSERS:
        if browser.exists():
            return browser
    raise SystemExit("No supported browser found for printing.")


def load_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def bank_root_for_level(level: int | None = None) -> Path:
    if level is None:
        return ROOT
    return BASE / f"lvl{level}-questionbank"


def load_bank(level: int | None = None) -> tuple[list[dict], dict]:
    bank_root = bank_root_for_level(level)
    questions = load_json(bank_root / "data" / "questions.json")
    config = load_json(bank_root / "bank_config.json")
    return questions, config


def extract_question(level: int | None, qid: str) -> dict:
    questions, config = load_bank(level)
    question = next(q for q in questions if q["id"] == qid)
    item = dict(question)
    item["_config"] = config
    item["_level"] = level
    return item


def localize_assets(html: str, config: dict) -> str:
    source_assets_dir = config["source_assets_dir"]
    html = re.sub(
        rf"\./({re.escape(source_assets_dir)}/[^\"')\s]+)",
        lambda m: file_uri(BASE / m.group(1)),
        html,
    )
    return html


def strip_header(html: str) -> str:
    html = re.sub(
        r'<div class="et_pb_text_inner"><h4>Question\s+\d+&nbsp;.*?</h4></div>',
        "",
        html,
        count=1,
        flags=re.I | re.S,
    )
    html = re.sub(r"^\s*</div>+", "", html)
    return html


def simplify_question_html(html: str) -> str:
    html = re.sub(r"</?div[^>]*>", "", html, flags=re.I)
    html = re.sub(r"</?picture[^>]*>", "", html, flags=re.I)
    html = re.sub(r"<source[^>]*>", "", html, flags=re.I)
    html = re.sub(r"<span style=\"font-weight:\s*400;?\">", "", html, flags=re.I)
    html = re.sub(r"</span>\s*</span>", "</span>", html, flags=re.I)
    return html


def parse_structured_subparts(question_text: str) -> list[dict]:
    lines = [line.strip() for line in question_text.splitlines() if line.strip()]
    subparts: list[dict] = []
    current: dict | None = None
    for line in lines[1:]:
        if re.match(r"^[a-z]\.", line):
            if current:
                subparts.append(current)
            current = {"label": line[0], "marks": 2}
        elif re.fullmatch(r"\[(\d+)\]", line):
            if current:
                current["marks"] = int(line.strip("[]"))
    if current:
        subparts.append(current)
    return subparts


def answer_box_height(marks: int) -> int:
    return {
        1: 26,
        2: 38,
        3: 54,
        4: 70,
    }.get(marks, 82 if marks >= 5 else 40)


def cover_page() -> str:
    return """
<section class="cover-page">
  <div class="ib-badge">
    <div class="ib-logo">ib</div>
    <div class="ib-badge-text">
      <div>Diploma Programme</div>
      <div>Programme du diplome</div>
      <div>Programa del Diploma</div>
    </div>
  </div>
  <div class="cover-title">
    <div>Physics</div>
    <div>Slightly above standard level</div>
    <div>Thermodynamics Practice Paper</div>
  </div>
  <div class="cover-meta">
    <div>The last day summative, very official so has no errors in tasks. At all. 100%.</div>
    <div class="session-row">
      <span>Candidate session number</span>
      <span class="session-boxes">□□□□□□□□</span>
    </div>
  </div>
  <div class="time-line">estimated time 20-200 min</div>
  <div class="instructions">
    <div class="head">Instructions to candidates</div>
    <ul>
      <li>Write your session number in the boxes above.</li>
      <li>Answer all questions.</li>
      <li>For Section A, select one answer for each multiple-choice question.</li>
      <li>For Section B, answers should be written in the spaces provided.</li>
      <li>A calculator is required for this paper.</li>
      <li>A clean copy of the physics data booklet is required for this paper.</li>
    </ul>
  </div>
</section>
"""


def section_heading_block(title: str, subtitle: str) -> str:
    return f"""
<div class="section-intro">
  <h1>{title}</h1>
  <p>{subtitle}</p>
</div>
"""


def render_p1_question(display_number: int, question: dict, heading_html: str = "") -> str:
    body = render_p1_text_body(question)
    return f"""
<section class="paper1-question">
  {heading_html}
  <div class="paper1-row">
    <div class="question-number">{display_number}.</div>
    <div class="question-content">
      {body}
    </div>
  </div>
</section>
"""


def text_to_html(text: str) -> str:
    return html_lib.escape(text)


def localize_image_name(question: dict, image_name: str) -> str:
    source_assets_dir = question["_config"]["source_assets_dir"]
    return file_uri(BASE / source_assets_dir / image_name)


def render_p1_text_body(question: dict) -> str:
    qid = question["id"]
    lines = [line.strip() for line in question["question_text"].splitlines() if line.strip()]
    content = lines[1:]
    images_html = "".join(
        f'<img src="{localize_image_name(question, name)}" alt="">'
        for name in question.get("images", [])
    )

    if qid == "P1-Q06":
        return f"""
<div class="mcq-stem">{text_to_html(content[0])}</div>
<table class="mcq-table">
  <tr><th></th><th>{text_to_html(content[1])}</th><th>{text_to_html(content[2])}</th></tr>
  <tr><td>A</td><td>{text_to_html(content[4])}</td><td>{text_to_html(content[5])}</td></tr>
  <tr><td>B</td><td>{text_to_html(content[7])}</td><td>{text_to_html(content[8])}</td></tr>
  <tr><td>C</td><td>{text_to_html(content[10])}</td><td>{text_to_html(content[11])}</td></tr>
  <tr><td>D</td><td>{text_to_html(content[13])}</td><td>{text_to_html(content[14])}</td></tr>
</table>
"""

    if qid == "P1-Q17":
        return f"""
<div class="mcq-stem">{text_to_html(content[0])}</div>
<table class="mcq-table">
  <tr><th></th><th>{text_to_html(content[1])}</th><th>{text_to_html(content[2])}</th></tr>
  <tr><td>A</td><td>{text_to_html(content[4])}</td><td>{text_to_html(content[5])}</td></tr>
  <tr><td>B</td><td>{text_to_html(content[7])}</td><td>{text_to_html(content[8])}</td></tr>
  <tr><td>C</td><td>{text_to_html(content[10])}</td><td>{text_to_html(content[11])}</td></tr>
  <tr><td>D</td><td>{text_to_html(content[13])}</td><td>{text_to_html(content[14])}</td></tr>
</table>
"""

    stem_lines = content[:-4]
    option_lines = content[-4:]
    stem_html = "".join(f"<p>{text_to_html(line)}</p>" for line in stem_lines)
    options_html = "".join(
        f"<li>{text_to_html(option)}</li>" for option in option_lines
    )
    return f"""
<div class="mcq-stem">
  {stem_html}
  {images_html}
</div>
<ol class="mcq-options">
  {options_html}
</ol>
"""


def render_answer_space(question: dict) -> str:
    subparts = parse_structured_subparts(question["question_text"])
    if not subparts:
        return '<div class="answer-space single-box"><div class="writing-lines" style="height:70mm;"></div></div>'

    blocks = []
    for part in subparts:
        height = answer_box_height(part["marks"])
        blocks.append(
            f"""
<div class="answer-space">
  <div class="answer-label">({part['label']}) [{part['marks']}]</div>
  <div class="writing-lines" style="height:{height}mm;"></div>
</div>
"""
        )
    return "".join(blocks)


def render_p2_question(display_number: int, question: dict, heading_html: str = "") -> str:
    body = strip_header(localize_assets(question["question_html"], question["_config"]))
    return f"""
<section class="paper2-question">
  <div class="paper2-head">
    <div class="question-number">{display_number}.</div>
    <div class="question-title">Answer all questions. Answers must be written within the answer boxes provided.</div>
  </div>
  <div class="question-content structured">
    {body}
  </div>
  {render_answer_space(question)}
</section>
"""


def wrap_document(body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Thermodynamics IB-style Practice Paper</title>
  <script>
    window.MathJax = {{
      tex: {{ inlineMath: [['$', '$'], ['\\\\(', '\\\\)']] }},
      svg: {{ fontCache: 'none' }}
    }};
  </script>
  <script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"></script>
  <style>
    {KATEX_CSS}
    @page {{
      size: A4;
      margin: 14mm 16mm 14mm 16mm;
    }}
    :root {{
      --ink: #222;
      --muted: #666;
      --rule: #999;
    }}
    * {{ box-sizing: border-box; }}
    html, body {{
      margin: 0;
      padding: 0;
      color: var(--ink);
      font-family: Arial, Helvetica, sans-serif;
      font-size: 11pt;
      line-height: 1.3;
      background: white;
    }}
    body {{
      counter-reset: page;
    }}
    .cover-page {{
      min-height: 232mm;
      position: relative;
    }}
    .ib-badge {{
      position: absolute;
      top: 8mm;
      right: 0;
      display: flex;
      align-items: center;
      gap: 3mm;
      color: white;
      background: linear-gradient(90deg, #7b7b7b, #555);
      border-radius: 18px 0 0 18px;
      padding: 3mm 6mm 3mm 3mm;
      min-width: 72mm;
    }}
    .ib-logo {{
      width: 15mm;
      height: 15mm;
      border-radius: 50%;
      background: white;
      color: #666;
      font-weight: 700;
      font-size: 12pt;
      display: flex;
      align-items: center;
      justify-content: center;
      text-transform: lowercase;
    }}
    .ib-badge-text {{
      font-size: 7pt;
      line-height: 1.15;
    }}
    .cover-title {{
      margin-top: 28mm;
      font-size: 16pt;
      font-weight: 700;
    }}
    .cover-meta {{
      margin-top: 20mm;
      font-size: 10.5pt;
    }}
    .session-row {{
      margin-top: 8mm;
      display: flex;
      justify-content: flex-end;
      align-items: center;
      gap: 4mm;
      font-size: 10pt;
    }}
    .session-boxes {{
      font-size: 20pt;
      letter-spacing: 1.4mm;
      line-height: 1;
    }}
    .time-line {{
      margin-top: 8mm;
      border-top: 1px solid #777;
      padding-top: 4mm;
      font-size: 11pt;
    }}
    .instructions {{
      margin-top: 8mm;
    }}
    .instructions .head {{
      font-weight: 700;
      margin-bottom: 3mm;
    }}
    .instructions ul {{
      margin: 0;
      padding-left: 5mm;
    }}
    .instructions li {{
      margin: 1.2mm 0;
    }}
    .section-intro {{
      margin: 0 0 7mm 0;
    }}
    .section-intro h1 {{
      margin: 0 0 3mm 0;
      font-size: 16pt;
    }}
    .section-intro p {{
      margin: 0;
      color: var(--muted);
    }}
    .paper1-question, .paper2-question {{
      page-break-inside: avoid;
      break-inside: avoid-page;
      margin-bottom: 8mm;
    }}
    .paper2-question {{
      break-before: page;
      page-break-before: always;
    }}
    .paper2-question:first-of-type {{
      break-before: auto;
      page-break-before: auto;
    }}
    .paper1-question {{
      display: block;
    }}
    .paper1-row {{
      display: grid;
      grid-template-columns: 8mm 1fr;
      column-gap: 4mm;
      align-items: start;
      width: 100%;
    }}
    .paper2-head {{
      display: flex;
      gap: 4mm;
      align-items: baseline;
      margin-bottom: 3mm;
    }}
    .question-number {{
      width: 8mm;
      min-width: 8mm;
      font-weight: 700;
    }}
    .question-content {{
      width: 100%;
      max-width: 100%;
      text-align: left;
      min-width: 0;
    }}
    .paper1-question > .question-number {{
      display: block;
      margin-bottom: 1.5mm;
    }}
    .paper1-question .section-intro {{
      display: block;
      width: 100%;
      margin: 0 0 5mm 0;
    }}
    .paper1-question .question-content p:first-child,
    .paper2-question .question-content p:first-child {{
      margin-top: 0;
    }}
    .mcq-stem p {{
      margin: 0 0 2.4mm 0;
    }}
    .mcq-options {{
      margin: 2mm 0 0 0;
      padding-left: 6mm;
      list-style-type: upper-alpha;
    }}
    .mcq-options li {{
      margin-bottom: 1.8mm;
      padding-left: 1mm;
    }}
    .mcq-table {{
      margin: 3mm 0;
      width: auto;
      min-width: 95mm;
    }}
    p {{
      margin: 0 0 2.5mm 0;
    }}
    img {{
      display: block;
      max-width: min(100%, 118mm);
      width: auto;
      height: auto;
      max-height: 70mm;
      margin: 2.5mm auto;
    }}
    table {{
      border-collapse: collapse;
      margin: 2.5mm auto;
      width: auto;
      max-width: 100%;
      font-size: 10pt;
    }}
    td, th {{
      border: 1px solid #999;
      padding: 2mm 2.4mm;
    }}
    ol {{
      margin: 2mm 0 0 5mm;
      padding-left: 5mm;
      list-style-type: upper-alpha;
    }}
    ol li {{
      margin-bottom: 1.5mm;
      padding-left: 1mm;
    }}
    .structured ol {{
      list-style-type: decimal;
    }}
    .katex-mathml {{
      display: none !important;
    }}
    h4, .et_pb_toggle, .fluid-width-video-wrapper, iframe, picture source {{
      display: none !important;
    }}
    .paper2-question .question-content .et_pb_text_inner p[style*="text-align: right"] {{
      text-align: right;
      margin-top: -1mm;
      margin-bottom: 2.5mm;
      font-size: 10pt;
    }}
    .paper2-question .question-content .et_pb_text_inner p[style*="padding-left"] {{
      padding-left: 0 !important;
      margin-left: 8mm;
    }}
    .question-content .et_pb_row,
    .question-content .et_pb_column,
    .question-content .et_pb_module,
    .question-content .et_pb_text,
    .question-content .et_pb_image,
    .question-content .et_pb_text_inner {{
      display: block !important;
      width: 100% !important;
      max-width: 100% !important;
      min-width: 0 !important;
      margin-left: 0 !important;
      margin-right: 0 !important;
      padding-left: 0 !important;
      padding-right: 0 !important;
      float: none !important;
      clear: both;
      text-align: left !important;
    }}
    .question-content .et_pb_row,
    .question-content .et_pb_column {{
      border: 0 !important;
    }}
    .question-content .et_pb_text_inner,
    .question-content p,
    .question-content li,
    .question-content ol {{
      text-align: left !important;
      white-space: normal !important;
      word-break: normal !important;
      overflow-wrap: normal !important;
    }}
    .question-content .et_pb_image_wrap {{
      display: block;
      text-align: left !important;
    }}
    .question-content img {{
      margin-left: 0;
      margin-right: auto;
    }}
    .paper1-question {{
      max-width: 168mm;
    }}
    .answer-space {{
      margin: 0 0 4mm 12mm;
      break-inside: avoid-page;
      page-break-inside: avoid;
    }}
    .answer-label {{
      font-size: 10pt;
      margin-bottom: 1mm;
    }}
    .writing-lines {{
      border: 1px solid #b8b8b8;
      background-image: repeating-linear-gradient(
        to bottom,
        transparent 0,
        transparent 7.2mm,
        #cfcfcf 7.2mm,
        #cfcfcf 7.45mm
      );
      background-size: 100% 7.45mm;
    }}
    .single-box {{
      margin-left: 0;
    }}
  </style>
</head>
<body>
{body}
</body>
</html>
"""


def build_html() -> tuple[str, dict]:
    thermo_lookup = {qid: extract_question(None, qid) for qid in P1_SELECTION}
    p1_questions = [thermo_lookup[qid] for qid in P1_SELECTION]
    p2_questions = [extract_question(item["level"], item["id"]) for item in P2_SELECTION]

    sections = [cover_page()]
    for i, question in enumerate(p1_questions, start=1):
        heading_html = ""
        if i == 1:
            heading_html = section_heading_block("Section A: Multiple Choice", "Answer all 16 questions. Select one answer for each question.")
        sections.append(render_p1_question(i, question, heading_html))
    for i, question in enumerate(p2_questions, start=1):
        sections.append(render_p2_question(i, question))

    manifest = {
        "title": "Thermodynamics IB-style Practice Paper",
        "paper1": [
            {
                "display_number": i,
                "source_bank": "thermodynamics-questionbank",
                "source_id": q["id"],
                "prompt": q["question_text"].splitlines()[1],
            }
            for i, q in enumerate(p1_questions, start=1)
        ],
        "paper2": [
            {
                "display_number": i,
                "source_bank": f"lvl{q['_level']}-questionbank",
                "source_id": q["id"],
                "prompt": q["question_text"].splitlines()[1],
            }
            for i, q in enumerate(p2_questions, start=1)
        ],
    }
    return wrap_document("\n".join(sections)), manifest


def print_to_pdf(browser: Path, html_path: Path, pdf_path: Path) -> None:
    cmd = [
        str(browser),
        "--headless=new",
        "--disable-gpu",
        "--allow-file-access-from-files",
        "--virtual-time-budget=12000",
        "--print-to-pdf-no-header",
        "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_path}",
        file_uri(html_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def main() -> None:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    browser = find_browser()
    html, manifest = build_html()
    html_path = EXPORT_DIR / "thermodynamics_ib_style_2025.html"
    pdf_path = EXPORT_DIR / "thermodynamics_ib_style_2025.pdf"
    manifest_path = EXPORT_DIR / "thermodynamics_ib_style_2025_manifest.json"
    html_path.write_text(html, encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print_to_pdf(browser, html_path, pdf_path)
    print(json.dumps({"pdf": str(pdf_path), "manifest": str(manifest_path)}, indent=2))


if __name__ == "__main__":
    main()
