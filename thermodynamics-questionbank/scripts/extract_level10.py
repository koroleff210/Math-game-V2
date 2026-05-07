from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT.parent
DATA_DIR = ROOT / "data"
IMAGE_DIR = ROOT / "images"
CONFIG_PATH = ROOT / "bank_config.json"
DECORATIVE_IMAGES = {
    "1-plane-15E688-18px.png",
    "2-planes-00BBAF-18px.png",
    "3-planes-3F63E0-18px.png",
    "4-planed-442B7E-18px.png",
    "5-planes-3B1E54-18px.png",
}


def load_config() -> Dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))


CONFIG = load_config()
SOURCE_HTML = SOURCE_DIR / CONFIG["source_html"]
SOURCE_ASSETS = SOURCE_DIR / CONFIG["source_assets_dir"]
PAPER1_PREFIX = CONFIG.get("paper1_prefix", "P1")
PAPER2_PREFIX = CONFIG.get("paper2_prefix", "P2")
ASSET_PATTERN = re.escape(f"./{CONFIG['source_assets_dir']}/")


def clean_whitespace(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


class HtmlToText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self.skip_depth = 0
        self.math_depth = 0
        self.capture_annotation = False
        self.annotation_parts: List[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        attr_map = dict(attrs)
        classes = attr_map.get("class", "")
        if self.skip_depth:
            self.skip_depth += 1
            return
        if "katex-html" in classes:
            self.skip_depth = 1
            return
        if tag in {"script", "style"}:
            self.skip_depth = 1
            return
        if tag == "math":
            self.math_depth += 1
            return
        if tag == "annotation" and attr_map.get("encoding") == "application/x-tex":
            self.capture_annotation = True
            self.annotation_parts = []
            return
        if tag in {"p", "div", "br", "li", "tr", "h4", "h5"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self.skip_depth:
            self.skip_depth -= 1
            return
        if tag == "math" and self.math_depth:
            self.math_depth -= 1
            return
        if tag == "annotation" and self.capture_annotation:
            tex = clean_whitespace("".join(self.annotation_parts))
            if tex:
                self.parts.append(f" ${tex}$ ")
            self.capture_annotation = False
            self.annotation_parts = []
            return
        if tag in {"p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        if self.capture_annotation:
            self.annotation_parts.append(data)
        elif self.math_depth:
            return
        else:
            self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        raw = unescape(raw)
        raw = raw.replace("Г—", "x").replace("−", "-").replace("ПЂ", "pi")
        raw = re.sub(r"\n\s*\n\s*\n+", "\n\n", raw)
        lines = [clean_whitespace(line) for line in raw.splitlines()]
        lines = [line for line in lines if line]
        return "\n".join(lines).strip()


def html_to_text(fragment: str) -> str:
    parser = HtmlToText()
    parser.feed(fragment)
    return parser.text()


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    for item in IMAGE_DIR.iterdir():
        if item.is_file():
            item.unlink()


def extract_section(html: str, section_id: str, next_section_id: str | None = None) -> str:
    marker = f'id="{section_id}"'
    start = html.find(marker)
    if start == -1:
        raise ValueError(f"Could not find section {section_id}")
    if next_section_id:
        next_marker = f'id="{next_section_id}"'
        end = html.find(next_marker, start + len(marker))
        if end == -1:
            raise ValueError(f"Could not find end marker {next_section_id}")
        return html[start:end]
    return html[start:]


def split_question_blocks(section_html: str) -> List[tuple[int, str]]:
    matches = list(re.finditer(r'<div class="et_pb_text_inner"><h4>Question\s+(\d+)&nbsp;', section_html))
    blocks: List[tuple[int, str]] = []
    for i, match in enumerate(matches):
        question_number = int(match.group(1))
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(section_html)
        blocks.append((question_number, section_html[start:end]))
    return blocks


def find_local_images(fragment: str) -> List[str]:
    refs = re.findall(
        rf'<img[^>]+src="{ASSET_PATTERN}([^"]+)"',
        fragment,
        flags=re.I,
    )
    unique: List[str] = []
    for ref in refs:
        if ref in DECORATIVE_IMAGES:
            continue
        if ref not in unique:
            unique.append(ref)
    return unique


def copy_images(names: List[str]) -> List[str]:
    copied: List[str] = []
    for name in names:
        source = SOURCE_ASSETS / name
        target = IMAGE_DIR / name
        if source.exists():
            shutil.copy2(source, target)
            copied.append(name)
    return copied


def split_mcq_block(block_html: str) -> Dict[str, str]:
    answer_marker = '<h5 class="et_pb_toggle_title">Answer</h5>'
    video_marker = '<h5 class="et_pb_toggle_title">Video Solution</h5>'
    done_marker = '<h5 class="et_pb_toggle_title">Done Under 90</h5>'

    answer_idx = block_html.find(answer_marker)
    video_idx = block_html.find(video_marker)
    done_idx = block_html.find(done_marker)

    body_html = block_html[:answer_idx] if answer_idx != -1 else block_html
    answer_html = block_html[answer_idx:video_idx] if answer_idx != -1 and video_idx != -1 else ""
    video_html = block_html[video_idx:done_idx] if video_idx != -1 and done_idx != -1 else ""
    done_html = block_html[done_idx:] if done_idx != -1 else ""
    return {
        "body_html": body_html,
        "answer_html": answer_html,
        "video_html": video_html,
        "done_html": done_html,
    }


def extract_toggle_content(block_html: str, title: str) -> str:
    pattern = re.escape(f'<h5 class="et_pb_toggle_title">{title}</h5>')
    match = re.search(pattern + r'.*?<div class="et_pb_toggle_content clearfix"[^>]*>(.*?)</div>', block_html, flags=re.S)
    return match.group(1) if match else ""


def first_toggle_content(block_html: str) -> str:
    match = re.search(r'<div class="et_pb_toggle_content clearfix"[^>]*>(.*?)</div>', block_html, flags=re.S)
    return match.group(1) if match else ""


def extract_iframe_src(block_html: str, title: str) -> str | None:
    pattern = re.escape(f'<h5 class="et_pb_toggle_title">{title}</h5>')
    match = re.search(pattern + r'.*?<iframe src="([^"]+)"', block_html, flags=re.S)
    return match.group(1) if match else None


def parse_mcq(question_number: int, block_html: str) -> Dict:
    pieces = split_mcq_block(block_html)
    body_html = pieces["body_html"]
    images = copy_images(find_local_images(body_html + pieces["answer_html"]))
    answer_content = first_toggle_content(pieces["answer_html"])
    answer_text = html_to_text(answer_content)
    answer_match = re.search(r"\b([A-D])\b", answer_text)

    return {
        "id": f"{PAPER1_PREFIX}-Q{question_number:02d}",
        "paper": "Paper 1",
        "question_number": question_number,
        "type": "mcq",
        "question_html": body_html,
        "question_text": html_to_text(body_html),
        "answer": answer_match.group(1) if answer_match else answer_text,
        "answer_html": answer_content,
        "video_solution": extract_iframe_src(block_html, "Video Solution"),
        "done_under_90_video": extract_iframe_src(block_html, "Done Under 90"),
        "images": images,
    }


@dataclass
class StructuredPart:
    label: str
    answer_html: str
    answer_text: str
    video_solution: str | None


def parse_structured(question_number: int, block_html: str) -> Dict:
    first_answer_idx = block_html.find('<h5 class="et_pb_toggle_title">Answer ')
    body_html = block_html[:first_answer_idx] if first_answer_idx != -1 else block_html
    images = copy_images(find_local_images(body_html + block_html[first_answer_idx:]))

    titles = list(re.finditer(r'<h5 class="et_pb_toggle_title">(Answer|Video Solution)\s+([^<]+)</h5>', block_html))
    part_map: Dict[str, Dict[str, str | None]] = {}
    for match in titles:
        kind = match.group(1)
        label = match.group(2).strip()
        if label not in part_map:
            part_map[label] = {"answer_html": "", "video_solution": None}
        if kind == "Answer":
            content = extract_toggle_content(block_html[match.start():], f"Answer {label}")
            part_map[label]["answer_html"] = content
        else:
            part_map[label]["video_solution"] = extract_iframe_src(block_html[match.start():], f"Video Solution {label}")

    subparts = []
    for label, payload in part_map.items():
        answer_html = str(payload["answer_html"] or "")
        subparts.append(
            {
                "label": label,
                "id": f"{PAPER2_PREFIX}-Q{question_number:02d}-{label}",
                "answer_html": answer_html,
                "answer_text": html_to_text(answer_html),
                "video_solution": payload["video_solution"],
            }
        )

    return {
        "id": f"{PAPER2_PREFIX}-Q{question_number:02d}",
        "paper": "Paper 2",
        "question_number": question_number,
        "type": "structured",
        "question_html": body_html,
        "question_text": html_to_text(body_html),
        "images": images,
        "subparts": subparts,
    }


def build_question_index(questions: List[Dict]) -> str:
    title = CONFIG.get("title", ROOT.name)
    lines = [f"# {title} Question Index", ""]
    lines.append("## Paper 1")
    for q in [q for q in questions if q["paper"] == "Paper 1"]:
        lines.append(f"- `{q['id']}`: Question {q['question_number']} | answer `{q['answer']}` | images `{len(q['images'])}`")
    lines.append("")
    lines.append("## Paper 2")
    for q in [q for q in questions if q["paper"] == "Paper 2"]:
        labels = ", ".join(part["label"] for part in q["subparts"])
        lines.append(f"- `{q['id']}`: Question {q['question_number']} | subparts `{labels}` | images `{len(q['images'])}`")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    ensure_dirs()
    html = SOURCE_HTML.read_text(encoding="utf-8", errors="replace")

    paper1_html = extract_section(html, "paper1", "paper2")
    paper2_html = extract_section(html, "paper2")

    paper1_blocks = split_question_blocks(paper1_html)
    paper2_blocks = split_question_blocks(paper2_html)

    questions: List[Dict] = []
    questions.extend(parse_mcq(number, block) for number, block in paper1_blocks)
    questions.extend(parse_structured(number, block) for number, block in paper2_blocks)

    index = {
        "title": CONFIG.get("title"),
        "source_html": str(SOURCE_HTML),
        "source_assets": str(SOURCE_ASSETS),
        "counts": {
            "total_questions": len(questions),
            "paper1_mcq": sum(1 for q in questions if q["paper"] == "Paper 1"),
            "paper2_structured": sum(1 for q in questions if q["paper"] == "Paper 2"),
            "paper2_total_subparts": sum(len(q.get("subparts", [])) for q in questions if q["paper"] == "Paper 2"),
        },
        "question_ids": [q["id"] for q in questions],
    }

    (DATA_DIR / "questions.json").write_text(json.dumps(questions, indent=2, ensure_ascii=False), encoding="utf-8")
    (DATA_DIR / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
    (DATA_DIR / "question_index.md").write_text(build_question_index(questions), encoding="utf-8")

    print(json.dumps(index, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
