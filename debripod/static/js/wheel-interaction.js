/*
 * Click-wheel interaction state machine.
 *
 * The wheel has a single pointer owner at a time.  Once an edge pull or a
 * contextual hold resolves, navigation and button handlers must not consume
 * the rest of that pointer sequence.  Keeping that rule here makes the
 * browser bindings and the keyboard fallback agree about the interaction.
 */
(function (globalScope, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (globalScope) {
    const root = globalScope.DebriPod = globalScope.DebriPod || {};
    root.wheelInteractionApi = api;
    if (globalScope.document && globalScope.document.getElementById("wheel")) {
      root.wheelInteraction = api.attach(globalScope);
    }
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const STATES = Object.freeze({
    NORMAL: "normal",
    POTENTIAL_EDGE: "potential_edge",
    RIGHT_PANEL_GESTURE: "right_panel_gesture",
    PANEL_OPEN: "right_panel_open",
    LYRICS_GESTURE: "lyrics_gesture",
    LYRICS_VISIBLE: "lyrics_visible",
    CENTER_HOLD_PENDING: "center_hold_pending",
    ACTION_MODE: "contextual_wheel_action_mode",
    ACTION_TARGET_SELECTED: "action_target_selected",
    ACTION_DEAD_ZONE: "action_dead_zone",
    ACTION_CONFIRMED: "action_confirmed",
    ACTION_CANCELLED: "action_cancelled",
    POTENTIAL_VERTICAL: "potential_vertical_gesture",
    FULLSCREEN_GESTURE: "fullscreen_gesture",
    RANDOM_GESTURE: "random_gesture",
    FULLSCREEN_CONFIRMED: "fullscreen_confirmed",
    RANDOM_CONFIRMED: "random_confirmed",
  });

  const ACTION_POSITIONS = Object.freeze({
    top: "toggle_like",
    bottom: "add_to_playlist",
    right: "play_next",
    left: "play_after",
  });

  const HOLD_DELAY = 320;
  const EDGE_START = 0.27;
  const EDGE_RESOLVE = 24;
  const EDGE_ANGLE_TOLERANCE = 42;
  const DEAD_ZONE = 0.30;
  const ACTION_ZONE = 0.52;
  const VERTICAL_RESOLVE = 24;
  const VERTICAL_ANGLE_TOLERANCE = 42;

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, Number(value) || 0));
  }

  function wheelPoint(point, rect) {
    const r = rect || { left: 0, top: 0, width: 1, height: 1 };
    const x = (Number(point && point.x) || 0) - r.left - r.width / 2;
    const y = (Number(point && point.y) || 0) - r.top - r.height / 2;
    const radius = Math.max(1, Math.min(r.width, r.height) / 2);
    return { x, y, radius, distance: Math.hypot(x, y), angle: Math.atan2(y, x) * 180 / Math.PI };
  }

  function edgeFor(point, rect, nowPlaying, panelOpen, lyricsOpen) {
    const p = wheelPoint(point, rect);
    const edgeX = p.x / p.radius;
    if(Math.abs(p.y / p.radius) > .55) return null;
    if (!nowPlaying && panelOpen && Math.abs(edgeX) <= 0.45) return "right_close";
    if (nowPlaying && lyricsOpen && Math.abs(edgeX) <= 0.45) return "left_close";
    if (nowPlaying) return edgeX <= -EDGE_START ? "left" : null;
    return edgeX >= EDGE_START ? "right" : null;
  }

  function actionForPoint(point, rect) {
    const p = wheelPoint(point, rect);
    const ratio = p.distance / p.radius;
    if (ratio < DEAD_ZONE) return null;
    if (ratio < ACTION_ZONE) return null;
    if (Math.abs(p.x) >= Math.abs(p.y)) return p.x > 0 ? "right" : "left";
    return p.y > 0 ? "bottom" : "top";
  }

  function edgeProgress(start, current, rect, direction) {
    const a = wheelPoint(start, rect);
    const b = wheelPoint(current, rect);
    const minTravel = rect.width * 0.20;
    const closeTravel = rect.width * 0.38;
    const startTravel = Math.max(minTravel, Math.abs(a.x));
    const travel = direction === "right_close" || direction === "left_close" ? closeTravel : startTravel;
    const delta = direction === "right" ? a.x - b.x : direction === "left" ? b.x - a.x : direction === "left_close" ? a.x - b.x : b.x - a.x;
    return clamp(delta / travel, 0, 1);
  }

  // wheel-controls may transfer capture from the hit target to the wheel when
  // a drag begins. Safari emits lostpointercapture for the old target during
  // that transfer; it must not cancel the resolved gesture while the wheel
  // still owns the pointer.
  function shouldIgnoreLostPointerCapture(host, event) {
    try {
      if (!host || !event) return false;
      if (event.target && event.target !== host) return true;
      return !!(typeof host.hasPointerCapture === "function" && event.pointerId != null && host.hasPointerCapture(event.pointerId));
    } catch (_error) {
      return false;
    }
  }

  function requestFullscreen(win){
    try{
      if(win && typeof win.forceFullscreenOn === "function") return Promise.resolve(win.forceFullscreenOn()).catch(()=>false);
      const element=win && win.document && win.document.documentElement;
      if(element && typeof element.requestFullscreen === "function") return Promise.resolve(element.requestFullscreen()).catch(()=>false);
    }catch(_error){}
    return Promise.resolve(false);
  }

  function triggerRandom(win){
    return Promise.resolve().then(()=>win && typeof win.randomFromCurrentList === "function" ? win.randomFromCurrentList() : false)
      .catch(error=>{ if(win && typeof win.reportUiStatus === "function") win.reportUiStatus(String(error.message || error), "warn"); return false; });
  }

  function createInteraction(options) {
    const opts = options || {};
    const callbacks = opts.callbacks || {};
    let state = STATES.NORMAL;
    let pointer = null;
    let timer = null;
    let actions = {};
    let selectedPosition = null;
    let actionTarget = null;
    let lastRect = null;
    let consumedLastPointer = false;

    function emit(name, ...args) {
      const fn = callbacks[name];
      if (typeof fn !== "function") return undefined;
      return fn(...args);
    }
    function transition(next, details) {
      if (state === next && !details) return state;
      const previous = state;
      state = next;
      emit("state", next, previous, details || {});
      return state;
    }
    function nowPlaying() {
      if (typeof opts.isNowPlaying === "function") return !!opts.isNowPlaying();
      return !!opts.nowPlaying;
    }
    function setPanel(open, progress) {
      const amount = clamp(progress == null ? (open ? 1 : 0) : progress, 0, 1);
      emit("panelProgress", amount);
      if (amount >= 1) {
        emit("panelOpen", true);
        transition(STATES.PANEL_OPEN);
      } else if (amount <= 0) {
        emit("panelOpen", false);
        transition(STATES.NORMAL);
      }
    }
    function setLyrics(open, progress) {
      const amount = clamp(progress == null ? (open ? 1 : 0) : progress, 0, 1);
      emit("lyricsProgress", amount);
      if (amount >= 1) {
        emit("lyricsOpen", true);
        transition(STATES.LYRICS_VISIBLE);
      } else if (amount <= 0) {
        emit("lyricsOpen", false);
        transition(STATES.NORMAL);
      }
    }
    function clearTimer() {
      if (timer != null) clearTimeout(timer);
      timer = null;
    }
    function availableActions(target) {
      actionTarget = target || (typeof opts.getTarget === "function" ? opts.getTarget() : null);
      const resolver = opts.actionsForTarget || (opts.mediaActions && opts.mediaActions.wheelActionsForTarget);
      actions = typeof resolver === "function" ? (resolver(actionTarget) || {}) : {};
      return actions;
    }
    function enterActionMode() {
      if (!pointer) return false;
      if (pointer) pointer.holdResolved = true;
      const available = availableActions();
      if (!available || !Object.values(available).some(item => item && item.enabled !== false)) {
        transition(STATES.ACTION_CANCELLED, { reason: "unsupported_target" });
        emit("actionMode", false, actions, actionTarget);
        return false;
      }
      selectedPosition = null;
      emit("actionMode", true, actions, actionTarget);
      transition(STATES.ACTION_DEAD_ZONE, { actions, target: actionTarget });
      return true;
    }
    function updateAction(point) {
      if (!pointer || (state !== STATES.ACTION_DEAD_ZONE && state !== STATES.ACTION_TARGET_SELECTED && state !== STATES.ACTION_MODE)) return;
      const position = actionForPoint(point, pointer.rect);
      const action = position ? actions[ACTION_POSITIONS[position]] : null;
      const next = position && action && action.enabled !== false ? position : null;
      if (next === selectedPosition) return;
      selectedPosition = next;
      emit("actionTarget", selectedPosition, selectedPosition ? actions[ACTION_POSITIONS[selectedPosition]] : null);
      transition(selectedPosition ? STATES.ACTION_TARGET_SELECTED : STATES.ACTION_DEAD_ZONE);
    }
    function begin(point, details) {
      if (pointer) return false;
      consumedLastPointer = false;
      const rect = (details && details.rect) || opts.rect || { left: 0, top: 0, width: 1, height: 1 };
      const target = details && details.target;
      const isCenter = !!(details && details.isCenter) || target === "center";
      const panelOpen = typeof opts.isPanelOpen === "function" ? !!opts.isPanelOpen() : false;
      const lyricsOpen = typeof opts.isLyricsOpen === "function" ? !!opts.isLyricsOpen() : false;
      const hintedEdge = details && details.edgeHint;
      const location = wheelPoint(point, rect);
      const hintedVertical = details && details.verticalHint || (Math.abs(location.x / location.radius) <= .55 && Math.abs(location.y / location.radius) >= .55 ? (location.y < 0 ? "top" : "bottom") : null);
      const edgeCandidate = hintedEdge === "right" || hintedEdge === "left"
        ? ((nowPlaying() && hintedEdge === "left") || (!nowPlaying() && hintedEdge === "right") ? hintedEdge : null)
        : edgeFor(point, rect, nowPlaying(), panelOpen, lyricsOpen);
      const edge = isCenter ? null : edgeCandidate;
      pointer = {
        start: { x: point.x, y: point.y }, current: { x: point.x, y: point.y }, rect, edge,
        edgeCandidate: isCenter ? edgeCandidate : null,
        verticalCandidate: isCenter || (hintedVertical !== "top" && hintedVertical !== "bottom") ? null : hintedVertical,
        isCenter, moved: false, edgeEligible: !!edge,
        pointerId: details && details.pointerId != null ? details.pointerId : null,
        panelInitial: panelOpen ? 1 : 0, lyricsInitial: lyricsOpen ? 1 : 0,
      };
      lastRect = rect;
      emit("suppress", false);
      if (edge) {
        transition(STATES.POTENTIAL_EDGE, { edge });
      } else if (!isCenter && (hintedVertical === "top" || hintedVertical === "bottom")) {
        transition(STATES.POTENTIAL_VERTICAL, { vertical: hintedVertical });
      } else if (isCenter) {
        transition(STATES.CENTER_HOLD_PENDING);
        clearTimer();
        timer = setTimeout(() => {
          timer = null;
          if (!pointer || pointer.moved) return;
          emit("suppress", true);
          enterActionMode();
        }, Number(opts.holdDelay || HOLD_DELAY));
      }
      return true;
    }
    function move(point, details) {
      if (!pointer) return false;
      const movePointerId = details && details.pointerId != null ? details.pointerId : (point && point.pointerId);
      if (pointer.pointerId != null && movePointerId != null && pointer.pointerId !== movePointerId) return false;
      pointer.current = { x: point.x, y: point.y };
      const dx = point.x - pointer.start.x;
      const dy = point.y - pointer.start.y;
      pointer.moved = pointer.moved || Math.hypot(dx, dy) >= 8;
      if (state === STATES.POTENTIAL_VERTICAL && pointer.verticalCandidate) {
        const vertical = pointer.verticalCandidate;
        const directionWrong = vertical === "top" ? dy <= 0 : dy >= 0;
        const angleOkay = Math.abs(dx) <= Math.abs(dy) * Math.tan(VERTICAL_ANGLE_TOLERANCE * Math.PI / 180);
        const thresholdCrossed = vertical === "top" ? dy >= VERTICAL_RESOLVE : dy <= -VERTICAL_RESOLVE;
        // Keep the candidate alive while the user is still moving in the
        // intended direction, even if the first move is below the threshold.
        // This avoids cancelling shallow diagonal pulls at 23px/8px.
        if (Math.hypot(dx, dy) >= VERTICAL_RESOLVE && (directionWrong || !angleOkay)) {
          pointer.verticalCandidate = null;
          transition(STATES.NORMAL, { reason: "circular_wheel_motion" });
        } else if (thresholdCrossed && !directionWrong && angleOkay) {
          clearTimer();
          emit("suppress", true);
          pointer.verticalProgress = clamp((vertical === "top" ? dy : -dy) / Math.max(VERTICAL_RESOLVE, pointer.rect.height * 0.22), 0, 1);
          transition(vertical === "top" ? STATES.FULLSCREEN_GESTURE : STATES.RANDOM_GESTURE, { vertical });
          emit("verticalProgress", vertical, pointer.verticalProgress);
        }
      } else if (state === STATES.FULLSCREEN_GESTURE || state === STATES.RANDOM_GESTURE) {
        const vertical = state === STATES.FULLSCREEN_GESTURE ? "top" : "bottom";
        const dy = point.y - pointer.start.y;
        pointer.verticalProgress = clamp((vertical === "top" ? dy : -dy) / Math.max(VERTICAL_RESOLVE, pointer.rect.height * 0.22), 0, 1);
        emit("verticalProgress", vertical, pointer.verticalProgress);
      } else if (state === STATES.POTENTIAL_EDGE && pointer.edge && pointer.edgeEligible) {
        const directionWrong = pointer.edge === "right" ? dx >= 0 : pointer.edge === "left" ? dx <= 0 : pointer.edge === "right_close" ? dx <= 0 : dx >= 0;
        const inward = pointer.edge === "right" ? dx <= -EDGE_RESOLVE : pointer.edge === "left" ? dx >= EDGE_RESOLVE : pointer.edge === "right_close" ? dx >= EDGE_RESOLVE : dx <= -EDGE_RESOLVE;
        const angleOkay = Math.abs(dy) <= Math.abs(dx) * Math.tan(EDGE_ANGLE_TOLERANCE * Math.PI / 180);
        if (Math.hypot(dx, dy) >= EDGE_RESOLVE && (directionWrong || !angleOkay)) {
          pointer.edgeEligible = false;
          transition(STATES.NORMAL, { reason: "circular_wheel_motion" });
        }
        if (inward && angleOkay) {
          clearTimer();
          emit("suppress", true);
          const progress = edgeProgress(pointer.start, point, pointer.rect, pointer.edge);
          transition(pointer.edge.indexOf("right") === 0 ? STATES.RIGHT_PANEL_GESTURE : STATES.LYRICS_GESTURE, { edge: pointer.edge });
          if (pointer.edge.indexOf("right") === 0) emit("panelProgress", pointer.edge === "right_close" ? 1 - progress : progress);
          else emit("lyricsProgress", pointer.edge === "left_close" ? 1 - progress : progress);
        }
      } else if (state === STATES.RIGHT_PANEL_GESTURE) {
        const progress = edgeProgress(pointer.start, point, pointer.rect, pointer.edge);
        emit("panelProgress", pointer.edge === "right_close" ? 1 - progress : progress);
      } else if (state === STATES.LYRICS_GESTURE) {
        const progress = edgeProgress(pointer.start, point, pointer.rect, pointer.edge);
        emit("lyricsProgress", pointer.edge === "left_close" ? 1 - progress : progress);
      } else if (state === STATES.CENTER_HOLD_PENDING) {
        if (Math.hypot(dx, dy) < 8) return true;
        const candidate = pointer.edgeCandidate;
        if(candidate && Math.abs(dx) >= Math.abs(dy) && Math.abs(dx) < EDGE_RESOLVE){clearTimer();return true;}
        const candidateInward = candidate === "right_close" ? dx > EDGE_RESOLVE : candidate === "left_close" ? dx < -EDGE_RESOLVE : false;
        if (candidate && Math.abs(dx) >= Math.abs(dy) && candidateInward) {
          clearTimer();
          pointer.edge = candidate;
          pointer.edgeEligible = true;
          emit("suppress", true);
          const progress = edgeProgress(pointer.start, point, pointer.rect, candidate);
          transition(candidate === "right_close" ? STATES.RIGHT_PANEL_GESTURE : STATES.LYRICS_GESTURE, {edge: candidate});
          if (candidate === "right_close") emit("panelProgress", 1 - progress);
          else emit("lyricsProgress", 1 - progress);
          return true;
        }
        clearTimer();
        emit("suppress", true);
        transition(STATES.NORMAL, { reason: "center_moved_before_hold" });
      } else if (state === STATES.ACTION_DEAD_ZONE || state === STATES.ACTION_TARGET_SELECTED || state === STATES.ACTION_MODE) {
        emit("suppress", true);
        updateAction(point);
      }
      return true;
    }
    function end(details) {
      if (!pointer) return { state, action: null };
      const endPointerId = details && details.pointerId != null ? details.pointerId : null;
      if (pointer.pointerId != null && endPointerId != null && pointer.pointerId !== endPointerId) return { state, action: null };
      clearTimer();
      const finished = state;
      let action = null;
      let gesture = null;
      if (finished === STATES.RIGHT_PANEL_GESTURE) {
        const progress = edgeProgress(pointer.start, pointer.current, pointer.rect, pointer.edge);
        const amount = pointer.edge === "right_close" ? 1 - progress : progress;
        setPanel(amount >= 0.5, amount >= 0.5 ? 1 : 0);
      } else if (finished === STATES.LYRICS_GESTURE) {
        const progress = edgeProgress(pointer.start, pointer.current, pointer.rect, pointer.edge);
        const amount = pointer.edge === "left_close" ? 1 - progress : progress;
        setLyrics(amount >= 0.5, amount >= 0.5 ? 1 : 0);
      } else if (finished === STATES.ACTION_TARGET_SELECTED && selectedPosition) {
        action = actions[ACTION_POSITIONS[selectedPosition]] || null;
        transition(STATES.ACTION_CONFIRMED, { position: selectedPosition, action });
        emit("action", action && (action.action || ACTION_POSITIONS[selectedPosition]), actionTarget, action);
      } else if (finished === STATES.ACTION_DEAD_ZONE || finished === STATES.ACTION_MODE) {
        transition(STATES.ACTION_CANCELLED, { reason: "dead_zone" });
      } else if (finished === STATES.FULLSCREEN_GESTURE && pointer.verticalProgress >= .5) {
        gesture = "fullscreen";
        transition(STATES.FULLSCREEN_CONFIRMED, { vertical: "top" });
        emit("fullscreen");
      } else if (finished === STATES.RANDOM_GESTURE && pointer.verticalProgress >= .5) {
        gesture = "random";
        transition(STATES.RANDOM_CONFIRMED, { vertical: "bottom" });
        emit("random");
      }
      const result = { state, action, gesture, position: selectedPosition, target: actionTarget };
      consumedLastPointer = !!pointer.holdResolved || finished === STATES.RIGHT_PANEL_GESTURE || finished === STATES.LYRICS_GESTURE || finished === STATES.ACTION_TARGET_SELECTED || finished === STATES.ACTION_DEAD_ZONE || finished === STATES.ACTION_MODE || finished === STATES.FULLSCREEN_GESTURE || finished === STATES.RANDOM_GESTURE;
      emit("actionMode", false, actions, actionTarget);
      emit("suppress", false);
      pointer = null;
      selectedPosition = null;
      actions = {};
      actionTarget = null;
      transition(STATES.NORMAL);
      return result;
    }
    function cancel(reason, details) {
      clearTimer();
      if (!pointer) return;
      const cancelPointerId = details && details.pointerId != null ? details.pointerId : null;
      if (pointer.pointerId != null && cancelPointerId != null && pointer.pointerId !== cancelPointerId) return;
      const restorePanel = pointer.edge && pointer.edge.indexOf("right") === 0 && (state === STATES.POTENTIAL_EDGE || state === STATES.RIGHT_PANEL_GESTURE);
      const restoreLyrics = pointer.edge && pointer.edge.indexOf("left") === 0 && (state === STATES.POTENTIAL_EDGE || state === STATES.LYRICS_GESTURE);
      transition(STATES.ACTION_CANCELLED, { reason: reason || "cancelled" });
      emit("actionMode", false, actions, actionTarget);
      if (restorePanel) {
        emit("panelProgress", pointer.panelInitial);
        emit("panelOpen", pointer.panelInitial >= 1);
      }
      if (restoreLyrics) {
        emit("lyricsProgress", pointer.lyricsInitial);
        emit("lyricsOpen", pointer.lyricsInitial >= 1);
      }
      if (pointer.verticalCandidate) {
        emit("verticalProgress", pointer.verticalCandidate, 0);
      }
      emit("suppress", false);
      pointer = null;
      selectedPosition = null;
      actions = {};
      actionTarget = null;
      transition(STATES.NORMAL);
    }
      return {
      STATES, ACTION_POSITIONS, begin, move, end, cancel, enterActionMode,
      state: () => state,
      isActive: () => !!pointer,
      selectedPosition: () => selectedPosition,
      actions: () => Object.assign({}, actions),
      consumePointer: () => { const result = consumedLastPointer; consumedLastPointer = false; return result; },
      requestFullscreen: () => requestFullscreen(opts.window),
      triggerRandom: () => triggerRandom(opts.window),
    };
  }

  function attach(win, options) {
    const doc = win.document;
    const wheel = (options && options.wheel) || doc.getElementById("wheel");
    if (!wheel) return null;
    if (wheel.__debripodWheelInteraction) return wheel.__debripodWheelInteraction;
    const root = win.DebriPod = win.DebriPod || {};
    const rowSystem = root.rowSystem || {};
    const lyrics = root.lyrics || {};
    const labels = { top: ".wlTop", right: ".wlRight", bottom: ".wlBottom", left: ".wlLeft" };
    const interaction = createInteraction({
      window: win,
      isNowPlaying: () => !!(win.nowPlaying && win.nowPlaying.style.display === "block"),
      isPanelOpen: () => typeof rowSystem.isPanelOpen === "function" && rowSystem.isPanelOpen(),
      isLyricsOpen: () => typeof lyrics.isOpen === "function" && lyrics.isOpen(),
      getTarget: () => root.mediaActions && root.mediaActions.targetFromCurrent ? root.mediaActions.targetFromCurrent() : null,
      actionsForTarget: target => root.mediaActions && root.mediaActions.wheelActionsForTarget ? root.mediaActions.wheelActionsForTarget(target) : {},
      callbacks: {
        panelProgress: value => typeof rowSystem.setPanelProgress === "function" && rowSystem.setPanelProgress(value, {immediate: true}),
        panelOpen: value => typeof rowSystem.setPanelOpen === "function" && rowSystem.setPanelOpen(value, {animate: true}),
        lyricsProgress: value => typeof lyrics.setProgress === "function" && lyrics.setProgress(value, {immediate: true}),
        lyricsOpen: value => typeof lyrics.setOpen === "function" && lyrics.setOpen(value, {animate: true}),
        fullscreen: () => requestFullscreen(win),
        random: () => triggerRandom(win),
        actionMode: (active, actions) => {
          wheel.classList.toggle("wheelActionMode", !!active);
          const actionSymbols = {toggle_like: "heart", add_to_playlist: "addToPlaylist", play_next: "playNext", play_after: "playAfter"};
          Object.keys(labels).forEach(position => {
            const label = wheel.querySelector(labels[position]);
            if (!label) return;
            const key = ACTION_POSITIONS[position];
            const item = actions && actions[key];
            label.dataset.wheelAction = active ? key : "";
            label.classList.toggle("wheelActionDisabled", !!active && (!item || item.enabled === false));
            if (active && item) {
              const icon = label.querySelector(".wheelIcon");
              const symbol = actionSymbols[key];
              if (icon && root.uiPrimitives && typeof root.uiPrimitives.setSymbol === "function") {
                root.uiPrimitives.setSymbol(icon, symbol, {active:!!item.active, label: item.label || key});
                icon.hidden = false;
              } else if (root.wheelIcons && typeof root.wheelIcons.update === "function") {
                root.wheelIcons.update(label, symbol, false);
              }
              const menu = label.querySelector(".menuWord");
              if (menu) menu.hidden = true;
            }
            if (root.uiPrimitives && typeof root.uiPrimitives.setSelectedState === "function") {
              root.uiPrimitives.setSelectedState(label, false);
            }
          });
          if (!active && typeof win.updateWheelLabels === "function") win.updateWheelLabels();
        },
        actionTarget: position => {
          Object.keys(labels).forEach(key => {
            const label = wheel.querySelector(labels[key]);
            if (label) {
              label.classList.toggle("wheelActionSelected", key === position);
              if (root.uiPrimitives && typeof root.uiPrimitives.setSelectedState === "function") root.uiPrimitives.setSelectedState(label, key === position, {symbolActive:true, label:label.dataset.wheelAction || key});
            }
          });
        },
        action: (action, target) => {
          if (root.mediaActions && typeof root.mediaActions.executeWheelAction === "function") {
            Promise.resolve(root.mediaActions.executeWheelAction(action, target)).catch(error => {
              if (typeof win.reportUiStatus === "function") win.reportUiStatus("Action failed: " + (error.message || error), "error");
            });
          }
        },
        suppress: active => wheel.classList.toggle("wheelInteractionResolved", !!active),
      },
    });
    ["pointerdown", "pointermove", "pointerup", "pointercancel", "lostpointercapture"].forEach(type => {
      wheel.addEventListener(type, event => {
        // Ordinary wheel rotation transfers capture from a directional hit
        // region to the wheel. That is still the same owned interaction.
        if(type === "lostpointercapture" && shouldIgnoreLostPointerCapture(wheel, event)) return;
        const point = { x: event.clientX, y: event.clientY };
        const rect = wheel.getBoundingClientRect();
        const pointerDetails = {pointerId: event.pointerId};
        if (type === "pointerdown") {
          const center = !!(event.target && event.target.closest && event.target.closest("#btnCenter"));
          const right = !!(event.target && event.target.closest && event.target.closest(".hitRight"));
          const left = !!(event.target && event.target.closest && event.target.closest(".hitLeft"));
          const top = !!(event.target && event.target.closest && event.target.closest(".hitTop"));
          const bottom = !!(event.target && event.target.closest && event.target.closest(".hitBottom"));
          interaction.begin(point, Object.assign(pointerDetails, {rect, target: center ? "center" : "", isCenter: center, edgeHint: right ? "right" : (left ? "left" : null), verticalHint: top ? "top" : (bottom ? "bottom" : null)}));
        }
        else if (type === "pointermove") interaction.move(point, pointerDetails);
        else if (type === "pointerup") interaction.end(pointerDetails);
        else if (type === "lostpointercapture") interaction.cancel("lostpointercapture", pointerDetails);
        else interaction.cancel(type === "lostpointercapture" ? "lostpointercapture" : "pointercancel", pointerDetails);
      }, { passive: false, capture: true });
    });
    wheel.__debripodWheelInteraction = interaction;
    return interaction;
  }

  return { STATES, ACTION_POSITIONS, createInteraction, attach, edgeFor, actionForPoint, shouldIgnoreLostPointerCapture, requestFullscreen, triggerRandom };
});
