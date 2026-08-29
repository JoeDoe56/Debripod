import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const sourcePath = path.resolve(here, "../../debripod/static/liquidGL.js");
const source = fs.readFileSync(sourcePath, "utf8");
let now = 0;
const context = {
  window: {},
  console,
  performance: {now: () => now},
  localStorage: {getItem: () => null},
  setTimeout,
  clearTimeout,
};
vm.createContext(context);
vm.runInContext(source, context, {filename: sourcePath});

const api = context.window.liquidGL;
const resolve = api.resolveMaterial;

function close(actual, expected, tolerance = 1e-9) {
  assert.ok(Math.abs(actual - expected) <= tolerance, `${actual} != ${expected}`);
}

function makeBareLens(material = 0) {
  const renderer = {
    _metricsDirty: false,
    requestCount: 0,
    captureCount: 0,
    canvas: {},
    texture: {},
    requestRender() { this.requestCount += 1; },
    captureSnapshot() { this.captureCount += 1; },
  };
  const Lens = api.testing.Lens;
  const lens = Object.create(Lens.prototype);
  lens.renderer = renderer;
  lens.el = {hasAttribute: () => false};
  lens.rectPx = {width: 240, height: 56};
  lens.options = {material, reveal: "none", shadow: true, tilt: false, specular: true};
  lens._transition = null;
  lens.setShadow = function(enabled, strength) {
    this.options.shadow = !!enabled;
    this.shadowStrength = strength;
  };
  lens.setTilt = function(enabled) { this.options.tilt = !!enabled; };
  return {lens, renderer};
}

test("signed material normalization and calibrated anchors", () => {
  assert.equal(api.normalizeMaterial(-4), -1);
  assert.equal(api.normalizeMaterial(4), 1);
  assert.equal(api.normalizeMaterial(Number.NaN), 0);
  assert.equal(api.normalizeMaterial(Number.POSITIVE_INFINITY), 0);

  const center = resolve(0);
  assert.equal(center.materialAlpha, 0);
  assert.equal(center.frostSigmaPx, 0);
  close(center.refraction, 0.045);
  close(center.refractionFill, 0);
  close(center.bevelDepth, 0.075);
  close(center.bevelWidth, 0.095);
  close(center.magnify, 1.012);
  close(center.shadowStrength, 0.08);
  assert.equal(center.tone[0], 1);

  for (const sign of [-1, 1]) {
    const clear = resolve(sign * 0.12);
    close(clear.materialAlpha, 0.12);
    close(clear.frostSigmaPx, 2.88);
    const tinted = resolve(sign * 0.52);
    close(tinted.materialAlpha, 0.52);
    close(tinted.frostSigmaPx, 12.48);
  }

  const dark = resolve(-1);
  const light = resolve(1);
  assert.equal(dark.materialAlpha, 1);
  assert.equal(dark.tone[0], 0);
  assert.equal(light.materialAlpha, 1);
  assert.equal(light.tone[0], 1);
  close(resolve(-0.52).tone[0], 35 / 255);
  close(dark.frostSigmaPx, 24);
  close(dark.refraction, 0.07);
  close(dark.bevelDepth, 0.12);
  close(dark.bevelWidth, 0.115);
  close(dark.magnify, 1.005);
  close(dark.shadowStrength, 0.18);
  assert.ok(resolve(-1).specularPrimary > resolve(1).specularPrimary);
  assert.ok(resolve(-1).specularSecondary < resolve(1).specularSecondary);
});

test("hundreds of live updates preserve lens, renderer, canvas, and texture identity", () => {
  const {lens, renderer} = makeBareLens();
  const identities = {lens, renderer, canvas: renderer.canvas, texture: renderer.texture};
  for (let index = 0; index < 500; index += 1) {
    lens.setOptions({material: -1 + (index % 201) / 100});
  }
  assert.equal(lens, identities.lens);
  assert.equal(renderer, identities.renderer);
  assert.equal(renderer.canvas, identities.canvas);
  assert.equal(renderer.texture, identities.texture);
  assert.equal(renderer.captureCount, 0);
  close(lens.options.material, -0.03);
});

test("a fast signed wheel sweep finishes on the current frame without rebuilding", () => {
  const {lens, renderer} = makeBareLens();
  const identities = {lens, renderer, canvas: renderer.canvas, texture: renderer.texture};
  const sweep = [0, -1, 0, 1, 0];
  for (let pass = 0; pass < 100; pass += 1) {
    for (const material of sweep) lens.setOptions({material});
  }
  assert.equal(lens.options.material, 0);
  assert.equal(lens.resolveOptics(1).materialAlpha, 0);
  assert.equal(lens, identities.lens);
  assert.equal(renderer, identities.renderer);
  assert.equal(renderer.canvas, identities.canvas);
  assert.equal(renderer.texture, identities.texture);
  assert.equal(renderer.captureCount, 0);
  assert.equal(renderer.requestCount, sweep.length * 100);
});

test("signed transitions interrupt from the current rendered scalar without a jump", () => {
  const {lens} = makeBareLens(-0.8);
  now = 0;
  lens.transitionOptions({material: 0.7}, {duration: 500, easing: "linear"});
  assert.equal(lens._advanceTransition(250), true);
  close(lens.options.material, -0.05);
  const beforeInterrupt = lens.options.material;

  now = 250;
  lens.transitionOptions({material: -0.2}, {duration: 500, easing: "linear"});
  close(lens.options.material, beforeInterrupt);
  lens._advanceTransition(500);
  close(lens.options.material, -0.125);
  const derived = lens.resolveOptics(1);
  close(derived.refraction, resolve(lens.options.material).refraction);
  close(derived.frostSigmaPx, resolve(lens.options.material).frostSigmaPx);

  lens.transitionOptions({material: 0.4}, {duration: 0});
  close(lens.options.material, 0.4);
  assert.equal(lens._transition, null);
});

test("frost and refraction unit conversions are source- and viewport-invariant", () => {
  const texelScales = [0.25, 1, 2].map((scale) => {
    const textureWidth = 1000 * scale;
    const perCss = api.testing.sourceTexelsPerCssPixel(textureWidth, textureWidth, 1000, 1000)[0];
    const textureUvPerTexel = 1 / textureWidth;
    return 12.48 * perCss * textureUvPerTexel;
  });
  texelScales.forEach((value) => close(value, 12.48 / 1000));

  for (const source of [[430, 932], [1440, 900]]) {
    const lensWidth = 240;
    const lensHeight = 56;
    const bounds = [lensWidth / source[0], lensHeight / source[1]];
    const uv = api.testing.lensMinorDimensionInSourceUV(lensWidth, lensHeight, bounds[0], bounds[1]);
    close(uv[0] * source[0], 56);
    close(uv[1] * source[1], 56);
  }
});

test("shader uses screen-space frost, lens-relative displacement, and SDF edge lobes", () => {
  assert.match(source, /u_sourceTexelsPerCssPixel/);
  assert.match(source, /lensMinorDimensionInSourceUV/);
  assert.match(source, /outerPeak/);
  assert.match(source, /innerRim/);
  assert.doesNotMatch(source, /\blp1\b|\blp2\b/);
  assert.doesNotMatch(source, /u_glassDarkAmount|u_glassLightAmount/);
  assert.doesNotMatch(source, /_on(?:MouseEnter|MouseMove|TouchStart|TouchMove|TouchEnd)\.bind\(this\)/);
});
