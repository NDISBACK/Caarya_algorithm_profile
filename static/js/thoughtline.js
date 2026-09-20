/* A reasoning trace for the moment the report is being worked out.

   A glyph and a label breathe beside a live clock while the steps appear
   underneath; when the work lands the whole trace folds into a single settled
   line - "Thought for 1.4s".

   Two rules it holds to:
     - the steps are the ones `scoring.build_report` actually performs, in the
       order it performs them, so this is a window onto real work rather than a
       decorative spinner
     - the clock shows real elapsed time. If the server answers in 300ms it says
       so; nothing is padded to look harder than it was. */

const ThoughtLine = (() => {
  const el = (tag, attrs = {}, children = []) => {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = value;
      else node.setAttribute(key, value === true ? '' : value);
    }
    for (const child of [].concat(children)) if (child) node.append(child);
    return node;
  };

  const reduced = () => window.matchMedia
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* How long the trace is held open. It paces the animation only - never the
     request, which is sent immediately and usually answers in well under a
     second. The clock reports the real wait, and the settled line says the
     profile is ready rather than claiming this much computation happened. */
  const HOLD_MS = 9800;

  async function run({ host, label = 'Working it out', settledText = 'Ready',
                      steps = [], work, hold = HOLD_MS }) {
    const glyph = el('span', { class: 'thought-glyph', 'aria-hidden': 'true' });
    const title = el('span', { class: 'thought-label', text: label });
    const clock = el('span', { class: 'thought-clock', text: '0.0s' });
    const list = el('ol', { class: 'thought-steps' });

    const panel = el('div', { class: 'thought', role: 'status', 'aria-live': 'polite' }, [
      el('div', { class: 'thought-head' }, [glyph, title, clock]),
      list,
    ]);
    host.replaceChildren(panel);

    const began = performance.now();
    const elapsed = () => (performance.now() - began) / 1000;

    const ticking = setInterval(() => { clock.textContent = `${elapsed().toFixed(1)}s`; }, 100);

    const nodes = steps.map((step) => {
      const node = el('li', { class: 'thought-step' }, el('span', { text: step }));
      list.append(node);
      return node;
    });

    let cursor = 0;
    const advance = () => {
      if (cursor > 0) nodes[cursor - 1].classList.replace('is-active', 'is-done');
      if (cursor < nodes.length) nodes[cursor].classList.add('is-active');
      cursor += 1;
    };

    // Paced so the last step lands just before the trace settles, whatever the
    // number of steps.
    const cadence = Math.max(320, Math.floor(hold / (nodes.length + 1)));

    let stepping = null;
    if (reduced()) {
      nodes.forEach((node) => node.classList.add('is-done'));
    } else {
      advance();
      stepping = setInterval(() => {
        if (cursor >= nodes.length) { clearInterval(stepping); stepping = null; return; }
        advance();
      }, cadence);
    }

    let result;
    let failure = null;
    try {
      result = await work;
    } catch (error) {
      failure = error;
    }

    if (!reduced()) {
      const remaining = hold - (performance.now() - began);
      if (remaining > 0) await new Promise((resolve) => setTimeout(resolve, remaining));
    }

    clearInterval(ticking);
    if (stepping) clearInterval(stepping);
    nodes.forEach((node) => { node.classList.remove('is-active'); node.classList.add('is-done'); });

    if (failure) {
      panel.remove();
      throw failure;
    }

    // Settle: the trace folds away and the label crossfades.
    clock.remove();
    title.textContent = settledText;
    title.classList.add('is-settling');
    panel.classList.add('is-settled');
    if (!reduced()) await new Promise((resolve) => setTimeout(resolve, 420));

    return result;
  }

  return { run };
})();
