import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const sourcePath = path.resolve(here, "../../debripod/static/js/video-ambient.js");
const source = fs.readFileSync(sourcePath, "utf8");

function samplePixels() {
  const names = ["clampByte", "luma", "nearBlack", "edgeBlackRun", "meanColor", "sampleVideoAmbientPixels"];
  const snippets = names.map((name) => {
    const match = source.match(new RegExp(`function ${name}\\([^)]*\\)\\{[\\s\\S]*?\\n  \\}`));
    assert.ok(match, `${name} must remain independently testable`);
    return match[0];
  });
  const context = {Math, Number, Uint8ClampedArray};
  vm.createContext(context);
  vm.runInContext(snippets.join("\n"), context, {filename: sourcePath});
  return context.sampleVideoAmbientPixels;
}

test("ambient sampler tracks colored edges while ignoring encoded black bars", () => {
  const sample = samplePixels();
  const width = 8;
  const height = 6;
  const data = new Uint8ClampedArray(width * height * 4);
  for(let y = 1; y < height - 1; y++) for(let x = 0; x < width; x++) {
    const offset = (y * width + x) * 4;
    data[offset] = x < 4 ? 220 : 30;
    data[offset + 1] = x < 4 ? 30 : 80;
    data[offset + 2] = x < 4 ? 40 : 230;
    data[offset + 3] = 255;
  }
  const colors = sample({data, width, height});
  assert.equal(colors.bars.top, 1);
  assert.equal(colors.bars.bottom, 1);
  assert.ok(colors.left[0] > colors.left[2]);
  assert.ok(colors.right[2] > colors.right[0]);
  assert.ok(colors.top[0] > 20);
  assert.ok(colors.bottom[2] > 20);
});
