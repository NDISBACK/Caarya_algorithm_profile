/* The profiling wizard.

   Five screens: your details, role, business services, value constructs, rate
   yourself. Everything else a company needs is collected on the report page
   afterwards, so nothing stands between a student and their result.

   The draft lives in localStorage so a refresh never costs them their answers. */

(() => {
  const { el } = Fields;
  const DRAFT_KEY = 'caarya.profile.draft.v2';

  const state = {
    stepIndex: 0,
    data: {},                                   // keyed by step id
    selections: { role_id: null, service_ids: [], vc_ids: [] },
    ratings: {},
    ratingSkills: [],                           // accumulated across rounds
    ratingRound: 0,
    ratingMaxRounds: 3,
    ratingDone: false,
    skillSetKey: null,                          // selections signature the skills were built for
  };

  const refreshJourney = () => {
    if (window.Journey && taxonomy) Journey.update(state, taxonomy);
  };

  /* Scrolling back to the top is part of the step change, not a separate
     event. The browser's own smooth scroll runs on its own clock and used to
     finish after the animation; jumping instead removed the drift but put a
     hard snap in its place. This tweens it over the same duration as the step
     animation, so the two read as one movement, and gets out of the way the
     moment the person touches the page themselves. */
  const STEP_MS = 520;          // leave .16s + 40ms gap + enter .32s
  let scrollFrame = null;

  function stopScrollTween() {
    if (scrollFrame !== null) cancelAnimationFrame(scrollFrame);
    scrollFrame = null;
    window.removeEventListener('wheel', stopScrollTween);
    window.removeEventListener('touchstart', stopScrollTween);
  }

  function tweenToTop(duration) {
    stopScrollTween();
    const from = window.scrollY;
    if (from <= 0) return;
    const started = performance.now();
    const ease = (x) => 1 - Math.pow(1 - x, 3);   // easeOutCubic, no overshoot
    window.addEventListener('wheel', stopScrollTween, { passive: true });
    window.addEventListener('touchstart', stopScrollTween, { passive: true });
    const frame = (now) => {
      const x = Math.min(1, (now - started) / duration);
      window.scrollTo(0, Math.round(from * (1 - ease(x))));
      if (x < 1) scrollFrame = requestAnimationFrame(frame);
      else stopScrollTween();
    };
    scrollFrame = requestAnimationFrame(frame);
  }

  let taxonomy = null;
  let schema = null;
  let lastRendered = null;      // which step index is currently on screen
  let heightTimer = null;
  let steps = [];                               // flattened core steps, each with .phase

  const dom = {
    boot: document.getElementById('boot'),
    steps: document.getElementById('steps'),
    rail: document.getElementById('rail'),
    back: document.getElementById('back'),
    next: document.getElementById('next'),
    reset: document.getElementById('reset'),
    fill: document.getElementById('progress-fill'),
    label: document.getElementById('progress-label'),
    saved: document.getElementById('saved-note'),
  };

  /* ------------------------------------------------------------- draft */

  const DRAFT_FIELDS = ['stepIndex', 'data', 'selections', 'ratings', 'ratingSkills',
                        'ratingRound', 'ratingMaxRounds', 'ratingDone', 'skillSetKey'];

  const saveDraft = () => {
    try {
      const draft = {};
      DRAFT_FIELDS.forEach((key) => { draft[key] = state[key]; });
      localStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
      dom.saved.textContent = 'Draft saved';
    } catch (error) {
      dom.saved.textContent = '';               // private mode or blocked storage
    }
  };

  const loadDraft = () => {
    try {
      const raw = localStorage.getItem(DRAFT_KEY);
      if (raw) Object.assign(state, JSON.parse(raw));
    } catch (error) {
      /* a corrupt draft should never block the form */
    }
  };

  let persistTimer = null;
  const persist = () => {
    clearTimeout(persistTimer);
    persistTimer = setTimeout(saveDraft, 250);
  };

  /* ------------------------------------------------------- step helpers */

  const stepData = (stepId) => (state.data[stepId] || (state.data[stepId] = {}));
  const current = () => steps[state.stepIndex];
  const selectionKey = () => JSON.stringify([
    state.selections.role_id, state.selections.service_ids, state.selections.vc_ids,
  ]);

  const servicesOfRole = (roleId) => {
    const role = taxonomy.roles.find((r) => r.id === roleId);
    return role ? role.business_services : [];
  };

  const chosenServices = () =>
    servicesOfRole(state.selections.role_id).filter((s) => state.selections.service_ids.includes(s.id));

  const resetRatings = () => {
    state.ratingSkills = [];
    state.ratingRound = 0;
    state.ratingDone = false;
    state.ratings = {};
    state.skillSetKey = null;
  };

  /* ----------------------------------------------------- choice screens */

  /* Choosing something repaints the cards' pressed state in place.

     These used to call render(), which rebuilt the whole step - and since the
     stylesheet gives every card a staggered entrance animation, that replayed
     on each click and read as the page reloading. Selecting should highlight,
     nothing more. */
  function paintChoices(wrap, isChosen, isDisabled) {
    wrap.querySelectorAll('.choice').forEach((card) => {
      const chosen = isChosen(card.dataset.id);
      card.setAttribute('aria-pressed', String(chosen));
      card.disabled = Boolean(isDisabled && isDisabled(card.dataset.id, chosen));
    });
  }

  function renderRole() {
    const wrap = el('div', { class: 'choices' });
    const paint = () => paintChoices(wrap, (id) => state.selections.role_id === id);
    taxonomy.roles.forEach((role) => {
      wrap.append(el('button', {
        type: 'button', class: 'choice', 'data-id': role.id,
        onclick: () => {
          if (state.selections.role_id !== role.id) {
            state.selections.role_id = role.id;
            state.selections.service_ids = [];
            state.selections.vc_ids = [];
            resetRatings();
          }
          paint();
          showErrors([]);
          refreshJourney();
          persist();
        },
      }, [
        el('h3', { text: role.name }),
        el('p', { text: role.tagline || '' }),
        el('div', { class: 'meta', text: `${role.business_services.length} areas of work · ${role.business_services.reduce((n, s) => n + s.value_constructs.length, 0)} things you could own` }),
      ]));
    });
    paint();
    return wrap;
  }

  function renderServices(step) {
    const services = servicesOfRole(state.selections.role_id);
    const wrap = el('div', { class: 'choices' });
    const max = step.max || 3;
    const paint = () => paintChoices(
      wrap,
      (id) => state.selections.service_ids.includes(id),
      (id, chosen) => !chosen && state.selections.service_ids.length >= max,
    );

    services.forEach((service) => {
      wrap.append(el('button', {
        type: 'button', class: 'choice', 'data-id': service.id,
        onclick: () => {
          const list = state.selections.service_ids;
          const index = list.indexOf(service.id);
          if (index >= 0) {
            list.splice(index, 1);
            // Dropping a service drops any of its value constructs too, or the
            // next step would score work the student can no longer see.
            const keep = new Set(services.filter((s) => list.includes(s.id))
              .flatMap((s) => s.value_constructs.map((vc) => vc.id)));
            state.selections.vc_ids = state.selections.vc_ids.filter((id) => keep.has(id));
          } else if (list.length < max) {
            list.push(service.id);
          }
          resetRatings();
          paint();
          showErrors([]);
          refreshJourney();
          persist();
        },
      }, [
        el('h3', { text: service.name }),
        el('p', { text: service.tagline || '' }),
        el('div', { class: 'meta', text: service.value_constructs.map((vc) => vc.name).join(' · ') }),
      ]));
    });
    paint();
    return wrap;
  }

  function renderValueConstructs() {
    const wrap = el('div');
    // One repaint across every group: the cards live in several grids but the
    // selection is a single list, and `chosen` must be read live rather than
    // captured when the card was built.
    const paint = () => paintChoices(wrap, (id) => state.selections.vc_ids.includes(id));

    chosenServices().forEach((service) => {
      wrap.append(el('div', { class: 'group-head', text: service.name }));
      const grid = el('div', { class: 'choices' });
      service.value_constructs.forEach((vc) => {
        const skills = [...vc.technical_skills, ...vc.transferable_skills]
          .map((id) => (taxonomy.skills[id] || {}).name).filter(Boolean);
        grid.append(el('button', {
          type: 'button', class: 'choice', 'data-id': vc.id,
          onclick: () => {
            const list = state.selections.vc_ids;
            const index = list.indexOf(vc.id);
            if (index >= 0) list.splice(index, 1);
            else list.push(vc.id);
            resetRatings();
            paint();
            showErrors([]);
            refreshJourney();
            persist();
          },
        }, [
          el('h3', { text: vc.name }),
          el('p', { text: vc.description || '' }),
          el('div', { class: 'meta', text: `Builds: ${[...new Set(skills)].join(', ')}` }),
        ]));
      });
      wrap.append(grid);
    });
    if (!chosenServices().length) {
      wrap.append(el('div', { class: 'card muted', text: 'Go back and choose a business service first.' }));
    }
    paint();
    return wrap;
  }

  /* ------------------------------------------------------------ ratings */

  function ratingRow(skill, scale) {
    const row = el('div', { class: 'rating-row', 'data-skill': skill.id });
    const scaleWrap = el('div', { class: 'scale' });
    scale.forEach((point) => {
      scaleWrap.append(el('button', {
        type: 'button', text: String(point.value), title: `${point.label} — ${point.hint}`,
        'aria-label': `${skill.name}: ${point.label}`,
        'aria-pressed': state.ratings[skill.id] === point.value,
        onclick: () => {
          state.ratings[skill.id] = point.value;
          scaleWrap.querySelectorAll('button').forEach((button, index) =>
            button.setAttribute('aria-pressed', scale[index].value === point.value));
          row.classList.remove('unanswered');
          refreshJourney();
          persist();
        },
      }));
    });
    row.append(el('div', {}, [
      el('div', { class: 'name', text: skill.name }),
      el('div', { class: 'hint', text: skill.hint || '' }),
    ]), scaleWrap);
    return row;
  }

  function renderRatings() {
    if (!state.ratingSkills.length) {
      return el('div', { class: 'card muted', text: 'Working out which skills to ask you about…' });
    }
    const scale = taxonomy.rating_scale;
    const wrap = el('div', {}, el('div', { class: 'scale-legend' },
      scale.map((point) => el('span', { html: `<b>${point.value}</b> ${point.label}` }))));

    const rounds = [...new Set(state.ratingSkills.map((skill) => skill.round))].sort();
    rounds.forEach((round) => {
      const skills = state.ratingSkills.filter((skill) => skill.round === round);
      if (round === 0) {
        [['Technical', 'technical'], ['Transferable', 'transferable']].forEach(([title, kind]) => {
          const list = skills.filter((skill) => skill.type === kind);
          if (!list.length) return;
          wrap.append(el('div', { class: 'group-head', text: `${title} — ${list.length} skills` }));
          wrap.append(el('div', { class: 'card' }, list.map((skill) => ratingRow(skill, scale))));
        });
      } else {
        wrap.append(el('div', { class: 'group-head', text: `A few more · round ${round}` }));
        wrap.append(el('div', { class: 'card' }, [
          el('p', { class: 'small muted', style: 'margin-bottom:6px',
            text: 'These sit outside what you picked. They\'re here so we can tell you if something else would suit you better.' }),
          ...skills.map((skill) => ratingRow(skill, scale)),
        ]));
      }
    });

    wrap.append(el('p', {
      class: 'small muted', style: 'margin-top:16px',
      text: state.ratingDone
        ? 'That\'s everything — your report is one click away.'
        : `After these we may ask up to ${state.ratingMaxRounds - state.ratingRound} more short round${state.ratingMaxRounds - state.ratingRound === 1 ? '' : 's'}, and fewer if your answers are already clear.`,
    }));
    return wrap;
  }

  /* -------------------------------------------------------------- flow */

  function renderFields(step) {
    const values = stepData(step.id);
    const ctx = {
      taxonomy,
      scopes: [],
      onChange: () => {
        ctx.scopes.forEach((scope) => Fields.applyConditions(scope));
        persist();
      },
    };
    return Fields.renderFieldsStep(step, values, ctx);
  }

  // direction: 'forward' | 'back' | undefined. When set, and a previous
  // step is already on screen, the outgoing step sinks back out of focus
  // while the new one swells forward to meet it (see the depth-carousel
  // keyframes in styles.css) instead of an instant swap.
  function render(direction) {
    const step = current();

    const head = el('div', { class: 'step-head' }, [
      el('div', { class: 'step-eyebrow', text: step.phase.name }),
      el('h1', { text: step.title || '' }),
      step.subtitle ? el('p', { text: step.subtitle }) : null,
    ]);

    let body;
    switch (step.kind) {
      case 'role': body = renderRole(); break;
      case 'business_services': body = renderServices(step); break;
      case 'value_constructs': body = renderValueConstructs(); break;
      // The tool stack is back in the main flow, so the wizard renders it again.
      // It writes straight into state.data.tool_stack, which is the shape the
      // evidence check and the database both already expect.
      case 'tool_stack': body = Fields.renderToolStack(taxonomy, stepData(step.id), persist); break;
      case 'ratings': body = renderRatings(); break;
      default: body = renderFields(step);
    }

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    // Ignore any step still mid-exit from a previous, rapid transition -
    // only the current, settled one should play the leave animation.
    const outgoing = dom.steps.querySelector('.step:not(.leaving)');
    const container = dom.steps;
    const previousHeight = container.offsetHeight;
    const movedStep = lastRendered !== state.stepIndex;
    lastRendered = state.stepIndex;
    const animating = Boolean(outgoing && direction && !reduceMotion);

    /* Only when the step actually changed - re-rendering in place (a new round
       of rating questions, say) must not yank you back to the top. Reduced
       motion gets the jump, which is the honest version of "no animation". */
    if (movedStep) {
      if (reduceMotion) window.scrollTo({ top: 0, behavior: 'auto' });
      else tweenToTop(STEP_MS);
    }
    // A class, not an id: two steps share the DOM during a transition, and a
    // duplicated id is invalid HTML that makes scoped #id lookups resolve to
    // the wrong element - which silently swallowed validation messages.
    const newStep = el('div', { class: 'step visible' }, [head, el('div', { class: 'step-errors' }), body]);

    // Re-rendering the same step shouldn't replay every entrance animation -
    // adding a round of questions should look like questions appearing, not
    // like the whole page reloading.
    if (!movedStep) newStep.classList.add('settled');

    if (animating) {
      const enterClass = direction === 'forward' ? 'enter-forward' : 'enter-back';
      const leaveClass = direction === 'forward' ? 'leave-forward' : 'leave-back';

      /* Pin the container to the height it already has. The outgoing step is
         about to become absolutely positioned, so without this the container
         collapses to the incoming step's height in a single frame - the jump
         happens underneath the animation, which is what makes it feel broken. */
      container.style.minHeight = `${previousHeight}px`;

      outgoing.classList.add('leaving', leaveClass);
      /* Removed on a timer rather than on animationend. animationend bubbles,
         so a descendant finishing its own animation used to remove the step
         early - and if the leave animation never ran at all, nothing removed
         it and the old step sat on top of the new one for good. A timer is
         the one thing that always fires. */
      setTimeout(() => outgoing.remove(), 180);
      newStep.classList.add(enterClass);
      container.appendChild(newStep);
      // Clear out any earlier step still fading from a previous click so
      // stray absolutely-positioned leftovers can't pile up underneath.
      container.querySelectorAll('.step.leaving').forEach((node) => {
        if (node !== outgoing) node.remove();
      });

      // Then ease from the old height to the new one, and let go afterwards so
      // later growth - another round of questions - isn't clamped.
      requestAnimationFrame(() => { container.style.minHeight = `${newStep.offsetHeight}px`; });
      clearTimeout(heightTimer);
      heightTimer = setTimeout(() => {
        container.style.minHeight = '';
        // .settled at the same time, not just the enter class off: the plain
        // `rise` rule matches any .step.visible that is not entering, leaving
        // or settled, so dropping the class on its own would make the step
        // fade in a second time after it had already arrived.
        newStep.classList.add('settled');
        newStep.classList.remove('enter-forward', 'enter-back');
        // Anything still marked as leaving by now is a leftover from a
        // rapid double-click; it can never come back, so drop it.
        container.querySelectorAll('.step.leaving').forEach((node) => node.remove());
      }, STEP_MS + 120);
    } else {
      container.replaceChildren(newStep);
      clearTimeout(heightTimer);
      container.style.minHeight = '';
    }

    dom.steps.hidden = false;
    dom.boot.hidden = true;

    dom.back.disabled = state.stepIndex === 0;
    const last = state.stepIndex === steps.length - 1;
    dom.next.textContent = last && state.ratingDone ? 'See my report' : 'Continue';
    dom.fill.style.width = `${(state.stepIndex / (steps.length - 1)) * 100}%`;
    dom.label.textContent = `${step.phase.name} · step ${state.stepIndex + 1} of ${steps.length}`;
    renderRail();
    refreshJourney();
  }

  function renderRail() {
    dom.rail.replaceChildren();
    const currentPhase = current().phase.id;
    const phases = schema.phases.filter((phase) => (phase.stage || 'core') === 'core');
    phases.forEach((phase, index) => {
      const phaseFirst = steps.findIndex((s) => s.phase.id === phase.id);
      const done = state.stepIndex > steps.map((s) => s.phase.id).lastIndexOf(phase.id);
      dom.rail.append(el('li', {
        class: `${phase.id === currentPhase ? 'active' : ''} ${done ? 'done' : ''}`,
        // Only the current stop is labelled on screen; the rest carry the
        // name in a tooltip and, via .rail-label, for screen readers.
        title: phase.name,
        onclick: () => { if (state.stepIndex > phaseFirst) { state.stepIndex = phaseFirst; render('back'); } },
        style: state.stepIndex > phaseFirst ? 'cursor:pointer' : '',
      }, [
        el('span', { class: 'dot', text: done ? '✓' : String(index + 1) }),
        el('span', { class: 'rail-label', text: phase.name }),
      ]));
    });
  }

  /* The live step: the last one that isn't mid-exit. */
  const currentStepNode = () => {
    const alive = dom.steps.querySelectorAll('.step:not(.leaving)');
    return alive[alive.length - 1] || null;
  };

  function showErrors(messages) {
    // Scoped to the step that is actually on screen: during a transition the
    // outgoing step is still in the DOM and owns a copy of every field.
    // Writing into it would show the student nothing.
    const slot = (currentStepNode() || document).querySelector('.step-errors');
    if (!slot) return;
    slot.replaceChildren();
    if (!messages.length) return;
    slot.append(el('div', { class: 'alert alert-error' }, [
      el('strong', { text: messages.length === 1 ? messages[0] : 'A few things need another look:' }),
      messages.length > 1 ? el('ul', {}, messages.map((message) => el('li', { text: message }))) : null,
    ]));
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function validateCurrent() {
    const step = current();

    if (step.kind === 'role') {
      return state.selections.role_id ? [] : ['Pick the kind of work you want to get paid for'];
    }
    if (step.kind === 'business_services') {
      return state.selections.service_ids.length >= (step.min || 1)
        ? [] : [`Choose at least ${step.min || 1}`];
    }
    if (step.kind === 'value_constructs') {
      const count = state.selections.vc_ids.length;
      return count >= (step.min || 3) ? [] : [`Choose at least ${step.min || 3} — you have ${count}`];
    }
    if (step.kind === 'ratings') {
      const missing = state.ratingSkills.filter((skill) => !state.ratings[skill.id]);
      document.querySelectorAll('.rating-row').forEach((row) =>
        row.classList.toggle('unanswered', missing.some((skill) => skill.id === row.dataset.skill)));
      if (missing.length) {
        const first = document.querySelector('.rating-row.unanswered');
        if (first) first.scrollIntoView({ behavior: 'smooth', block: 'center' });
        return [`${missing.length} skill${missing.length > 1 ? 's' : ''} still need a rating. Every one matters to the result.`];
      }
      return [];
    }
    const problems = Fields.validateStep(step, stepData(step.id));
    Fields.showErrors(currentStepNode() || dom.steps, problems);
    return problems.map((problem) => problem.message);
  }

  async function loadFirstRound() {
    const key = selectionKey();
    if (state.ratingSkills.length && state.skillSetKey === key) return;
    const result = await api.post('/api/skill-set', state.selections);
    state.ratingSkills = result.path.map((skill) => ({ ...skill, round: 0 }));
    state.ratingRound = 0;
    state.ratingDone = false;
    state.skillSetKey = key;
    // Drop anything rated under a previous set of choices, so a changed
    // selection can't leave a stale answer behind in the payload.
    const asked = new Set(state.ratingSkills.map((skill) => skill.id));
    Object.keys(state.ratings).forEach((id) => { if (!asked.has(id)) delete state.ratings[id]; });
    persist();
  }

  async function loadNextRound() {
    const result = await api.post('/api/skill-set/next', {
      selections: state.selections,
      ratings: state.ratings,
    });
    state.ratingRound = result.round;
    state.ratingMaxRounds = result.max_rounds;
    if (result.done || !result.skills.length) {
      state.ratingDone = true;
    } else {
      const known = new Set(state.ratingSkills.map((skill) => skill.id));
      state.ratingSkills.push(...result.skills
        .filter((skill) => !known.has(skill.id))
        .map((skill) => ({ ...skill, round: result.round })));
    }
    persist();
    return result;
  }

  async function next() {
    const problems = validateCurrent();
    if (problems.length) { showErrors(problems); return; }
    showErrors([]);

    const step = current();

    if (step.kind === 'ratings') {
      if (state.ratingDone) { await submit(); return; }
      dom.next.disabled = true;
      dom.next.textContent = 'Working out what to ask…';
      try {
        const result = await loadNextRound();
        render();
        if (result.done) showErrors([]);
      } catch (error) {
        // Rebuild first, then write the message into the fresh step: rendering
        // afterwards - as a finally block used to - threw the error away before
        // anyone could read it.
        render();
        showErrors([error.message]);
      } finally {
        dom.next.disabled = false;
      }
      return;
    }

    state.stepIndex += 1;
    persist();
    render('forward');

    if (current().kind === 'ratings') {
      try {
        await loadFirstRound();
      } catch (error) {
        showErrors([error.message]);
        return;
      }
      render();
    }
  }

  function back() {
    if (state.stepIndex === 0) return;
    state.stepIndex -= 1;
    showErrors([]);
    persist();
    render('back');
  }

  /* What scoring.build_report actually does, in the order it does it. Shown
     while the request is in flight so the wait is a window onto the work
     rather than a spinner. */
  const SCORING_STEPS = [
    'Reading your ratings',
    'Adjusting for how you rate compared with yourself',
    'Scoring each piece of work you picked',
    'Weighing technical against people skills',
    'Finding the weakest skill each piece of work depends on',
    'Working out how sure we can be of each score',
    'Estimating the areas we did not ask you about',
    'Comparing what you picked against the rest of the role',
    'Working out what is closest to within reach',
    'Drawing your skills map',
  ];

  async function submit() {
    dom.next.disabled = true;
    dom.next.textContent = 'Working it out…';

    const host = currentStepNode() || dom.steps;
    const body = el('div');
    host.replaceChildren(body);

    // The draft is dropped the moment the profile is safely stored, not when
    // the animation finishes - closing the tab mid-trace must not leave a
    // submitted profile sitting in the wizard. Cancelling the debounced save
    // first matters too, or it fires afterwards and writes the draft back.
    const request = api.post('/api/profile', {
      ...state.data,
      selections: state.selections,
      ratings: state.ratings,
    }).then((result) => {
      clearTimeout(persistTimer);
      localStorage.removeItem(DRAFT_KEY);
      return result;
    });

    try {
      const result = await ThoughtLine.run({
        host: body,
        label: 'Working out your profile',
        settledText: 'Your profile is ready',
        steps: SCORING_STEPS,
        work: request,
      });
      window.location.href = `/report/${result.profile_id}`;
    } catch (error) {
      render();
      showErrors(error.details && error.details.length ? error.details : [error.message]);
      dom.next.disabled = false;
      dom.next.textContent = 'See my report';
    }
  }

  /* -------------------------------------------------------------- boot */

  async function boot() {
    try {
      [taxonomy, schema] = await Promise.all([api.get('/api/taxonomy'), api.get('/api/profile-schema')]);
    } catch (error) {
      dom.boot.textContent = `Couldn't load the form: ${error.message}`;
      return;
    }

    /* Suggestions for the state and college boxes. Deliberately not awaited
       with the two above: if this one fails the form still works, those
       fields just stop suggesting. */
    api.get('/api/institutions')
      .then((data) => {
        Fields.setReference({ states: data.states || [], colleges: data.colleges || [] });
        // Only if the step on screen is actually showing one of those boxes,
        // so an unrelated step is never rebuilt under someone mid-answer.
        if (dom.steps.querySelector('.combo')) render();
      })
      .catch(() => {});

    steps = schema.phases
      .filter((phase) => (phase.stage || 'core') === 'core')
      .flatMap((phase) => phase.steps.map((step) => ({ ...step, phase })));

    if (window.Journey) Journey.mount('#map-slot');

    loadDraft();
    state.stepIndex = Math.min(state.stepIndex, steps.length - 1);

    dom.next.addEventListener('click', next);
    dom.back.addEventListener('click', back);
    dom.reset.addEventListener('click', () => {
      if (!confirm('Clear everything you have filled in so far?')) return;
      localStorage.removeItem(DRAFT_KEY);
      window.location.reload();
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) next();
    });

    render();
    if (current().kind === 'ratings') {
      loadFirstRound().then(render).catch((error) => showErrors([error.message]));
    }
  }

  boot();
})();
