/* The map of what you're building, filling in as you answer.

   A vertical spine: the role at the top, the areas of work you chose branching
   off it, the jobs under those, and a row of pips under each job - one per
   skill, brightening as you rate it. By the last step it is the same picture the
   report opens with, which is the point: the form visibly builds the result
   rather than just collecting answers.

   It is driven from wizard state, never from the DOM - `Journey.update(state,
   taxonomy)` is the whole interface. Below 1000px the same module renders a
   summary strip above the form instead, so there is one implementation rather
   than two that drift apart. */

const Journey = (() => {
  const el = (tag, attrs = {}, children = []) => {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = value;
      else if (key.startsWith('on')) node.addEventListener(key.slice(2).toLowerCase(), value);
      else node.setAttribute(key, value === true ? '' : value);
    }
    for (const child of [].concat(children)) if (child) node.append(child);
    return node;
  };

  let host = null;
  let expanded = false;          // only meaningful in the collapsed layout

  /* The same thresholds the report's skills map uses, so a pip here and a mark
     there mean the same thing. */
  const level = (rating) => (rating >= 4 ? 'high' : rating === 3 ? 'mid' : 'low');

  const findRole = (taxonomy, id) => (taxonomy.roles || []).find((r) => r.id === id);
  const servicesOf = (role) => (role && role.business_services) || [];

  function skillsOf(vc) {
    return [...(vc.technical_skills || []), ...(vc.transferable_skills || [])]
      .filter((id, index, all) => all.indexOf(id) === index);
  }

  /* ------------------------------------------------------------- the tree */

  function nodeRow(kind, label, extras = []) {
    return el('div', { class: `jn jn-${kind}` }, [
      el('span', { class: 'jn-mark', 'aria-hidden': 'true' }),
      el('span', { class: 'jn-label', text: label }),
      ...extras,
    ]);
  }

  function pips(vc, ratings) {
    const skills = skillsOf(vc);
    const row = el('span', { class: 'jn-pips' });
    skills.forEach((id) => {
      const rating = ratings[id];
      row.append(el('i', {
        class: `jn-pip ${rating ? `is-rated level-${level(rating)}` : ''}`,
        title: rating ? `${id}: ${rating} of 5` : `${id}: not rated yet`,
      }));
    });
    return row;
  }

  function tree(state, taxonomy) {
    const wrap = el('div', { class: 'journey-tree' });
    const role = findRole(taxonomy, state.selections.role_id);

    if (!role) {
      // Never an empty box: a dim placeholder says what is about to appear.
      wrap.append(nodeRow('placeholder', 'Your role appears here'));
      return wrap;
    }

    wrap.append(nodeRow('role', role.name));

    const chosenServices = servicesOf(role).filter((s) => state.selections.service_ids.includes(s.id));
    if (!chosenServices.length) {
      wrap.append(nodeRow('placeholder', 'Then the areas you choose'));
      return wrap;
    }

    chosenServices.forEach((service) => {
      wrap.append(nodeRow('service', service.name));
      const jobs = (service.value_constructs || [])
        .filter((vc) => state.selections.vc_ids.includes(vc.id));

      if (!jobs.length) {
        wrap.append(nodeRow('placeholder', 'Jobs you pick land here'));
        return;
      }
      jobs.forEach((vc) => {
        wrap.append(el('div', { class: 'jn jn-job' }, [
          el('span', { class: 'jn-mark', 'aria-hidden': 'true' }),
          el('span', { class: 'jn-label', text: vc.name }),
          pips(vc, state.ratings || {}),
        ]));
      });
    });

    return wrap;
  }

  /* -------------------------------------------------------------- counts */

  function tally(state, taxonomy) {
    const role = findRole(taxonomy, state.selections.role_id);
    const chosen = servicesOf(role).filter((s) => state.selections.service_ids.includes(s.id));
    const jobs = chosen.flatMap((s) => (s.value_constructs || [])
      .filter((vc) => state.selections.vc_ids.includes(vc.id)));

    const skills = new Set(jobs.flatMap(skillsOf));
    const rated = [...skills].filter((id) => (state.ratings || {})[id]).length;

    return {
      role: role ? role.name : null,
      areas: chosen.length,
      jobs: jobs.length,
      rated,
      total: skills.size,
    };
  }

  function summaryLine(counts) {
    if (!counts.role) return 'Nothing picked yet';
    const parts = [counts.role];
    if (counts.areas) parts.push(`${counts.areas} area${counts.areas > 1 ? 's' : ''}`);
    if (counts.jobs) parts.push(`${counts.jobs} job${counts.jobs > 1 ? 's' : ''}`);
    if (counts.total) parts.push(`${counts.rated}/${counts.total} rated`);
    return parts.join(' · ');
  }

  /* --------------------------------------------------------------- render */

  function update(state, taxonomy) {
    if (!host || !taxonomy) return;
    const counts = tally(state, taxonomy);

    const body = el('div', { class: `journey-body ${expanded ? 'is-open' : ''}` }, tree(state, taxonomy));

    // The header doubles as the collapsed summary: in the narrow layout it is
    // the whole thing, and tapping it opens the tree underneath.
    const header = el('button', {
      class: 'journey-head',
      type: 'button',
      'aria-expanded': String(expanded),
      onclick: () => { expanded = !expanded; update(state, taxonomy); },
    }, [
      el('span', { class: 'journey-title', text: 'Your map' }),
      el('span', { class: 'journey-summary', text: summaryLine(counts) }),
      el('span', { class: 'journey-chevron', 'aria-hidden': 'true', text: '▾' }),
    ]);

    const footer = counts.total
      ? el('div', { class: 'journey-foot' }, [
          el('span', { text: `${counts.rated} of ${counts.total} rated` }),
          el('span', { class: 'journey-bar' },
            el('i', { style: `width:${Math.round((counts.rated / counts.total) * 100)}%` })),
        ])
      : el('div', { class: 'journey-foot journey-foot-quiet' },
          el('span', { text: 'This fills in as you answer' }));

    host.replaceChildren(el('div', { class: 'journey' }, [header, body, footer]));
  }

  function mount(selector) {
    host = document.querySelector(selector);
    return Boolean(host);
  }

  return { mount, update };
})();

// A top-level `const` in a classic script lives in the global lexical scope, not
// on `window` - so the feature checks in wizard.js need this to be explicit.
window.Journey = Journey;
