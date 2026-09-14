/*
 * liquidGL – Ultra-light glassmorphism for the web
 * -----------------------------------------------------------------------------
 *
 * Author: NaughtyDuk© – https://liquidgl.naughtyduk.com
 * Licence: MIT
 */

(() => {
  "use strict";

  /* --------------------------------------------------
   *  Utilities
   * ------------------------------------------------*/
  function liquidGLDebugEnabled() {
    try {
      if (window.LIQUID_GL_DEBUG === true || window.DEBRIPOD_UI_DEBUG === true) {
        return true;
      }
      return (localStorage.getItem("debripod_ui_debug") || "") === "1";
    } catch (e) {
      return false;
    }
  }

  function liquidGLLog(method, ...args) {
    if (!liquidGLDebugEnabled()) return;
    try {
      if (console && console[method]) console[method](...args);
    } catch (e) {}
  }

  function debounce(fn, wait) {
    let t;
    return (...a) => {
      clearTimeout(t);
      t = setTimeout(() => fn.apply(null, a), wait);
    };
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function finiteNumber(value, fallback) {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  }

  function isPowerOfTwoTexture(width, height) {
    return Number.isInteger(width) && Number.isInteger(height) && width > 0 && height > 0 &&
      (width & (width - 1)) === 0 && (height & (height - 1)) === 0;
  }

  function normalizeLiquidGlassMaterial(value, fallback = 0) {
    return clamp(finiteNumber(value, fallback), -1, 1);
  }

  function mixNumber(from, to, amount) {
    return from + (to - from) * amount;
  }

  function resolveLiquidGlassMaterial(material, geometry, quality) {
    const m = normalizeLiquidGlassMaterial(material, 0);
    const density = Math.abs(m);
    const side = m < 0 ? -1 : (m > 0 ? 1 : 0);
    const beyondApple = clamp((density - 0.52) / 0.48, 0, 1);
    const darkTone = mixNumber(35 / 255, 0, beyondApple);
    const tone = side < 0
      ? [darkTone, darkTone, darkTone]
      : [1, 1, 1];
    const qualityScale = clamp(finiteNumber(quality, 1), 0.45, 1);

    return {
      material: m,
      density,
      side,
      tone,
      materialAlpha: density,
      frostSigmaPx: 24 * density,
      frostSampleScale: qualityScale,
      refraction: 0.045 + 0.025 * density,
      refractionFill: 0,
      bevelDepth: 0.075 + 0.045 * density,
      bevelWidth: 0.095 + 0.020 * density,
      magnify: 1.012 - 0.007 * density,
      specularPrimary: mixNumber(0.1675, 0.145, m),
      specularSecondary: mixNumber(0.080, 0.105, m),
      shadowStrength: 0.08 + 0.10 * density,
      specular: true,
      geometry: geometry || null,
    };
  }

  function sourceTexelsPerCssPixel(textureWidth, textureHeight, cssWidth, cssHeight) {
    return [
      Math.max(1, finiteNumber(textureWidth, 1)) / Math.max(1, finiteNumber(cssWidth, 1)),
      Math.max(1, finiteNumber(textureHeight, 1)) / Math.max(1, finiteNumber(cssHeight, 1)),
    ];
  }

  function lensMinorDimensionInSourceUV(lensWidth, lensHeight, boundsWidth, boundsHeight) {
    const width = Math.max(1, finiteNumber(lensWidth, 1));
    const height = Math.max(1, finiteNumber(lensHeight, 1));
    const minor = Math.min(width, height);
    return [
      (minor / width) * finiteNumber(boundsWidth, 0),
      (minor / height) * finiteNumber(boundsHeight, 0),
    ];
  }

  const LIQUID_GL_EASINGS = Object.freeze({
    linear: (t) => t,
    easeIn: (t) => t * t,
    easeOut: (t) => 1 - (1 - t) * (1 - t),
    easeInOut: (t) => t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2,
  });

  const LIQUID_GL_LIVE_NUMERIC_OPTIONS = Object.freeze({
    material: [-1, 1],
    refraction: [0, 1],
    refractionFill: [0, 1],
    bevelDepth: [0, 1],
    bevelWidth: [0, 1],
    frost: [0, 100],
    magnify: [0.001, 3],
  });

  /* --------------------------------------------------
   *  Helper : Effective z-index (highest stacking context)
   * ------------------------------------------------*/
  function effectiveZ(el) {
    let node = el;
    while (node && node !== document.body) {
      const style = window.getComputedStyle(node);
      if (style.position !== "static" && style.zIndex !== "auto") {
        const z = parseInt(style.zIndex, 10);
        if (!isNaN(z)) return z;
      }
      node = node.parentElement;
    }
    return 0;
  }

  /* --------------------------------------------------
   *  WebGL helpers
   * ------------------------------------------------*/
  function compileShader(gl, type, src) {
    const s = gl.createShader(type);
    gl.shaderSource(s, src.trim());
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
      const detail = gl.getShaderInfoLog(s) || "unknown compiler error";
      gl.deleteShader(s);
      throw new Error(`liquidGL: ${type === gl.VERTEX_SHADER ? "vertex" : "fragment"} shader failed: ${detail}`);
    }
    return s;
  }

  function createProgram(gl, vsSource, fsSource) {
    const vs = compileShader(gl, gl.VERTEX_SHADER, vsSource);
    const fs = compileShader(gl, gl.FRAGMENT_SHADER, fsSource);
    if (!vs || !fs) return null;
    const p = gl.createProgram();
    gl.attachShader(p, vs);
    gl.attachShader(p, fs);
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) {
      throw new Error(`liquidGL: program link failed: ${gl.getProgramInfoLog(p) || "unknown linker error"}`);
    }
    return p;
  }

  /* --------------------------------------------------
   *  Glassworks capture backend.
   *  DebriPod uses direct visualizer, album art, video, or WebGL sources for
   *  normal renderers. DOM snapshots are snapdom-only and never use fallback
   *  canvas rasterizers, so text can stay isolated above the glass.
   * ------------------------------------------------*/

  function parseBackgroundImageUrl(value) {
    if (!value || value === "none") return null;
    const m = String(value).match(/^url\(["']?([^)"']+)["']?\)\s*$/);
    return m ? m[1] : null;
  }

  async function injectBackgroundImageShims(target) {
    const cleanups = [];
    const loads = [];
    if (!target || !target.querySelectorAll) return cleanups;
    target.querySelectorAll("*").forEach((el) => {
      let cs;
      try { cs = window.getComputedStyle(el); } catch (e) { return; }
      const url = parseBackgroundImageUrl(cs.backgroundImage);
      if (!url) return;
      const restores = [];
      if (cs.position === "static") {
        const prev = el.style.position;
        el.style.position = "relative";
        restores.push(() => { el.style.position = prev; });
      }
      if (cs.isolation !== "isolate") {
        const prev = el.style.isolation;
        el.style.isolation = "isolate";
        restores.push(() => { el.style.isolation = prev; });
      }
      const shim = document.createElement("img");
      shim.crossOrigin = "anonymous";
      shim.setAttribute("data-liquidgl-bg-shim", "");
      shim.setAttribute("data-liquid-ignore", "");
      shim.style.cssText = [
        "position:absolute",
        "inset:0",
        "width:100%",
        "height:100%",
        "object-fit:" + (cs.backgroundSize === "contain" ? "contain" : "cover"),
        "object-position:" + (cs.backgroundPosition || "50% 50%"),
        "pointer-events:none",
        "z-index:-1",
        "border-radius:" + cs.borderRadius,
        "user-select:none"
      ].join(";");
      loads.push(new Promise((resolve) => {
        let done = false;
        const finish = () => { if (!done) { done = true; resolve(); } };
        shim.addEventListener("load", finish, { once: true });
        shim.addEventListener("error", finish, { once: true });
        setTimeout(finish, 1500);
      }));
      shim.src = url;
      el.insertBefore(shim, el.firstChild);
      cleanups.push(() => {
        if (shim.parentNode) shim.parentNode.removeChild(shim);
        for (let i = restores.length - 1; i >= 0; i--) restores[i]();
      });
    });
    if (loads.length) await Promise.all(loads);
    return cleanups;
  }

  function snapshotLooksComplete(canvas) {
    if (!canvas || canvas.width <= 0 || canvas.height <= 0 || canvas.height < 200) return true;
    let ctx;
    try { ctx = canvas.getContext("2d", { willReadFrequently: true }); } catch (e) { return true; }
    if (!ctx) return true;
    const rows = [Math.floor(canvas.height * 0.55), Math.floor(canvas.height * 0.75), Math.max(0, canvas.height - 32)];
    for (const y of rows) {
      let data;
      try { data = ctx.getImageData(0, y, canvas.width, 1).data; } catch (e) { return true; }
      let opaque = 0;
      for (let i = 0; i < data.length; i += 4) if (data[i + 3] > 16) opaque++;
      if (opaque / Math.max(1, data.length / 4) > 0.01) return true;
    }
    return false;
  }

  async function snapdomCapture(target, scale) {
    return window.snapdom.toCanvas(target, {
      scale,
      dpr: 1,
      outerTransforms: false,
      backgroundColor: "transparent",
      crossOrigin: "anonymous",
      embedFonts: true
    });
  }

  async function snapToCanvas(target, { scale, ignore, engine, onEngineFallback, validateCompleteness } = {}) {
    if ((engine || "snapdom") !== "snapdom") throw new Error("liquidGL: DOM snapshot engine disabled.");
    if (typeof window.snapdom === "undefined") {
      throw new Error("liquidGL: snapdom missing and DOM snapshot fallback is disabled.");
    }
    const restores = [];
    if (typeof ignore === "function" && target.querySelectorAll) {
      target.querySelectorAll("*").forEach((el) => {
        try {
          if (ignore(el)) {
            const prev = el.style.visibility;
            el.style.visibility = "hidden";
            restores.push(() => { el.style.visibility = prev; });
          }
        } catch (e) {}
      });
    }
    const shimCleanups = await injectBackgroundImageShims(target);
    let canvas = null;
    let failed = false;
    try {
      canvas = await snapdomCapture(target, scale);
    } catch (e) {
      failed = true;
      liquidGLLog("warn", "liquidGL: snapdom capture failed.", e);
    } finally {
      for (let i = restores.length - 1; i >= 0; i--) restores[i]();
    }
    if (failed || (validateCompleteness === true && !snapshotLooksComplete(canvas))) {
      if (typeof onEngineFallback === "function") onEngineFallback("disabled");
      for (let i = shimCleanups.length - 1; i >= 0; i--) shimCleanups[i]();
      throw new Error("liquidGL: DOM snapshot capture unavailable.");
    }
    for (let i = shimCleanups.length - 1; i >= 0; i--) shimCleanups[i]();
    return canvas;
  }

  /* --------------------------------------------------
   *  Shared renderer (one per page)
   * ------------------------------------------------*/
  class liquidGLRenderer {
    constructor(snapshotSelector, snapshotResolution = 1.0, rendererKey = "default", sourceOptions = {}) {
      this.canvas = document.createElement("canvas");
      this.canvas.style.cssText = `position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:0;`;
      this.canvas.setAttribute("data-liquid-ignore", "");
      this.canvas.setAttribute("data-liquid-renderer", rendererKey || "default");
      document.body.appendChild(this.canvas);

      const isMobileSafari = /iPad|iPhone|iPod/.test(navigator.userAgent);
      const ctxAttribs = {
        alpha: true,
        premultipliedAlpha: true,
        antialias: false,
        depth: false,
        stencil: false,
        preserveDrawingBuffer: false,
      };
      this.gl =
        this.canvas.getContext("webgl", ctxAttribs) ||
        this.canvas.getContext("experimental-webgl", ctxAttribs);
      if (!this.gl) throw new Error("liquidGL: WebGL unavailable");

      this.lenses = [];
      this.rendererKey = rendererKey || "default";
      this.texture = null;
      this.textureWidth = 0;
      this.textureHeight = 0;
      this.scaleFactor = 1;
      this.startTime = Date.now();
      this._scrollUpdateCounter = 0;
      this._snapshotResolution = Math.max(
        0.1,
        Math.min(3.0, snapshotResolution)
      );
      this.sourceType = sourceOptions.sourceType || "visualizerWebgl";
      this.sourceSelector = sourceOptions.sourceElement || sourceOptions.source || "#visualizerBg";
      this.sourceCssSelector = sourceOptions.sourceCssElement || sourceOptions.sourceCssSelector || null;
      this.sourceProvider = typeof sourceOptions.sourceProvider === "function" ? sourceOptions.sourceProvider : null;
      this._engine = "snapdom";
      this._sourceElement = null;
      this._sourceCssRect = null;
      this._sourceTextureReady = false;
      this._sourceIsSolidFallback = false;
      this._sourceOwnsTexture = true;
      this._reactiveArtKey = "";
      this._reactiveArtActive = false;
      this._solidCanvas = null;
      this._albumCurrentTexture = null;
      this._albumNextTexture = null;
      this._albumUploadedCurrentSrc = "";
      this._albumUploadedNextSrc = "";
      this._albumCurrentSize = { width: 1, height: 1 };
      this._albumNextSize = { width: 1, height: 1 };
      this._albumMix = 0;
      this._albumTransitioning = false;
      this._albumFrameId = 0;
      this._albumSourceKey = "";
      this._albumRenderedAt = 0;
      this._albumSourceRect = null;
      this._albumSourceSize = { width: 1, height: 1 };
      this._debugCanaryTexture = null;
      this._hiddenSkipSince = 0;
      this.renderCount = 0;
      this.sourceRefreshCount = 0;
      this._renderSubmissionSamples = [];
      this._renderSubmissionTotalMs = 0;
      this.visible = true;
      this._adaptiveQuality = 1;

      this._initGL();

      this.snapshotTarget =
        document.querySelector(snapshotSelector) || document.body;
      if (!this.snapshotTarget) this.snapshotTarget = document.body;

      this._isScrolling = false;
      let lastScrollY = window.scrollY;
      let scrollTimeout;
      const scrollCheck = () => {
        if (window.scrollY !== lastScrollY) {
          this._isScrolling = true;
          lastScrollY = window.scrollY;
          clearTimeout(scrollTimeout);
          scrollTimeout = setTimeout(() => {
            this._isScrolling = false;
          }, 200);
        }
      };
      window.addEventListener("scroll", scrollCheck, { passive: true });

      const onResize = debounce(() => {
        if (this._capturing || this._isScrolling) return;

        if (window.visualViewport && window.visualViewport.scale !== 1) {
          return;
        }

        this._dynamicNodes.forEach((node) => {
          const meta = this._dynMeta.get(node.el);
          if (meta) {
            meta.needsRecapture = true;
            meta.prevDrawRect = null;
            meta.lastCapture = null;
          }
        });

        this._resizeCanvas();
        this._metricsDirty = true;
        this.lenses.forEach((l) => l.updateMetrics());
        this._snapshotRectPx = this.snapshotTarget.getBoundingClientRect();
        this.refreshSourceTexture("resize");
      }, 250);
      window.addEventListener("resize", onResize, { passive: true });

      if ("ResizeObserver" in window) {
        new ResizeObserver(onResize).observe(this.snapshotTarget);
      }

      /* --------------------------------------------------
       *  Dynamic DOM elements (non-video, e.g. animating text)
       * ------------------------------------------------*/
      this._dynamicNodes = [];
      this._dynMeta = new WeakMap();
      this._lastDynamicUpdate = 0;
      this._metricsDirty = true;
      this._snapshotRectPx = null;
      this._externalFrameState = null;
      this._dpr = Math.min(2, window.devicePixelRatio || 1);

      const styleEl = document.createElement("style");
      styleEl.id = "liquid-gl-dynamic-styles";
      document.head.appendChild(styleEl);
      this._dynamicStyleSheet = styleEl.sheet;

      this._resizeCanvas();
      this._pendingReveal = [];
      this.refreshSourceTexture("init");

      /* --------------------------------------------------
       *  Dynamic media (video) support
       * ------------------------------------------------*/
      this._videoNodes = Array.from(
        this.snapshotTarget.querySelectorAll("video")
      );
      this._videoNodes = this._videoNodes.filter((v) => !this._isIgnored(v));
      this._tmpCanvas = document.createElement("canvas");
      this._tmpCtx = this._tmpCanvas.getContext("2d");

      this.canvas.style.opacity = "0";

      this.useExternalTicker = false;

      /* --------------------------------------------------
       *  Inline worker for heavy dynamic nodes
       * ------------------------------------------------*/
      this._workerEnabled =
        typeof OffscreenCanvas !== "undefined" &&
        typeof Worker !== "undefined" &&
        typeof ImageBitmap !== "undefined";

      if (this._workerEnabled) {
        const workerSrc = `
          /* dynamic-element worker (runs in its own thread) */
          self.onmessage = async (e) => {
            const { id, width, height, snap, dyn } = e.data;
            const off = new OffscreenCanvas(width, height);
            const ctx = off.getContext('2d');

            ctx.drawImage(snap, 0, 0, width, height);
            ctx.drawImage(dyn, 0, 0, width, height);

            const bmp = await off.transferToImageBitmap();
            self.postMessage({ id, bmp }, [bmp]);
          };
        `;
        const blob = new Blob([workerSrc], { type: "application/javascript" });
        this._dynWorker = new Worker(URL.createObjectURL(blob), {
          type: "module",
        });

        this._dynJobs = new Map();

        this._dynWorker.onmessage = (e) => {
          const { id, bmp } = e.data;
          const meta = this._dynJobs.get(id);
          if (!meta) return;
          this._dynJobs.delete(id);

          const { x, y, w, h } = meta;
          const gl = this.gl;
          gl.bindTexture(gl.TEXTURE_2D, this.texture);
          gl.texSubImage2D(
            gl.TEXTURE_2D,
            0,
            x,
            y,
            gl.RGBA,
            gl.UNSIGNED_BYTE,
            bmp
          );
        };
      }
    }

    /* ----------------------------- */
    _initGL() {
      const isWebGL2 = typeof WebGL2RenderingContext !== "undefined" && this.gl instanceof WebGL2RenderingContext;
      const hasDerivatives = !!(this.gl && (isWebGL2 || this.gl.getExtension("OES_standard_derivatives")));
      this._hasStandardDerivatives = hasDerivatives;
      const vsSource = `
        attribute vec2 a_position;
        varying vec2 v_uv;
        void main(){
          v_uv = (a_position + 1.0) * 0.5;
          gl_Position = vec4(a_position, 0.0, 1.0);
        }`;

      const fsSource = `${hasDerivatives ? `${isWebGL2 ? "" : "#extension GL_OES_standard_derivatives : enable\n"}#define DP_HAS_DERIVATIVES 1\n` : ""}
        #ifdef GL_FRAGMENT_PRECISION_HIGH
        precision highp float;
        #else
        precision mediump float;
        #endif
        varying vec2 v_uv;
        uniform sampler2D u_tex;
        uniform sampler2D u_underGlass;
        uniform bool u_hasUnderGlass;
        uniform sampler2D u_underText;
        uniform vec4 u_underTextBounds;
        uniform bool u_hasUnderText;
        uniform sampler2D u_albumCurrentTex;
        uniform sampler2D u_albumNextTex;
        uniform vec2  u_resolution;
        uniform vec2  u_textureResolution;
        uniform vec2  u_sourceTexelsPerCssPixel;
        uniform vec2  u_lensCssSize;
        uniform float u_devicePixelRatio;
        uniform vec2  u_albumSourceSize;
        uniform vec2  u_albumCurrentSize;
        uniform vec2  u_albumNextSize;
        uniform vec4  u_bounds;
        uniform float u_albumMix;
        uniform float u_refraction;
        uniform float u_refractionFill;
        uniform float u_bevelDepth;
        uniform float u_bevelWidth;
        uniform float u_frost;
        uniform float u_frostSamples;
        uniform float u_radius;
        uniform float u_time;
        uniform bool  u_specular;
        uniform float u_revealProgress;
        uniform int   u_revealType;
        uniform float u_tiltX;
        uniform float u_tiltY;
        uniform float u_magnify;
        uniform float u_hollowInset;
        uniform bool  u_hollowMaskContent;
        uniform float u_material;
        uniform float u_materialDensity;
        uniform float u_materialSign;
        uniform vec3  u_materialTone;
        uniform float u_materialAlpha;
        uniform float u_specularPrimary;
        uniform float u_specularSecondary;
        uniform bool  u_useAlbumTransitionSource;
        uniform bool  u_debugAlbumSourceFlat;
        uniform bool  u_reactiveArtSource;
        uniform sampler2D u_reactivePreviousTex;
        uniform float u_reactiveArtMix;
        uniform float u_reactivePreviousAngle;
        uniform vec2  u_reactiveViewport;
        uniform vec2  u_reactiveParallax;
        uniform float u_reactiveAngle;
        uniform float u_reactiveLumaLow;
        uniform float u_reactiveLumaHigh;
        uniform float u_reactiveFade;
        uniform float u_reactiveBrightnessCap;
        uniform float u_reactiveEnergy;
        uniform float u_reactiveBeat;
        uniform float u_reactiveBands[9];
        uniform float u_reactiveBandCenters[9];
        uniform float u_reactiveBandWidths[9];
        uniform vec4  u_reactiveFrequencyResponse;
        uniform vec4  u_reactiveEnergyResponse;
        uniform vec4  u_reactiveBeatResponse;
        uniform vec2  u_globalLight;
        uniform float u_globalLightIntensity;

        float udRoundBox( vec2 p, vec2 b, float r ) {
          vec2 q = abs(p) - b + r;
          return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
        }

        float edgeFactor(vec2 uv, float radius_px){
          vec2 p_px = (uv - 0.5) * u_resolution;
          vec2 b_px = 0.5 * u_resolution;
          float d = -udRoundBox(p_px, b_px, radius_px);
          float bevel_px = u_bevelWidth * min(u_resolution.x, u_resolution.y);
          return 1.0 - smoothstep(0.0, bevel_px, d);
        }

        float hollowInnerShapeAtTextureUV(vec2 textureUV) {
          vec2 flippedUV = (textureUV - u_bounds.xy) / u_bounds.zw;
          vec2 localUV = vec2(flippedUV.x, 1.0 - flippedUV.y);
          vec2 p_px = (localUV - 0.5) * u_resolution;
          vec2 b_px = 0.5 * u_resolution;
          vec2 innerB = max(vec2(0.0), b_px - vec2(u_hollowInset));
          float innerRadius = max(0.0, u_radius - u_hollowInset);
          float innerD = udRoundBox(p_px, innerB, innerRadius);
          float fallbackAA = max(0.75, 1.0 / max(1.0, u_devicePixelRatio));
          #ifdef DP_HAS_DERIVATIVES
            float aa = max(fwidth(innerD), fallbackAA);
          #else
            float aa = fallbackAA;
          #endif
          return 1.0 - smoothstep(-aa, aa, innerD);
        }

        vec2 albumCoverUVFromSourceUV(vec2 sourceUV, vec2 sourceSize, vec2 imageSize) {
          vec2 safeSourceSize = max(sourceSize, vec2(1.0));
          vec2 safeImageSize = max(imageSize, vec2(1.0));
          float ca = safeSourceSize.x / safeSourceSize.y;
          float ia = safeImageSize.x / safeImageSize.y;
          vec2 outUv = sourceUV;
          if (ca > ia) {
            outUv.y = (sourceUV.y - 0.5) * ca / ia + 0.5;
          } else {
            outUv.x = (sourceUV.x - 0.5) * ia / ca + 0.5;
          }
          return clamp(vec2(outUv.x, 1.0 - outUv.y), vec2(0.0), vec2(1.0));
        }

        vec4 sampleAlbumArtSource(vec2 sourceUV) {
          vec2 curUV = albumCoverUVFromSourceUV(sourceUV, u_albumSourceSize, u_albumCurrentSize);
          vec2 nextUV = albumCoverUVFromSourceUV(sourceUV, u_albumSourceSize, u_albumNextSize);
          vec4 cur = texture2D(u_albumCurrentTex, curUV);
          vec4 next = texture2D(u_albumNextTex, nextUV);
          vec4 col = mix(cur, next, clamp(u_albumMix, 0.0, 1.0));
          if (col.a < 0.01) {
            col.a = 1.0;
          }
          return col;
        }

        // Convert the source UV into the same gently curved, bottom-left
        // projected space used by the visualizer.  Keeping this in one helper
        // is important: refracted/frosted samples must move with the visible
        // background instead of exposing a second, flat parallax plane.
        vec2 reactiveProjectedUV(vec2 uv, float angle) {
          vec2 backgroundUv = vec2(clamp(uv.x, 0.0, 1.0), 1.0 - clamp(uv.y, 0.0, 1.0));
          vec2 centered = backgroundUv - 0.5;
          float radius2 = dot(centered, centered);
          float hemisphere = sqrt(max(0.2, 1.0 - radius2 * 1.4));
          // Seven CSS pixels per axis is deliberately subtle. The hemisphere
          // term gives the centre more depth while keeping the rounded edges
          // from shearing or exposing a hard seam. Express the travel in
          // screen pixels so portrait and landscape phones behave alike.
          vec2 projected = centered * (1.0 + 0.035 * radius2);
          vec2 screen = projected * u_reactiveViewport + u_reactiveParallax * (7.0 * (0.28 + 0.72 * hemisphere));
          float c = cos(angle);
          float s = sin(angle);
          vec2 rotated = vec2(c * screen.x + s * screen.y, -s * screen.x + c * screen.y);
          return clamp(rotated / max(1.0, length(u_reactiveViewport)) + 0.5, 0.0, 1.0);
        }

        vec4 sampleBaseLiquidSource(vec2 uv) {
          if (u_reactiveArtSource) {
            // Lens bounds are CSS top-left UVs; the visualizer background is
            // rendered with bottom-left WebGL UVs. Keep both paths identical.
            vec2 artUv = reactiveProjectedUV(uv, u_reactiveAngle);
            // DOM images are uploaded without a flip in this renderer; the
            // visualizer uploads flipped images. Match its bottom-left UVs.
            vec4 color = texture2D(u_tex, vec2(artUv.x, 1.0-artUv.y));
            if (u_reactiveArtMix < 1.0) {
              float pc = cos(u_reactivePreviousAngle), ps = sin(u_reactivePreviousAngle);
              vec2 previousUv = reactiveProjectedUV(uv, u_reactivePreviousAngle);
              vec4 previous = texture2D(u_reactivePreviousTex,vec2(previousUv.x,1.0-previousUv.y));
              color = mix(previous,color,u_reactiveArtMix);
            }
            float luma = dot(color.rgb, vec3(0.2126, 0.7152, 0.0722));
            float useful = clamp((luma - u_reactiveLumaLow) / max(0.08, u_reactiveLumaHigh - u_reactiveLumaLow), 0.0, 1.0);
            float w0 = max(0.0, 1.0 - abs(useful - u_reactiveBandCenters[0]) / max(0.0001, u_reactiveBandWidths[0]));
            float w1 = max(0.0, 1.0 - abs(useful - u_reactiveBandCenters[1]) / max(0.0001, u_reactiveBandWidths[1]));
            float w2 = max(0.0, 1.0 - abs(useful - u_reactiveBandCenters[2]) / max(0.0001, u_reactiveBandWidths[2]));
            float w3 = max(0.0, 1.0 - abs(useful - u_reactiveBandCenters[3]) / max(0.0001, u_reactiveBandWidths[3]));
            float w4 = max(0.0, 1.0 - abs(useful - u_reactiveBandCenters[4]) / max(0.0001, u_reactiveBandWidths[4]));
            float w5 = max(0.0, 1.0 - abs(useful - u_reactiveBandCenters[5]) / max(0.0001, u_reactiveBandWidths[5]));
            float w6 = max(0.0, 1.0 - abs(useful - u_reactiveBandCenters[6]) / max(0.0001, u_reactiveBandWidths[6]));
            float w7 = max(0.0, 1.0 - abs(useful - u_reactiveBandCenters[7]) / max(0.0001, u_reactiveBandWidths[7]));
            float w8 = max(0.0, 1.0 - abs(useful - u_reactiveBandCenters[8]) / max(0.0001, u_reactiveBandWidths[8]));
            float total = max(0.0001, w0+w1+w2+w3+w4+w5+w6+w7+w8);
            float bandEligible = smoothstep(0.04, 0.10, luma) * (1.0 - smoothstep(0.90, 0.96, luma));
            float frequency = bandEligible * (w0*u_reactiveBands[0]+w1*u_reactiveBands[1]+w2*u_reactiveBands[2]+w3*u_reactiveBands[3]+w4*u_reactiveBands[4]+w5*u_reactiveBands[5]+w6*u_reactiveBands[6]+w7*u_reactiveBands[7]+w8*u_reactiveBands[8]) / total;
            float brightness = clamp(1.0 + frequency*u_reactiveFrequencyResponse.x + u_reactiveEnergy*u_reactiveEnergyResponse.x + u_reactiveBeat*u_reactiveBeatResponse.x, 0.0, 4.0);
            float opacity = clamp(1.0 + frequency*u_reactiveFrequencyResponse.y + u_reactiveEnergy*u_reactiveEnergyResponse.y + u_reactiveBeat*u_reactiveBeatResponse.y, 0.0, 1.0);
            float saturation = clamp(1.0 + frequency*u_reactiveFrequencyResponse.z + u_reactiveEnergy*u_reactiveEnergyResponse.z + u_reactiveBeat*u_reactiveBeatResponse.z, 0.0, 3.0);
            float contrast = clamp(1.0 + frequency*u_reactiveFrequencyResponse.w + u_reactiveEnergy*u_reactiveEnergyResponse.w + u_reactiveBeat*u_reactiveBeatResponse.w, 0.0, 3.0);
            color.rgb = mix(vec3(luma), color.rgb, saturation);
            color.rgb = min(clamp((color.rgb - 0.5) * contrast + 0.5, 0.0, 1.0) * brightness, vec3(u_reactiveBrightnessCap));
            // The visualizer canvas is cleared to opaque black.  Composite
            // the reactive layer over that black here and keep source alpha
            // opaque; propagating fade into alpha makes the glass disappear
            // after pause instead of showing its material over black.
            color.rgb *= opacity * u_reactiveFade;
            color.a = 1.0;
            return color;
          }
          if (u_useAlbumTransitionSource) {
            return sampleAlbumArtSource(uv);
          }
          return texture2D(u_tex, clamp(uv, vec2(0.0), vec2(1.0)));
        }

        vec4 sampleLiquidSource(vec2 uv) {
          vec4 base = sampleBaseLiquidSource(uv);
          if (u_hasUnderGlass) {
            vec4 under = texture2D(u_underGlass, vec2(clamp(uv.x, 0.0, 1.0), 1.0 - clamp(uv.y, 0.0, 1.0)));
            base = vec4(under.rgb + base.rgb * (1.0 - under.a), under.a + base.a * (1.0 - under.a));
          }
          if (u_hasUnderText) {
            vec2 textUV = (uv - u_underTextBounds.xy) / u_underTextBounds.zw;
            if (textUV.x >= 0.0 && textUV.y >= 0.0 && textUV.x <= 1.0 && textUV.y <= 1.0) {
              vec4 text = texture2D(u_underText, textUV);
              base = vec4(text.rgb + base.rgb * (1.0 - text.a), text.a + base.a * (1.0 - text.a));
            }
          }
          return base;
        }

        void main(){
          vec2 localUV = (v_uv - 0.5) / u_magnify + 0.5;
          vec2 flippedUV = vec2(localUV.x, 1.0 - localUV.y);
          vec2 mapped = u_bounds.xy + flippedUV * u_bounds.zw;

          if (u_debugAlbumSourceFlat) {
            vec4 albumCol = sampleAlbumArtSource(mapped);
            if (albumCol.a < 0.01) {
              albumCol = vec4(1.0, 0.0, 1.0, 1.0);
            }
            gl_FragColor = albumCol;
            return;
          }

          vec2 p = v_uv - 0.5;
          p.x *= u_resolution.x / u_resolution.y;

          float edge = edgeFactor(v_uv, u_radius);
          float min_dimension = min(u_resolution.x, u_resolution.y);
          float centreDistance = length(p);
          float fill = clamp(u_refractionFill, 0.0, 1.0);
          float refractionField = mix(edge, max(edge, 0.34), fill);
          float offsetAmt = (refractionField * u_refraction + pow(edge, 10.0) * u_bevelDepth);
          float edgeCentreBlend = smoothstep(0.15, 0.45, centreDistance);
          float centreBlend = mix(edgeCentreBlend, 1.0, fill);
          vec2 refractDirection = centreDistance > 0.0001 ? p / centreDistance : vec2(0.0);
          float lensMinorCss = min(u_lensCssSize.x, u_lensCssSize.y);
          vec2 lensMinorDimensionInSourceUV = vec2(
            (lensMinorCss / max(1.0, u_lensCssSize.x)) * u_bounds.z,
            (lensMinorCss / max(1.0, u_lensCssSize.y)) * u_bounds.w
          );
          vec2 offset = refractDirection * offsetAmt * centreBlend * lensMinorDimensionInSourceUV;

          float tiltRefractionScale = 0.05;
          vec2 tiltOffset = vec2(tan(radians(u_tiltY)), -tan(radians(u_tiltX))) *
            tiltRefractionScale * lensMinorDimensionInSourceUV;

          vec2 refracted = mapped + offset - tiltOffset;

          float oob = max(max(-refracted.x, refracted.x - 1.0), max(-refracted.y, refracted.y - 1.0));
          float blend = 1.0 - smoothstep(0.0, 0.01, oob);
          vec2 sampleUV = mix(mapped, refracted, blend);

          if (u_hollowInset > 0.0 && u_hollowMaskContent) {
            float sampledInnerShape = hollowInnerShapeAtTextureUV(sampleUV);
            if (sampledInnerShape > 0.01) {
              float innerEdgeFade = smoothstep(0.01, 0.30, sampledInnerShape);
              sampleUV = mix(sampleUV, mapped, innerEdgeFade);
            }
          }

          vec4 baseCol   = sampleLiquidSource(mapped);

          vec2 texel = 1.0 / u_textureResolution;
          vec4 refrCol;

          if (u_frost > 0.0 && u_frostSamples > 0.5) {
              float radiusCss = u_frost * 2.0;
              vec4 sum = vec4(0.0);
              const int MAX_FROST_SAMPLES = 16;
              float sampleCount = clamp(u_frostSamples, 1.0, 16.0);

              for (int i = 0; i < MAX_FROST_SAMPLES; i++) {
                float enabled = 1.0 - step(sampleCount, float(i));
                float angle = (float(i) + 0.5) * 0.78539816339;
                  float distCss = (0.35 + 0.65 * mod(float(i) * 0.61803398875, 1.0)) * radiusCss;
                  vec2 offsetUv = vec2(cos(angle), sin(angle)) *
                    distCss * u_sourceTexelsPerCssPixel * texel;
                  sum += sampleLiquidSource(sampleUV + offsetUv) * enabled;
              }
              refrCol = sum / sampleCount;
          } else {
              refrCol = sampleLiquidSource(sampleUV);
              refrCol += sampleLiquidSource(sampleUV + vec2( texel.x, 0.0));
              refrCol += sampleLiquidSource(sampleUV + vec2(-texel.x, 0.0));
              refrCol += sampleLiquidSource(sampleUV + vec2(0.0,  texel.y));
              refrCol += sampleLiquidSource(sampleUV + vec2(0.0, -texel.y));
              refrCol /= 5.0;
          }

          if (refrCol.a < 0.1) {
              refrCol = baseCol;
          }

          float diff = clamp(length(refrCol.rgb - baseCol.rgb) * 4.0, 0.0, 1.0);

          float antiHalo = (1.0 - centreBlend) * diff;

          vec4 final    = refrCol;

          vec2 p_px = (v_uv - 0.5) * u_resolution;
          vec2 b_px = 0.5 * u_resolution;
          float dmask = udRoundBox(p_px, b_px, u_radius);
          float fallbackAA = max(0.75, 1.0 / max(1.0, u_devicePixelRatio));
          #ifdef DP_HAS_DERIVATIVES
            float edgeAA = max(fwidth(dmask), fallbackAA);
          #else
            float edgeAA = fallbackAA;
          #endif
          float inShape = 1.0 - smoothstep(-edgeAA, edgeAA, dmask);
          if (u_hollowInset > 0.0) {
            vec2 innerB = max(vec2(0.0), b_px - vec2(u_hollowInset));
            float innerRadius = max(0.0, u_radius - u_hollowInset);
            float innerD = udRoundBox(p_px, innerB, innerRadius);
            #ifdef DP_HAS_DERIVATIVES
              float innerAA = max(fwidth(innerD), fallbackAA);
            #else
              float innerAA = fallbackAA;
            #endif
            float innerShape = 1.0 - smoothstep(-innerAA, innerAA, innerD);
            inShape *= (1.0 - innerShape);
          }
          if (inShape <= 0.0001) discard;

          float sourceLuma = dot(final.rgb, vec3(0.2126, 0.7152, 0.0722));
          vec3 sourceChroma = final.rgb - vec3(sourceLuma);
          float sourceTransmission = 1.0 - u_materialAlpha;
          float chromaTransmission = max(0.0, 1.0 - u_materialDensity * 0.92);
          final.rgb = vec3(sourceLuma) * sourceTransmission +
            sourceChroma * chromaTransmission +
            u_materialTone * u_materialAlpha;

          if (u_specular) {
            float normalStep = max(0.75, u_devicePixelRatio);
            float sdfXp = udRoundBox(p_px + vec2(normalStep, 0.0), b_px, u_radius);
            float sdfXm = udRoundBox(p_px - vec2(normalStep, 0.0), b_px, u_radius);
            float sdfYp = udRoundBox(p_px + vec2(0.0, normalStep), b_px, u_radius);
            float sdfYm = udRoundBox(p_px - vec2(0.0, normalStep), b_px, u_radius);
            vec2 n2 = normalize(vec2(sdfXp - sdfXm, sdfYp - sdfYm) + vec2(0.00001));
            float insideCss = max(0.0, -dmask / max(0.5, u_devicePixelRatio));
            float outerPeak = 1.0 - smoothstep(0.0, 1.15, insideCss);
            float innerRim = 1.0 - smoothstep(0.5, 5.5, insideCss);
            float rimSlope = mix(0.58, 1.35, outerPeak);
            vec3 N = normalize(vec3(n2 * rimSlope, 0.62));
            vec2 tiltNormal = vec2(sin(radians(u_tiltY)), -sin(radians(u_tiltX))) * 0.34;
            N = normalize(vec3(N.xy + tiltNormal, N.z));
            vec2 globalLight = mix(vec2(-0.48, 0.76), vec2(u_globalLight.x, -u_globalLight.y) * 1.4, u_globalLightIntensity);
            vec3 primaryLight = normalize(vec3(globalLight, 0.52));
            vec3 secondaryLight = normalize(vec3(-globalLight, 0.46));
            float primaryFacing = max(dot(N, primaryLight), 0.0);
            float secondaryFacing = max(dot(N, secondaryLight), 0.0);
            float sharp = outerPeak * pow(primaryFacing, 7.0) * u_specularPrimary;
            float soft = innerRim * pow(primaryFacing, 2.2) * u_specularPrimary * 0.62;
            float opposite = (outerPeak * 0.65 + innerRim * 0.42) *
              pow(secondaryFacing, 2.8) * u_specularSecondary;
            vec3 softRimColor = mix(vec3(1.0), refrCol.rgb, 0.08);
            final.rgb += sharp * vec3(1.0) + (soft + opposite) * softRimColor;
          }

          if (u_revealType == 1) {
              // Reveal is applied to alpha; RGB is premultiplied once below.
              final.a  *= u_revealProgress;
          }

          // The renderer is created with premultipliedAlpha:true. Without
          // this multiplication fade/AA pixels can retain dark opaque edges.
          final.rgb *= final.a;
          final.rgb *= inShape;
          final.a   *= inShape;

          gl_FragColor = final;
        }`;

      this.program = createProgram(this.gl, vsSource, fsSource);
      const gl = this.gl;
      if (!this.program) throw new Error("liquidGL: Shader failed");

      const posBuf = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, posBuf);
      gl.bufferData(
        gl.ARRAY_BUFFER,
        new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]),
        gl.STATIC_DRAW
      );

      const posLoc = gl.getAttribLocation(this.program, "a_position");
      gl.enableVertexAttribArray(posLoc);
      gl.vertexAttribPointer(posLoc, 2, gl.FLOAT, false, 0, 0);

      this.u = {
        tex: gl.getUniformLocation(this.program, "u_tex"),
        underGlass: gl.getUniformLocation(this.program, "u_underGlass"),
        hasUnderGlass: gl.getUniformLocation(this.program, "u_hasUnderGlass"),
        underText: gl.getUniformLocation(this.program, "u_underText"),
        underTextBounds: gl.getUniformLocation(this.program, "u_underTextBounds"),
        hasUnderText: gl.getUniformLocation(this.program, "u_hasUnderText"),
        albumCurrentTex: gl.getUniformLocation(this.program, "u_albumCurrentTex"),
        albumNextTex: gl.getUniformLocation(this.program, "u_albumNextTex"),
        res: gl.getUniformLocation(this.program, "u_resolution"),
        textureResolution: gl.getUniformLocation(
          this.program,
          "u_textureResolution"
        ),
        sourceTexelsPerCssPixel: gl.getUniformLocation(this.program, "u_sourceTexelsPerCssPixel"),
        lensCssSize: gl.getUniformLocation(this.program, "u_lensCssSize"),
        devicePixelRatio: gl.getUniformLocation(this.program, "u_devicePixelRatio"),
        albumSourceSize: gl.getUniformLocation(this.program, "u_albumSourceSize"),
        albumCurrentSize: gl.getUniformLocation(this.program, "u_albumCurrentSize"),
        albumNextSize: gl.getUniformLocation(this.program, "u_albumNextSize"),
        bounds: gl.getUniformLocation(this.program, "u_bounds"),
        albumMix: gl.getUniformLocation(this.program, "u_albumMix"),
        refraction: gl.getUniformLocation(this.program, "u_refraction"),
        refractionFill: gl.getUniformLocation(this.program, "u_refractionFill"),
        bevelDepth: gl.getUniformLocation(this.program, "u_bevelDepth"),
        bevelWidth: gl.getUniformLocation(this.program, "u_bevelWidth"),
        frost: gl.getUniformLocation(this.program, "u_frost"),
        frostSamples: gl.getUniformLocation(this.program, "u_frostSamples"),
        radius: gl.getUniformLocation(this.program, "u_radius"),
        time: gl.getUniformLocation(this.program, "u_time"),
        specular: gl.getUniformLocation(this.program, "u_specular"),
        revealProgress: gl.getUniformLocation(this.program, "u_revealProgress"),
        revealType: gl.getUniformLocation(this.program, "u_revealType"),
        tiltX: gl.getUniformLocation(this.program, "u_tiltX"),
        tiltY: gl.getUniformLocation(this.program, "u_tiltY"),
        magnify: gl.getUniformLocation(this.program, "u_magnify"),
        hollowInset: gl.getUniformLocation(this.program, "u_hollowInset"),
        hollowMaskContent: gl.getUniformLocation(this.program, "u_hollowMaskContent"),
        material: gl.getUniformLocation(this.program, "u_material"),
        materialDensity: gl.getUniformLocation(this.program, "u_materialDensity"),
        materialSign: gl.getUniformLocation(this.program, "u_materialSign"),
        materialTone: gl.getUniformLocation(this.program, "u_materialTone"),
        materialAlpha: gl.getUniformLocation(this.program, "u_materialAlpha"),
        specularPrimary: gl.getUniformLocation(this.program, "u_specularPrimary"),
        specularSecondary: gl.getUniformLocation(this.program, "u_specularSecondary"),
        useAlbumTransitionSource: gl.getUniformLocation(this.program, "u_useAlbumTransitionSource"),
        debugAlbumSourceFlat: gl.getUniformLocation(this.program, "u_debugAlbumSourceFlat"),
        reactiveArtSource: gl.getUniformLocation(this.program, "u_reactiveArtSource"),
        reactivePreviousTex: gl.getUniformLocation(this.program, "u_reactivePreviousTex"),
        reactiveArtMix: gl.getUniformLocation(this.program, "u_reactiveArtMix"),
        reactivePreviousAngle: gl.getUniformLocation(this.program, "u_reactivePreviousAngle"),
        reactiveViewport: gl.getUniformLocation(this.program, "u_reactiveViewport"),
        reactiveParallax: gl.getUniformLocation(this.program, "u_reactiveParallax"),
        reactiveAngle: gl.getUniformLocation(this.program, "u_reactiveAngle"),
        reactiveLumaLow: gl.getUniformLocation(this.program, "u_reactiveLumaLow"),
        reactiveLumaHigh: gl.getUniformLocation(this.program, "u_reactiveLumaHigh"),
        reactiveFade: gl.getUniformLocation(this.program, "u_reactiveFade"),
        reactiveBrightnessCap: gl.getUniformLocation(this.program, "u_reactiveBrightnessCap"),
        reactiveEnergy: gl.getUniformLocation(this.program, "u_reactiveEnergy"),
        reactiveBeat: gl.getUniformLocation(this.program, "u_reactiveBeat"),
        reactiveBands: gl.getUniformLocation(this.program, "u_reactiveBands[0]"),
        reactiveBandCenters: gl.getUniformLocation(this.program, "u_reactiveBandCenters[0]"),
        reactiveBandWidths: gl.getUniformLocation(this.program, "u_reactiveBandWidths[0]"),
        reactiveFrequencyResponse: gl.getUniformLocation(this.program, "u_reactiveFrequencyResponse"),
        reactiveEnergyResponse: gl.getUniformLocation(this.program, "u_reactiveEnergyResponse"),
        reactiveBeatResponse: gl.getUniformLocation(this.program, "u_reactiveBeatResponse"),
        globalLight: gl.getUniformLocation(this.program, "u_globalLight"),
        globalLightIntensity: gl.getUniformLocation(this.program, "u_globalLightIntensity"),
      };
      // LiquidGL writes premultiplied RGB (including SDF edge coverage).
      // Enable matching compositing so overlapping lenses accumulate their
      // coverage instead of overwriting one another with jagged transparent
      // edge pixels.
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    }

    /* ----------------------------- */
    _resizeCanvas() {
      const configuredScale = window.DebriPod && window.DebriPod.uiSettings && window.DebriPod.uiSettings.settings
        ? Number(window.DebriPod.uiSettings.settings.glassRenderScale)
        : 1;
      const renderScale = Math.max(0.5, Math.min(2, Number.isFinite(configuredScale) ? configuredScale : 1.5));
      this._dpr = renderScale;
      this.canvas.width = Math.max(1, Math.round(innerWidth * renderScale));
      this.canvas.height = Math.max(1, Math.round(innerHeight * renderScale));
      this.canvas.style.width = `${innerWidth}px`;
      this.canvas.style.height = `${innerHeight}px`;
      this.gl.viewport(0, 0, this.canvas.width, this.canvas.height);
      this._metricsDirty = true;
    }

    /* ----------------------------- */
    async captureSnapshot(reason = "") {
      if (this.sourceType !== "domSnapshot") {
        return this.refreshSourceTexture(reason || "direct source");
      }
      if (this._capturing) return false;
      this._capturing = true;
      const ignore = (element) => {
        try {
          return !!(
            !element ||
            element === this.canvas ||
            (element.hasAttribute && (element.hasAttribute("data-liquid-ignore") || element.hasAttribute("data-liquidgl-bg-shim"))) ||
            (element.closest && element.closest("[data-liquid-ignore]"))
          );
        } catch (e) {
          return false;
        }
      };
      try {
        const scale = Math.max(0.1, Math.min(3.0, this._snapshotResolution || 1));
        const snapCanvas = await snapToCanvas(this.snapshotTarget, {
          scale,
          ignore,
          engine: this._engine,
          validateCompleteness: true
        });
        if (!snapCanvas) return false;
        this._snapshotRectPx = this.snapshotTarget.getBoundingClientRect();
        this.scaleFactor = scale;
        return this._uploadTextureSource(snapCanvas, snapCanvas.width, snapCanvas.height, reason || "dom snapshot", { allowDark: true, skipBlankCheck: false, scaleFactor: scale });
      } catch (e) {
        liquidGLLog("warn", "liquidGL: DOM snapshot capture failed.", e);
        return false;
      } finally {
        this._capturing = false;
      }
    }

    _resolveSourceElement() {
      if (this._sourceElement && document.documentElement.contains(this._sourceElement)) {
        return this._sourceElement;
      }
      if (this.sourceSelector && typeof this.sourceSelector === "string") {
        this._sourceElement = document.querySelector(this.sourceSelector);
      }
      return this._sourceElement;
    }

    configureSource(options = {}) {
      const nextType = options.sourceType || this.sourceType || "visualizerWebgl";
      const nextSelector = options.sourceElement || options.source || this.sourceSelector || "#visualizerBg";
      const nextCssSelector = options.sourceCssElement || options.sourceCssSelector || this.sourceCssSelector || null;
      const nextProvider = typeof options.sourceProvider === "function" ? options.sourceProvider : this.sourceProvider;
      const providerChanged = nextProvider !== this.sourceProvider;
      this._engine = "snapdom";
      if (nextType !== this.sourceType || nextSelector !== this.sourceSelector || nextCssSelector !== this.sourceCssSelector || providerChanged) {
        this.sourceType = nextType;
        this.sourceSelector = nextSelector;
        this.sourceCssSelector = nextCssSelector;
        this.sourceProvider = nextProvider;
        this._sourceElement = null;
        this.refreshSourceTexture("source configured");
      }
    }

    _resolveSourceCssRect() {
      const el = this.sourceCssSelector ? document.querySelector(this.sourceCssSelector) : null;
      if (!el) return null;
      const rect = el.getBoundingClientRect();
      if (!rect || !(rect.width > 0) || !(rect.height > 0)) return null;
      return {
        left: rect.left || 0,
        top: rect.top || 0,
        width: rect.width || 1,
        height: rect.height || 1
      };
    }

    _fallbackCanvas(width = 8, height = 8, rgba = [5, 5, 7, 255]) {
      if (!this._solidCanvas) this._solidCanvas = document.createElement("canvas");
      if (this._solidCanvas.width !== width || this._solidCanvas.height !== height) {
        this._solidCanvas.width = width;
        this._solidCanvas.height = height;
      }
      const ctx = this._solidCanvas.getContext("2d");
      ctx.fillStyle = `rgba(${rgba[0]},${rgba[1]},${rgba[2]},${(rgba[3] == null ? 255 : rgba[3]) / 255})`;
      ctx.fillRect(0, 0, width, height);
      return this._solidCanvas;
    }

    _sourceWidth(source) {
      return source ? (source.videoWidth || source.naturalWidth || source.width || 0) : 0;
    }

    _sourceHeight(source) {
      return source ? (source.videoHeight || source.naturalHeight || source.height || 0) : 0;
    }

    debugState() {
      return {
        rendererKey: this.rendererKey,
        sourceType: this.sourceType,
        visible: this.visible,
        canvasOpacity: this.canvas ? this.canvas.style.opacity : "",
        canvasDisplay: this.canvas ? this.canvas.style.display : "",
        canvasVisibility: this.canvas ? this.canvas.style.visibility : "",
        canvasWidth: this.canvas ? this.canvas.width : 0,
        canvasHeight: this.canvas ? this.canvas.height : 0,
        lensCount: this.lenses ? this.lenses.length : 0,
        lensRects: (this.lenses || []).map((ln) => ln && ln.rectPx ? {
          left: ln.rectPx.left,
          top: ln.rectPx.top,
          width: ln.rectPx.width,
          height: ln.rectPx.height
        } : null),
        hasTexture: !!this.texture,
        textureWidth: this.textureWidth || 0,
        textureHeight: this.textureHeight || 0,
        sourceReady: !!this._sourceTextureReady,
        albumCurrentTexture: !!this._albumCurrentTexture,
        albumNextTexture: !!this._albumNextTexture,
        albumUploadedCurrentSrc: this._albumUploadedCurrentSrc || "",
        albumUploadedNextSrc: this._albumUploadedNextSrc || "",
        canaryEnabled: this._forceGlassCanary(),
        albumFlatDebugEnabled: this._debugAlbumSourceFlat(),
        useAlbumTransitionSource: this.sourceType === "albumArtTransition" && !!this._albumCurrentTexture,
        albumSourceSize: this._albumSourceSize || null,
        albumCurrentSize: this._albumCurrentSize || null,
        albumNextSize: this._albumNextSize || null,
        albumMix: this._albumMix || 0,
        albumTransitioning: this._albumTransitioning === true,
        albumFrameId: this._albumFrameId || 0,
        albumSourceKey: this._albumSourceKey || "",
        sourceCssRect: this._sourceCssRect || null,
        albumSourceRect: this._albumSourceRect || null,
        pendingRevealCount: this._pendingReveal ? this._pendingReveal.length || 0 : 0,
        renderCount: this.renderCount || 0,
        visibleLensCount: (this.lenses || []).filter((lens) => this._lensVisible(lens)).length,
        sourceRefreshCount: this.sourceRefreshCount || 0,
        frostSamples: this._configuredFrostSamples(),
        renderScale: this._dpr || 1,
        averageRenderSubmissionMs: this._renderSubmissionSamples && this._renderSubmissionSamples.length
          ? this._renderSubmissionTotalMs / this._renderSubmissionSamples.length
          : 0
      };
    }

    _rendererDebugEnabled() {
      try {
        return this.rendererKey === "removedOverlayKey" && (
          window.DEBRIPOD_UI_DEBUG === true ||
          window.DEBRIPOD_LIQUID_RENDERER_DEBUG === true ||
          (localStorage.getItem("debripod_ui_debug") || "") === "1" ||
          (localStorage.getItem("debripod_liquid_renderer_debug") || "") === "1"
        );
      } catch (e) {
        return false;
      }
    }

    _debugRenderSkip(reason, details = {}) {
      if (!this._rendererDebugEnabled()) return;
      liquidGLLog("warn", "liquidGL: renderer diagnostic", Object.assign({
        reason,
        rendererState: this.debugState ? this.debugState() : null
      }, details || {}));
    }

    _isLensIntentionallyHidden(lens) {
      try {
        let node = lens && lens.el ? lens.el : null;
        while (node && node !== document.body) {
          const style = window.getComputedStyle(node);
          if (
            Number(style.opacity || 1) <= 0.01
          ) {
            return true;
          }
          node = node.parentElement;
        }
      } catch (e) {}
      return false;
    }

    _debugLensHidden(lens) {
      if (this.rendererKey !== "removedOverlayKey" || !this._rendererDebugEnabled()) return;
      if (this._isLensIntentionallyHidden(lens)) {
        this._hiddenSkipSince = 0;
        return;
      }
      const now = performance && performance.now ? performance.now() : Date.now();
      if (!this._hiddenSkipSince) {
        this._hiddenSkipSince = now;
        return;
      }
      if (now - this._hiddenSkipSince < 250) return;
      this._hiddenSkipSince = now;
      this._debugRenderSkip("lens skipped: not visible", {
        lensClassName: lens && lens.el ? lens.el.className : ""
      });
    }

    _forceGlassCanary() {
      try {
        return this.rendererKey === "removedOverlayKey" && (
          window.DEBRIPOD_FORCE_NP_GLASS_CANARY === true ||
          (localStorage.getItem("debripod_force_glass_canary") || "") === "1"
        );
      } catch (e) {
        return false;
      }
    }

    _debugAlbumSourceFlat() {
      try {
        return this.rendererKey === "removedOverlayKey" &&
          this.sourceType === "albumArtTransition" &&
          (localStorage.getItem("debripod_debug_album_source_flat") || "") === "1";
      } catch (e) {
        return false;
      }
    }

    _ensureDebugCanaryTexture() {
      if (this._debugCanaryTexture) return this._debugCanaryTexture;
      const gl = this.gl;
      const tex = gl.createTexture();
      if (!tex) return null;
      const pixels = new Uint8Array([
        255, 64, 64, 255, 255, 220, 80, 255,
        80, 180, 255, 255, 255, 255, 255, 255
      ]);
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 2, 2, 0, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      this._debugCanaryTexture = tex;
      return tex;
    }

    _albumSourceSizeForUniform() {
      const rect = this._sourceCssRect || this._albumSourceRect || null;
      return {
        width: Math.max(1, Number(rect && rect.width || this._albumSourceSize && this._albumSourceSize.width || this.textureWidth || 1) || 1),
        height: Math.max(1, Number(rect && rect.height || this._albumSourceSize && this._albumSourceSize.height || this.textureHeight || 1) || 1)
      };
    }

    _bindAlbumTransitionUniforms() {
      const gl = this.gl;
      const useAlbumTransitionSource = this.sourceType === "albumArtTransition" && !!this._albumCurrentTexture;
      if (this.u.useAlbumTransitionSource) gl.uniform1i(this.u.useAlbumTransitionSource, useAlbumTransitionSource ? 1 : 0);
      if (this.u.debugAlbumSourceFlat) gl.uniform1i(this.u.debugAlbumSourceFlat, this._debugAlbumSourceFlat() ? 1 : 0);
      if (this.u.albumCurrentTex) {
        gl.activeTexture(gl.TEXTURE1);
        gl.bindTexture(gl.TEXTURE_2D, this._albumCurrentTexture || this.texture);
        gl.uniform1i(this.u.albumCurrentTex, 1);
      }
      if (this.u.albumNextTex) {
        gl.activeTexture(gl.TEXTURE2);
        gl.bindTexture(gl.TEXTURE_2D, this._albumNextTexture || this._albumCurrentTexture || this.texture);
        gl.uniform1i(this.u.albumNextTex, 2);
      }
      if (this.u.albumMix) gl.uniform1f(this.u.albumMix, this._albumMix || 0);
      if (this.u.albumCurrentSize) {
        gl.uniform2f(this.u.albumCurrentSize, this._albumCurrentSize.width || 1, this._albumCurrentSize.height || 1);
      }
      if (this.u.albumNextSize) {
        gl.uniform2f(this.u.albumNextSize, this._albumNextSize.width || 1, this._albumNextSize.height || 1);
      }
      if (this.u.albumSourceSize) {
        const sourceSize = this._albumSourceSizeForUniform();
        gl.uniform2f(this.u.albumSourceSize, sourceSize.width, sourceSize.height);
      }
      gl.activeTexture(gl.TEXTURE0);
    }

    _configuredFrostSamples() {
      try {
        const settings = window.DebriPod && window.DebriPod.uiSettings && window.DebriPod.uiSettings.settings || {};
        const value = Number(settings.glassFrostSamples);
        return Math.max(0, Math.min(16, Math.round(Number.isFinite(value) ? value : 8)));
      } catch (e) {
        return 8;
      }
    }

    _bindReactiveVisualizerUniforms(frameState) {
      const gl = this.gl;
      const fs = frameState || {};
      const reactive = this._reactiveArtActive === true && !!this.texture;
      const finite = (value, fallback) => Number.isFinite(Number(value)) ? Number(value) : fallback;
      const values = (input, fallback) => new Float32Array(Array.from({ length: 9 }, (_unused, index) => finite(input && input[index], fallback[index])));
      const bandFallback = [0, 0, 0, 0, 0, 0, 0, 0, 0];
      const centerFallback = [0, .125, .25, .375, .5, .625, .75, .875, 1];
      const widthFallback = [.125, .125, .125, .125, .125, .125, .125, .125, .125];
      const response = (kind) => ["brightness", "opacity", "saturation", "contrast"].map((channel) => finite(fs.responseSettings && fs.responseSettings[kind] && fs.responseSettings[kind][channel], 0));
      if (this.u.reactiveArtSource) gl.uniform1i(this.u.reactiveArtSource, reactive ? 1 : 0);
      if (!reactive) return;
      const transition = fs.artTransition || {};
      let artMix = 1;
      gl.activeTexture(gl.TEXTURE4);
      if(transition.active && transition.fromImage && transition.fromKey){
        if(this._reactivePreviousKey !== transition.fromKey){
          const uploaded = this._uploadAlbumImageTexture(transition.fromImage,this._reactivePreviousTexture);
          if(uploaded){this._reactivePreviousTexture=uploaded;this._reactivePreviousKey=transition.fromKey;}
        }
        if(this._reactivePreviousTexture && this._reactivePreviousKey === transition.fromKey) artMix = Math.max(0,Math.min(1,finite(transition.progress,0)));
      }
      gl.bindTexture(gl.TEXTURE_2D,artMix < 1 ? this._reactivePreviousTexture : this.texture);
      gl.uniform1i(this.u.reactivePreviousTex,4);
      gl.uniform1f(this.u.reactiveArtMix,artMix);
      gl.uniform1f(this.u.reactivePreviousAngle,finite(transition.fromAngle,finite(fs.angleRadians,Math.PI)));
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D,this.texture);
      gl.uniform2f(this.u.reactiveViewport, window.innerWidth || 1, window.innerHeight || 1);
      let parallaxX = 0;
      let parallaxY = 0;
      try {
        const lighting = window.DebriPod && window.DebriPod.glassLighting;
        const motion = lighting && typeof lighting.parallax === "function" ? lighting.parallax() : null;
        parallaxX = Math.max(-1, Math.min(1, finite(motion && motion.x, 0)));
        parallaxY = Math.max(-1, Math.min(1, finite(motion && motion.y, 0)));
      } catch (e) {}
      if (this.u.reactiveParallax) gl.uniform2f(this.u.reactiveParallax, parallaxX, parallaxY);
      gl.uniform1f(this.u.reactiveAngle, transition.active ? finite(transition.toAngle, Math.PI) : finite(fs.angleRadians, Math.PI));
      gl.uniform1f(this.u.reactiveLumaLow, Math.max(0, Math.min(1, finite(fs.lumaLow, 0))));
      gl.uniform1f(this.u.reactiveLumaHigh, Math.max(.04, Math.min(1, finite(fs.lumaHigh, 1))));
      gl.uniform1f(this.u.reactiveFade, Math.max(0, Math.min(1, finite(fs.fade, fs.active ? 1 : 0))));
      gl.uniform1f(this.u.reactiveBrightnessCap, Math.max(0, Math.min(1, finite(fs.brightnessCap, 1))));
      gl.uniform1f(this.u.reactiveEnergy, Math.max(0, Math.min(1, finite(fs.energy, 0))));
      gl.uniform1f(this.u.reactiveBeat, Math.max(0, Math.min(1, finite(fs.beat, 0))));
      gl.uniform1fv(this.u.reactiveBands, values(fs.bands, bandFallback));
      gl.uniform1fv(this.u.reactiveBandCenters, values(fs.bandCenters, centerFallback));
      gl.uniform1fv(this.u.reactiveBandWidths, values(fs.bandWidths, widthFallback));
      gl.uniform4fv(this.u.reactiveFrequencyResponse, new Float32Array(response("frequency")));
      gl.uniform4fv(this.u.reactiveEnergyResponse, new Float32Array(response("energy")));
      gl.uniform4fv(this.u.reactiveBeatResponse, new Float32Array(response("beat")));
    }

    _globalLightingState() {
      try {
        const lighting = window.DebriPod && window.DebriPod.glassLighting;
        const state = lighting && typeof lighting.state === "function" ? lighting.state() : null;
        if (!state) return { x: -0.16, y: -0.22, intensity: 0.22, source: "default" };
        return {
          x: Math.max(-1, Math.min(1, Number(state.x) || 0)),
          y: Math.max(-1, Math.min(1, Number(state.y) || 0)),
          intensity: Math.max(0, Math.min(1, Number(state.intensity) || 0)),
          source: String(state.source || "default")
        };
      } catch (e) {
        return { x: -0.16, y: -0.22, intensity: 0.22, source: "default" };
      }
    }

    _bindGlobalLightingUniforms(state) {
      const light = state || this._globalLightingState();
      if (this.u.globalLight) this.gl.uniform2f(this.u.globalLight, light.x, light.y);
      if (this.u.globalLightIntensity) this.gl.uniform1f(this.u.globalLightIntensity, light.intensity);
      const signature = [light.x.toFixed(3), light.y.toFixed(3), light.intensity.toFixed(3)].join(":");
      if (signature === this._globalLightSignature) return;
      this._globalLightSignature = signature;
      this.lenses.forEach((lens) => {
        try { if (lens && lens.setGlobalLighting) lens.setGlobalLighting(light); } catch (e) {}
      });
    }

    refreshSourceTexture(reason = "") {
      this.sourceRefreshCount++;
      const source = this._resolveSourceElement();
      if (this.sourceType === "albumArtTransition") {
        return this._refreshAlbumArtTransitionSource(reason || "album art transition");
      }
      if (this.sourceType === "visualizerWebgl" || this.sourceType === "webglTexture") {
        const adapter =
          window.DebriPod &&
          window.DebriPod.visualizerRenderer &&
          typeof window.DebriPod.visualizerRenderer.sourceForLiquidGL === "function"
            ? window.DebriPod.visualizerRenderer.sourceForLiquidGL()
            : null;
        if (adapter && adapter.ready && adapter.image) {
          const artKey = String(adapter.artKey || adapter.sourceRevision || adapter.image.currentSrc || adapter.image.src || "reactive-art");
          const sourceRect = adapter.sourceRect || { left: 0, top: 0, width: window.innerWidth || 1, height: window.innerHeight || 1 };
          this._reactiveArtActive = true;
          this._sourceCssRect = sourceRect;
          if (artKey === this._reactiveArtKey && this.texture && !this._sourceIsSolidFallback) return true;
          const uploaded = this.updateTextureFromImage(adapter.image, { reason: reason || "reactive artwork", sourceRect });
          if (uploaded) this._reactiveArtKey = artKey;
          return uploaded;
        }
        this._reactiveArtActive = false;
        this._reactiveArtKey = "";
        this._dpReactiveArtKey = "";
        if (adapter && adapter.ready && adapter.texture && adapter.gl === this.gl) {
          this.texture = adapter.texture;
          this.textureWidth = adapter.width || 1;
          this.textureHeight = adapter.height || 1;
          this._sourceCssRect = adapter.sourceRect || { left: 0, top: 0, width: window.innerWidth || 1, height: window.innerHeight || 1 };
          this._sourceTextureReady = true;
          this._sourceIsSolidFallback = false;
          this._sourceOwnsTexture = false;
          return true;
        }
        if (adapter && adapter.ready && adapter.canvas) {
          return this.updateTextureFromCanvas(adapter.canvas, {
            reason: reason || "visualizer webgl source",
            allowDark: true,
            sourceRect: adapter.sourceRect || { left: 0, top: 0, width: window.innerWidth || adapter.width || 1, height: window.innerHeight || adapter.height || 1 }
          });
        }
        return this.updateTextureFromSolidColor(8, 8, [0, 0, 0, 255], { reason: reason || "visualizer webgl fallback", allowDark: true });
      }
      if (this.sourceType === "albumArtCanvasOrImage") {
        if (source && source instanceof HTMLCanvasElement && source.width && source.height) {
          const rect = source.getBoundingClientRect();
          const sourceRect = this._resolveSourceCssRect ? this._resolveSourceCssRect() : null;
          return this.updateTextureFromCanvas(source, {
            reason: reason || "album art canvas",
            allowDark: !this.sourceCssSelector,
            sourceRect: sourceRect || {
              left: rect.left || 0,
              top: rect.top || 0,
              width: rect.width || source.width || 1,
              height: rect.height || source.height || 1
            }
          });
        }
        if (source && source.complete && source.naturalWidth && source.naturalHeight) {
          const sourceRect = this._resolveSourceCssRect ? this._resolveSourceCssRect() : null;
          return this.updateTextureFromImage(source, {
            reason: reason || "album art",
            sourceRect: sourceRect || undefined
          });
        }
        return false;
      }
      if (this.sourceType === "liveVideoFrame") {
        if (source && source.readyState >= 2 && source.videoWidth && source.videoHeight) {
          return this.updateTextureFromVideo(source, { reason: reason || "video frame" });
        }
        return this.updateTextureFromSolidColor(8, 8, [0, 0, 0, 255], { reason: reason || "video fallback", allowDark: true });
      }
      if (source && source.width && source.height) {
        return this.updateTextureFromCanvas(source, {
          reason: reason || this.sourceType || "canvas source",
          allowDark: true,
          sourceRect: { left: 0, top: 0, width: window.innerWidth || source.width || 1, height: window.innerHeight || source.height || 1 },
        });
      }
      return this.updateTextureFromSolidColor(8, 8, [0, 0, 0, 255], { reason: reason || "fallback", allowDark: true });
    }

    _createAlbumTexture() {
      const gl = this.gl;
      const tex = gl.createTexture();
      if (!tex) return null;
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([0, 0, 0, 0]));
      return tex;
    }

    _uploadAlbumImageTexture(image, existingTexture) {
      if (!image || !image.complete || !image.naturalWidth || !image.naturalHeight) return null;
      const gl = this.gl;
      const texture = existingTexture || this._createAlbumTexture();
      if (!texture) return null;
      try {
        gl.bindTexture(gl.TEXTURE_2D, texture);
        gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        if (isPowerOfTwoTexture(image.naturalWidth, image.naturalHeight) && gl.generateMipmap && gl.LINEAR_MIPMAP_LINEAR != null) {
          gl.generateMipmap(gl.TEXTURE_2D);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
        }
        if (this._rendererDebugEnabled()) {
          liquidGLLog("log", "liquidGL: album image uploaded", {
            rendererKey: this.rendererKey,
            complete: image.complete === true,
            naturalWidth: image.naturalWidth || 0,
            naturalHeight: image.naturalHeight || 0,
            currentSrc: image.currentSrc || image.src || ""
          });
        }
      } catch (e) {
        liquidGLLog("warn", "liquidGL: Album art transition texture upload failed.", {
          rendererKey: this.rendererKey,
          message: e && e.message ? e.message : e
        });
        return null;
      }
      return texture;
    }

    _albumImageSize(image, fallback) {
      const fromFallback = fallback || {};
      return {
        width: Math.max(1, Number(fromFallback.width || image && image.naturalWidth || image && image.width || 1) || 1),
        height: Math.max(1, Number(fromFallback.height || image && image.naturalHeight || image && image.height || 1) || 1)
      };
    }

    _refreshAlbumArtTransitionSource(reason = "") {
      this._sourceTextureReady = false;
      const provider = typeof this.sourceProvider === "function" ? this.sourceProvider : null;
      const adapter = provider ? provider() : null;
      if (!adapter || !adapter.ready || !adapter.currentImage) return false;
      const sourceRect = this._resolveSourceCssRect ? this._resolveSourceCssRect() : null;
      if (!sourceRect || !(sourceRect.width > 0) || !(sourceRect.height > 0)) {
        liquidGLLog("warn", "liquidGL: albumArtTransition source rect missing", this.debugState ? this.debugState() : {});
        return false;
      }

      const currentSrc = String(adapter.currentSrc || adapter.sourceKey || "");
      const nextSrc = String(adapter.nextSrc || "");
      if (!this._albumCurrentTexture || currentSrc !== this._albumUploadedCurrentSrc) {
        const uploaded = this._uploadAlbumImageTexture(adapter.currentImage, this._albumCurrentTexture);
        if (!uploaded) return false;
        this._albumCurrentTexture = uploaded;
        this._albumUploadedCurrentSrc = currentSrc;
      }

      if (nextSrc && adapter.nextImage) {
        if (!this._albumNextTexture || nextSrc !== this._albumUploadedNextSrc) {
          const uploaded = this._uploadAlbumImageTexture(adapter.nextImage, this._albumNextTexture);
          if (!uploaded) return false;
          this._albumNextTexture = uploaded;
          this._albumUploadedNextSrc = nextSrc;
        }
      } else {
        this._albumNextTexture = this._albumCurrentTexture;
        this._albumUploadedNextSrc = currentSrc;
      }

      this.texture = this._albumCurrentTexture;
      this._sourceOwnsTexture = false;
      this._albumCurrentSize = this._albumImageSize(adapter.currentImage, adapter.currentImageSize);
      this._albumNextSize = this._albumImageSize(adapter.nextImage || adapter.currentImage, adapter.nextImageSize || adapter.currentImageSize);
      this._albumMix = Math.max(0, Math.min(1, Number(adapter.mix || 0) || 0));
      this._albumTransitioning = adapter.transitioning === true;
      this._albumFrameId = Number(adapter.frameId || 0) || 0;
      this._albumSourceKey = String(adapter.sourceKey || currentSrc || "");
      this._albumRenderedAt = Number(adapter.renderedAt || 0) || 0;
      this._sourceCssRect = sourceRect;
      this._albumSourceRect = sourceRect;
      this._albumSourceSize = {
        width: Math.max(1, sourceRect.width || 1),
        height: Math.max(1, sourceRect.height || 1)
      };
      this.textureWidth = Math.max(1, Math.round(sourceRect.width || 1));
      this.textureHeight = Math.max(1, Math.round(sourceRect.height || 1));
      const drawable =
        !!this._albumCurrentTexture &&
        !!this.texture &&
        (this.textureWidth || 0) > 0 &&
        (this.textureHeight || 0) > 0 &&
        this._sourceCssRect &&
        (this._sourceCssRect.width || 0) > 0 &&
        (this._sourceCssRect.height || 0) > 0;
      if (!drawable) {
        liquidGLLog("warn", "liquidGL: albumArtTransition source not drawable", this.debugState ? this.debugState() : {});
        return false;
      }
      this._markSourceReadyAfterUpload(reason || "album art transition provider");
      return true;
    }

    updateTextureFromCanvas(canvas, options = {}) {
      if (!canvas || !canvas.width || !canvas.height) {
        if (this.texture) return false;
        return this.updateTextureFromSolidColor(8, 8, [0, 0, 0, 255], { reason: options.reason || "canvas fallback", allowDark: true });
      }
      if (options.sourceRect) this._sourceCssRect = options.sourceRect;
      else this._sourceCssRect = { left: 0, top: 0, width: window.innerWidth || canvas.width || 1, height: window.innerHeight || canvas.height || 1 };
      return this._uploadTextureSource(canvas, canvas.width, canvas.height, options.reason || "canvas source", { allowDark: options.allowDark === true, solidFallback: false });
    }

    updateTextureFromImage(img, options = {}) {
      if (!img || !img.complete || !img.naturalWidth || !img.naturalHeight) return false;
      if (options.sourceRect) this._sourceCssRect = options.sourceRect;
      else this._sourceCssRect = null;
      return this._uploadTextureSource(img, img.naturalWidth, img.naturalHeight, options.reason || "image source", { allowDark: true, skipBlankCheck: true, solidFallback: false });
    }

    updateTextureFromVideo(video, options = {}) {
      if (!video || video.readyState < 2 || !video.videoWidth || !video.videoHeight) return false;
      this._sourceCssRect = null;
      return this._uploadTextureSource(video, video.videoWidth, video.videoHeight, options.reason || "video source", { allowDark: options.allowDark === true, skipBlankCheck: true, solidFallback: false });
    }

    updateTextureFromSolidColor(width = 8, height = 8, rgba = [0, 0, 0, 255], options = {}) {
      const canvas = this._fallbackCanvas(width, height, rgba);
      this._sourceCssRect = null;
      return this._uploadTextureSource(canvas, canvas.width, canvas.height, options.reason || "solid fallback", { allowDark: true, skipBlankCheck: true, solidFallback: true });
    }

    clearSourceTexture(reason = "") {
      try {
        if (this.texture && this._sourceOwnsTexture !== false) {
          this.gl.deleteTexture(this.texture);
        }
      } catch (e) {}
      this.texture = null;
      this.textureWidth = 0;
      this.textureHeight = 0;
      this.staticSnapshotCanvas = null;
      this._sourceTextureReady = false;
      this._sourceIsSolidFallback = false;
      this._sourceOwnsTexture = true;
      this._sourceCssRect = null;
      this._albumFrameId = 0;
      this._albumSourceKey = "";
      this._albumMix = 0;
      this._albumTransitioning = false;
      this._albumSourceRect = null;
      this._albumSourceSize = { width: 1, height: 1 };
      this.clear();
      liquidGLLog("log", "liquidGL: Source texture cleared.", {
        rendererKey: this.rendererKey,
        reason
      });
    }

    _uploadTexture(srcCanvas, reason = "") {
      return this._uploadTextureSource(srcCanvas, this._sourceWidth(srcCanvas), this._sourceHeight(srcCanvas), reason, {});
    }

    _markSourceReadyAfterUpload(reason = "", options = {}) {
      this._sourceTextureReady = true;
      this._sourceIsSolidFallback = options.solidFallback === true;

      if (this.canvas) {
        this.canvas.style.opacity = "1";
        this.canvas.style.visibility = "";
        this.canvas.style.display = "";
      }

      if (this._pendingReveal && this._pendingReveal.length) {
        this._pendingReveal.forEach((ln) => {
          try {
            if (ln && ln._reveal) ln._reveal();
          } catch (e) {}
        });
        this._pendingReveal.length = 0;
      }

      if (this.lenses && this.lenses.length) {
        this.lenses.forEach((ln) => {
          try {
            if (ln && ln.el && !ln._initCalled && ln._TriggerInit) ln._TriggerInit();
          } catch (e) {}
        });
      }

      this._metricsDirty = true;
    }

    _uploadTextureSource(source, width, height, reason = "", options = {}) {
      if (!source || !(width > 0) || !(height > 0)) return false;
      const gl = this.gl;
      const maxTex = gl.getParameter(gl.MAX_TEXTURE_SIZE) || 8192;
      if (width > maxTex || height > maxTex) {
        const scale = Math.min(maxTex / width, maxTex / height);
        const canvas = document.createElement("canvas");
        canvas.width = Math.max(1, Math.floor(width * scale));
        canvas.height = Math.max(1, Math.floor(height * scale));
        const ctx = canvas.getContext("2d");
        if (!ctx) return false;
        try {
          ctx.drawImage(source, 0, 0, canvas.width, canvas.height);
        } catch (e) {
          liquidGLLog("warn", "liquidGL: oversized texture clamp draw failed.", e);
          return false;
        }
        source = canvas;
        width = canvas.width;
        height = canvas.height;
        options.scaleFactor = (Number(options.scaleFactor) || 1) * scale;
      }
      if (!options.skipBlankCheck && !options.allowDark && source instanceof HTMLCanvasElement && this._canvasLooksBlankForUpload(source)) {
        liquidGLLog("warn", "liquidGL: Refusing to replace texture with a blank source.", {
          rendererKey: this.rendererKey,
          reason
        });
        return false;
      }
      if (!this.texture || this._sourceOwnsTexture === false) {
        this.texture = gl.createTexture();
        if (!this.texture) return false;
        this._sourceOwnsTexture = true;
      }
      const textureSizeChanged = this.textureWidth !== width || this.textureHeight !== height;
      try {
        gl.bindTexture(gl.TEXTURE_2D, this.texture);
        gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
        gl.texImage2D(
          gl.TEXTURE_2D,
          0,
          gl.RGBA,
          gl.RGBA,
          gl.UNSIGNED_BYTE,
          source
        );
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        if (isPowerOfTwoTexture(width, height) && gl.generateMipmap && gl.LINEAR_MIPMAP_LINEAR != null) {
          gl.generateMipmap(gl.TEXTURE_2D);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
        }
      } catch (e) {
        liquidGLLog("error", "liquidGL: Texture upload failed; keeping previous texture.", e);
        if (this.texture) gl.bindTexture(gl.TEXTURE_2D, this.texture);
        return false;
      }

      this.staticSnapshotCanvas = source instanceof HTMLCanvasElement ? source : null;
      this.textureWidth = width;
      this.textureHeight = height;
      this.scaleFactor = Number(options.scaleFactor) || 1;
      this._markSourceReadyAfterUpload(reason, { solidFallback: options.solidFallback === true });
      if (textureSizeChanged && this._dynMeta && this._dynamicNodes) {
        this._dynamicNodes.forEach((node) => {
          const meta = this._dynMeta.get(node.el);
          if (meta) meta.prevDrawRect = null;
        });
      }
      liquidGLLog("log", "liquidGL: Texture uploaded.", {
        rendererKey: this.rendererKey,
        reason,
        width: this.textureWidth,
        height: this.textureHeight,
        lensCount: this.lenses.length,
        lensClasses: this.lenses.map((lens) => lens.el && lens.el.className).filter(Boolean),
        canvasClassName: this.canvas.className,
        canvasZIndex: window.getComputedStyle(this.canvas).zIndex
      });

      return true;
    }

    /* ----------------------------- */
    _canvasLooksBlankForUpload(canvas) {
      let ctx;
      try {
        ctx = canvas.getContext("2d", { willReadFrequently: true });
      } catch (e) {
        return false;
      }
      if (!ctx) return false;

      const w = canvas.width || 0;
      const h = canvas.height || 0;
      if (w <= 0 || h <= 0) return true;

      let allTransparent = true;
      let allNearBlack = true;
      const samples = 12;
      try {
        for (let y = 0; y < samples; y++) {
          for (let x = 0; x < samples; x++) {
            const px = Math.min(w - 1, Math.max(0, Math.round(((x + 0.5) / samples) * w)));
            const py = Math.min(h - 1, Math.max(0, Math.round(((y + 0.5) / samples) * h)));
            const data = ctx.getImageData(px, py, 1, 1).data;
            const a = data[3];
            if (a > 0) allTransparent = false;
            if (!(a > 250 && data[0] <= 2 && data[1] <= 2 && data[2] <= 2)) {
              allNearBlack = false;
            }
            if (!allTransparent && !allNearBlack) return false;
          }
        }
      } catch (e) {
        return false;
      }
      return allTransparent || allNearBlack;
    }

    /* ----------------------------- */
    addLens(element, options) {
      const lens = new liquidGLLens(this, element, options);
      this.lenses.push(lens);

      const maxZ = this._getMaxLensZ();
      if (maxZ > 0) {
        this.canvas.style.zIndex = maxZ - 1;
      }

      if (!this.texture) {
        this._pendingReveal.push(lens);
      } else {
        lens._reveal();
      }
      return lens;
    }

    syncLenses(elements, options) {
      const wanted = new Set(Array.from(elements || []).filter(Boolean));
      this.lenses = this.lenses.filter((lens) => {
        const keep = lens && lens.el && wanted.has(lens.el) && lens.el.isConnected;
        if (!keep && lens && lens.destroy) lens.destroy();
        return keep;
      });
      wanted.forEach((el) => {
        const existing = this.lenses.find((lens) => lens.el === el);
        if (existing && options) {
          existing.setOptions(options);
        }
        if (!existing) {
          this.addLens(el, options);
        }
      });
      this._metricsDirty = true;
      return this.lenses.filter((lens) => wanted.has(lens.el));
    }

    syncLensGroup(group, elements, options) {
      const groupKey = String(group || "default");
      const wanted = new Set(Array.from(elements || []).filter(Boolean));
      this.lenses = this.lenses.filter((lens) => {
        if (!lens || !lens.el) return false;
        if (lens._dpLensGroup !== groupKey) {
          if (!lens.el.isConnected && lens.destroy) lens.destroy();
          return lens.el.isConnected;
        }
        const keep = wanted.has(lens.el) && lens.el.isConnected;
        if (!keep && lens.destroy) lens.destroy();
        return keep;
      });
      wanted.forEach((el) => {
        let existing = this.lenses.find((lens) => lens.el === el);
        if (existing && options) existing.setOptions(options);
        if (!existing) {
          existing = this.addLens(el, options);
          existing._dpLensGroup = groupKey;
        }
        existing._dpLensGroup = groupKey;
      });
      this._metricsDirty = true;
      return this.lenses.filter((lens) => lens._dpLensGroup === groupKey && wanted.has(lens.el));
    }

    requestRender() {
      if (document.hidden) return;
      const scheduler = window.DebriPod && window.DebriPod.frameScheduler;
      if (this.useExternalTicker && scheduler && scheduler.mark) {
        scheduler.mark({ render: true });
        return;
      }
      if (this._rafId || this._optionRafId) return;
      this._optionRafId = requestAnimationFrame((timestamp) => {
        this._optionRafId = 0;
        this.render({ timestamp });
      });
    }

    /* ----------------------------- */
    clear() {
      try {
        const gl = this.gl;
        gl.bindFramebuffer(gl.FRAMEBUFFER, null);
        if (this.canvas.width && this.canvas.height) {
          gl.viewport(0, 0, this.canvas.width, this.canvas.height);
        }
        gl.clearColor(0, 0, 0, 0);
        gl.clear(gl.COLOR_BUFFER_BIT);
        if (this.canvas) this.canvas.style.opacity = "0";
      } catch (e) {}
    }

    setVisible(on) {
      const next = !!on;
      if(!next && this.rendererKey === "main" && window.DebriPod && window.DebriPod.rowRefraction) window.DebriPod.rowRefraction.clear();
      if (this.visible === next) {
        if (!next) {
          this.clear();
        } else if (this.canvas) {
          this.canvas.style.opacity = "1";
          this.canvas.style.visibility = "";
          this.canvas.style.display = "";
        }
        return;
      }
      this.visible = next;
      if (!next) {
        this.lenses.forEach((lens) => {
          lens.rectPx = null;
        });
        this.clear();
        return;
      }
      if (this.canvas) {
        this.canvas.style.opacity = "1";
        this.canvas.style.visibility = "";
        this.canvas.style.display = "";
      }
      this._metricsDirty = true;
    }

    /* ----------------------------- */
    render(frameState) {
      const renderStartedAt = typeof performance !== "undefined" && performance.now ? performance.now() : Date.now();
      const gl = this.gl;
      if (!this.visible || document.hidden) {
        if (!this.visible) this._debugRenderSkip("render skipped: renderer not visible");
        this.clear();
        return;
      }
      if (!this.texture) this.refreshSourceTexture("render fallback");
      if (!this.texture && this._forceGlassCanary()) {
        const canary = this._ensureDebugCanaryTexture();
        if (canary) {
          this.texture = canary;
          this.textureWidth = 2;
          this.textureHeight = 2;
          this._sourceTextureReady = true;
        }
      }
      if (!this.texture) {
        this._debugRenderSkip("render skipped: missing texture");
        this.clear();
        return;
      }
      if (this.sourceType === "albumArtTransition" && !this._albumCurrentTexture && !this._forceGlassCanary()) {
        this._debugRenderSkip("render skipped: albumArtTransition missing current texture");
        this.clear();
        return;
      }
      if (frameState) this._externalFrameState = frameState;
      const fs = this._externalFrameState || {};
      this._adaptiveQuality = Math.max(0.45, Math.min(1, Number(fs.qualityBias || 1)));
      if (this._isScrolling) this._adaptiveQuality = Math.min(this._adaptiveQuality, 0.7);

      if (this._isScrolling) {
        this._scrollUpdateCounter++;
      }
      this.renderCount++;

      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.useProgram(this.program);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, this.texture);
      gl.uniform1i(this.u.tex, 0);
      this._bindAlbumTransitionUniforms();
      this._bindReactiveVisualizerUniforms(fs);
      this._bindGlobalLightingUniforms(this._globalLightingState());

      const time = Number.isFinite(fs.timestamp) ? fs.timestamp / 1000 : (Date.now() - this.startTime) / 1000;
      gl.uniform1f(this.u.time, time);

      if (this._metricsDirty || !this._snapshotRectPx) {
        this._snapshotRectPx = this.snapshotTarget.getBoundingClientRect();
        this.lenses.forEach((lens) => {
          lens.updateMetrics();
        });
        this._metricsDirty = false;
      } else if (this.lenses.some((lens) => lens && lens._syncDomRect)) {
        // CSS transitions can move a pill without ResizeObserver firing.
        // Refresh only explicitly live targets on each render frame.
        this.lenses.forEach((lens) => {
          if (lens && lens._syncDomRect) lens.updateMetrics();
        });
      }

      let hasActiveVisibleTransition = false;
      const transitionTime = Number.isFinite(fs.timestamp) ? fs.timestamp : performance.now();
      // One copy per optical depth, not per row. Each upper lens samples the
      // completed lower glass pass at its refracted UV coordinates.
      const depth = lens => {
        const el = lens.el;
        if (el.id === "libListSelectedGlass") return 2;
        if (el.matches && el.matches("[data-liquid-row-pill]") && el.closest(".ipodItem.sel")) return 3;
        if (el.matches && el.matches("[data-liquid-row-pill], .wheelCenterGlass, .pathPillGlass, .infoPillGlass")) return 1;
        return 0;
      };
      const textLayer = this.rendererKey === "main" && window.DebriPod && window.DebriPod.rowRefraction;
      if(textLayer) textLayer.beginFrame();
      let currentDepth = 0;
      gl.uniform1i(this.u.hasUnderGlass, 0);
      this.lenses.slice().sort((a,b) => depth(a) - depth(b)).forEach((lens) => {
        if (this._lensVisible(lens)) {
          const nextDepth = depth(lens);
          if (nextDepth !== currentDepth) {
            this._captureUnderGlass();
            currentDepth = nextDepth;
          }
          this._hiddenSkipSince = 0;
          if (lens._advanceTransition && lens._advanceTransition(transitionTime)) {
            hasActiveVisibleTransition = true;
          }
          this._renderLens(lens);
        } else {
          this._debugLensHidden(lens);
        }
      });

      if(textLayer) textLayer.endFrame();
      if (hasActiveVisibleTransition) this.requestRender();
      const renderFinishedAt = typeof performance !== "undefined" && performance.now ? performance.now() : Date.now();
      const submissionMs = Math.max(0, renderFinishedAt - renderStartedAt);
      this._renderSubmissionSamples.push(submissionMs);
      this._renderSubmissionTotalMs += submissionMs;
      if (this._renderSubmissionSamples.length > 120) {
        this._renderSubmissionTotalMs -= this._renderSubmissionSamples.shift();
      }
    }

    _bindUnderText(source) {
      const gl = this.gl;
      gl.activeTexture(gl.TEXTURE5);
      if(!this._underTextTexture) this._underTextTexture = this._createAlbumTexture();
      gl.bindTexture(gl.TEXTURE_2D,this._underTextTexture);
      if(this._underTextRevision !== source.revision){
        gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,false);
        gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL,true);
        gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,source.canvas);
        gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL,false);
        this._underTextRevision = source.revision;
      }
      gl.uniform1i(this.u.underText,5);
      const r=source.bounds, w=window.innerWidth || 1, h=window.innerHeight || 1;
      gl.uniform4f(this.u.underTextBounds,r.left/w,r.top/h,r.width/w,r.height/h);
      gl.uniform1i(this.u.hasUnderText,1);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D,this.texture);
    }

    _captureUnderGlass() {
      const gl = this.gl;
      gl.activeTexture(gl.TEXTURE3);
      if (!this._underGlassTexture) {
        this._underGlassTexture = gl.createTexture();
        gl.bindTexture(gl.TEXTURE_2D, this._underGlassTexture);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      } else gl.bindTexture(gl.TEXTURE_2D, this._underGlassTexture);
      if (this._underGlassWidth !== this.canvas.width || this._underGlassHeight !== this.canvas.height) {
        gl.copyTexImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 0, 0, this.canvas.width, this.canvas.height, 0);
        this._underGlassWidth = this.canvas.width;
        this._underGlassHeight = this.canvas.height;
      } else gl.copyTexSubImage2D(gl.TEXTURE_2D, 0, 0, 0, 0, 0, this.canvas.width, this.canvas.height);
      gl.uniform1i(this.u.underGlass, 3);
      gl.uniform1i(this.u.hasUnderGlass, 1);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, this.texture);
    }

    _lensVisible(lens) {
      try {
        if (!lens || !lens.el || !lens.el.isConnected) return false;
        const style = window.getComputedStyle(lens.el);
        if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity || 1) <= 0.01) return false;
        let node = lens.el.parentElement;
        while (node && node !== document.body) {
          const parentStyle = window.getComputedStyle(node);
          if (
            parentStyle.display === "none" ||
            parentStyle.visibility === "hidden" ||
            Number(parentStyle.opacity || 1) <= 0.01
          ) {
            return false;
          }
          node = node.parentElement;
        }
        const rect = lens.rectPx || lens.el.getBoundingClientRect();
        if (!rect || !(rect.width > 0) || !(rect.height > 0)) return false;
        if (rect.right < -2 || rect.bottom < -2 || rect.left > (window.innerWidth || 0) + 2 || rect.top > (window.innerHeight || 0) + 2) return false;
        return true;
      } catch (e) {
        return true;
      }
    }

    /* ----------------------------- */
    _renderLens(lens) {
      const gl = this.gl;
      const rect = lens.rectPx;
      gl.uniform1i(this.u.hasUnderText, 0);
      const textLayer = this.rendererKey === "main" && window.DebriPod && window.DebriPod.rowRefraction;
      if(rect && lens.el.id === "libListSelectedGlass" && textLayer){
        const textSource = textLayer.prepare(rect,lens.radiusCss);
        if(textSource) this._bindUnderText(textSource);
      }
      const forceCanary = this._forceGlassCanary();
      if (forceCanary && !this.texture) {
        const canary = this._ensureDebugCanaryTexture();
        if (canary) {
          this.texture = canary;
          this.textureWidth = 2;
          this.textureHeight = 2;
        }
      }
      if (!rect) {
        this._debugRenderSkip("_renderLens skipped: missing rect");
        return;
      }
      if ((!this.texture || !this.textureWidth || !this.textureHeight) && !forceCanary) {
        this._debugRenderSkip("_renderLens skipped: missing texture dimensions");
        return;
      }
      if (!(rect.width > 0) || !(rect.height > 0)) {
        this._debugRenderSkip("_renderLens skipped: zero lens rect", { rect });
        return;
      }
      if (this.sourceType === "albumArtTransition" && !forceCanary) {
        if (!this._albumCurrentTexture) {
          this._debugRenderSkip("_renderLens skipped: albumArtTransition missing current texture");
          return;
        }
        if (!this._sourceCssRect || !(this._sourceCssRect.width > 0) || !(this._sourceCssRect.height > 0)) {
          this._debugRenderSkip("_renderLens skipped: albumArtTransition missing source rect");
          return;
        }
      }

      const dpr = this._dpr || Math.min(2, window.devicePixelRatio || 1);

      let overscrollY = 0;
      let overscrollX = 0;

      if (window.visualViewport) {
        overscrollX = window.visualViewport.offsetLeft;
        overscrollY = window.visualViewport.offsetTop;
      }

      // WebGL viewport coordinates are integer raster bounds.  Passing CSS
      // transition fractions through implicit float-to-int conversion makes
      // adjacent lens edges choose different pixels from frame to frame.
      const x = Math.round((rect.left + overscrollX) * dpr);
      const y = Math.round(
        this.canvas.height - (rect.top + overscrollY + rect.height) * dpr
      );
      const w = Math.max(1, Math.round(rect.width * dpr));
      const h = Math.max(1, Math.round(rect.height * dpr));

      gl.viewport(x, y, w, h);
      gl.uniform2f(this.u.res, w, h);

      let leftUV = 0;
      let topUV = 0;
      let wUV = 1;
      let hUV = 1;
      if (this._sourceCssRect || forceCanary || (this.sourceType !== "albumArtCanvasOrImage" && this.sourceType !== "liveVideoFrame")) {
        const srcRect = this._sourceCssRect || (forceCanary ? rect : { left: 0, top: 0, width: window.innerWidth || 1, height: window.innerHeight || 1 });
        leftUV = (rect.left - srcRect.left) / Math.max(1, srcRect.width);
        topUV = (rect.top - srcRect.top) / Math.max(1, srcRect.height);
        wUV = rect.width / Math.max(1, srcRect.width);
        hUV = rect.height / Math.max(1, srcRect.height);
      }
      if (
        !Number.isFinite(leftUV) ||
        !Number.isFinite(topUV) ||
        !Number.isFinite(wUV) ||
        !Number.isFinite(hUV) ||
        wUV <= 0 ||
        hUV <= 0 ||
        leftUV + wUV <= -0.02 ||
        topUV + hUV <= -0.02 ||
        leftUV >= 1.02 ||
        topUV >= 1.02
      ) {
        this._debugRenderSkip("_renderLens skipped: invalid bounds", {
          leftUV,
          topUV,
          wUV,
          hUV,
          rect,
          sourceCssRect: this._sourceCssRect || null
        });
        return;
      }
      gl.uniform4f(this.u.bounds, leftUV, topUV, wUV, hUV);

      gl.uniform2f(
        this.u.textureResolution,
        this.textureWidth,
        this.textureHeight
      );
      const sourceCssRect = this._sourceCssRect || {
        width: window.innerWidth || rect.width || 1,
        height: window.innerHeight || rect.height || 1,
      };
      const texelsPerCss = sourceTexelsPerCssPixel(
        this.textureWidth,
        this.textureHeight,
        sourceCssRect.width,
        sourceCssRect.height
      );
      gl.uniform2f(this.u.sourceTexelsPerCssPixel, texelsPerCss[0], texelsPerCss[1]);
      gl.uniform2f(this.u.lensCssSize, rect.width, rect.height);
      gl.uniform1f(this.u.devicePixelRatio, dpr);
      if (this.u.albumSourceSize) {
        const albumSourceSize = this._albumSourceSizeForUniform();
        gl.uniform2f(this.u.albumSourceSize, albumSourceSize.width, albumSourceSize.height);
      }
      const resolved = lens.resolveOptics(this._adaptiveQuality || 1);
      gl.uniform1f(this.u.refraction, resolved.refraction);
      gl.uniform1f(this.u.refractionFill, resolved.refractionFill);
      gl.uniform1f(this.u.bevelDepth, resolved.bevelDepth);
      gl.uniform1f(this.u.bevelWidth, resolved.bevelWidth);
      gl.uniform1f(this.u.frost, Math.max(0, resolved.frostSigmaPx));
      gl.uniform1f(this.u.frostSamples, this._configuredFrostSamples());
      gl.uniform1f(this.u.radius, lens.radiusGl);
      gl.uniform1i(this.u.specular, resolved.specular ? 1 : 0);
      gl.uniform1f(this.u.revealProgress, lens._revealProgress == null ? 1.0 : lens._revealProgress);
      gl.uniform1i(this.u.revealType, lens.revealTypeIndex || 0);

      const mag = Math.max(
        0.001,
        Math.min(
          3.0,
          resolved.magnify !== undefined ? resolved.magnify : 1.0
        )
      );
      gl.uniform1f(this.u.magnify, mag);

      gl.uniform1f(this.u.tiltX, lens.tiltX || 0);
      gl.uniform1f(this.u.tiltY, lens.tiltY || 0);
      gl.uniform1f(this.u.hollowInset, lens.hollowInsetGl || 0);
      gl.uniform1i(this.u.hollowMaskContent, lens.hollowMaskContent ? 1 : 0);
      gl.uniform1f(this.u.material, resolved.material);
      gl.uniform1f(this.u.materialDensity, resolved.density);
      gl.uniform1f(this.u.materialSign, resolved.side);
      gl.uniform3f(this.u.materialTone, resolved.tone[0], resolved.tone[1], resolved.tone[2]);
      gl.uniform1f(this.u.materialAlpha, resolved.materialAlpha);
      gl.uniform1f(this.u.specularPrimary, resolved.specularPrimary);
      gl.uniform1f(this.u.specularSecondary, resolved.specularSecondary);

      if (forceCanary) {
        const canary = this._ensureDebugCanaryTexture();
        if (canary) {
          gl.activeTexture(gl.TEXTURE0);
          gl.bindTexture(gl.TEXTURE_2D, canary);
          gl.uniform1i(this.u.tex, 0);
          gl.uniform2f(this.u.textureResolution, 2, 2);
          if (this.u.useAlbumTransitionSource) gl.uniform1i(this.u.useAlbumTransitionSource, 0);
          if (this.u.debugAlbumSourceFlat) gl.uniform1i(this.u.debugAlbumSourceFlat, 0);
        }
      }

      const clip = lens.clipRectPx;
      if (clip) {
        gl.enable(gl.SCISSOR_TEST);
        // Round the scissor outwards. Rounding a lens' own visible bounds
        // inward removes the outer SDF coverage on fractional positions and
        // turns smooth rounded corners into flat one pixel cuts.
        const left = Math.max(0, Math.floor(clip.left * dpr));
        const right = Math.min(this.canvas.width, Math.ceil(clip.right * dpr));
        const bottom = Math.max(0, Math.floor(this.canvas.height - clip.bottom * dpr));
        const top = Math.min(this.canvas.height, Math.ceil(this.canvas.height - clip.top * dpr));
        gl.scissor(left, bottom, Math.max(0, right - left), Math.max(0, top - bottom));
      }
      gl.drawArrays(gl.TRIANGLES, 0, 6);
      gl.disable(gl.SCISSOR_TEST);
    }

    /* ----------------------------- */
    _createRoundedRectPath(ctx, w, h, radii) {
      ctx.beginPath();
      ctx.moveTo(radii.tl, 0);
      ctx.lineTo(w - radii.tr, 0);
      ctx.arcTo(w, 0, w, radii.tr, radii.tr);
      ctx.lineTo(w, h - radii.br);
      ctx.arcTo(w, h, w - radii.br, h, radii.br);
      ctx.lineTo(radii.bl, h);
      ctx.arcTo(0, h, 0, h - radii.bl, radii.bl);
      ctx.lineTo(0, radii.tl);
      ctx.arcTo(0, 0, radii.tl, 0, radii.tl);
      ctx.closePath();
    }

    /* ----------------------------- */
    _updateDynamicVideos() {
      if (this._isScrolling && this._scrollUpdateCounter % 2 !== 0) return;
      if (
        !this.texture ||
        !this.staticSnapshotCanvas ||
        !this._videoNodes.length
      )
        return;
      const gl = this.gl;

      const snapRect = this._snapshotRectPx || this.snapshotTarget.getBoundingClientRect();

      const maxLensZ = this._getMaxLensZ();

      this._videoNodes.forEach((vid) => {
        if (effectiveZ(vid) >= maxLensZ) {
          return;
        }

        if (this._isIgnored(vid) || vid.readyState < 2) return;

        const rect = vid.getBoundingClientRect();
        const texX = (rect.left - snapRect.left) * this.scaleFactor;
        const texY = (rect.top - snapRect.top) * this.scaleFactor;
        const texW = rect.width * this.scaleFactor;
        const texH = rect.height * this.scaleFactor;

        const drawW = Math.round(texW);
        const drawH = Math.round(texH);

        if (drawW <= 0 || drawH <= 0) return;

        if (
          this._tmpCanvas.width !== drawW ||
          this._tmpCanvas.height !== drawH
        ) {
          this._tmpCanvas.width = drawW;
          this._tmpCanvas.height = drawH;
        }

        try {
          this._tmpCtx.save();
          this._tmpCtx.clearRect(0, 0, drawW, drawH);

          const style = window.getComputedStyle(vid);
          const scaledRadii = {
            tl: parseFloat(style.borderTopLeftRadius) * this.scaleFactor,
            tr: parseFloat(style.borderTopRightRadius) * this.scaleFactor,
            br: parseFloat(style.borderBottomRightRadius) * this.scaleFactor,
            bl: parseFloat(style.borderBottomLeftRadius) * this.scaleFactor,
          };

          if (Object.values(scaledRadii).some((r) => r > 0)) {
            this._createRoundedRectPath(
              this._tmpCtx,
              drawW,
              drawH,
              scaledRadii
            );
            this._tmpCtx.clip();
          }

          this._tmpCtx.drawImage(
            this.staticSnapshotCanvas,
            texX,
            texY,
            texW,
            texH,
            0,
            0,
            drawW,
            drawH
          );

          this._tmpCtx.drawImage(vid, 0, 0, drawW, drawH);
          this._tmpCtx.restore();
        } catch (e) {
          liquidGLLog("warn", "liquidGL: Error drawing video frame", e);
          return;
        }

        const drawX = Math.round(texX);
        const drawY = Math.round(texY);

        if (drawW <= 0 || drawH <= 0) return;

        const maxW = this.textureWidth;
        const maxH = this.textureHeight;
        let dstX = drawX;
        let dstY = drawY;
        let srcX = 0,
          srcY = 0,
          updW = drawW,
          updH = drawH;

        if (dstX < 0) {
          srcX = -dstX;
          updW += dstX;
          dstX = 0;
        }
        if (dstY < 0) {
          srcY = -dstY;
          updH += dstY;
          dstY = 0;
        }

        if (dstX + updW > maxW) {
          updW = maxW - dstX;
        }
        if (dstY + updH > maxH) {
          updH = maxH - dstY;
        }

        if (updW <= 0 || updH <= 0) return;

        gl.bindTexture(gl.TEXTURE_2D, this.texture);
        gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
        gl.texSubImage2D(
          gl.TEXTURE_2D,
          0,
          dstX,
          dstY,
          gl.RGBA,
          gl.UNSIGNED_BYTE,
          this._tmpCanvas
        );
      });
    }

    /* ----------------------------- */
    _updateDynamicNodes() {
      if (this._isScrolling && this._scrollUpdateCounter % 2 !== 0) return;
      const gl = this.gl;
      if (!this.texture || !this._dynMeta || !this._dynamicNodes.length) return;
      const snapRect = this._snapshotRectPx || this.snapshotTarget.getBoundingClientRect();
      const maxLensZ = this._getMaxLensZ();

      const lensRects = this.lenses.map((ln) => ln.rectPx).filter(Boolean);

      const rectsIntersect = (a, b) =>
        a.left < b.left + b.width &&
        a.left + a.width > b.left &&
        a.top < b.top + b.height &&
        a.top + a.height > b.top;

      const rectWithin = (a, b) =>
        a.left >= b.left &&
        a.top >= b.top &&
        a.left + a.width <= b.left + b.width &&
        a.top + a.height <= b.top + b.height;

      const lensVisibleForRect = (lens, rect) => {
        if (!lens || !lens.rectPx || !rectsIntersect(rect, lens.rectPx)) return false;
        const inset = Number(lens.hollowInsetCss || 0);
        if (inset > 0) {
          const lr = lens.rectPx;
          const inner = {
            left: lr.left + inset,
            top: lr.top + inset,
            width: Math.max(0, lr.width - inset * 2),
            height: Math.max(0, lr.height - inset * 2),
          };
          if (rectWithin(rect, inner)) return false;
        }
        return true;
      };

      if (!this._compositeCtx) {
        this._compositeCtx = document.createElement("canvas").getContext("2d");
      }

      const compositeVideos = (compositeCtx, dynamicElRect) => {
        this._videoNodes.forEach((vid) => {
          if (effectiveZ(vid) > maxLensZ) return;
          const vidRect = vid.getBoundingClientRect();

          if (
            dynamicElRect.left < vidRect.right &&
            dynamicElRect.right > vidRect.left &&
            dynamicElRect.top < vidRect.bottom &&
            dynamicElRect.bottom > vidRect.top
          ) {
            const xInComposite =
              (vidRect.left - dynamicElRect.left) * this.scaleFactor;
            const yInComposite =
              (vidRect.top - dynamicElRect.top) * this.scaleFactor;
            const wInComposite = vidRect.width * this.scaleFactor;
            const hInComposite = vidRect.height * this.scaleFactor;
            compositeCtx.drawImage(
              vid,
              xInComposite,
              yInComposite,
              wInComposite,
              hInComposite
            );
          }
        });
      };

      this._dynamicNodes.forEach((node) => {
        const el = node.el;
        const meta = this._dynMeta.get(el);
        if (!meta) return;

        if (meta.needsRecapture && !meta._capturing && !this._isScrolling) {
          const imageCapture = this._captureImageElement(el);
          if (imageCapture) {
            meta.lastCapture = imageCapture;
            meta.needsRecapture = false;
            requestAnimationFrame(() => this.render());
          } else if (el && el.tagName === "IMG") {
            liquidGLLog(
              "warn",
              "liquidGL: Image dynamic capture failed; relying on the static snapshot.",
              el.currentSrc || el.src || el
            );
            meta.needsRecapture = false;
          }
        }

        if (meta.needsRecapture && !meta._capturing && !this._isScrolling) {
          meta.needsRecapture = false;
        }

        if (meta.lastCapture) {
          if (meta.prevDrawRect && !(this._workerEnabled && meta._heavyAnim)) {
            const { x, y, w, h } = meta.prevDrawRect;
            if (w > 0 && h > 0) {
              const eraseCanvas = this._compositeCtx.canvas;
              if (eraseCanvas.width !== w || eraseCanvas.height !== h) {
                eraseCanvas.width = w;
                eraseCanvas.height = h;
              }
              this._compositeCtx.drawImage(
                this.staticSnapshotCanvas,
                x,
                y,
                w,
                h,
                0,
                0,
                w,
                h
              );
              gl.bindTexture(gl.TEXTURE_2D, this.texture);
              try {
                gl.texSubImage2D(
                  gl.TEXTURE_2D,
                  0,
                  x,
                  y,
                  gl.RGBA,
                  gl.UNSIGNED_BYTE,
                  eraseCanvas
                );
              } catch (e) {
                liquidGLLog("warn", "liquidGL: Dynamic texture erase failed.", e);
              }
            }
          }

          const rect = el.getBoundingClientRect();
          if (
            effectiveZ(el) > maxLensZ ||
            !document.contains(el) ||
            rect.width === 0 ||
            rect.height === 0
          ) {
            meta.prevDrawRect = null;
            return;
          }

          if (!this.lenses.some((lens) => lensVisibleForRect(lens, rect))) {
            meta.prevDrawRect = null;
            return;
          }

          const texX = (rect.left - snapRect.left) * this.scaleFactor;
          const texY = (rect.top - snapRect.top) * this.scaleFactor;
          const drawW = Math.round(rect.width * this.scaleFactor);
          const drawH = Math.round(rect.height * this.scaleFactor);
          const drawX = Math.round(texX);
          const drawY = Math.round(texY);

          if (drawW <= 0 || drawH <= 0) return;

          const maxW = this.textureWidth;
          const maxH = this.textureHeight;
          let dstX = drawX;
          let dstY = drawY;
          let srcX = 0,
            srcY = 0,
            updW = drawW,
            updH = drawH;

          if (dstX < 0) {
            srcX = -dstX;
            updW += dstX;
            dstX = 0;
          }
          if (dstY < 0) {
            srcY = -dstY;
            updH += dstY;
            dstY = 0;
          }

          if (dstX + updW > maxW) {
            updW = maxW - dstX;
          }
          if (dstY + updH > maxH) {
            updH = maxH - dstY;
          }

          if (updW <= 0 || updH <= 0) return;

          const compositeCanvas = this._compositeCtx.canvas;
          if (
            compositeCanvas.width !== drawW ||
            compositeCanvas.height !== drawH
          ) {
            compositeCanvas.width = drawW;
            compositeCanvas.height = drawH;
          }
          this._compositeCtx.clearRect(0, 0, drawW, drawH);

          this._compositeCtx.drawImage(
            this.staticSnapshotCanvas,
            texX,
            texY,
            rect.width * this.scaleFactor,
            rect.height * this.scaleFactor,
            0,
            0,
            drawW,
            drawH
          );
          compositeVideos(this._compositeCtx, rect);

          const style = window.getComputedStyle(el);
          this._compositeCtx.save();
          this._compositeCtx.translate(drawW / 2, drawH / 2);
          if (style.transform !== "none") {
            this._compositeCtx.transform(
              ...this._parseTransform(style.transform)
            );
          }
          this._compositeCtx.translate(-drawW / 2, -drawH / 2);
          this._compositeCtx.globalAlpha = parseFloat(style.opacity) || 1.0;
          this._compositeCtx.drawImage(meta.lastCapture, 0, 0, drawW, drawH);
          this._compositeCtx.restore();

          gl.bindTexture(gl.TEXTURE_2D, this.texture);
          try {
            gl.texSubImage2D(
              gl.TEXTURE_2D,
              0,
              dstX,
              dstY,
              gl.RGBA,
              gl.UNSIGNED_BYTE,
              compositeCanvas
            );
          } catch (e) {
            liquidGLLog("warn", "liquidGL: Dynamic texture update failed.", e);
            return;
          }

          if (this._workerEnabled && meta._heavyAnim) {
            const jobId = `${Date.now()}_${Math.random()}`;
            this._dynJobs.set(jobId, {
              x: dstX,
              y: dstY,
              w: updW,
              h: updH,
            });

            Promise.all([
              createImageBitmap(
                this.staticSnapshotCanvas,
                dstX,
                dstY,
                updW,
                updH
              ),
              createImageBitmap(meta.lastCapture),
            ]).then(([snapBmp, dynBmp]) => {
              this._dynWorker.postMessage(
                {
                  id: jobId,
                  width: updW,
                  height: updH,
                  snap: snapBmp,
                  dyn: dynBmp,
                },
                [snapBmp, dynBmp]
              );
            });
            meta.prevDrawRect = { x: dstX, y: dstY, w: updW, h: updH };
            return;
          }

          meta.prevDrawRect = { x: dstX, y: dstY, w: updW, h: updH };
        }
      });
    }

    _parseTransform(transform) {
      if (transform === "none") return [1, 0, 0, 1, 0, 0];
      const matrixMatch = transform.match(/matrix\((.+)\)/);
      if (matrixMatch) {
        const values = matrixMatch[1].split(",").map(parseFloat);
        return values;
      }
      const matrix3dMatch = transform.match(/matrix3d\((.+)\)/);
      if (matrix3dMatch) {
        const v = matrix3dMatch[1].split(",").map(parseFloat);
        return [v[0], v[1], v[4], v[5], v[12], v[13]];
      }
      return [1, 0, 0, 1, 0, 0];
    }

    _captureImageElement(el) {
      try {
        if (!el || el.tagName !== "IMG" || !el.complete || !el.naturalWidth || !el.naturalHeight) {
          return null;
        }
        const rect = el.getBoundingClientRect();
        const w = Math.max(1, Math.round(rect.width * this.scaleFactor));
        const h = Math.max(1, Math.round(rect.height * this.scaleFactor));
        const canvas = document.createElement("canvas");
        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext("2d");
        const iw = el.naturalWidth;
        const ih = el.naturalHeight;
        const fit = window.getComputedStyle(el).objectFit || "fill";
        let dw = w;
        let dh = h;
        let dx = 0;
        let dy = 0;
        if (fit === "cover") {
          const s = Math.max(w / iw, h / ih);
          dw = iw * s;
          dh = ih * s;
          dx = (w - dw) / 2;
          dy = (h - dh) / 2;
        } else if (fit === "contain") {
          const s = Math.min(w / iw, h / ih);
          dw = iw * s;
          dh = ih * s;
          dx = (w - dw) / 2;
          dy = (h - dh) / 2;
        }
        ctx.drawImage(el, dx, dy, dw, dh);
        return canvas;
      } catch (e) {
        liquidGLLog("warn", "liquidGL: Image element capture failed.", e);
        return null;
      }
    }

    /* ----------------------------- */
    _getMaxLensZ() {
      let maxZ = 0;
      this.lenses.forEach((ln) => {
        const z = effectiveZ(ln.el);
        if (z > maxZ) maxZ = z;
      });
      return maxZ;
    }

    /* ----------------------------- */
    addDynamicElement(el) {
      if (!el) return;
      if (typeof el === "string") {
        this.snapshotTarget
          .querySelectorAll(el)
          .forEach((n) => this.addDynamicElement(n));
        return;
      }
      if (NodeList.prototype.isPrototypeOf(el) || Array.isArray(el)) {
        Array.from(el).forEach((n) => this.addDynamicElement(n));
        return;
      }
      if (!el.getBoundingClientRect) return;
      if (el.id === "visualizerBg" || (el.classList && el.classList.contains("visualizerBg"))) return;
      if (el.closest && el.closest("[data-liquid-ignore]")) return;
      if (this._dynamicNodes.some((n) => n.el === el)) return;

      this._dynamicNodes = this._dynamicNodes.filter((n) => !el.contains(n.el));

      const meta = {
        _capturing: false,
        prevDrawRect: null,
        lastCapture: null,
        needsRecapture: true,
        hoverClassName: null,
        _animating: false,
        _rafId: null,
        _lastCaptureTs: 0,
        _heavyAnim: false,
        lastDrawSignature: null,
      };
      this._dynMeta.set(el, meta);

      const setDirty = () => {
        const m = this._dynMeta.get(el);
        if (m && !m.needsRecapture) {
          m.needsRecapture = true;
          requestAnimationFrame(() => this.render());
        }
      };

      const findAppliedHoverStyles = (element) => {
        let cssText = "";
        for (const sheet of document.styleSheets) {
          try {
            for (const rule of sheet.cssRules) {
              if (!rule.selectorText || !rule.selectorText.includes(":hover")) {
                continue;
              }
              const baseSelector = rule.selectorText.split(":hover")[0];
              if (element.matches(baseSelector)) {
                cssText += rule.style.cssText;
              }
            }
          } catch (e) {}
        }
        return cssText;
      };

      const handleLeave = () => {
        const m = this._dynMeta.get(el);
        if (!m || !m.hoverClassName) return;

        el.classList.remove(m.hoverClassName);
        for (let i = this._dynamicStyleSheet.cssRules.length - 1; i >= 0; i--) {
          const rule = this._dynamicStyleSheet.cssRules[i];
          if (rule.selectorText === `.${m.hoverClassName}`) {
            this._dynamicStyleSheet.deleteRule(i);
            break;
          }
        }
        m.hoverClassName = null;
        setDirty();
      };

      el.addEventListener(
        "mouseenter",
        () => {
          const m = this._dynMeta.get(el);
          if (!m) return;
          const hoverCss = findAppliedHoverStyles(el);
          if (hoverCss) {
            const className = `lqgl-h-${Math.random()
              .toString(36)
              .substr(2, 9)}`;
            const rule = `.${className} { ${hoverCss} }`;
            try {
              this._dynamicStyleSheet.insertRule(
                rule,
                this._dynamicStyleSheet.cssRules.length
              );
              m.hoverClassName = className;
              el.classList.add(className);
            } catch (e) {
              liquidGLLog("error", "liquidGL: Failed to insert hover style rule.", e);
            }
          }
          setDirty();
        },
        { passive: true }
      );

      el.addEventListener("mouseleave", handleLeave, { passive: true });
      el.addEventListener("transitionend", setDirty, { passive: true });

      const startRealtime = () => {
        const m = this._dynMeta.get(el);
        if (!m || m._animating) return;
        m._animating = true;

        m._heavyAnim = false;

        const step = (ts) => {
          const meta = this._dynMeta.get(el);
          if (!meta || !meta._animating) return;

          if (
            meta._heavyAnim &&
            !meta._capturing &&
            ts - meta._lastCaptureTs > 33
          ) {
            meta._lastCaptureTs = ts;
            meta.needsRecapture = true;
          }
          if (meta._heavyAnim) {
            meta._rafId = requestAnimationFrame(step);
          } else {
            meta._rafId = null;
          }
        };
        m._rafId = requestAnimationFrame(step);
      };

      const trackProperty = (prop) => {
        const m = this._dynMeta.get(el);
        if (!m) return;
        const low = (prop || "").toLowerCase();
        if (!(low.includes("transform") || low.includes("opacity"))) {
          const wasHeavy = m._heavyAnim;
          m._heavyAnim = true;
          if (m._animating && !wasHeavy && !m._rafId) {
            m._animating = false;
            startRealtime();
          }
        }
      };

      const transitionRunHandler = (e) => {
        trackProperty(e.propertyName);
        startRealtime();
      };

      el.addEventListener("transitionrun", transitionRunHandler, {
        passive: true,
      });
      el.addEventListener("transitionstart", transitionRunHandler, {
        passive: true,
      });
      el.addEventListener(
        "animationstart",
        () => {
          const m = this._dynMeta.get(el);
          if (m) m._heavyAnim = true;
          startRealtime();
        },
        { passive: true }
      );

      el.addEventListener(
        "animationiteration",
        () => {
          const m = this._dynMeta.get(el);
          if (m) {
            m._heavyAnim = true;
            if (!m._animating) startRealtime();
          }
        },
        { passive: true }
      );

      const stopRealtime = () => {
        const m = this._dynMeta.get(el);
        if (!m || !m._animating) return;
        m._animating = false;
        if (m._rafId) {
          cancelAnimationFrame(m._rafId);
          m._rafId = null;
        }
        m._heavyAnim = false;
        setDirty();
      };

      el.addEventListener("transitionend", stopRealtime, { passive: true });
      el.addEventListener("transitioncancel", stopRealtime, { passive: true });
      el.addEventListener("animationend", stopRealtime, { passive: true });
      el.addEventListener("animationcancel", stopRealtime, { passive: true });

      /* --------------------------------------------------
       *  Removal clean-up
       * --------------------------------------------------*/
      if (typeof MutationObserver !== "undefined") {
        const removalObserver = new MutationObserver(() => {
          if (!document.contains(el)) {
            handleLeave();
            removalObserver.disconnect();
            this._dynamicNodes = this._dynamicNodes.filter((n) => n.el !== el);
            this._dynMeta.delete(el);
          }
        });
        removalObserver.observe(document.body, {
          childList: true,
          subtree: true,
        });
      }

      this._dynamicNodes.push({ el });
    }

    /* ----------------------------- */
    _isIgnored(el) {
      return !!(
        el &&
        typeof el.closest === "function" &&
        el.closest("[data-liquid-ignore]")
      );
    }
  }

  /* --------------------------------------------------
   *  Per-element lens wrapper
   * ------------------------------------------------*/
  class liquidGLLens {
    constructor(renderer, element, options) {
      this.renderer = renderer;
      this.el = element;
      this.options = Object.assign({}, options || {});
      if (this.options.material !== null && this.options.material !== undefined) {
        this.options.material = normalizeLiquidGlassMaterial(this.options.material, 0);
      }
      this._transition = null;
      this._initCalled = false;
      this._syncDomRect = this.options.liveGeometry === true;
      this.rectPx = null;
      this.radiusGl = 0;
      this.radiusCss = 0;
      this.hollowInsetGl = 0;
      this.hollowMaskContent =
        !!this.options.hollowMaskContent ||
        this.el.hasAttribute("data-liquid-mask-content");
      this.revealTypeIndex = this.options.reveal === "fade" ? 1 : 0;
      this._revealProgress = this.revealTypeIndex === 0 ? 1 : 0;
      this.tiltX = 0;
      this.tiltY = 0;

      this.originalShadow = this.el.style.boxShadow;
      this.originalOpacity = this.el.style.opacity;
      this.originalTransition = this.el.style.transition;
      this.el.style.transition = "none";
      this.el.style.opacity = 0;

      this.el.style.position =
        this.el.style.position === "static"
          ? "relative"
          : this.el.style.position;

      const bgCol = window.getComputedStyle(this.el).backgroundColor;
      const rgbaMatch = bgCol.match(/rgba?\(([^)]+)\)/);
      this._bgColorComponents = null;
      if (rgbaMatch) {
        const comps = rgbaMatch[1].split(/[ ,]+/).map(parseFloat);
        const [r, g, b, a = 1] = comps;
        this._bgColorComponents = { r, g, b, a };
        this.el.style.backgroundColor = `rgba(${r}, ${g}, ${b}, 0)`;
      }

      this.el.style.backdropFilter = "none";
      this.el.style.webkitBackdropFilter = "none";
      this.el.style.backgroundImage = "none";
      this.el.style.background = "transparent";

      this.updateMetrics();
      const initialOptics = this.resolveOptics(1);
      this.setShadow(
        this.options.material !== null && this.options.material !== undefined ? true : this.options.shadow,
        initialOptics.shadowStrength
      );
      if (this.options.tilt) this._bindTiltHandlers();

      if (typeof ResizeObserver !== "undefined" && !this._sizeObs) {
        this._sizeObs = new ResizeObserver(() => {
          this.renderer._metricsDirty = true;
          this.updateMetrics();
          this.renderer.render();
        });
        this._sizeObs.observe(this.el);
      }
    }

    _normalizeOptionsPatch(patch) {
      const normalized = {};
      Object.keys(patch || {}).forEach((key) => {
        const value = patch[key];
        if (key === "material") {
          normalized.material = value === null ? null : normalizeLiquidGlassMaterial(value, 0);
          return;
        }
        const bounds = LIQUID_GL_LIVE_NUMERIC_OPTIONS[key];
        if (bounds) {
          const fallback = finiteNumber(this.options[key], key === "magnify" ? 1 : 0);
          normalized[key] = clamp(finiteNumber(value, fallback), bounds[0], bounds[1]);
          return;
        }
        normalized[key] = value;
      });
      return normalized;
    }

    _applyOptionsPatch(patch, requestFrame) {
      const hadTilt = !!this.options.tilt;
      const hadShadow = !!this.options.shadow;
      Object.assign(this.options, patch || {});
      this.revealTypeIndex = this.options.reveal === "fade" ? 1 : 0;
      this.hollowMaskContent =
        !!this.options.hollowMaskContent ||
        this.el.hasAttribute("data-liquid-mask-content");
      if (Object.prototype.hasOwnProperty.call(patch || {}, "liveGeometry")) {
        this._syncDomRect = this.options.liveGeometry === true;
      }

      if (Object.prototype.hasOwnProperty.call(patch || {}, "tilt") && hadTilt !== !!this.options.tilt) {
        this.setTilt(this.options.tilt);
      }

      const optics = this.resolveOptics(1);
      if (this.options.material !== null && this.options.material !== undefined) {
        this.setShadow(true, optics.shadowStrength);
      } else if (
        Object.prototype.hasOwnProperty.call(patch || {}, "shadow") ||
        hadShadow !== !!this.options.shadow
      ) {
        this.setShadow(this.options.shadow, optics.shadowStrength);
      }

      this.renderer._metricsDirty = true;
      if (requestFrame !== false && this.renderer.requestRender) this.renderer.requestRender();
      return this;
    }

    setOptions(patch) {
      this._transition = null;
      return this._applyOptionsPatch(this._normalizeOptionsPatch(patch), true);
    }

    transitionOptions(patch, transition) {
      const config = transition || {};
      const duration = Math.max(0, finiteNumber(config.duration, 200));
      if (duration === 0) return this.setOptions(patch);

      const now = performance.now();
      if (this._transition) this._advanceTransition(now);
      const normalized = this._normalizeOptionsPatch(patch);
      const from = {};
      const to = {};
      const immediate = {};
      Object.keys(normalized).forEach((key) => {
        if (LIQUID_GL_LIVE_NUMERIC_OPTIONS[key] && normalized[key] !== null) {
          from[key] = finiteNumber(this.options[key], key === "magnify" ? 1 : 0);
          to[key] = normalized[key];
        } else {
          immediate[key] = normalized[key];
        }
      });
      if (Object.keys(immediate).length) this._applyOptionsPatch(immediate, false);
      if (!Object.keys(to).length) {
        if (this.renderer.requestRender) this.renderer.requestRender();
        return this;
      }

      const easing = typeof config.easing === "function"
        ? config.easing
        : (LIQUID_GL_EASINGS[config.easing] || LIQUID_GL_EASINGS.easeOut);
      this._transition = { startTime: now, duration, easing, from, to };
      if (this.renderer.requestRender) this.renderer.requestRender();
      return this;
    }

    _advanceTransition(now) {
      const transition = this._transition;
      if (!transition) return false;
      const progress = clamp((now - transition.startTime) / transition.duration, 0, 1);
      const eased = clamp(finiteNumber(transition.easing(progress), progress), 0, 1);
      const next = {};
      Object.keys(transition.to).forEach((key) => {
        next[key] = mixNumber(transition.from[key], transition.to[key], eased);
      });
      this._applyOptionsPatch(next, false);
      if (progress >= 1) {
        this._transition = null;
        return false;
      }
      return true;
    }

    resolveOptics(quality) {
      if (this.options.material !== null && this.options.material !== undefined) {
        return resolveLiquidGlassMaterial(this.options.material, {
          width: this.rectPx ? this.rectPx.width : 0,
          height: this.rectPx ? this.rectPx.height : 0,
        }, quality);
      }
      return {
        material: 0,
        density: 0,
        side: 0,
        tone: [1, 1, 1],
        materialAlpha: 0,
        frostSigmaPx: Math.max(0, finiteNumber(this.options.frost, 0)),
        refraction: Math.max(0, finiteNumber(this.options.refraction, 0.01)),
        refractionFill: clamp(finiteNumber(this.options.refractionFill, 0), 0, 1),
        bevelDepth: Math.max(0, finiteNumber(this.options.bevelDepth, 0.08)),
        bevelWidth: Math.max(0, finiteNumber(this.options.bevelWidth, 0.15)),
        magnify: clamp(finiteNumber(this.options.magnify, 1), 0.001, 3),
        specularPrimary: 0.1675,
        specularSecondary: 0.08,
        shadowStrength: 0.1,
        specular: this.options.specular !== false,
      };
    }

    _resolveCssLength(raw, fallback = 0) {
      const value = String(raw || "").trim();
      if (!value) return fallback;

      const direct = parseFloat(value);
      if (Number.isFinite(direct) && !value.includes("var(") && !value.includes("calc(")) {
        return direct;
      }

      let probe = null;
      try {
        probe = document.createElement("div");
        probe.style.position = "absolute";
        probe.style.visibility = "hidden";
        probe.style.pointerEvents = "none";
        probe.style.width = value;
        probe.style.height = "0";
        this.el.appendChild(probe);
        const resolved = parseFloat(window.getComputedStyle(probe).width);
        if (Number.isFinite(resolved)) return resolved;
      } catch (e) {
      } finally {
        try {
          if (probe && probe.parentNode) probe.parentNode.removeChild(probe);
        } catch (e) {}
      }

      return Number.isFinite(direct) ? direct : fallback;
    }

    _isEffectivelyHidden() {
      let node = this.el;
      while (node && node !== document.body) {
        const style = window.getComputedStyle(node);
        if (
          style.display === "none" ||
          style.visibility === "hidden" ||
          (node !== this.el && parseFloat(style.opacity || "1") <= 0.01)
        ) {
          return true;
        }
        node = node.parentElement;
      }
      return false;
    }

    /* ----------------------------- */
    updateMetrics() {
      const suppliedRect = this.options && typeof this.options.geometryRect === "function" ? this.options.geometryRect(this.el) : null;
      const rect = suppliedRect || (
        this._mirrorActive && this._baseRect
          ? this._baseRect
          : this.el.getBoundingClientRect());
      const style = window.getComputedStyle(this.el);

      if (
        rect.width <= 0 ||
        rect.height <= 0 ||
        style.display === "none" ||
        style.visibility === "hidden" ||
        this._isEffectivelyHidden()
      ) {
        this.rectPx = null;
        return;
      }

      let visibleRect = {
        left: rect.left,
        top: rect.top,
        right: rect.left + rect.width,
        bottom: rect.top + rect.height,
      };
      if (this.options && this.options.clipTarget) {
        const clipEl = document.querySelector(this.options.clipTarget);
        if (clipEl) {
          const clipRect = clipEl.getBoundingClientRect();
          let clipLeft = clipRect.left;
          let clipTop = clipRect.top;
          let clipRight = clipRect.right;
          let clipBottom = clipRect.bottom;
          if (this.options.clipToPaddingBox) {
            const clipStyle = window.getComputedStyle(clipEl);
            clipLeft += parseFloat(clipStyle.paddingLeft || "0") || 0;
            clipTop += parseFloat(clipStyle.paddingTop || "0") || 0;
            clipRight -= parseFloat(clipStyle.paddingRight || "0") || 0;
            clipBottom -= parseFloat(clipStyle.paddingBottom || "0") || 0;
          }
          visibleRect = {
            left: Math.max(visibleRect.left, clipLeft),
            top: Math.max(visibleRect.top, clipTop),
            right: Math.min(visibleRect.right, clipRight),
            bottom: Math.min(visibleRect.bottom, clipBottom),
          };
          if (visibleRect.right <= visibleRect.left || visibleRect.bottom <= visibleRect.top) {
            this.rectPx = null;
            return;
          }
        }
      }

      // Clip raster output, never squeeze the lens geometry as it scrolls.
      this.clipRectPx = visibleRect;
      this.rectPx = {left:rect.left, top:rect.top, width:rect.width, height:rect.height};

      const brRaw = style.borderTopLeftRadius.split(" ")[0];
      const isPct = brRaw.trim().endsWith("%");
      let brPx;
      if (isPct) {
        const pct = parseFloat(brRaw);
        brPx = (Math.min(rect.width, rect.height) * pct) / 100;
      } else {
        brPx = this._resolveCssLength(brRaw, 0);
      }
      const maxAllowedCss = Math.min(rect.width, rect.height) * 0.5;
      this.radiusCss = Math.min(brPx, maxAllowedCss);

      const insetRaw = (
        style.getPropertyValue("--liquid-hole-inset") ||
        this.el.getAttribute("data-liquid-hole-inset") ||
        "0"
      ).trim();
      let insetPx = this._resolveCssLength(insetRaw, 0);
      if (!Number.isFinite(insetPx)) insetPx = 0;
      this.hollowInsetCss = Math.max(0, Math.min(insetPx, maxAllowedCss));

      const dpr = this.renderer && this.renderer._dpr ? this.renderer._dpr : Math.min(2, window.devicePixelRatio || 1);
      this.radiusGl = this.radiusCss * dpr;
      this.hollowInsetGl = this.hollowInsetCss * dpr;

      if (this._shadowSyncFn) {
        this._shadowSyncFn();
      }
    }

    /* ----------------------------- */
    _handleOverscrollCompensation() {
      let overscrollY = 0;
      let overscrollX = 0;

      if (window.visualViewport) {
        overscrollX = -window.visualViewport.offsetLeft;
        overscrollY = -window.visualViewport.offsetTop;
      } else {
        const bodyStyle = window.getComputedStyle(document.body);
        const htmlStyle = window.getComputedStyle(document.documentElement);

        if (bodyStyle.transform && bodyStyle.transform !== "none") {
          const matrix = new DOMMatrix(bodyStyle.transform);
          overscrollX = matrix.m41;
          overscrollY = matrix.m42;
        }

        if (
          overscrollY === 0 &&
          overscrollX === 0 &&
          htmlStyle.transform &&
          htmlStyle.transform !== "none"
        ) {
          const matrix = new DOMMatrix(htmlStyle.transform);
          overscrollX = matrix.m41;
          overscrollY = matrix.m42;
        }
      }

      this._currentOverscrollX = overscrollX;
      this._currentOverscrollY = overscrollY;

      if (overscrollY !== 0 || overscrollX !== 0) {
        const compensationTransform = `translate(${-overscrollX}px, ${-overscrollY}px)`;

        let currentTransform = this.el.style.transform;
        currentTransform = currentTransform
          .replace(/translate\([^)]*\)\s*/g, "")
          .trim();

        this.el.style.transform =
          compensationTransform +
          (currentTransform ? " " + currentTransform : "");

        if (this._shadowEl) {
          let shadowTransform = this._shadowEl.style.transform || "";
          shadowTransform = shadowTransform
            .replace(/translate\([^)]*\)\s*/g, "")
            .trim();
          this._shadowEl.style.transform =
            compensationTransform +
            (shadowTransform ? " " + shadowTransform : "");
        }
      } else if (!this._tiltInteracting) {
        this.el.style.transform = this._savedTransform || "";
        if (this._shadowEl) {
          this._shadowEl.style.transform = "";
        }
      }
    }

    /* ----------------------------- */
    setTilt(enabled) {
      this.options.tilt = !!enabled;
      if (this.options.tilt) {
        this._bindTiltHandlers();
      } else {
        this._unbindTiltHandlers();
      }
    }

    /* ----------------------------- */
    _shadowValue(strength) {
      const light = this._globalLightState || { x: 0, y: 0, intensity: 0 };
      const intensity = clamp(finiteNumber(light.intensity, 0), 0, 1);
      const offsetX = clamp(finiteNumber(light.x, 0), -1, 1) * intensity * 2.0;
      const offsetY = clamp(finiteNumber(light.y, 0), -1, 1) * intensity * 2.0;
      return `${offsetX.toFixed(2)}px ${(10 + offsetY).toFixed(2)}px 30px rgba(0,0,0,${strength.toFixed(4)}), ` +
        `${(-offsetX * 0.25).toFixed(2)}px ${(-offsetY * 0.25).toFixed(2)}px 0 0.5px rgba(0,0,0,${(strength * 0.5).toFixed(4)})`;
    }

    setGlobalLighting(state) {
      this._globalLightState = state || { x: 0, y: 0, intensity: 0 };
      if (!this.options || !this.options.shadow) return;
      const value = this._shadowValue(clamp(finiteNumber(this._shadowStrength, 0.1), 0, 0.4));
      this.el.style.boxShadow = value;
      if (this._shadowEl) this._shadowEl.style.boxShadow = value;
    }

    setShadow(enabled, strength) {
      this.options.shadow = !!enabled;
      const shadowStrength = clamp(finiteNumber(strength, 0.1), 0, 0.4);
      this._shadowStrength = shadowStrength;
      const shadowValue = this._shadowValue(shadowStrength);

      // The lens DOM element already owns the rounded shadow and follows
      // scrolling, clipping, transforms and visibility. A body-level clone
      // leaves stale rectangular ghosts when virtual rows are recycled.
      if (this._shadowEl) {
        window.removeEventListener("resize", this._shadowSyncFn);
        this._shadowEl.remove();
        this._shadowEl = null;
      }
      this.el.style.boxShadow = enabled ? shadowValue : this.originalShadow;
    }

    /* ----------------------------- */
    _reveal() {
      if (this.revealTypeIndex === 0) {
        this.el.style.opacity = this.originalOpacity || 1;
        this.renderer.canvas.style.opacity = "1";
        this._revealProgress = 1;
        this._TriggerInit();
        return;
      }

      if (this.renderer._revealAnimating) return;

      this.renderer._revealAnimating = true;

      const dur = 1000;
      const start = performance.now();

      const animate = () => {
        const progress = Math.min(1, (performance.now() - start) / dur);

        this.renderer.lenses.forEach((ln) => {
          ln._revealProgress = progress;
          ln.el.style.opacity = (ln.originalOpacity || 1) * progress;
          if (ln._shadowEl) {
            ln._shadowEl.style.opacity = progress;
          }
        });

        this.renderer.canvas.style.opacity = String(progress);

        this.renderer.render();

        if (progress < 1) {
          requestAnimationFrame(animate);
        } else {
          this.renderer._revealAnimating = false;
          this.renderer.lenses.forEach((ln) => {
            ln.el.style.transition = ln.originalTransition || "";
            ln._TriggerInit();
          });
        }
      };

      requestAnimationFrame(animate);
    }

    /* ----------------------------- */
    _bindTiltHandlers() {
      if (this._tiltHandlersBound) return;

      if (this._savedTransform === undefined) {
        const currentTransform = this.el.style.transform;
        if (currentTransform && currentTransform.includes("translate")) {
          this._savedTransform = currentTransform
            .replace(/translate\([^)]*\)\s*/g, "")
            .trim();
          if (this._savedTransform === "") this._savedTransform = "none";
        } else {
          this._savedTransform = currentTransform;
        }
      }
      if (this._savedTransformStyle === undefined) {
        this._savedTransformStyle = this.el.style.transformStyle;
      }
      this.el.style.transformStyle = "preserve-3d";

      const getMaxTilt = () =>
        Number.isFinite(this.options.tiltFactor) ? this.options.tiltFactor : 5;

      this._applyTilt = (clientX, clientY) => {
        if (!this._tiltInteracting) {
          this._tiltInteracting = true;
          this.el.style.transition =
            "transform 0.12s cubic-bezier(0.33,1,0.68,1)";
          this._createMirrorCanvas();
          if (this._mirror) {
            this._mirror.style.transition =
              "transform 0.12s cubic-bezier(0.33,1,0.68,1)";
          }
          if (this._shadowEl) {
            this._shadowEl.style.transition =
              "transform 0.12s cubic-bezier(0.33,1,0.68,1)";
          }
        }

        const r = this._baseRect || (this._baseRect = this.el.getBoundingClientRect());
        const cx = r.left + r.width / 2;
        const cy = r.top + r.height / 2;

        this._pivotOrigin = `${cx}px ${cy}px`;

        const pctX = (clientX - cx) / (r.width / 2);
        const pctY = (clientY - cy) / (r.height / 2);
        const maxTilt = getMaxTilt();
        const rotY = pctX * maxTilt;
        const rotX = -pctY * maxTilt;
        const baseTransform =
          this._savedTransform && this._savedTransform !== "none"
            ? this._savedTransform + " "
            : "";

        let overscrollCompensation = "";
        const bodyStyle = window.getComputedStyle(document.body);
        if (bodyStyle.transform && bodyStyle.transform !== "none") {
          const matrix = new DOMMatrix(bodyStyle.transform);
          const overscrollX = matrix.m41;
          const overscrollY = matrix.m42;
          if (overscrollX !== 0 || overscrollY !== 0) {
            overscrollCompensation = `translate(${-overscrollX}px, ${-overscrollY}px) `;
          }
        }

        const transformStr = `${overscrollCompensation}${baseTransform}perspective(800px) rotateX(${rotX}deg) rotateY(${rotY}deg)`;

        this.tiltX = rotX;
        this.tiltY = rotY;

        this.el.style.transformOrigin = `50% 50%`;
        this.el.style.transform = transformStr;

        if (this._mirror) {
          this._mirror.style.transformOrigin = this._pivotOrigin;
          this._mirror.style.transform = transformStr;
        }

        if (this._shadowEl) {
          this._shadowEl.style.transformOrigin = `50% 50%`;
          this._shadowEl.style.transform = transformStr;
        }

      };

      this._smoothReset = () => {
        this.el.style.transition = "transform 0.4s cubic-bezier(0.33,1,0.68,1)";
        this.el.style.transformOrigin = `50% 50%`;
        const baseRest =
          this._savedTransform && this._savedTransform !== "none"
            ? this._savedTransform + " "
            : "";

        let overscrollCompensation = "";
        const bodyStyle = window.getComputedStyle(document.body);
        if (bodyStyle.transform && bodyStyle.transform !== "none") {
          const matrix = new DOMMatrix(bodyStyle.transform);
          const overscrollX = matrix.m41;
          const overscrollY = matrix.m42;
          if (overscrollX !== 0 || overscrollY !== 0) {
            overscrollCompensation = `translate(${-overscrollX}px, ${-overscrollY}px) `;
          }
        }

        this.el.style.transform = `${overscrollCompensation}${baseRest}perspective(800px) rotateX(0deg) rotateY(0deg)`;

        this.tiltX = 0;
        this.tiltY = 0;
        this.renderer.render();

        if (this._mirror) {
          this._mirror.style.transition =
            "transform 0.4s cubic-bezier(0.33, 1, 0.68, 1)";
          this._mirror.style.transformOrigin = this._pivotOrigin || "50% 50%";
          this._mirror.style.transform = `${baseRest}perspective(800px) rotateX(0deg) rotateY(0deg)`;
          const clean = () => {
            this._destroyMirrorCanvas();
            this._resetCleanupTimer = null;
          };
          this._mirror.addEventListener("transitionend", clean, {
            once: true,
          });
          this._resetCleanupTimer = setTimeout(clean, 350);
        }

        if (this._shadowEl) {
          this._shadowEl.style.transition =
            "transform 0.4s cubic-bezier(0.33,1,0.68,1)";
          this._shadowEl.style.transformOrigin = `50% 50%`;
          this._shadowEl.style.transform = `${baseRest}perspective(800px) rotateX(0deg) rotateY(0deg)`;
        }
      };

      this._onMouseEnter = (e) => {
        if (this._resetCleanupTimer) {
          clearTimeout(this._resetCleanupTimer);
          this._resetCleanupTimer = null;
          this._destroyMirrorCanvas();
          this.el.style.transition = "none";
          this.el.style.transform = this._savedTransform || "";
          void this.el.offsetHeight;
        }

        this._tiltInteracting = false;
        this._createMirrorCanvas();

        const r = this._baseRect || this.el.getBoundingClientRect();
        const cx = r.left + r.width / 2;
        const cy = r.top + r.height / 2;

        this._applyTilt(cx, cy);

        if (e && typeof e.clientX === "number") {
          requestAnimationFrame(() => {
            this._applyTilt(e.clientX, e.clientY);
          });
        }

        document.addEventListener("mousemove", this._boundCheckLeave, {
          passive: true,
        });
      };

      this._onMouseMove = (e) => this._applyTilt(e.clientX, e.clientY);

      this._onTouchStart = (e) => {
        this._tiltInteracting = false;
        this._createMirrorCanvas();
        if (e.touches && e.touches.length === 1) {
          const t = e.touches[0];
          this._applyTilt(t.clientX, t.clientY);
        }
      };
      this._onTouchMove = (e) => {
        if (e.touches && e.touches.length === 1) {
          const t = e.touches[0];
          this._applyTilt(t.clientX, t.clientY);
        }
      };
      this._onTouchEnd = () => {
        this._smoothReset();
      };

      this.el.addEventListener("mouseenter", this._onMouseEnter, {
        passive: true,
      });
      this.el.addEventListener("mousemove", this._onMouseMove, {
        passive: true,
      });
      this.el.addEventListener("touchstart", this._onTouchStart, {
        passive: true,
      });
      this.el.addEventListener("touchmove", this._onTouchMove, {
        passive: true,
      });
      this.el.addEventListener("touchend", this._onTouchEnd, {
        passive: true,
      });

      /* ----------------------------- */
      this._tiltActive = false;

      this._docPointerMove = (e) => {
        const x = e.clientX ?? (e.touches && e.touches[0].clientX);
        const y = e.clientY ?? (e.touches && e.touches[0].clientY);
        if (x === undefined || y === undefined) return;

        const r = this._baseRect || (this._baseRect = this.el.getBoundingClientRect());
        const inside =
          x >= r.left && x <= r.right && y >= r.top && y <= r.bottom;

        if (inside) {
          if (!this._tiltActive) {
            this._tiltActive = true;
            this._onMouseEnter({ clientX: x, clientY: y });
          } else {
            this._applyTilt(x, y);
          }
        } else if (this._tiltActive) {
          this._tiltActive = false;
          this._smoothReset();
        }
      };

      document.addEventListener("pointermove", this._docPointerMove, {
        passive: true,
      });

      this._tiltHandlersBound = true;
    }

    _unbindTiltHandlers() {
      if (!this._tiltHandlersBound) return;
      this.el.removeEventListener("mouseenter", this._onMouseEnter);
      this.el.removeEventListener("mousemove", this._onMouseMove);
      document.removeEventListener("mousemove", this._boundCheckLeave);
      this.el.removeEventListener("touchstart", this._onTouchStart);
      this.el.removeEventListener("touchmove", this._onTouchMove);
      this.el.removeEventListener("touchend", this._onTouchEnd);

      if (this._docPointerMove) {
        document.removeEventListener("pointermove", this._docPointerMove);
        this._docPointerMove = null;
      }
      this._tiltHandlersBound = false;

      this.el.style.transform = this._savedTransform || "";
      this.el.style.transformStyle = this._savedTransformStyle || "";

      this.renderer.render();
    }

    _createMirrorCanvas() {
      this._baseRect = this.el.getBoundingClientRect();
      if (this._mirror) return;
      this._mirror = document.createElement("canvas");
      Object.assign(this._mirror.style, {
        position: "fixed",
        top: 0,
        left: 0,
        width: "100%",
        height: "100%",
        pointerEvents: "none",
        zIndex: effectiveZ(this.el) - 1,
        willChange: "transform",
      });
      this._mirrorCtx = this._mirror.getContext("2d");
      document.body.appendChild(this._mirror);

      const updateClip = () => {
        if (this._mirrorActive) this._baseRect = this._baseRect || this.el.getBoundingClientRect();
        const r = this._baseRect || this.el.getBoundingClientRect();
        const radius = `${this.radiusCss}px`;
        this._mirror.style.clipPath = `inset(${r.top}px ${
          innerWidth - r.right
        }px ${innerHeight - r.bottom}px ${r.left}px round ${radius})`;
        this._mirror.style.webkitClipPath = this._mirror.style.clipPath;
      };
      updateClip();
      this._mirrorClipUpdater = updateClip;
      window.addEventListener("resize", updateClip, { passive: true });

      this._mirrorActive = true;
    }

    _destroyMirrorCanvas() {
      if (!this._mirror) return;
      window.removeEventListener("resize", this._mirrorClipUpdater);
      this._mirror.remove();
      this._mirror = this._mirrorCtx = null;
      this._baseRect = null;
      this._mirrorActive = false;
    }

    destroy() {
      this._transition = null;
      try {
        if (this._sizeObs) this._sizeObs.disconnect();
      } catch (e) {}
      try {
        if (this._shadowEl) this._shadowEl.remove();
      } catch (e) {}
      this._destroyMirrorCanvas();
    }

    _TriggerInit() {
      if (this._initCalled) return;
      this._initCalled = true;
      if (this.options.on && this.options.on.init) {
        this.options.on.init(this);
      }
    }
  }

  /* --------------------------------------------------
   *  Public API
   * ------------------------------------------------*/
  window.liquidGL = function (userOptions = {}) {
    const defaults = {
      target: ".liquidGL",
      snapshot: "body",
      resolution: 2.0,
      refraction: 0.01,
      refractionFill: 0,
      bevelDepth: 0.08,
      bevelWidth: 0.15,
      frost: 0,
      shadow: true,
      specular: true,
      reveal: "fade",
      tilt: false,
      tiltFactor: 5,
      magnify: 1,
      material: null,
      engine: "snapdom",
      sourceType: "visualizerWebgl",
      sourceElement: "#visualizerBg",
      on: {},
    };
    const options = { ...defaults, ...userOptions };

    if (typeof window.__liquidGLNoWebGL__ === "undefined") {
      const testCanvas = document.createElement("canvas");
      const testCtx =
        testCanvas.getContext("webgl") ||
        testCanvas.getContext("experimental-webgl");
      window.__liquidGLNoWebGL__ = !testCtx;
    }

    const noWebGL = window.__liquidGLNoWebGL__;

    if (noWebGL) {
      liquidGLLog(
        "warn",
        "liquidGL: WebGL not available – falling back to CSS backdrop-filter."
      );
      const fallbackNodes = document.querySelectorAll(options.target);
      fallbackNodes.forEach((node) => {
        Object.assign(node.style, {
          background: "transparent",
          backdropFilter: "none",
          webkitBackdropFilter: "none",
          boxShadow: "none",
        });
      });
      return fallbackNodes.length === 1
        ? fallbackNodes[0]
        : Array.from(fallbackNodes);
    }

    const rendererKey = options.rendererKey || "default";
    const rendererStore =
      window.__liquidGLRenderers__ || (window.__liquidGLRenderers__ = {});
    let renderer =
      rendererStore[rendererKey] ||
      (rendererKey === "default" ? window.__liquidGLRenderer__ : null);
    if (!renderer) {
      renderer = new liquidGLRenderer(options.snapshot, options.resolution, rendererKey, options);
    } else if (renderer.configureSource) {
      renderer.configureSource(options);
    }
    rendererStore[rendererKey] = renderer;
    if (rendererKey === "default") {
      window.__liquidGLRenderer__ = renderer;
    }

    const nodeList = document.querySelectorAll(options.target);
    if (!nodeList || nodeList.length === 0) {
      if (options.syncTargets && renderer.syncLenses) {
        renderer.syncLenses([], options);
        renderer.render();
      }
      liquidGLLog(
        "warn",
        `liquidGL: Target element(s) '${options.target}' not found.`
      );
      return;
    }

    const instances = options.syncTargets && renderer.syncLenses
      ? renderer.syncLenses(nodeList, options)
      : Array.from(nodeList).map((el) => renderer.addLens(el, options));
    liquidGLLog("log", "liquidGL: Renderer lenses registered.", {
      rendererKey,
      lensCount: renderer.lenses.length,
      lensClasses: renderer.lenses.map((lens) => lens.el && lens.el.className).filter(Boolean),
      hollowLensCount: renderer.lenses.filter((lens) => lens.hollowMaskContent).length,
      canvasClassName: renderer.canvas.className,
      canvasZIndex: window.getComputedStyle(renderer.canvas).zIndex
    });

    if (window.DebriPod && window.DebriPod.frameScheduler) {
      renderer.useExternalTicker = true;
      if (window.DebriPod.frameScheduler.mark) window.DebriPod.frameScheduler.mark({ render: true });
    }

    if (!renderer._rafId && !renderer.useExternalTicker) {
      const loop = () => {
        renderer.render();
        renderer._rafId = requestAnimationFrame(loop);
      };
      renderer._rafId = requestAnimationFrame(loop);
    }

    return instances.length === 1 ? instances[0] : instances;
  };

  window.liquidGL.resolveMaterial = resolveLiquidGlassMaterial;
  window.liquidGL.normalizeMaterial = normalizeLiquidGlassMaterial;
  window.liquidGL.easings = LIQUID_GL_EASINGS;
  window.liquidGL.testing = Object.freeze({
    Lens: liquidGLLens,
    Renderer: liquidGLRenderer,
    sourceTexelsPerCssPixel,
    lensMinorDimensionInSourceUV,
  });

  /* --------------------------------------------------
   *  Public helper: register elements that need live updates
   * ------------------------------------------------*/
  window.liquidGL.registerDynamic = function (elements) {
    const renderers = window.__liquidGLRenderers__ || {};
    const list = Object.keys(renderers).map((key) => renderers[key]).filter(Boolean);
    if (window.__liquidGLRenderer__ && list.indexOf(window.__liquidGLRenderer__) < 0) {
      list.push(window.__liquidGLRenderer__);
    }
    list.forEach((renderer) => {
      try {
        if (!renderer || !renderer.addDynamicElement) return;
        renderer.addDynamicElement(elements);
        if (renderer.captureSnapshot) renderer.captureSnapshot("registerDynamic");
      } catch (e) {
        liquidGLLog("warn", "liquidGL: registerDynamic failed for renderer.", e);
      }
    });
  };

  /* --------------------------------------------------
   *  Public helper: Universal smooth scroll / animation sync
   * ------------------------------------------------*/
  window.liquidGL.syncWith = function (config = {}) {
    const renderer = window.__liquidGLRenderer__;
    if (!renderer) {
      liquidGLLog(
        "warn",
        "liquidGL: Please initialize liquidGL *before* calling syncWith()."
      );
      return;
    }

    const G = window.gsap;
    const L = window.Lenis;
    const LS = window.LocomotiveScroll;
    const ST = G ? G.ScrollTrigger : null;

    let lenis = config.lenis;
    let loco = config.locomotiveScroll;
    const useGSAP = config.gsap !== false && G && ST;

    if (config.lenis !== false && L && !lenis) {
      lenis = new L();
    }

    if (
      config.locomotiveScroll !== false &&
      LS &&
      !loco &&
      document.querySelector("[data-scroll-container]")
    ) {
      loco = new LS({
        el: document.querySelector("[data-scroll-container]"),
        smooth: true,
      });
    }

    if (useGSAP && ST) {
      if (loco) {
        loco.on("scroll", ST.update);
        ST.scrollerProxy(loco.el, {
          scrollTop(value) {
            return arguments.length
              ? loco.scrollTo(value, { duration: 0, disableLerp: true })
              : loco.scroll.instance.scroll.y;
          },
          getBoundingClientRect() {
            return {
              top: 0,
              left: 0,
              width: window.innerWidth,
              height: window.innerHeight,
            };
          },
          pinType: loco.el.style.transform ? "transform" : "fixed",
        });
        ST.addEventListener("refresh", () => loco.update());
        ST.refresh();
      } else if (lenis) {
        lenis.on("scroll", ST.update);
      }
    }

    if (renderer._rafId) {
      cancelAnimationFrame(renderer._rafId);
      renderer._rafId = null;
    }
    renderer.useExternalTicker = true;

    if (useGSAP) {
      G.ticker.add((time) => {
        if (lenis) lenis.raf(time * 1000);
        renderer.render();
      });
      G.ticker.lagSmoothing(0);
    } else {
      const loop = (time) => {
        if (lenis) lenis.raf(time);
        if (loco) loco.update();
        renderer.render();
        renderer._rafId = requestAnimationFrame(loop);
      };
      renderer._rafId = requestAnimationFrame(loop);
    }

    return { lenis, locomotiveScroll: loco };
  };
})();
