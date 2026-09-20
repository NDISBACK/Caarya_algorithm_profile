/* Light/dark toggle. Purely presentational: it only ever sets data-theme
   on <html> and remembers the choice, the same override hook the
   stylesheet's dark-mode block already reads. Nothing here touches form
   state, scoring, or the profile draft. */

(() => {
  const KEY = 'caarya-theme';
  const root = document.documentElement;

  const stored = localStorage.getItem(KEY);
  if (stored === 'light' || stored === 'dark') root.setAttribute('data-theme', stored);

  const effective = () => {
    const attr = root.getAttribute('data-theme');
    if (attr === 'light' || attr === 'dark') return attr;
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  };

  // Inline SVG rather than the ☀ / ☾ text glyphs: those are drawn by whatever font the
  // system falls back to, so they sit off-centre, vary in weight, and can turn into emoji.
  const SUN = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4.2"/>'
    + '<path d="M12 2.5v2.3M12 19.2v2.3M2.5 12h2.3M19.2 12h2.3M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M18.7 5.3l-1.6 1.6M6.9 17.1l-1.6 1.6"/></svg>';
  const MOON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.5 14.2A8.6 8.6 0 0 1 9.8 3.5a8.6 8.6 0 1 0 10.7 10.7z"/></svg>';

  const paint = (btn) => {
    const eff = effective();
    btn.setAttribute('aria-pressed', String(eff === 'dark'));
    btn.setAttribute('aria-label', eff === 'dark' ? 'Switch to light mode' : 'Switch to dark mode');
    btn.innerHTML = eff === 'dark' ? SUN : MOON;
  };

  const wire = () => {
    const buttons = document.querySelectorAll('.theme-toggle');
    buttons.forEach((btn) => {
      paint(btn);
      btn.addEventListener('click', () => {
        const next = effective() === 'dark' ? 'light' : 'dark';
        localStorage.setItem(KEY, next);
        root.setAttribute('data-theme', next);
        buttons.forEach(paint);
      });
    });
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', wire);
  } else {
    wire();
  }
})();
