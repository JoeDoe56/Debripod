# SF Symbol asset provenance

These local PNG glyphs are fetched from the public `wan-kong/sf-symbols-online`
repository, revision `09aa1fb1ed675def165a633b0122724ff882175d`:

<https://github.com/wan-kong/sf-symbols-online/tree/09aa1fb1ed675def165a633b0122724ff882175d/packages/sf-symbols/glyphs>

The repository README credits the glyph collection to `@andrewtavis` and notes
that SF Symbols is a trademark of Apple Inc. Its README declares the project
MIT licensed; that revision provides no separate LICENSE file. This records
the upstream declaration without assigning a new license or copyright to
Apple's glyphs. DebriPod stores the upstream PNGs locally so the app remains
self-contained and does not add a runtime dependency.

The following names requested by the redesign are absent from that upstream
collection: `line.3.horizontal`, `gearshape`, `books.vertical`, `network`,
`text.line.first.and.arrowtriangle.forward`, and
`text.line.last.and.arrowtriangle.forward`. The registry records the closest
available upstream glyphs explicitly:

| Requested name | Local upstream glyph | Reason |
| --- | --- | --- |
| `gearshape` | `gear` | settings control |
| `books.vertical` | `rectangle.stack` | library collection |
| `network` | `antenna.radiowaves.left.and.right` | connected service |
| `text.line.first.and.arrowtriangle.forward` | `forward.end.fill` | play next |
| `text.line.last.and.arrowtriangle.forward` | `arrowshape.turn.up.right.fill` | insert after |

`line.3.horizontal` is intentionally not substituted for the normal wheel
MENU label; MENU remains text. Shuffle remains DebriPod's existing shuffle
asset until an approved replacement is selected.

The upstream glyphs are antialiased PNGs with non-binary alpha edges. Their
source canvases use different intrinsic bounds (for example, the playback
glyphs are wider than `heart`), so DebriPod presents them through one
contain-sized mask box in the existing wheel and row icon slots. No per-icon
pixel redraw or aspect-ratio distortion is applied.
