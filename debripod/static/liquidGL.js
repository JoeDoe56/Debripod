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
      liquidGLLog("error", "Shader error", gl.getShaderInfoLog(s));
      gl.deleteShader(s);
      return null;
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
      liquidGLLog("error", "Program link error", gl.getProgramInfoLog(p));
      return null;
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
        preserveDrawingBuffer: isMobileSafari,
      };
      this.gl =
        this.canvas.getContext("webgl2", ctxAttribs) ||
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
      this.renderCount = 0;
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
      const vsSource = `
        attribute vec2 a_position;
        varying vec2 v_uv;
        void main(){
          v_uv = (a_position + 1.0) * 0.5;
          gl_Position = vec4(a_position, 0.0, 1.0);
        }`;

      const fsSource = `
        precision mediump float;
        varying vec2 v_uv;
        uniform sampler2D u_tex;
        uniform sampler2D u_albumCurrentTex;
        uniform sampler2D u_albumNextTex;
        uniform vec2  u_resolution;
        uniform vec2  u_textureResolution;
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
        uniform int   u_glassMode;
        uniform float u_glassDarkAmount;
        uniform float u_glassLightAmount;
        uniform bool  u_useAlbumTransitionSource;
        uniform bool  u_debugAlbumSourceFlat;

        float udRoundBox( vec2 p, vec2 b, float r ) {
          return length(max(abs(p)-b+r,0.0))-r;
        }

        float random(vec2 st) {
          return fract(sin(dot(st.xy, vec2(12.9898,78.233))) * 43758.5453123);
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
          return 1.0 - smoothstep(-1.25, 1.25, innerD);
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
          return vec2(outUv.x, 1.0 - outUv.y);
        }

        vec4 sampleAlbumArtSource(vec2 sourceUV) {
          vec2 curUV = albumCoverUVFromSourceUV(sourceUV, u_albumSourceSize, u_albumCurrentSize);
          vec2 nextUV = albumCoverUVFromSourceUV(sourceUV, u_albumSourceSize, u_albumNextSize);
          curUV = clamp(curUV, vec2(0.0), vec2(1.0));
          nextUV = clamp(nextUV, vec2(0.0), vec2(1.0));
          vec4 cur = texture2D(u_albumCurrentTex, curUV);
          vec4 next = texture2D(u_albumNextTex, nextUV);
          vec4 col = mix(cur, next, clamp(u_albumMix, 0.0, 1.0));
          if (col.a < 0.01) {
            col.a = 1.0;
          }
          return col;
        }

        vec4 sampleLiquidSource(vec2 uv) {
          if (u_useAlbumTransitionSource) {
            return sampleAlbumArtSource(uv);
          }
          return texture2D(u_tex, uv);
        }

        void main(){
          if (u_debugAlbumSourceFlat) {
            vec4 albumCol = sampleAlbumArtSource(v_uv);
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
          vec2 offset = refractDirection * offsetAmt * centreBlend;

          float tiltRefractionScale = 0.05;
          vec2 tiltOffset = vec2(tan(radians(u_tiltY)), -tan(radians(u_tiltX))) * tiltRefractionScale;

          vec2 localUV = (v_uv - 0.5) / u_magnify + 0.5;
          vec2 flippedUV = vec2(localUV.x, 1.0 - localUV.y);
          vec2 mapped = u_bounds.xy + flippedUV * u_bounds.zw;
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

          if (u_frost > 0.0) {
              float radius = u_frost * 4.0;
              vec4 sum = vec4(0.0);
              const int SAMPLES = 16;

              for (int i = 0; i < SAMPLES; i++) {
                  float angle = random(v_uv + float(i)) * 6.283185;
                  float dist = sqrt(random(v_uv - float(i))) * radius;
                  vec2 offset = vec2(cos(angle), sin(angle)) * texel * dist;
                  sum += sampleLiquidSource(sampleUV + offset);
              }
              refrCol = sum / float(SAMPLES);
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
          float inShape = 1.0 - smoothstep(-1.25, 1.25, dmask);
          if (u_hollowInset > 0.0) {
            vec2 innerB = max(vec2(0.0), b_px - vec2(u_hollowInset));
            float innerRadius = max(0.0, u_radius - u_hollowInset);
            float innerD = udRoundBox(p_px, innerB, innerRadius);
            float innerShape = 1.0 - smoothstep(-1.25, 1.25, innerD);
            inShape *= (1.0 - innerShape);
          }
          if (inShape <= 0.001) discard;

          if (u_specular) {
            vec2 tilt = vec2(u_tiltY, -u_tiltX) * 0.010;
            vec2 lp1 = vec2(0.27, 0.20) + tilt;
            vec2 lp2 = vec2(0.72, 0.66) - tilt * 0.7;
            float h = 0.0;
            h += smoothstep(0.32,0.0,distance(v_uv, lp1))*0.18;
            h += smoothstep(0.44,0.0,distance(v_uv, lp2))*0.11;
            h += pow(edge, 2.2) * (0.11 + abs(u_tiltX + u_tiltY) * 0.012);
            final.rgb += h * vec3(1.0, 0.97, 0.90);
          }

          final.rgb = mix(final.rgb, vec3(0.0), clamp(u_glassDarkAmount, 0.0, 0.80));
          final.rgb = mix(final.rgb, vec3(1.0), clamp(u_glassLightAmount, 0.0, 0.80));

          if (u_revealType == 1) {
              final.rgb *= u_revealProgress;
              final.a  *= u_revealProgress;
          }

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
        albumCurrentTex: gl.getUniformLocation(this.program, "u_albumCurrentTex"),
        albumNextTex: gl.getUniformLocation(this.program, "u_albumNextTex"),
        res: gl.getUniformLocation(this.program, "u_resolution"),
        textureResolution: gl.getUniformLocation(
          this.program,
          "u_textureResolution"
        ),
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
        glassMode: gl.getUniformLocation(this.program, "u_glassMode"),
        glassDarkAmount: gl.getUniformLocation(this.program, "u_glassDarkAmount"),
        glassLightAmount: gl.getUniformLocation(this.program, "u_glassLightAmount"),
        useAlbumTransitionSource: gl.getUniformLocation(this.program, "u_useAlbumTransitionSource"),
        debugAlbumSourceFlat: gl.getUniformLocation(this.program, "u_debugAlbumSourceFlat"),
      };
    }

    /* ----------------------------- */
    _resizeCanvas() {
      const isMobileSafari = /iPad|iPhone|iPod/.test(navigator.userAgent);
      const dpr = Math.min(isMobileSafari ? 1.45 : 2, window.devicePixelRatio || 1);
      this._dpr = dpr;
      this.canvas.width = innerWidth * dpr;
      this.canvas.height = innerHeight * dpr;
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
        canaryEnabled: this._forceNpGlassCanary(),
        albumFlatDebugEnabled: this._debugNpAlbumSourceFlat(),
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
        renderCount: this.renderCount || 0
      };
    }

    _npOverlayDebugEnabled() {
      try {
        return this.rendererKey === "npOverlay" && (
          window.DEBRIPOD_UI_DEBUG === true ||
          window.DEBRIPOD_NP_OVERLAY_DEBUG === true ||
          (localStorage.getItem("debripod_ui_debug") || "") === "1" ||
          (localStorage.getItem("debripod_np_overlay_debug") || "") === "1"
        );
      } catch (e) {
        return false;
      }
    }

    _debugNpOverlaySkip(reason, details = {}) {
      if (!this._npOverlayDebugEnabled()) return;
      liquidGLLog("warn", "liquidGL: npOverlay render diagnostic", Object.assign({
        reason,
        rendererState: this.debugState ? this.debugState() : null
      }, details || {}));
    }

    _forceNpGlassCanary() {
      try {
        return this.rendererKey === "npOverlay" && (
          window.DEBRIPOD_FORCE_NP_GLASS_CANARY === true ||
          (localStorage.getItem("debripod_force_np_glass_canary") || "") === "1"
        );
      } catch (e) {
        return false;
      }
    }

    _debugNpAlbumSourceFlat() {
      try {
        return this.rendererKey === "npOverlay" &&
          this.sourceType === "albumArtTransition" &&
          (localStorage.getItem("debripod_debug_np_album_source_flat") || "") === "1";
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
      if (this.u.debugAlbumSourceFlat) gl.uniform1i(this.u.debugAlbumSourceFlat, this._debugNpAlbumSourceFlat() ? 1 : 0);
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

    refreshSourceTexture(reason = "") {
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
      const provider = typeof this.sourceProvider === "function"
        ? this.sourceProvider
        : (window.DebriPod && window.DebriPod.albumArtTexture && typeof window.DebriPod.albumArtTexture.sourceForLiquidGL === "function"
          ? window.DebriPod.albumArtTexture.sourceForLiquidGL
          : null);
      const adapter = provider ? provider() : null;
      if (!adapter || !adapter.ready || !adapter.currentImage) return false;
      const sourceRect = this._resolveSourceCssRect ? this._resolveSourceCssRect() : null;
      if (!sourceRect || !(sourceRect.width > 0) || !(sourceRect.height > 0)) {
        liquidGLLog("warn", "liquidGL: npOverlay albumArtTransition source rect missing", this.debugState ? this.debugState() : {});
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
        liquidGLLog("warn", "liquidGL: npOverlay albumArtTransition source not drawable", this.debugState ? this.debugState() : {});
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
          existing.options = Object.assign({}, existing.options || {}, options || {});
        }
        if (!existing) {
          this.addLens(el, options);
        }
      });
      this._metricsDirty = true;
      return this.lenses.filter((lens) => wanted.has(lens.el));
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
      const gl = this.gl;
      if (!this.visible || document.hidden) {
        if (!this.visible) this._debugNpOverlaySkip("render skipped: renderer not visible");
        this.clear();
        return;
      }
      if (!this.texture) this.refreshSourceTexture("render fallback");
      if (!this.texture && this._forceNpGlassCanary()) {
        const canary = this._ensureDebugCanaryTexture();
        if (canary) {
          this.texture = canary;
          this.textureWidth = 2;
          this.textureHeight = 2;
          this._sourceTextureReady = true;
        }
      }
      if (!this.texture) {
        this._debugNpOverlaySkip("render skipped: missing texture");
        return;
      }
      if (this.sourceType === "albumArtTransition" && !this._albumCurrentTexture && !this._forceNpGlassCanary()) {
        this._debugNpOverlaySkip("render skipped: albumArtTransition missing current texture");
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

      const time = Number.isFinite(fs.timestamp) ? fs.timestamp / 1000 : (Date.now() - this.startTime) / 1000;
      gl.uniform1f(this.u.time, time);

      if (this._metricsDirty || !this._snapshotRectPx) {
        this._snapshotRectPx = this.snapshotTarget.getBoundingClientRect();
        this.lenses.forEach((lens) => {
          lens.updateMetrics();
          if (lens._mirrorActive && lens._mirrorClipUpdater) {
            lens._mirrorClipUpdater();
          }
        });
        this._metricsDirty = false;
      }

      this.lenses.forEach((lens) => {
        if (this._lensVisible(lens)) {
          this._renderLens(lens);
        } else {
          this._debugNpOverlaySkip("lens skipped: not visible", {
            lensClassName: lens && lens.el ? lens.el.className : ""
          });
        }
      });

      this.lenses.forEach((ln) => {
        if (ln._mirrorActive && ln._mirrorCtx) {
          const mirror = ln._mirror;
          if (
            mirror.width !== this.canvas.width ||
            mirror.height !== this.canvas.height
          ) {
            mirror.width = this.canvas.width;
            mirror.height = this.canvas.height;
          }
          ln._mirrorCtx.drawImage(this.canvas, 0, 0);
        }
      });

      const dpr = this._dpr || Math.min(2, window.devicePixelRatio || 1);
      this.lenses.forEach((ln) => {
        if (ln._mirrorActive && ln.rectPx) {
          const { left, top, width, height } = ln.rectPx;
          const expand = 2;
          const x = Math.max(0, Math.round(left * dpr) - expand);
          const y = Math.max(
            0,
            Math.round(this.canvas.height - (top + height) * dpr) - expand
          );
          const w = Math.min(
            this.canvas.width - x,
            Math.round(width * dpr) + expand * 2
          );
          const h = Math.min(
            this.canvas.height - y,
            Math.round(height * dpr) + expand * 2
          );
          if (w > 0 && h > 0) {
            gl.enable(gl.SCISSOR_TEST);
            gl.scissor(x, y, w, h);
            gl.clearColor(0, 0, 0, 0);
            gl.clear(gl.COLOR_BUFFER_BIT);
            gl.disable(gl.SCISSOR_TEST);
          }
        }
      });
    }

    _lensVisible(lens) {
      try {
        if (!lens || !lens.el || !lens.el.isConnected) return false;
        const style = window.getComputedStyle(lens.el);
        if (style.display === "none" || style.visibility === "hidden") return false;
        let node = lens.el.parentElement;
        while (node && node !== document.body) {
          const parentStyle = window.getComputedStyle(node);
          if (
            parentStyle.display === "none" ||
            parentStyle.visibility === "hidden" ||
            Number(parentStyle.opacity || 1) <= 0.01 ||
            (node.classList &&
              (node.classList.contains("npPillHidden") ||
                node.classList.contains("npPillSwapHidden")))
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
      const forceCanary = this._forceNpGlassCanary();
      if (forceCanary && !this.texture) {
        const canary = this._ensureDebugCanaryTexture();
        if (canary) {
          this.texture = canary;
          this.textureWidth = 2;
          this.textureHeight = 2;
        }
      }
      if (!rect) {
        this._debugNpOverlaySkip("_renderLens skipped: missing rect");
        return;
      }
      if ((!this.texture || !this.textureWidth || !this.textureHeight) && !forceCanary) {
        this._debugNpOverlaySkip("_renderLens skipped: missing texture dimensions");
        return;
      }
      if (!(rect.width > 0) || !(rect.height > 0)) {
        this._debugNpOverlaySkip("_renderLens skipped: zero lens rect", { rect });
        return;
      }
      if (this.sourceType === "albumArtTransition" && !forceCanary) {
        if (!this._albumCurrentTexture) {
          this._debugNpOverlaySkip("_renderLens skipped: albumArtTransition missing current texture");
          return;
        }
        if (!this._sourceCssRect || !(this._sourceCssRect.width > 0) || !(this._sourceCssRect.height > 0)) {
          this._debugNpOverlaySkip("_renderLens skipped: albumArtTransition missing source rect");
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

      const x = (rect.left + overscrollX) * dpr;
      const y =
        this.canvas.height - (rect.top + overscrollY + rect.height) * dpr;
      const w = rect.width * dpr;
      const h = rect.height * dpr;

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
        this._debugNpOverlaySkip("_renderLens skipped: invalid bounds", {
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
      if (this.u.albumSourceSize) {
        const albumSourceSize = this._albumSourceSizeForUniform();
        gl.uniform2f(this.u.albumSourceSize, albumSourceSize.width, albumSourceSize.height);
      }
      gl.uniform1f(this.u.refraction, lens.options.refraction);
      gl.uniform1f(this.u.refractionFill, Number.isFinite(Number(lens.options.refractionFill)) ? Number(lens.options.refractionFill) : 0);
      gl.uniform1f(this.u.bevelDepth, lens.options.bevelDepth);
      gl.uniform1f(this.u.bevelWidth, lens.options.bevelWidth);
      gl.uniform1f(this.u.frost, Math.max(0, Number(lens.options.frost || 0) * (this._adaptiveQuality || 1)));
      gl.uniform1f(this.u.radius, lens.radiusGl);
      gl.uniform1i(this.u.specular, lens.options.specular ? 1 : 0);
      gl.uniform1f(this.u.revealProgress, lens._revealProgress || 1.0);
      gl.uniform1i(this.u.revealType, lens.revealTypeIndex || 0);

      const mag = Math.max(
        0.001,
        Math.min(
          3.0,
          lens.options.magnify !== undefined ? lens.options.magnify : 1.0
        )
      );
      gl.uniform1f(this.u.magnify, mag);

      gl.uniform1f(this.u.tiltX, lens.tiltX || 0);
      gl.uniform1f(this.u.tiltY, lens.tiltY || 0);
      gl.uniform1f(this.u.hollowInset, lens.hollowInsetGl || 0);
      gl.uniform1i(this.u.hollowMaskContent, lens.hollowMaskContent ? 1 : 0);
      gl.uniform1i(this.u.glassMode, lens.glassModeIndex || 0);
      gl.uniform1f(this.u.glassDarkAmount, Number.isFinite(Number(lens.options.glassDarkAmount)) ? Number(lens.options.glassDarkAmount) : 0.18);
      gl.uniform1f(this.u.glassLightAmount, Number.isFinite(Number(lens.options.glassLightAmount)) ? Number(lens.options.glassLightAmount) : 0.18);

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

      gl.drawArrays(gl.TRIANGLES, 0, 6);
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
      this.options = options;
      this._initCalled = false;
      this.rectPx = null;
      this.radiusGl = 0;
      this.radiusCss = 0;
      this.hollowInsetGl = 0;
      this.hollowMaskContent =
        !!this.options.hollowMaskContent ||
        this.el.hasAttribute("data-liquid-mask-content");
      this.glassModeIndex = this._glassModeIndex(this.options.glassMode);
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

      this.el.style.pointerEvents = "none";

      this.updateMetrics();
      this.setShadow(this.options.shadow);
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

    _glassModeIndex(mode) {
      const value = String(mode || "clear").toLowerCase();
      if (value === "dark") return 1;
      if (value === "light") return 2;
      return 0;
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
          (node !== this.el && parseFloat(style.opacity || "1") <= 0.01) ||
            (node.classList &&
            (node.classList.contains("npPillHidden") ||
              node.classList.contains("npPillSwapHidden")))
        ) {
          return true;
        }
        node = node.parentElement;
      }
      return false;
    }

    /* ----------------------------- */
    updateMetrics() {
      const rect =
        this._mirrorActive && this._baseRect
          ? this._baseRect
          : this.el.getBoundingClientRect();
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

      this.rectPx = {
        left: visibleRect.left,
        top: visibleRect.top,
        width: visibleRect.right - visibleRect.left,
        height: visibleRect.bottom - visibleRect.top,
      };

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
    setShadow(enabled) {
      this.options.shadow = !!enabled;

      const SHADOW_VAL =
        "0 10px 30px rgba(0,0,0,0.1), 0 0 0 0.5px rgba(0,0,0,0.05)";

      const syncShadow = () => {
        if (!this._shadowEl) return;
        const r =
          this._mirrorActive && this._baseRect
            ? this._baseRect
            : this.el.getBoundingClientRect();
        this._shadowEl.style.left = `${r.left}px`;
        this._shadowEl.style.top = `${r.top}px`;
        this._shadowEl.style.width = `${r.width}px`;
        this._shadowEl.style.height = `${r.height}px`;
        this._shadowEl.style.borderRadius = `${this.radiusCss}px`;
      };

      if (enabled) {
        this.el.style.boxShadow = SHADOW_VAL;

        if (!this._shadowEl) {
          this._shadowEl = document.createElement("div");
          Object.assign(this._shadowEl.style, {
            position: "fixed",
            pointerEvents: "none",
            zIndex: effectiveZ(this.el) - 2,
            boxShadow: SHADOW_VAL,
            willChange: "transform, width, height",
            opacity: this.revealTypeIndex === 1 ? 0 : 1,
          });
          document.body.appendChild(this._shadowEl);

          this._shadowSyncFn = syncShadow;
          window.addEventListener("resize", this._shadowSyncFn, {
            passive: true,
          });
        }
        syncShadow();
      } else {
        if (this._shadowEl) {
          window.removeEventListener("resize", this._shadowSyncFn);
          this._shadowEl.remove();
          this._shadowEl = null;
        }
        this.el.style.boxShadow = this.originalShadow;
      }
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

      this.el.addEventListener("mouseenter", this._onMouseEnter.bind(this), {
        passive: true,
      });
      this.el.addEventListener("mousemove", this._onMouseMove.bind(this), {
        passive: true,
      });
      this.el.addEventListener("touchstart", this._onTouchStart.bind(this), {
        passive: true,
      });
      this.el.addEventListener("touchmove", this._onTouchMove.bind(this), {
        passive: true,
      });
      this.el.addEventListener("touchend", this._onTouchEnd.bind(this), {
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
      this.el.removeEventListener("mouseenter", this._onMouseEnter.bind(this));
      this.el.removeEventListener("mousemove", this._onMouseMove.bind(this));
      document.removeEventListener("mousemove", this._boundCheckLeave);
      this.el.removeEventListener("touchstart", this._onTouchStart.bind(this));
      this.el.removeEventListener("touchmove", this._onTouchMove.bind(this));
      this.el.removeEventListener("touchend", this._onTouchEnd.bind(this));

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
        if (this._mirrorActive) {
          this._baseRect = this._baseRect || this.el.getBoundingClientRect();
        }
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
      glassMode: "clear",
      engine: "snapdom",
      sourceType: "visualizerWebgl",
      sourceElement: "#visualizerBg",
      on: {},
    };
    const options = { ...defaults, ...userOptions };

    if (typeof window.__liquidGLNoWebGL__ === "undefined") {
      const testCanvas = document.createElement("canvas");
      const testCtx =
        testCanvas.getContext("webgl2") ||
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
