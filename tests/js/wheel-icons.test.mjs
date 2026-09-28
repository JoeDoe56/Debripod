import assert from "node:assert/strict";
import {createRequire} from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const wheelIcons = require("../../debripod/static/js/wheel-icons.js");

function fakeLabel(){
  const classes = new Set();
  const icon = {
    attributes: new Map([["src", "/icons/button4_media-paused.svg"]]),
    hidden: false,
    style: {getPropertyValue(name){return this[name] || "";},setProperty(name, value){ this[name] = value; }},
    classList: {toggle(name, enabled){ enabled ? classes.add(name) : classes.delete(name); }},
    getAttribute(name){ return this.attributes.get(name) || null; },
    setAttribute(name, value){ this.attributes.set(name, value); }
  };
  const menu = {hidden: true};
  const label = {
    dataset: {},
    hidden: false,
    querySelector(selector){
      if(selector === ".menuWord") return menu;
      if(selector === ".wheelIcon") return icon;
      return null;
    }
  };
  return {label, menu, icon, classes};
}

test("wheel label updates the repository image asset without replacing its image node", () => {
  const fixture = fakeLabel();
  const originalIcon = fixture.icon;

  wheelIcons.update(fixture.label, "heart", false, {seekMode: true});
  assert.equal(fixture.icon.getAttribute("src"), "/icons/button2_seek-mode_liked-inactive.svg");
  assert.equal(fixture.icon.style["--wheel-icon-mask"], 'url("/icons/button2_seek-mode_liked-inactive.svg")');
  assert.equal(fixture.icon, originalIcon);
  assert.equal(fixture.menu.hidden, true);
  assert.equal(fixture.classes.has("seekModeIcon"), true);

  wheelIcons.update(fixture.label, "heart", true, {seekMode: true});
  assert.equal(fixture.icon.getAttribute("src"), "/icons/button2_seek-mode_liked-active.svg");
  assert.equal(fixture.icon, originalIcon);

  wheelIcons.update(fixture.label, "menu", false);
  assert.equal(fixture.menu.hidden, false);
  assert.equal(fixture.icon.hidden, true);
});

test("wheel symbol mapping covers every playback state", () => {
  assert.deepEqual(
    [
      wheelIcons.symbolFor("prev"), wheelIcons.symbolFor("next"),
      wheelIcons.symbolFor("back15"), wheelIcons.symbolFor("forward15"),
      wheelIcons.symbolFor("play"), wheelIcons.symbolFor("pause"),
      wheelIcons.symbolFor("heart", false), wheelIcons.symbolFor("heart", true),
      wheelIcons.symbolFor("shuffle", false), wheelIcons.symbolFor("shuffle", true)
    ],
    [
      "button5_previous-track.svg", "button3_next-track.svg",
      "button5_seek-mode_skip-back.svg", "button3_seek-mode_skip-forward.svg",
      "button4_media-paused.svg", "button4_media-playing.svg",
      "button2_seek-mode_liked-inactive.svg", "button2_seek-mode_liked-active.svg",
      "shuffleinactivefull-fixed.svg", "shuffleactivefull-fixed.svg"
    ]
  );
});
