# Gear Studio

Open **Admin → Economy → Gear Studio** at
https://game.korephysics.com/admin/gear-studio/.

1. Choose Face, Headgear, Chest, Boots, Main hand or Off hand, then the avatar body.
2. Leave **Save to → Create new** for a new element, or select existing gear to
   adjust its artwork. Choose a transparent PNG from your computer.
3. Drag the imported artwork to position it. Drag its bottom-right corner or use
   the Size slider to scale it. **Fine adjustments** offers exact position,
   width and rotation. Choose **Eraser** to remove small parts of this artwork,
   with a 1–80 pixel brush. **Zoom** supports 100–400%; scroll within the preview
   to reach details. Undo/Redo covers both placement and erased pixels (Ctrl+Z /
   Ctrl+Shift+Z while the canvas is focused). Return to **Move / resize** to fit it.
4. Use the gear selectors and previous/next arrows on the right to check the fit
   against existing gear and faces. The library includes catalog gear and bundled
   art that has no shop entry, including main/off hand and boots/legs. References
   with no artwork for the selected body are labeled accordingly; male artwork
   is not silently substituted for missing female artwork. Background, opacity,
   guides and reference selections affect only the preview.
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

Erasing changes only the editable source. Saved/reopened erasures preserve its
coordinate frame, so removing an outer edge does not enlarge or reposition the
remaining artwork. Erasing everything prevents saving until visible artwork is
restored, for example with Undo. Existing packaged files are preserved.

The 18 October 2026 release exposes 35 gear references and the existing nine
male/six female faces online. These counts follow the files/catalog and can grow.
No extra shop items or player ownership records are created by previewing them.

Imports accept PNGs up to 16 MiB / 40 megapixels. Transparent margins are cropped
for fitting; existing 1100×1200 artwork retains its original placement. Images
need visible artwork inside the avatar canvas to save. Student accounts cannot
access the editor. Conflicting saves from another tab ask you to reopen first.

Online uploads live in the server's persistent media directory and database.
Deploying code must preserve them; never synchronize an old local database or
media folder over production. The existing game backup includes originals,
exports, thumbnails and placement metadata.
