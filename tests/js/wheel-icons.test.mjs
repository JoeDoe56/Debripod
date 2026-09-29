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
  assert.equal(fixture.icon.getAttribute("src"), "/static/icons/sf/heart.png");
  assert.equal(fixture.icon.style["--wheel-icon-mask"], 'url("/static/icons/sf/heart.png")');
  assert.equal(fixture.icon, originalIcon);
  assert.equal(fixture.menu.hidden, true);
  assert.equal(fixture.classes.has("seekModeIcon"), true);

  wheelIcons.update(fixture.label, "heart", true, {seekMode: true});
  assert.equal(fixture.icon.getAttribute("src"), "/static/icons/sf/heart.fill.png");
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
      "backward.end.alt.fill", "forward.end.alt.fill",
      "gobackward.15", "goforward.15",
      "playpause", "playpause.fill", "heart", "heart.fill", "shuffle", "shuffle.fill"
    ]
  );
  assert.equal(wheelIcons.assetFor("shuffle",false),"/icons/shuffleinactivefull-fixed.svg");
  assert.equal(wheelIcons.assetFor("shuffle",true),"/icons/shuffleactivefull-fixed.svg");
});
