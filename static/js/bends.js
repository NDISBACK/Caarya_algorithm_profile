/* The colour-bends background: flowing, bending bands of the brand palette,
   drawn on the GPU.

   Written as raw WebGL rather than pulling in a framework - the whole site is
   vanilla JS with no build step, and the effect is one fragment shader.

   It is built to be cheap, because the students using this are on mid-range
   phones:
     - renders at half resolution into a stretched canvas; the effect is soft
       enough that nobody can tell
     - capped at ~30fps, which the eye reads as smooth for something this soft
     - stops entirely when the tab is hidden
     - draws a single frame and stops under prefers-reduced-motion
     - falls back to the stylesheet's own background if WebGL is unavailable,
       so nothing is ever missing, just static */

(() => {
  const canvas = document.getElementById('bends-bg');
  if (!canvas) return;

  const gl = canvas.getContext('webgl', { antialias: false, alpha: false, depth: false,
                                          powerPreference: 'low-power' })
    || canvas.getContext('experimental-webgl');
  if (!gl) return;                        // the CSS background stays; nothing breaks

  canvas.classList.add('is-live');

  const VERTEX = `
    attribute vec2 aPos;
    void main() { gl_Position = vec4(aPos, 0.0, 1.0); }
  `;

  /* Two domain warps then a banded sine. Enough folding to look organic,
     few enough operations to stay cheap on an integrated GPU. */
  const FRAGMENT = `
    precision mediump float;
    uniform vec2  uResolution;
    uniform float uTime;
    uniform vec3  uBg;
    uniform vec3  uC1;
    uniform vec3  uC2;
    uniform vec3  uC3;
    uniform vec3  uC4;
    uniform float uStrength;
    uniform float uSpeed;

    void main() {
      vec2 uv = gl_FragCoord.xy / uResolution;
      vec2 p  = (uv - 0.5) * vec2(uResolution.x / uResolution.y, 1.0) * 2.6;
      float t = uTime * uSpeed;

      p += 0.55 * vec2(sin(p.y * 1.3 + t),        cos(p.x * 1.1 - t * 0.8));
      p += 0.28 * vec2(cos(p.y * 2.1 - t * 1.3),  sin(p.x * 1.9 + t * 0.9));

      float band = 0.5 + 0.5 * sin(p.x * 0.9 + p.y * 0.6 + t * 1.4);

      vec3 c = mix(uC1, uC2, smoothstep(0.00, 0.45, band));
      c      = mix(c,   uC3, smoothstep(0.35, 0.78, band));
      c      = mix(c,   uC4, smoothstep(0.70, 1.00, band));

      // Held close to the page background: this is a tint behind real content,
      // not a picture competing with it.
      c = mix(uBg, c, uStrength);

      // The content sits in a centred column, so the bands are calmed there and
      // left loud at the edges. That is what lets the palette stay saturated
      // without small text on the background dropping under 4.5:1.
      float column = 1.0 - smoothstep(0.08, 0.42, abs(uv.x - 0.5));
      c = mix(c, uBg, 0.62 * column);

      // A little extra calm towards the middle generally.
      c = mix(c, uBg, 0.12 * (1.0 - smoothstep(0.0, 0.8, length(uv - 0.5))));

      gl_FragColor = vec4(c, 1.0);
    }
  `;

  const compile = (type, source) => {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      console.warn('bends: shader failed', gl.getShaderInfoLog(shader));
      return null;
    }
    return shader;
  };

  const vertex = compile(gl.VERTEX_SHADER, VERTEX);
  const fragment = compile(gl.FRAGMENT_SHADER, FRAGMENT);
  if (!vertex || !fragment) return;

  const program = gl.createProgram();
  gl.attachShader(program, vertex);
  gl.attachShader(program, fragment);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return;
  gl.useProgram(program);

  // One triangle covering the screen - cheaper than a quad and no seam.
  const buffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const position = gl.getAttribLocation(program, 'aPos');
  gl.enableVertexAttribArray(position);
  gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);

  const uniform = (name) => gl.getUniformLocation(program, name);
  const uResolution = uniform('uResolution');
  const uTime = uniform('uTime');
  const uStrength = uniform('uStrength');
  const uSpeed = uniform('uSpeed');
  const colourUniforms = ['uBg', 'uC1', 'uC2', 'uC3', 'uC4'].map(uniform);

  /* ------------------------------------------------- palette from the CSS */

  const rgb = (value, fallback) => {
    const hex = (value || '').trim();
    const match = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex);
    if (!match) return fallback;
    let body = match[1];
    if (body.length === 3) body = body.split('').map((c) => c + c).join('');
    return [0, 2, 4].map((i) => parseInt(body.slice(i, i + 2), 16) / 255);
  };

  /* Read straight from the stylesheet, so the background follows the theme and
     any palette change without this file knowing the brand colours. */
  function applyPalette() {
    const style = getComputedStyle(document.documentElement);
    const tokens = ['--bend-bg', '--bend-1', '--bend-2', '--bend-3', '--bend-4'];
    const fallbacks = [[1, .97, .94], [.98, .86, .72], [.78, .28, 0], [.96, .74, .55], [1, .93, .86]];
    tokens.forEach((token, index) => {
      gl.uniform3fv(colourUniforms[index], rgb(style.getPropertyValue(token), fallbacks[index]));
    });
    gl.uniform1f(uStrength, parseFloat(style.getPropertyValue('--bend-strength')) || 0.5);
    gl.uniform1f(uSpeed, parseFloat(style.getPropertyValue('--bend-speed')) || 0.3);
  }

  /* ------------------------------------------------------------ the loop */

  const HALF = 0.5;                    // render scale; the effect is soft enough
  const FRAME_MS = 1000 / 30;

  function resize() {
    const width = Math.max(1, Math.floor(window.innerWidth * HALF));
    const height = Math.max(1, Math.floor(window.innerHeight * HALF));
    if (canvas.width === width && canvas.height === height) return;
    canvas.width = width;
    canvas.height = height;
    gl.viewport(0, 0, width, height);
    gl.uniform2f(uResolution, width, height);
  }

  const reduceMotion = window.matchMedia
    ? window.matchMedia('(prefers-reduced-motion: reduce)')
    : { matches: false, addEventListener: () => {} };

  let start = null;
  let last = 0;
  let frame = null;

  function draw(elapsed) {
    gl.uniform1f(uTime, elapsed);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }

  function tick(now) {
    frame = requestAnimationFrame(tick);
    if (now - last < FRAME_MS) return;
    last = now;
    if (start === null) start = now;
    draw((now - start) / 1000);
  }

  function play() {
    if (frame !== null) return;
    if (reduceMotion.matches || document.hidden) return;
    frame = requestAnimationFrame(tick);
  }

  function pause() {
    if (frame === null) return;
    cancelAnimationFrame(frame);
    frame = null;
  }

  function restart() {
    resize();
    applyPalette();
    if (reduceMotion.matches) { pause(); draw(12); return; }   // one settled frame
    play();
  }

  window.addEventListener('resize', () => { resize(); if (reduceMotion.matches) draw(12); },
                          { passive: true });
  document.addEventListener('visibilitychange', () => (document.hidden ? pause() : play()));
  if (reduceMotion.addEventListener) reduceMotion.addEventListener('change', restart);

  // theme.js flips data-theme on <html>; the palette has to follow it.
  new MutationObserver(applyPalette).observe(document.documentElement,
    { attributes: true, attributeFilter: ['data-theme'] });
  if (window.matchMedia) {
    const scheme = window.matchMedia('(prefers-color-scheme: dark)');
    if (scheme.addEventListener) scheme.addEventListener('change', () => setTimeout(applyPalette, 0));
  }

  restart();
})();
