"""Avatar-aligned PNG authoring using the same layers as the player renderer."""
from io import BytesIO
import math
from types import SimpleNamespace
from uuid import uuid4

from flask import url_for
from PIL import Image

from app.extensions import db
from app.models.gear import GearItemDefinition
from app.models.media import UploadedAsset
from app.services.avatar import build_player_avatar_view, list_available_face_keys
from app.services.gear import resolve_gear_icon_static_path
from app.services.uploaded_media import asset_url, remove_image, validate_image, write_image

CANVAS = (1100, 1200)
SLOTS = {'face': 'Face', 'head': 'Headgear', 'chest': 'Chest', 'boots': 'Boots',
         'main_hand': 'Main hand', 'off_hand': 'Off hand'}
LAYER_NAMES = {'face': {'front': 'face'}, 'head': {'front': 'head-front', 'back': 'head-back'},
               'chest': {'front': 'chest', 'underlay': 'chest-underlay'},
               'boots': {'front': 'boots'}, 'main_hand': {'front': 'main-hand'},
               'off_hand': {'front': 'off-hand'}}
ORDER = ['head-back', 'chest-underlay', 'body-upper', 'body-lower', 'boots', 'main-hand',
         'chest', 'face', 'head-front', 'off-hand', 'off-hand-base']


class StudioConflict(ValueError):
    pass


def _avatar(variant, face='001', item=None):
    loadout = SimpleNamespace(**{slot + '_item_id': None for slot in SLOTS if slot != 'face'})
    if item:
        setattr(loadout, item.slot_type + '_item_id', item.id)
    return build_player_avatar_view(SimpleNamespace(avatar_body_variant=variant, selected_face_key=face), loadout)


def catalog():
    assets = UploadedAsset.query.all()
    by_id = {a.id: a for a in assets}
    def versioned(path):
        if path.startswith('/media/'):
            asset = by_id.get(int(path.split('/')[-1]))
            if asset:
                return path + '?v=' + asset.sha256[:16]
        return path
    base, faces, items = {}, {}, []
    for variant in ('m', 'f'):
        base[variant] = {k: versioned(v['static_path']) for k, v in _avatar(variant)['layer_map'].items()}
        face_assets = {a.asset_key: a for a in assets if a.category == 'face_' + variant}
        faces[variant] = []
        for key in list_available_face_keys(variant):
            view = _avatar(variant, key)
            layer = view['layer_map'].get('face')
            if layer:
                asset = face_assets.get(key)
                faces[variant].append(dict(key=key, name=asset.display_name if asset else 'Face ' + key,
                                           asset_id=asset.id if asset else None, image=versioned(layer['static_path'])))
    for item in GearItemDefinition.query.order_by(GearItemDefinition.slot_type, GearItemDefinition.name).all():
        if item.slot_type not in SLOTS:
            continue
        layers = {}
        for variant in ('m', 'f'):
            view = _avatar(variant, item=item)
            layers[variant] = {k: versioned(v['static_path']) for k, v in view['layer_map'].items()
                               if k in LAYER_NAMES[item.slot_type].values()}
        items.append(dict(id=item.id, name=item.name, slot=item.slot_type, layers=layers,
                          active=item.is_active, price=item.diamond_cost,
                          icon=resolve_gear_icon_static_path(item_id=item.id, slot_type=item.slot_type,
                               image_key=item.image_key, avatar_asset_key=item.avatar_asset_key)))
    return dict(width=CANVAS[0], height=CANVAS[1], slots=SLOTS, layer_names=LAYER_NAMES,
                order=ORDER, base=base, faces=faces, items=items)


def target_asset(slot, target, variant, layer, *, lock=False):
    if not all(isinstance(value, str) for value in (slot, target, variant, layer)):
        raise ValueError('Choose a valid element, body and layer.')
    if slot not in SLOTS or variant not in ('m', 'f') or layer not in LAYER_NAMES[slot]:
        raise ValueError('Choose a valid element, body and layer.')
    if target == 'new':
        return None, None
    if slot == 'face':
        try:
            asset_id = int(target)
        except (TypeError, ValueError):
            raise ValueError('Choose a saved face.') from None
        query = UploadedAsset.query.filter_by(id=asset_id, category='face_' + variant)
        asset = (query.with_for_update() if lock else query).first()
        if asset is None:
            raise ValueError('That saved face is not available for this body.')
        return None, asset
    query = GearItemDefinition.query.filter_by(id=target, slot_type=slot)
    item = (query.with_for_update() if lock else query).first()
    if item is None:
        raise ValueError('Gear item not found in this slot.')
    # Exact body only: a shared layer is a reference, never silently overwritten.
    asset = UploadedAsset.query.filter_by(category='gear_layer', gear_item_id=item.id,
                                          variant=variant, layer=layer).first()
    return item, asset


def editor_view(slot, target, variant, layer):
    _item, asset = target_asset(slot, target, variant, layer)
    if asset is None:
        return dict(revision='', source_url=None, transform=None)
    state = asset.editor_state or {}
    return dict(revision=asset.sha256, source_url=url_for('gear_studio.source', asset_id=asset.id)
                if state.get('source_name') else asset_url(asset) + '?v=' + asset.sha256[:16],
                transform=state.get('transform'), name=asset.display_name)


def _number(data, key, minimum, maximum):
    try:
        value = float(data[key])
    except (KeyError, TypeError, ValueError):
        raise ValueError('Invalid image position or size.') from None
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError('Image position or size is outside the canvas limits.')
    return value


def render_layer(data, transform):
    cleaned, extension, _mime, _w, _h = validate_image(data)
    if extension != 'png':
        raise ValueError('Import a PNG image.')
    with Image.open(BytesIO(cleaned)) as image:
        image = image.convert('RGBA')
        bounds = image.getchannel('A').getbbox()
        if bounds is None:
            raise ValueError('This PNG is completely transparent. Choose visible artwork.')
        image = image.crop(bounds)
        x, y = (_number(transform, key, -4400, 4400) for key in ('x', 'y'))
        width = _number(transform, 'width', 1, 4400)
        angle = _number(transform, 'rotation', -180, 180)
        height = width * image.height / image.width
        if height > 4800 or width * height > 8_000_000:
            raise ValueError('The scaled image is too large. Reduce its size.')
        source = BytesIO()
        image.save(source, format='PNG')
        resized = image.resize((max(1, round(width)), max(1, round(height))), Image.Resampling.LANCZOS)
        rotated = resized.rotate(-angle, resample=Image.Resampling.BICUBIC, expand=True)
        left = round(x + width / 2 - rotated.width / 2)
        top = round(y + height / 2 - rotated.height / 2)
        result = Image.new('RGBA', CANVAS)
        result.alpha_composite(rotated, (left, top))
        if result.getchannel('A').getbbox() is None:
            raise ValueError('The image is outside the avatar canvas. Move it back before saving.')
        exported = BytesIO()
        result.save(exported, format='PNG')
        icon = result.crop(result.getchannel('A').getbbox())
        icon.thumbnail((160, 160), Image.Resampling.LANCZOS)
        icon_bytes = BytesIO()
        icon.save(icon_bytes, format='PNG')
        state = dict(x=x, y=y, width=width, rotation=angle)
        return source.getvalue(), exported.getvalue(), icon_bytes.getvalue(), state


def save_element(data, png):
    slot, variant = data.get('slot'), data.get('variant')
    target, layer = data.get('target', 'new'), data.get('layer', 'front')
    item, asset = target_asset(slot, target, variant, layer, lock=True)
    if str(data.get('revision') or '') != (asset.sha256 if asset else ''):
        raise StudioConflict('This image was changed in another tab. Reopen it before saving.')
    if target == 'new' and layer != 'front':
        raise ValueError('Create the front layer first. Then reopen the item to add its other layer.')
    name = str(data.get('name') or '').strip()
    if not 1 <= len(name) <= (128 if slot == 'face' else 80):
        raise ValueError('Enter a name of 1–' + ('128' if slot == 'face' else '80') + ' characters.')
    source, exported, icon_bytes, transform = render_layer(png, data.get('transform') or {})
    if target == 'new' and slot != 'face':
        try:
            price = int(data.get('price', 0))
        except (TypeError, ValueError):
            raise ValueError('Diamond price must be a whole number.') from None
        if not 0 <= price <= 1_000_000:
            raise ValueError('Diamond price must be between 0 and 1,000,000.')
        item = GearItemDefinition(id='studio_' + uuid4().hex, slot_type=slot, name=name,
                                  avatar_asset_key='u' + uuid4().hex[:12],
                                  description='', diamond_cost=price, is_active=True,
                                  is_blacksmith_visible=True, mine_gold_delta=0,
                                  steal_gold_delta=0, shield_duration_delta=0)
        db.session.add(item)
        db.session.flush()
    created_files, old_files = [], []
    def store(pixels):
        saved = write_image(pixels)
        created_files.append(saved['storage_name'])
        return saved
    try:
        saved_source, saved_layer = store(source), store(exported)
        if asset is None:
            asset = UploadedAsset(category='face_' + variant if slot == 'face' else 'gear_layer',
                                  display_name=name, variant=variant,
                                  layer=None if slot == 'face' else layer,
                                  asset_key='u' + uuid4().hex[:12] if slot == 'face' else None,
                                  gear_item_id=item.id if item else None)
            db.session.add(asset)
        else:
            old_files.extend([asset.storage_name, (asset.editor_state or {}).get('source_name')])
        for key in ('storage_name', 'media_type', 'sha256'):
            setattr(asset, key, saved_layer[key])
        asset.display_name = name
        asset.editor_state = dict(version=1, source_name=saved_source['storage_name'], transform=transform)
        if slot != 'face' and layer == 'front':
            icon = UploadedAsset.query.filter_by(category='gear_icon', gear_item_id=item.id,
                                                 variant=variant, layer='icon').first()
            if icon is None:
                icon = UploadedAsset(category='gear_icon', gear_item_id=item.id,
                                     display_name=item.name, variant=variant, layer='icon')
                db.session.add(icon)
            else:
                old_files.append(icon.storage_name)
            saved_icon = store(icon_bytes)
            for key in ('storage_name', 'media_type', 'sha256'):
                setattr(icon, key, saved_icon[key])
        db.session.commit()
    except Exception:
        db.session.rollback()
        for filename in created_files:
            remove_image(filename)
        raise
    for filename in old_files:
        if filename:
            remove_image(filename)
    return dict(target=str(asset.id) if slot == 'face' else item.id, revision=asset.sha256,
                asset_id=asset.id, name=asset.display_name, variant=variant, layer=layer,
                message='Face saved to character selection.' if slot == 'face' else
                        'Gear added to the catalog and Blacksmith. Bonuses can be set in Gear Catalog.' if target == 'new' else
                        'Artwork saved. Existing catalog settings are unchanged.')
