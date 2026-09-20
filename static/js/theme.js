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

  const paint = (btn) => {
    const eff = effective();
    btn.setAttribute('aria-pressed', String(eff === 'dark'));
    btn.setAttribute('aria-label', eff === 'dark' ? 'Switch to light mode' : 'Switch to dark mode');
    btn.textContent = eff === 'dark' ? '☀' : '☾';
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
