/*
 * liquidGL – Ultra-light glassmorphism for the web
 * -----------------------------------------------------------------------------
 *
 * Author: NaughtyDuk© – https://liquidgl.naughtyduk.com
 * Licence: MIT
 * Optical material adapted from medfa12/liquid-glass-react (MIT).
 * See static/vendor/liquid-glass/NOTICE.md for provenance and adaptations.
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

  const glassContact = { x: -100000, y: -100000, down: false, pointerDown: false, touchId: null, attached: false };
  function fsTime(frame) {
    return frame && Number.isFinite(frame.timestamp) ? frame.timestamp : performance.now();
  }
  function attachGlassContact() {
    if (glassContact.attached) return;
    glassContact.attached = true;
    const renderContact = () => {
      glassContact.down = glassContact.pointerDown || glassContact.touchId !== null;
      const renderers = window.__liquidGLRenderers__ || {};
      Object.values(renderers).forEach(renderer => renderer.requestRender());
    };
    const update = event => {
      if (glassContact.touchId === null) {
        if (Number.isFinite(event.clientX)) glassContact.x = event.clientX;
        if (Number.isFinite(event.clientY)) glassContact.y = event.clientY;
      }
      if (event.type === "pointerdown") glassContact.pointerDown = true;
      if (["pointerup", "pointercancel", "blur"].includes(event.type)) glassContact.pointerDown = false;
      if (event.type === "blur") glassContact.touchId = null;
      if (event.type === "pointermove" && !glassContact.down) return;
      renderContact();
    };
    const updateTouch = event => {
      const touches = Array.from(event.touches || []);
      const touch = touches.find(item => item.identifier === glassContact.touchId) || touches[0];
      if (touch) {
        glassContact.touchId = touch.identifier;
        glassContact.x = touch.clientX;
        glassContact.y = touch.clientY;
      } else {
        glassContact.touchId = null;
        glassContact.pointerDown = false;
      }
      renderContact();
    };
    // Controls inside a glass surface (the list rows and wheel hit regions)
    // are allowed to stop bubbling while they arbitrate a gesture.  Observe
    // the stream during capture so the optical contact state cannot miss the
    // press or release, including after a pointer is captured by the wheel.
    ["pointerdown", "pointermove", "pointerup", "pointercancel", "blur"].forEach(name =>
      window.addEventListener(name, update, { passive: true, capture: true }));
    // Native touch scrolling cancels Pointer Events, but the touch stream
    // continues until the finger lifts. Keep the contact glow for that stream.
    ["touchstart", "touchmove", "touchend", "touchcancel"].forEach(name =>
      window.addEventListener(name, updateTouch, { passive: true, capture: true }));
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
   *  Shared renderer (one per page)
   * ------------------------------------------------*/
  class liquidGLRenderer {
    constructor(snapshotSelector, snapshotResolution = 1.0, rendererKey = "default", sourceOptions = {}) {
      attachGlassContact();
      this.canvas = document.createElement("canvas");
      this.canvas.style.cssText = `position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:0;`;
      this.canvas.setAttribute("data-liquid-ignore", "");
      this.canvas.setAttribute("data-liquid-renderer", rendererKey || "default");
      document.body.appendChild(this.canvas);

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
      this._scrollUpdateCounter = 0;
      this.sourceType = sourceOptions.sourceType || "visualizerWebgl";
      this.sourceSelector = sourceOptions.sourceElement || sourceOptions.source || "#visualizerBg";
      this.sourceCssSelector = sourceOptions.sourceCssElement || sourceOptions.sourceCssSelector || null;
      this.sourceProvider = typeof sourceOptions.sourceProvider === "function" ? sourceOptions.sourceProvider : null;
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

      this._metricsDirty = true;
      this._snapshotRectPx = null;
      this._externalFrameState = null;
      this._dpr = Math.min(2, window.devicePixelRatio || 1);

      this._resizeCanvas();
      this._pendingReveal = [];
      this.refreshSourceTexture("init");

      /* --------------------------------------------------
       *  Dynamic media (video) support
       * ------------------------------------------------*/
      this.canvas.style.opacity = "0";

      this.useExternalTicker = false;
    }

    /* ----------------------------- */
    _initGL() {
      const isWebGL2 = typeof WebGL2RenderingContext !== "undefined" && this.gl instanceof WebGL2RenderingContext;
      const hasDerivatives = !!(this.gl && (isWebGL2 || this.gl.getExtension("OES_standard_derivatives")));
      this._hasStandardDerivatives = hasDerivatives;
      // Keep the existing WebGL1/shared-renderer architecture. Explicit LOD
      // enables upstream's mip blur without requiring a context per control.
      this._hasTextureLod = !!this.gl.getExtension("EXT_shader_texture_lod");
      const vsSource = `
        attribute vec2 a_position;
        varying vec2 v_uv;
        void main(){
          v_uv = (a_position + 1.0) * 0.5;
          gl_Position = vec4(a_position, 0.0, 1.0);
        }`;

      const fsSource = `${this._hasTextureLod ? "#extension GL_EXT_shader_texture_lod : enable\n#define DP_HAS_TEXTURE_LOD 1\n" : ""}${hasDerivatives ? `${isWebGL2 ? "" : "#extension GL_OES_standard_derivatives : enable\n"}#define DP_HAS_DERIVATIVES 1\n` : ""}
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
        uniform float u_frost;
        uniform float u_frostSamples;
        uniform float u_radius;
        uniform float u_cornerPower;
        uniform bool  u_specular;
        uniform float u_revealProgress;
        uniform int   u_revealType;
        uniform float u_tiltX;
        uniform float u_tiltY;
        uniform vec4 u_tiltProjection;
        uniform float u_magnify;
        uniform float u_hollowInset;
        uniform bool  u_hollowMaskContent;
        uniform float u_materialDensity;
        uniform float u_materialSign;
        uniform vec3  u_materialTone;
        uniform float u_specularPrimary;
        uniform float u_specularSecondary;
        uniform bool  u_useAlbumTransitionSource;
        uniform bool  u_debugAlbumSourceFlat;
        uniform bool  u_reactiveArtSource;
        uniform bool u_wallpaperSource;
        uniform sampler2D u_reactivePreviousTex;
        uniform float u_reactiveArtMix;
        uniform float u_reactivePreviousAngle;
        uniform vec2  u_reactiveViewport;
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
        uniform sampler2D u_opticalSource;
        uniform vec2 u_opticalSize;
        uniform bool u_prepareOpticalSource;
        uniform bool u_hasOpticalSource;
        uniform vec4 u_contact;
        uniform float u_scrollEdge;

        float udRoundBox( vec2 p, vec2 b, float r ) {
          vec2 q = abs(p) - b + r;
          vec2 outside = max(q, 0.0);
          // A superellipse above L2 has zero curvature at the straight-edge
          // join. Use the same power as the CSS surface; wheels remain L2.
          float power = max(2.0, u_cornerPower);
          vec2 unit = outside / max(r, 1.0);
          float corner = power > 2.01
            ? pow(pow(unit.x, power) + pow(unit.y, power), 1.0 / power) * max(r, 1.0)
            : length(outside);
          return corner + min(max(q.x, q.y), 0.0) - r;
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
          vec2 screen = centered * u_reactiveViewport;
          float c = cos(angle);
          float s = sin(angle);
          vec2 rotated = vec2(c * screen.x + s * screen.y, -s * screen.x + c * screen.y);
          return clamp(rotated / max(1.0, length(u_reactiveViewport)) + 0.5, 0.0, 1.0);
        }

        vec4 sampleBaseLiquidSource(vec2 uv) {
          if (u_wallpaperSource) {
            // Match the wallpaper element's centered object-fit:cover exactly.
            float viewAspect = u_reactiveViewport.x / max(1.0, u_reactiveViewport.y);
            float imageAspect = u_textureResolution.x / max(1.0, u_textureResolution.y);
            vec2 coverUV = uv;
            if (viewAspect > imageAspect) coverUV.y = (uv.y - 0.5) * imageAspect / viewAspect + 0.5;
            else coverUV.x = (uv.x - 0.5) * viewAspect / imageAspect + 0.5;
            vec4 color = texture2D(u_tex, clamp(coverUV, 0.0, 1.0));
            return vec4(color.rgb * color.a, 1.0);
          }
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

        // Adapted from liquid-glass-react's QuartzCore reconstruction. Shapes
        // remain DebriPod's DOM-aligned rounded rectangles and hollow wheel.
        float lensCurve(float t) {
          t = clamp(t, 0.0, 1.0);
          return sqrt(max(0.0, (2.0 - t) * t));
        }
        float refractLobe(float dist, float amount, float height) {
          return amount * (1.0 - lensCurve(-dist / max(height, 0.001)));
        }
        float shadowFalloff(float d, float invRadius) {
          float x = 4.0 * clamp(0.25 * d * invRadius + 0.5, 0.0, 1.0) - 2.0;
          float x2 = x * x;
          return (((0.002954 * x2 - 0.034460) * x2 + 0.168210) * x2 - 0.560550) * x + 0.5;
        }
        vec2 shapeNormal(vec2 p, vec2 b, float r) {
          vec2 q = abs(p) - b + r;
          vec2 outside = max(q, 0.0);
          if (dot(outside, outside) > 0.00001) {
            vec2 gradient = u_cornerPower > 2.01
              ? pow(outside / max(r, 1.0), vec2(u_cornerPower - 1.0)) : outside;
            return gradient / max(length(gradient), 0.0001) * sign(p);
          }
          // The nearest-edge normal jumps by 90 degrees on the rectangle's
          // medial diagonals. Blend only the interior gradients, reaching the
          // exact edge normal at the corner/straight-edge boundary.
          float band = max(0.001, min(max(r, 1.0), max(-q.x, -q.y)));
          float weight = smoothstep(-band, band, q.x - q.y);
          vec2 gradient = vec2(sign(p.x) * weight, sign(p.y) * (1.0 - weight));
          return gradient / max(length(gradient), 0.0001);
        }
        vec2 projectBackdrop(vec2 sourceUV) {
          if (u_tiltProjection.w < 0.5) return sourceUV;
          vec2 sourceCssSize = u_lensCssSize / max(u_bounds.zw, vec2(0.00001));
          vec2 q = (sourceUV - u_tiltProjection.xy) * sourceCssSize;
          float rx = radians(u_tiltX), ry = radians(u_tiltY);
          // CSS applies rotateY, then rotateX, then perspective to the plane.
          vec3 rotated = vec3(cos(ry) * q.x,
            cos(rx) * q.y + sin(rx) * sin(ry) * q.x,
            sin(rx) * q.y - cos(rx) * sin(ry) * q.x);
          float w = max(0.1, 1.0 - rotated.z / u_tiltProjection.z);
          return u_tiltProjection.xy + rotated.xy / w / sourceCssSize;
        }
        vec4 compositeOpticalLayers(vec4 base, vec2 uv) {
          // The same lower-glass and text layers are sampled at displaced UVs.
          // They are not baked into every pill's backdrop or uploaded per frame.
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
        vec4 opticalSample(vec2 uv, float radiusCss) {
          #ifdef DP_HAS_TEXTURE_LOD
            if (u_hasOpticalSource) {
              vec2 cssSize = u_textureResolution / max(u_sourceTexelsPerCssPixel, vec2(0.001));
              float radius = radiusCss * min(u_opticalSize.x / cssSize.x, u_opticalSize.y / cssSize.y);
              float lod = max(0.0, log2(max(1.0, radius < 2.0 ? radius * 0.5 + 1.0 : radius)));
              vec4 base = texture2DLodEXT(u_opticalSource, clamp(vec2(uv.x, 1.0 - uv.y), 0.0, 1.0), lod);
              return compositeOpticalLayers(base, uv);
            }
          #endif
          // Older GPUs: bounded kernel with a real exit, not masked reads.
          // Dispersive/bleed samples use the sharp fallback; only the face
          // evaluates this kernel, keeping reactive-art ALU work bounded.
          return sampleLiquidSource(uv);
        }
        vec4 frostedFace(vec2 uv, float radiusCss) {
          #ifdef DP_HAS_TEXTURE_LOD
            if (u_hasOpticalSource) return opticalSample(uv, radiusCss);
          #endif
          if (radiusCss <= 0.01 || u_frostSamples < 0.5) return sampleLiquidSource(uv);
          vec4 sum = vec4(0.0);
          float count = clamp(u_frostSamples, 1.0, 16.0);
          const int MAX_FROST_SAMPLES = 16;
          for (int i = 0; i < MAX_FROST_SAMPLES; ++i) {
            if (float(i) >= count) break;
            float angle = float(i) * 2.39996323;
            float reach = sqrt((float(i) + 0.5) / count) * radiusCss;
            vec2 offsetUv = vec2(cos(angle), sin(angle)) * reach * u_sourceTexelsPerCssPixel / u_textureResolution;
            sum += sampleLiquidSource(uv + offsetUv);
          }
          return sum / count;
        }
        vec3 gradeGlass(vec3 rgb) {
          // GLASS_RECIPE / GLASS_RECIPE_DARK from upstream glass.ts. Interpolate
          // from identity so the existing signed material's zero stays clear.
          float bias = u_materialSign < 0.0 ? 0.0813 : 0.235;
          vec3 grade = vec3(dot(rgb, vec3(0.921, -0.265, -0.027)),
                            dot(rgb, vec3(-0.079, 0.735, -0.027)),
                            dot(rgb, vec3(-0.079, -0.265, 0.973))) + bias;
          float recipe = smoothstep(0.0, 0.52, u_materialDensity);
          return mix(rgb, grade, recipe);
        }
        void main(){
          if (u_prepareOpticalSource) {
            gl_FragColor = sampleBaseLiquidSource(vec2(v_uv.x, 1.0 - v_uv.y));
            return;
          }
          vec2 localUV = (v_uv - 0.5) / u_magnify + 0.5;
          vec2 localMapped = u_bounds.xy + vec2(localUV.x, 1.0 - localUV.y) * u_bounds.zw;
          vec2 mapped = projectBackdrop(localMapped);
          if (u_debugAlbumSourceFlat) {
            gl_FragColor = sampleAlbumArtSource(mapped);
            return;
          }
          // Reject outside/hollow pixels BEFORE any optical sampling.
          vec2 p_px = (v_uv - 0.5) * u_resolution;
          vec2 b_px = 0.5 * u_resolution;
          float dmask = udRoundBox(p_px, b_px, u_radius);
          vec2 normal = shapeNormal(p_px, b_px, u_radius);
          float fallbackAA = max(0.75, 1.0 / max(1.0, u_devicePixelRatio));
          #ifdef DP_HAS_DERIVATIVES
            float edgeAA = max(fwidth(dmask), fallbackAA);
          #else
            float edgeAA = fallbackAA;
          #endif
          float inShape = 1.0 - smoothstep(-edgeAA, edgeAA, dmask);
          float opticalDistance = dmask;
          if (u_hollowInset > 0.0) {
            vec2 innerB = max(vec2(0.0), b_px - vec2(u_hollowInset));
            float innerRadius = max(0.0, u_radius - u_hollowInset);
            float innerD = udRoundBox(p_px, innerB, innerRadius);
            float innerShape = 1.0 - smoothstep(-edgeAA, edgeAA, innerD);
            inShape *= 1.0 - innerShape;
            if (-innerD > opticalDistance) {
              opticalDistance = -innerD;
              normal = -shapeNormal(p_px, innerB, innerRadius);
            }
          }
          if (inShape <= 0.0001) discard;
          float d = opticalDistance / max(0.5, u_devicePixelRatio);
          float insideCss = max(0.0, -d);
          float diffusion = u_revealType == 1 ? clamp(u_revealProgress, 0.0, 1.0) : 1.0;
          float dRefract = pow(diffusion, 0.55);
          float dBlur = pow(diffusion, 1.30);
          float dBody = pow(diffusion, 1.60);
          float press = u_contact.z;
          float scale = clamp(min(u_lensCssSize.x, u_lensCssSize.y) / 150.0, 0.35, 1.5);
          vec2 cssToUV = u_sourceTexelsPerCssPixel / u_textureResolution;
          vec2 direction = vec2(normal.x, -normal.y);
          float opticalStrength = clamp(u_refraction / 0.045, 0.0, 2.5);
          float inner = refractLobe(d, 4.0 * scale, 18.0 * scale) * opticalStrength * dRefract;
          float outer = refractLobe(d, -13.0 * scale, 10.0 * scale) * opticalStrength * dRefract;
          vec2 innerUV = projectBackdrop(localMapped + direction * inner * cssToUV);
          vec2 outerUV = projectBackdrop(localMapped + direction * outer * cssToUV);
          if (u_hollowInset > 0.0 && u_hollowMaskContent) {
            innerUV = mix(innerUV, mapped, smoothstep(0.01, 0.30, hollowInnerShapeAtTextureUV(innerUV)));
            outerUV = mix(outerUV, mapped, smoothstep(0.01, 0.30, hollowInnerShapeAtTextureUV(outerUV)));
          }
          // Blur rises into the body; the bevel stays optically sharp.
          float blur = u_frost * dBlur * (1.0 + 0.20 * press) * mix(0.18, 1.0, smoothstep(0.0, 20.0 * scale, insideCss));
          float edgeMask = u_scrollEdge * (1.0 - smoothstep(0.0, 22.0, min(v_uv.y, 1.0-v_uv.y) * u_lensCssSize.y));
          blur = max(blur, edgeMask * u_frost * 1.4);
          if (u_frostSamples < 0.5) blur = 0.0;
          vec4 face = frostedFace(innerUV, blur);
          float crossover = clamp((d + 30.0 * scale) / (30.0 * scale), 0.0, 1.0) * 0.65;
          face = mix(face, opticalSample(outerUV, blur), crossover);
          // Opposing spectral taps concentrate dispersion at the bevel.
          float dispersion = refractLobe(d, 3.0 * scale, 14.0 * scale) * dRefract;
          if (dispersion > 0.02) {
            vec2 chroma = direction * dispersion * cssToUV;
            vec3 acc = vec3(0.0);
            for (int i = 0; i < 3; ++i) {
              float w = 1.0 - float(i) / 3.0;
              vec3 tap = opticalSample(innerUV + chroma * w, blur).rgb;
              acc.r += tap.r * w;
              acc.g += tap.g * (1.0 - w);
            }
            for (int i = 0; i < 4; ++i) {
              float w = float(i) / 3.0;
              vec3 tap = opticalSample(innerUV - chroma * w, blur).rgb;
              acc.g += tap.g * (1.0 - w);
              acc.b += tap.b * w;
            }
            face.rgb = mix(face.rgb, acc * vec3(0.5, 1.0/3.0, 0.5), 0.75);
          }
          float bleedBand = 1.0 - smoothstep(0.0, 14.0 * scale, insideCss);
          float bleedMag = refractLobe(d, 24.0 * scale, 12.0 * scale);
          vec3 bleed = opticalSample(mapped + direction * bleedMag * cssToUV, max(blur, u_frost * 1.3)).rgb * 0.92;
          vec3 rgb = mix(face.rgb, bleed, bleedBand * mix(0.08, 0.15, u_materialDensity));
          // Ring shadow uses the difference of two analytic soft edges.
          float ring = shadowFalloff(insideCss * 0.70710678, 1.0 / (30.0 * scale))
                     - shadowFalloff((insideCss + 9.0 * scale) * 0.70710678, 1.0 / (30.0 * scale));
          rgb *= 1.0 - max(0.0, ring) * 0.30;
          rgb = gradeGlass(rgb);
          // Independent blur fill, with lighten/darken/normal contributions.
          if (u_materialDensity > 0.005 && u_frostSamples > 0.5) {
            vec3 fill = gradeGlass(opticalSample(mapped, u_frost * 1.7).rgb);
            vec3 mixed = 0.30 * max(rgb, fill) + 0.22 * min(rgb, fill) + 0.48 * rgb;
            rgb = mix(rgb, mix(mixed, fill, 0.15), min(1.0, u_materialDensity / 0.52));
          }
          // Local adaptive material tone uses a mip that already exists. No
          // readPixels, CPU reduction, or automatic changes to text settings.
          #ifdef DP_HAS_TEXTURE_LOD
            if (u_hasOpticalSource && u_materialDensity > 0.005) {
              vec3 average = texture2DLodEXT(u_opticalSource, vec2(0.5), log2(max(u_opticalSize.x, u_opticalSize.y))).rgb;
              float luma = dot(average, vec3(0.212646, 0.715332, 0.072205));
              float chameleon = 1.0 / (1.0 + exp(-10.25 * (luma - 0.5)));
              rgb += (0.5 - chameleon) * 0.04 * min(1.0, u_materialDensity / 0.52);
            }
          #endif
          // Preserve the signed slider's endpoints and its clear zero.
          float opaque = clamp((u_materialDensity - 0.52) / 0.48, 0.0, 1.0);
          rgb = mix(rgb, u_materialTone, opaque * dBody);
          if (u_specular) {
            // Keep testing3's 3D light response. The positive Z components
            // remain well defined as the phone's planar light crosses zero,
            // letting opposite rims fade through neutral without flipping.
            float outerPeak = 1.0 - smoothstep(0.0, 1.15, insideCss);
            float innerRim = 1.0 - smoothstep(0.5, 5.5, insideCss);
            float rimSlope = mix(0.58, 1.35, outerPeak);
            vec3 N = normalize(vec3(normal * rimSlope, 0.62));
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
            vec3 softRimColor = mix(vec3(1.0), face.rgb, 0.08);
            float heightMask = 1.0 - smoothstep(0.0, 70.0 * scale, insideCss);
            // Use a radial face normal to avoid the panel's medial diagonals.
            // The 3D light's XY projection fades smoothly through neutral;
            // normalizing it again in 2D would reintroduce the direction flip.
            vec2 faceGradient = p_px / max(b_px, vec2(1.0));
            vec2 faceNormal = faceGradient / max(length(faceGradient), 0.0001);
            vec2 faceFacing = vec2(dot(faceNormal, primaryLight.xy), dot(faceNormal, secondaryLight.xy));
            vec2 lobes = clamp((faceFacing - 0.55) / 0.45, 0.0, 1.0) * heightMask;
            vec2 key = lobes / (0.7 * (1.0 - lobes) + 1.0);
            vec2 contactPx = (v_uv - u_contact.xy) * u_lensCssSize;
            float contactLight = exp(-dot(contactPx, contactPx) / 3200.0) * press * 0.065;
            rgb += (sharp * vec3(1.0) + (soft + opposite) * softRimColor) * (1.0 + 0.45 * press) +
              vec3((key.x + key.y) * 0.035 + contactLight);
          }
          // SDR holding tone preserves hue at luminous rims.
          rgb = max(rgb, vec3(0.0));
          rgb /= max(1.0, max(rgb.r, max(rgb.g, rgb.b)));
          vec4 final = vec4(rgb, face.a * dBody);
          final.rgb *= final.a;
          final.rgb *= inShape;
          final.a *= inShape;
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
        opticalSource: gl.getUniformLocation(this.program, "u_opticalSource"),
        opticalSize: gl.getUniformLocation(this.program, "u_opticalSize"),
        prepareOpticalSource: gl.getUniformLocation(this.program, "u_prepareOpticalSource"),
        hasOpticalSource: gl.getUniformLocation(this.program, "u_hasOpticalSource"),
        contact: gl.getUniformLocation(this.program, "u_contact"),
        scrollEdge: gl.getUniformLocation(this.program, "u_scrollEdge"),
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
        frost: gl.getUniformLocation(this.program, "u_frost"),
        frostSamples: gl.getUniformLocation(this.program, "u_frostSamples"),
        radius: gl.getUniformLocation(this.program, "u_radius"),
        cornerPower: gl.getUniformLocation(this.program, "u_cornerPower"),
        specular: gl.getUniformLocation(this.program, "u_specular"),
        revealProgress: gl.getUniformLocation(this.program, "u_revealProgress"),
        revealType: gl.getUniformLocation(this.program, "u_revealType"),
        tiltX: gl.getUniformLocation(this.program, "u_tiltX"),
        tiltY: gl.getUniformLocation(this.program, "u_tiltY"),
        tiltProjection: gl.getUniformLocation(this.program, "u_tiltProjection"),
        magnify: gl.getUniformLocation(this.program, "u_magnify"),
        hollowInset: gl.getUniformLocation(this.program, "u_hollowInset"),
        hollowMaskContent: gl.getUniformLocation(this.program, "u_hollowMaskContent"),
        materialDensity: gl.getUniformLocation(this.program, "u_materialDensity"),
        materialSign: gl.getUniformLocation(this.program, "u_materialSign"),
        materialTone: gl.getUniformLocation(this.program, "u_materialTone"),
        specularPrimary: gl.getUniformLocation(this.program, "u_specularPrimary"),
        specularSecondary: gl.getUniformLocation(this.program, "u_specularSecondary"),
        useAlbumTransitionSource: gl.getUniformLocation(this.program, "u_useAlbumTransitionSource"),
        debugAlbumSourceFlat: gl.getUniformLocation(this.program, "u_debugAlbumSourceFlat"),
        reactiveArtSource: gl.getUniformLocation(this.program, "u_reactiveArtSource"),
        wallpaperSource: gl.getUniformLocation(this.program, "u_wallpaperSource"),
        reactivePreviousTex: gl.getUniformLocation(this.program, "u_reactivePreviousTex"),
        reactiveArtMix: gl.getUniformLocation(this.program, "u_reactiveArtMix"),
        reactivePreviousAngle: gl.getUniformLocation(this.program, "u_reactivePreviousAngle"),
        reactiveViewport: gl.getUniformLocation(this.program, "u_reactiveViewport"),
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

    _prepareOpticalBackdrop(frame) {
      const gl = this.gl;
      gl.uniform1i(this.u.hasOpticalSource, 0);
      gl.uniform2f(this.u.textureResolution, this.textureWidth, this.textureHeight);
      if (!this._hasTextureLod || this._opticalUnavailable) return;
      // Prepare the audio-reactive artwork once per renderer, then reuse it
      // for every lens and every blur/dispersion tap. No canvas uploads.
      const sourceRect = this._sourceCssRect || {width:window.innerWidth, height:window.innerHeight};
      const cap = Math.min(1024, gl.getParameter(gl.MAX_TEXTURE_SIZE));
      const pot = value => Math.min(cap, Math.pow(2, Math.ceil(Math.log2(Math.max(2, value)))));
      const scale = Math.min(1, this._dpr || 1, cap / Math.max(sourceRect.width, sourceRect.height, 1));
      const width = pot(sourceRect.width * scale), height = pot(sourceRect.height * scale);
      const fs = frame || {};
      const art = fs.artTransition || {};
      const signature = JSON.stringify([this._sourceUploadRevision, this.textureWidth, this.textureHeight,
        this._reactiveArtActive, this._albumMix, this._reactiveArtKey,
        this._reactiveArtActive ? [fs.angleRadians, fs.lumaLow, fs.lumaHigh, fs.fade, fs.active, fs.brightnessCap,
          fs.energy, fs.beat, fs.bands, fs.bandCenters, fs.bandWidths, fs.responseSettings,
          art.active, art.progress, art.fromKey, art.fromAngle, art.toAngle] : null, width, height,
        sourceRect.width, sourceRect.height, this._wallpaperActive]);
      try {
        gl.activeTexture(gl.TEXTURE6);
        // A sampler may not reference the texture attached to the framebuffer,
        // even when a uniform branch would skip that sample.
        gl.bindTexture(gl.TEXTURE_2D, this.texture);
        gl.uniform1i(this.u.opticalSource, 6);
        if (!this._opticalTexture) {
          this._opticalTexture = gl.createTexture();
          this._opticalFramebuffer = gl.createFramebuffer();
        }
        if (this._opticalWidth !== width || this._opticalHeight !== height) {
          gl.bindTexture(gl.TEXTURE_2D, this._opticalTexture);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
          gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, width, height, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
          gl.bindTexture(gl.TEXTURE_2D, this.texture);
          gl.bindFramebuffer(gl.FRAMEBUFFER, this._opticalFramebuffer);
          gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, this._opticalTexture, 0);
          if (gl.checkFramebufferStatus(gl.FRAMEBUFFER) !== gl.FRAMEBUFFER_COMPLETE) throw new Error("Optical framebuffer unavailable");
          this._opticalWidth = width;
          this._opticalHeight = height;
          this._opticalSignature = null;
        }
        if (signature !== this._opticalSignature) {
          gl.bindFramebuffer(gl.FRAMEBUFFER, this._opticalFramebuffer);
          gl.disable(gl.SCISSOR_TEST);
          gl.disable(gl.BLEND);
          gl.viewport(0, 0, width, height);
          gl.uniform1i(this.u.prepareOpticalSource, 1);
          gl.drawArrays(gl.TRIANGLES, 0, 6);
          gl.bindFramebuffer(gl.FRAMEBUFFER, null);
          gl.bindTexture(gl.TEXTURE_2D, this._opticalTexture);
          gl.generateMipmap(gl.TEXTURE_2D);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
          this._opticalSignature = signature;
          this._opticalPrepareCount = (this._opticalPrepareCount || 0) + 1;
        }
        gl.bindTexture(gl.TEXTURE_2D, this._opticalTexture);
        gl.uniform2f(this.u.opticalSize, width, height);
        gl.uniform1i(this.u.hasOpticalSource, 1);
      } catch (error) {
        this._opticalUnavailable = true;
        if (this._opticalTexture) gl.deleteTexture(this._opticalTexture);
        if (this._opticalFramebuffer) gl.deleteFramebuffer(this._opticalFramebuffer);
        this._opticalTexture = this._opticalFramebuffer = null;
        gl.bindTexture(gl.TEXTURE_2D, this.texture);
        liquidGLLog("warn", "liquidGL: using bounded optical blur fallback", error);
      } finally {
        gl.bindFramebuffer(gl.FRAMEBUFFER, null);
        gl.uniform1i(this.u.prepareOpticalSource, 0);
        gl.enable(gl.BLEND);
        gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
        gl.activeTexture(gl.TEXTURE0);
        gl.bindTexture(gl.TEXTURE_2D, this.texture);
      }
    }

    _lensContact(lens, now) {
      const rect = lens.rectPx;
      const state = lens._opticalContact || (lens._opticalContact = { press: 0, time: now, x: 0.5, y: 0.5 });
      const inside = rect && glassContact.x >= rect.left && glassContact.x <= rect.left + rect.width && glassContact.y >= rect.top && glassContact.y <= rect.top + rect.height;
      const target = inside && glassContact.down ? 1 : 0;
      if (inside) {
        state.x = (glassContact.x - rect.left) / Math.max(1, rect.width);
        state.y = 1 - (glassContact.y - rect.top) / Math.max(1, rect.height);
      }
      const reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      const elapsed = Math.max(1, Math.min(64, now - state.time));
      state.press += (target - state.press) * (reduced ? 1 : 1 - Math.exp(-elapsed / 55));
      state.time = now;
      if (Math.abs(target - state.press) < 0.005) state.press = target;
      else this.requestRender();
      return state;
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
        opticalBackend: this._hasTextureLod && !this._opticalUnavailable ? "shared-mip" : "bounded-kernel",
        opticalPrepareCount: this._opticalPrepareCount || 0,
        opticalTextureSize: [this._opticalWidth || 0, this._opticalHeight || 0],
        renderScale: this._dpr || 1,
        averageRenderSubmissionMs: this._renderSubmissionSamples && this._renderSubmissionSamples.length
          ? this._renderSubmissionTotalMs / this._renderSubmissionSamples.length
          : 0
      };
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
      if (this.u.debugAlbumSourceFlat) gl.uniform1i(this.u.debugAlbumSourceFlat, 0);
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
      if (this.u.wallpaperSource) gl.uniform1i(this.u.wallpaperSource, this._wallpaperActive ? 1 : 0);
      if (this.u.reactiveViewport) gl.uniform2f(this.u.reactiveViewport, window.innerWidth || 1, window.innerHeight || 1);
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
        this._wallpaperActive = !!(adapter && adapter.ready && adapter.wallpaper);
        if (adapter && adapter.ready && adapter.image) {
          const artKey = String(adapter.artKey || adapter.sourceRevision || adapter.image.currentSrc || adapter.image.src || "reactive-art");
          const sourceRect = adapter.sourceRect || { left: 0, top: 0, width: window.innerWidth || 1, height: window.innerHeight || 1 };
          this._reactiveArtActive = !this._wallpaperActive;
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
      this._sourceUploadRevision = (this._sourceUploadRevision || 0) + 1;
      this.textureWidth = width;
      this.textureHeight = height;
      this.scaleFactor = Number(options.scaleFactor) || 1;
      this._markSourceReadyAfterUpload(reason, { solidFallback: options.solidFallback === true });
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
        this.clear();
        return;
      }
      if (!this.texture) this.refreshSourceTexture("render fallback");
      if (!this.texture) {
        this.clear();
        return;
      }
      if (this.sourceType === "albumArtTransition" && !this._albumCurrentTexture) {
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
      this._prepareOpticalBackdrop(fs);

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
          if (lens._advanceTransition && lens._advanceTransition(transitionTime)) {
            hasActiveVisibleTransition = true;
          }
          this._renderLens(lens);
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
      if (!rect) {
        return;
      }
      if (!this.texture || !this.textureWidth || !this.textureHeight) {
        return;
      }
      if (!(rect.width > 0) || !(rect.height > 0)) {
        return;
      }
      if (this.sourceType === "albumArtTransition") {
        if (!this._albumCurrentTexture) {
          return;
        }
        if (!this._sourceCssRect || !(this._sourceCssRect.width > 0) || !(this._sourceCssRect.height > 0)) {
          return;
        }
      }

      let textPrepared = false;
      if(lens.el.id === "libListSelectedGlass" && textLayer){
        // A translucent reveal must not cut away fully visible native text.
        if(Number(getComputedStyle(lens.el).opacity) >= .995){
          const textSource = textLayer.prepare(rect,lens.radiusCss,true);
          if(textSource){this._bindUnderText(textSource);textPrepared=true;}
        }else textLayer.clear();
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
      if (this._sourceCssRect || (this.sourceType !== "albumArtCanvasOrImage" && this.sourceType !== "liveVideoFrame")) {
        const srcRect = this._sourceCssRect || { left: 0, top: 0, width: window.innerWidth || 1, height: window.innerHeight || 1 };
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
      gl.uniform1f(this.u.frost, Math.max(0, resolved.frostSigmaPx));
      gl.uniform1f(this.u.frostSamples, this._configuredFrostSamples());
      gl.uniform1f(this.u.radius, lens.radiusGl);
      gl.uniform1f(this.u.cornerPower, lens.cornerPower || 2);
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
      const tiltProjection = typeof lens.options.tiltProjection === "function"
        ? lens.options.tiltProjection() : null;
      gl.uniform4f(this.u.tiltProjection,
        tiltProjection ? (tiltProjection.x - (sourceCssRect.left || 0)) / Math.max(1, sourceCssRect.width) : 0,
        tiltProjection ? (tiltProjection.y - (sourceCssRect.top || 0)) / Math.max(1, sourceCssRect.height) : 0,
        tiltProjection ? tiltProjection.perspective : 900, tiltProjection ? 1 : 0);
      gl.uniform1f(this.u.hollowInset, lens.hollowInsetGl || 0);
      gl.uniform1i(this.u.hollowMaskContent, lens.hollowMaskContent ? 1 : 0);
      gl.uniform1f(this.u.materialDensity, resolved.density);
      gl.uniform1f(this.u.materialSign, resolved.side);
      gl.uniform3f(this.u.materialTone, resolved.tone[0], resolved.tone[1], resolved.tone[2]);
      gl.uniform1f(this.u.specularPrimary, resolved.specularPrimary);
      gl.uniform1f(this.u.specularSecondary, resolved.specularSecondary);
      const contact = this._lensContact(lens, fsTime(this._externalFrameState));
      gl.uniform4f(this.u.contact, contact.x, contact.y, contact.press, 0);
      gl.uniform1f(this.u.scrollEdge, lens.el.id === "libList" && lens.el.scrollTop > 0 ? 1 : 0);

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
      if(textPrepared) textLayer.commit();
      gl.disable(gl.SCISSOR_TEST);
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
      const hadShadow = !!this.options.shadow;
      Object.assign(this.options, patch || {});
      this.revealTypeIndex = this.options.reveal === "fade" ? 1 : 0;
      this.hollowMaskContent =
        !!this.options.hollowMaskContent ||
        this.el.hasAttribute("data-liquid-mask-content");
      if (Object.prototype.hasOwnProperty.call(patch || {}, "liveGeometry")) {
        this._syncDomRect = this.options.liveGeometry === true;
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
      const rect = suppliedRect || this.el.getBoundingClientRect();
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
      this.cornerPower = Number(style.getPropertyValue("--liquid-corner-power")) ||
        (/squircle|superellipse\(2\)/.test(style.getPropertyValue("corner-shape")) ? 4 : 2);
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
    }

    setShadow(enabled, strength) {
      this.options.shadow = !!enabled;
      const shadowStrength = clamp(finiteNumber(strength, 0.1), 0, 0.4);
      this._shadowStrength = shadowStrength;
      const shadowValue = this._shadowValue(shadowStrength);

      // The lens DOM element already owns the rounded shadow and follows
      // scrolling, clipping, transforms and visibility. A body-level clone
      // leaves stale rectangular ghosts when virtual rows are recycled.
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

    destroy() {
      this._transition = null;
      try {
        if (this._sizeObs) this._sizeObs.disconnect();
      } catch (e) {}
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
      magnify: 1,
      material: null,
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

  window.liquidGL.motion = window.LiquidGlassMotion;
  window.liquidGL.overlays = window.LiquidGlassOverlays;
})();
