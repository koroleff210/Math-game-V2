"""Generate smaller, content-addressed display copies; keep authored PNGs intact."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

from PIL import Image

STATIC = Path(__file__).resolve().parents[1] / 'app' / 'static'
MANIFEST = STATIC/'optimized'/'manifest.json'
EXISTING = json.loads(MANIFEST.read_text(encoding='utf-8')) if MANIFEST.exists() else {}


def convert(path):
    source = path.read_bytes()
    if len(source) < 128 or ' - Copy' in path.name:
        return None
    key = path.relative_to(STATIC).as_posix()
    existing = EXISTING.get(key)
    if existing and existing['source_sha256'] == sha256(source).hexdigest() and (STATIC/existing['path']).is_file():
        return key, existing
    with Image.open(BytesIO(source)) as image:
        image.load()
        if 'icons' in path.parts:
            image.thumbnail((96, 96), Image.Resampling.LANCZOS)
        elif path.name == 'panel_texture.png':
            image.thumbnail((512, 512), Image.Resampling.LANCZOS)
        output = BytesIO()
        image.save(output, 'WEBP', quality=90 if 'player_ui' not in path.parts else 85, method=4, exact=True)
    data = output.getvalue()
    if len(data) >= len(source):
        return None
    name = sha256(data).hexdigest() + '.webp'
    target = STATIC / 'optimized' / name
    target.write_bytes(data)
    return path.relative_to(STATIC).as_posix(), {
        'path': 'optimized/' + name, 'source_sha256': sha256(source).hexdigest(),
        'original_bytes': len(source), 'display_bytes': len(data),
    }


def main():
    (STATIC/'optimized').mkdir(exist_ok=True)
    paths = sorted({p for folder in ('classic_ui/player_ui', 'classic_ui/treasure/backgrounds', 'classic_ui/steal/backgrounds', 'classic_ui/icons', 'classic_ui/treasure/containers', 'classic_ui/steal/containers', 'avatars', 'gear', 'gear_icons')
                    for p in (STATIC/folder).rglob('*.png')})
    with ThreadPoolExecutor(max_workers=3) as pool:
        manifest = dict(result for result in pool.map(convert, paths) if result)
    (STATIC/'optimized'/'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding='utf-8')
    print(json.dumps({'images':len(manifest), 'original_bytes':sum(v['original_bytes'] for v in manifest.values()),
                      'display_bytes':sum(v['display_bytes'] for v in manifest.values())}))


if __name__ == '__main__':
    main()
