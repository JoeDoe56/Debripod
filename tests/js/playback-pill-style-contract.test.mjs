import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import {fileURLToPath} from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const css = fs.readFileSync(path.resolve(here, "../../debripod/static/debripod.css"), "utf8");
const html = fs.readFileSync(path.resolve(here, "../../debripod/static/shell.html"), "utf8");

function cssBlock(selector) {
  const match = css.match(new RegExp(`${selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*\\{([\\s\\S]*?)\\n\\s*\\}`));
  assert.ok(match, `missing ${selector} CSS block`);
  return match[1];
}

test("playback meters share one thickness, have no track border, and retain range semantics", () => {
  assert.match(css, /--infoBarThickness:\s*8\.4px/);
  assert.doesNotMatch(cssBlock(".npMeterTrack"), /\bborder\s*:/);
  assert.match(cssBlock(".npMeterFill"), /border-radius:\s*999px/);
  assert.match(html, /class="npSeek"[^>]*type="range"/);
  assert.match(html, /class="[^"]*npVolumeMeter[^"]*"[^>]*aria-valuemin="0"[^>]*aria-valuemax="100"/);
});

test("playback pills animate in opposite vertical directions", () => {
  assert.match(cssBlock(".pathPill.pathPillHidden"), /translateY\(10px\)/);
  assert.match(cssBlock(".infoPill.infoPillHidden"), /translateY\(-8px\)/);
  assert.match(css, /pathPillTextScrollable[\s\S]*-webkit-mask-image/);
});
