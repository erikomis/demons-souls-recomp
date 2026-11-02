Model import / export (docs/NOTES.md fix 61)
============================================

Export a model to glTF, edit it in Blender (or anything that reads and writes glTF 2.0), import it back.
Run these from the repo folder (.venv\Scripts\python made by SETUP works, any Python 3.10+ does too):

  python tools\flver_tool.py list   game\PS3_GAME\USRDIR\PARTS\bd_f_5010.partsbnd.dcx
  python tools\flver_tool.py export game\PS3_GAME\USRDIR\PARTS\bd_f_5010.partsbnd.dcx
      -> models\BD_F_5010\BD_F_5010.gltf (+ .bin and textures\*.png)
  ... Blender: File > Import > glTF 2.0, edit, File > Export > glTF 2.0 (.glb is fine) ...
  python tools\flver_tool.py import models\BD_F_5010\edited.glb game\PS3_GAME\USRDIR\PARTS\bd_f_5010.partsbnd.dcx
      -> writes game_mod\ (a copy of game\ made of hard links: no extra disk space; game\ is never
         changed). Play it with PLAY_MODDED.bat. Delete game_mod\ to undo everything.

Which file holds what (all under game\PS3_GAME\USRDIR; use the .dcx -- that is what the game reads):
  PARTS\  armour and weapons: hd_ head, bd_ body, am_ arms, lg_ legs, wp_ weapons/shields;
          _m_ male, _f_ female, _a_ both; *_l = the low-detail copy shown at a distance
          (edit it too, or the old shape comes back far away).
  CHR\    characters and enemies: cXXXX\cXXXX.chrbnd.dcx
  OBJ\    objects (doors, chests, breakables): oXXXX.objbnd.dcx
  MAP\    level geometry: MAP\M02_00_00_00\m4000b0.flver.dcx etc. (*l1 = low-detail copy)

What import keeps and what it takes from your file:
  - Each Blender object goes into the game mesh its name starts with: m00_..., m01_..., and
    several objects may share a number. A new object whose name starts with no number becomes a
    new mesh using the material its own material is named after (give it one of the model's
    materials). Meshes you did not export stay as they were (add --delete-missing to drop them).
  - From your file: shape, triangles, normals, UVs (UV map 1, and 2 = the lightmap UV of map
    pieces), vertex colours, bone weights. Triangulate in Blender if you get a "non-triangle" error.
  - Kept from the game: materials, shaders, textures, the skeleton, collision, animations.
    Bones are matched by name; weights to a bone the game model lacks are refused.
    To change textures use texture packs (textures\README.txt) -- the exported PNGs are for reference.
  - More than 28 bones or 65535 vertices in one mesh: split into several meshes automatically.
  - Several models in one archive (some weapons): pick one with --entry 0, --entry 1, ...
  - --mod game_remaster puts the change into the PC Remaster copy instead (play with PLAY_REMASTER.bat).

python tools\flver_tool.py selftest   reads and writes back every model in game\ and checks the
export -> import round trip (takes a few minutes).

The game's left-handed space is mirrored on X for glTF and mirrored back on import, so the model
looks right in Blender and in game. Collision and animations are separate files and are not changed:
a much bigger model still collides like the old one.
