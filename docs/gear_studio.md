# Gear Studio

Open **Admin → Economy → Gear Studio** at
https://game.korephysics.com/admin/gear-studio/.

1. Choose Face, Headgear, Chest, Boots, Main hand or Off hand, then the avatar body.
2. Leave **Save to → Create new** for a new element, or select existing gear to
   adjust its artwork. Choose a transparent PNG from your computer.
3. Drag the imported artwork to position it. Drag its bottom-right corner or use
   the Size slider to scale it. **Fine adjustments** offers exact position,
   width and rotation. Undo/Redo works on placement changes.
4. Use the gear selectors and previous/next arrows on the right to check the fit
   against existing gear and faces. Background, opacity, guides and reference
   selections affect only the preview.
5. Name the new element and click **Add face/gear to game**. Faces appear in
   character selection; gear appears in Gear Catalog and the Blacksmith, with a
   generated thumbnail. New gear has zero bonuses; configure bonuses in Gear
   Catalog. The default Diamond price is zero; set it before adding a new item.

The server saves only the imported artwork on the game's transparent 1100×1200
canvas, alongside an editable source and placement settings. Reopening a saved
element preserves those settings. Existing catalog prices, bonuses, ownership,
equipment and packaged image files stay unchanged when adjusting artwork.

Male and female artwork saves separately. To make the same gear available for
both bodies, save it for one body, switch bodies while retaining the existing
gear target, then import/fit the second version. Faces are separate choices for
each body. Headgear can optionally have a layer behind the head; chest items can
have a layer behind the body. Create the front layer first, then reopen that
item and select the other layer.

Existing catalog gear can be reopened even when its artwork was originally a
packaged file. Built-in faces remain available as references; import a PNG to
create an editable face. Use Assets or Gear Catalog to remove saved elements.
Replacing an image through Assets replaces the editable source too.

Imports accept PNGs up to 16 MiB / 40 megapixels. Transparent margins are cropped
for fitting; existing 1100×1200 artwork retains its original placement. Images
need visible artwork inside the avatar canvas to save. Student accounts cannot
access the editor. Conflicting saves from another tab ask you to reopen first.

Online uploads live in the server's persistent media directory and database.
Deploying code must preserve them; never synchronize an old local database or
media folder over production. The existing game backup includes originals,
exports, thumbnails and placement metadata.
