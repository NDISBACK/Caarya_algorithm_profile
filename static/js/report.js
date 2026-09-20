/* Renders a stored profile two ways off the same report JSON: the student's own
   read of their result, and the denser snapshot a company sees.

   The report page also hosts the optional follow-up form. Filling it in feeds
   the evidence check, so the scores are recomputed and the confidence figures
   genuinely move - which is the honest reason to ask for it here rather than
   before the student has seen anything. */

(() => {
  const el = (tag, attrs = {}, children = []) => {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      // ARIA state attributes are strings: an empty aria-pressed reads as
      // invalid, and "false" is meaningfully different from absent.
      if (key.startsWith('aria-') && typeof value === 'boolean') {
        node.setAttribute(key, String(value));
        continue;
      }
      if (value === null || value === undefined || value === false) continue;
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = value;
      else if (key === 'html') node.innerHTML = value;
      else if (key.startsWith('on')) node.addEventListener(key.slice(2).toLowerCase(), value);
      else node.setAttribute(key, value === true ? '' : value);
    }
    for (const child of [].concat(children)) if (child) node.append(child);
    return node;
  };

  const section = (title, ...body) =>
    el('section', {}, [el('div', { class: 'section-title', text: title }), ...body.filter(Boolean)]);

  const card = (...children) => el('div', { class: 'card' }, children.filter(Boolean));

  const kv = (pairs) => el('div', { class: 'kv' },
    pairs.filter(([, value]) => value !== undefined && value !== null && value !== ''
      && !(Array.isArray(value) && !value.length))
      .map(([key, value]) => el('div', {}, [
        el('div', { class: 'k', text: key }),
        el('div', { class: 'v', text: Array.isArray(value) ? value.join(', ') : String(value) }),
      ])));

  const confidenceChip = (confidence) => {
    if (confidence === undefined || confidence === null) return null;
    const percent = Math.round(confidence * 100);
    const level = percent >= 70 ? 'strong' : percent >= 45 ? 'emerging' : 'stretch';
    return el('span', {
      class: `pill ${level}`, text: `${percent}% sure`,
      title: 'How much of this area you rated, how consistent your answers were, and whether your history backs them up.',
    });
  };

  /* An area with too little rated is shown as an empty track, never as a short
     red bar - a missing answer is not the same as a low score, and drawing it
     like one would invent a weakness the student never claimed. */
  const meter = (name, score, band, badges = [], opts = {}) => {
    const unscored = score === null || score === undefined;
    const marks = badges.filter(Boolean);
    if (unscored && !marks.length) marks.push(el('span', { class: 'pill neutral', text: 'Not enough rated' }));
    return el('div', { class: 'meter-row' }, [
      el('div', {}, [
        el('div', { class: 'meter-label' }, [document.createTextNode(name), ...marks]),
        el('div', { class: 'meter-track' }, [
          // Starts at zero and is filled by animateIn: the stylesheet already
          // transitions width, but a bar rendered at its final value has
          // nothing to transition from.
          unscored ? null : el('div', {
            class: `meter-fill ${band || 'gap'}`, style: 'width:0%',
            'data-target': `${Math.max(score, 2)}%`,
          }),
          // The tick is what turns a bare number into a judgement a student can
          // make for themselves: above the line is ready, below it isn't.
          opts.readyLine ? el('div', { class: 'meter-ready', title: 'Ready starts here' }) : null,
        ]),
      ]),
      el('div', { class: 'meter-score' }, [
        unscored
          ? el('div', { text: '—' })
          : el('div', { class: 'count', 'data-to': String(Math.round(score)), text: '0' }),
        opts.plain && !unscored ? el('div', { class: 'meter-plain', text: opts.plain }) : null,
      ]),
    ]);
  };

  const estimatedChip = (on) => (on ? el('span', {
    class: 'pill neutral', text: 'Estimated',
    title: "We didn't ask you about all of this - part of it is inferred from skills it shares with what you did rate.",
  }) : null);

  const skillList = (items, emptyText) => items.length
    ? el('ul', { class: 'list-plain' }, items.map((item) => el('li', {}, [
        el('span', { text: item.name }),
        el('span', { class: 'rate', text: `${item.rating}/5` }),
      ])))
    : el('p', { class: 'muted small', text: emptyText });

  const dateOf = (iso) => {
    if (!iso) return '';
    const date = new Date(iso);
    return Number.isNaN(date.getTime()) ? iso
      : date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
  };

  const WORK_STYLE_POLES = {
    direction: ['Wants clear structure', 'Self-directed'],
    collaboration: ['Prefers solo focus', 'Highly collaborative'],
    pace: ['Steady pace', 'Sprint-driven'],
    variety: ['Deep single focus', 'Juggles many threads'],
    feedback: ['Wants blunt feedback', 'Wants gentle feedback'],
    learning: ['Learns by reading', 'Learns by doing'],
  };

  const workStyleTags = (style) => Object.entries(style || {})
    .map(([key, value]) => {
      const poles = WORK_STYLE_POLES[key];
      if (!poles) return null;
      if (value >= 65) return poles[1];
      if (value <= 35) return poles[0];
      return null;
    })
    .filter(Boolean);

  /* ----------------------------------------------------- the skills map */

  /* Every skill behind the work they chose, drawn twice: a filled mark where
     they are and a ring where "ready" sits. The distance between the two is the
     point of the picture - a list of numbers would say the same thing and be
     read by nobody. */
  function skillMap(map) {
    if (!map || !map.groups || !map.groups.length) return null;
    const scale = map.scale || 5;
    const at = (value) => `${((value - 1) / (scale - 1)) * 100}%`;

    const legend = el('div', { class: 'map-legend' }, [
      el('span', {}, [el('i', { class: 'map-dot level-mid' }), document.createTextNode('where you are')]),
      el('span', {}, [el('i', { class: 'map-ring' }), document.createTextNode('what the work needs')]),
      el('span', {}, [el('i', { class: 'map-dot level-mid is-estimated' }), document.createTextNode("estimated — we didn't ask you")]),
    ]);

    const rows = (skills) => skills.map((skill) => el('div', {
      class: `map-row ${skill.met ? 'is-met' : 'is-short'}`,
    }, [
      el('div', { class: 'map-name' }, [
        document.createTextNode(skill.name),
        skill.type === 'transferable' ? el('span', { class: 'tiny muted', text: ' · people skill' }) : null,
      ]),
      el('div', { class: 'map-track' }, [
        skill.met ? null : el('span', {
          class: 'map-gap',
          style: `left:${at(skill.from)}; right:${100 - parseFloat(at(skill.to))}%`,
        }),
        // Coloured by the level itself, never by whether this particular job
        // happens to need it raised. A skill at 1 of 5 must not look healthy
        // just because something else is the bigger blocker here.
        el('span', {
          class: `map-dot level-${skill.from >= 4 ? 'high' : skill.from === 3 ? 'mid' : 'low'}`
            + (skill.estimated ? ' is-estimated' : ''),
          style: `left:${at(skill.from)}`,
          title: skill.estimated ? "Estimated - you weren't asked about this one" : `You rated this ${skill.from} of ${scale}`,
        }),
        el('span', { class: 'map-ring', style: `left:${at(skill.to)}`,
          title: `Ready needs about ${skill.to} of ${scale}` }),
      ]),
      el('div', { class: 'map-figures', text: skill.met ? `${skill.from}/${scale}` : `${skill.from} → ${skill.to}` }),
    ]));

    return section('Your skills, against what the work needs', card(
      el('p', { class: 'small muted', style: 'margin-bottom:4px' }, [
        document.createTextNode('Each skill behind the work you picked, plus what we suggested. '),
        el('strong', { text: 'The gap is the distance left to cover.' }),
      ]),
      legend,
      ...map.groups.flatMap((group) => [
        el('div', { class: 'group-head' }, [
          document.createTextNode(group.service_name),
          group.selected
            ? el('span', { class: 'pill chosen', text: 'you picked this' })
            : el('span', { class: 'pill neutral', text: 'suggested' }),
        ]),
        ...group.value_constructs.flatMap((vc) => [
          el('div', { class: 'map-vc' }, [
            el('strong', { text: vc.name }),
            el('span', { class: `pill ${vc.ready ? 'strong' : vc.band || 'gap'}`,
              text: vc.ready ? 'ready' : vc.summary || 'not yet' }),
          ]),
          el('div', { class: 'map-rows' }, rows(vc.skills)),
        ]),
      ]),
    ));
  }

  /* ---------------------------------------------------------- the grid */

  const GRID_ORDER = ['sweet_spot', 'stretch', 'hidden_strength', 'park_it'];

  function gridCard(grid) {
    const wrap = el('div', { class: 'quad' });
    GRID_ORDER.forEach((key) => {
      const entries = grid.boxes[key] || [];
      const label = grid.labels[key];
      wrap.append(el('div', { class: `quad-box ${key}` }, [
        el('div', { class: 'quad-title', text: label.title }),
        el('div', { class: 'quad-blurb', text: label.blurb }),
        entries.length
          ? el('ul', { class: 'quad-list' }, entries.map((entry) => el('li', {}, [
              el('span', {}, [
                document.createTextNode(entry.name),
                // An inferred score sitting in "hidden strength" with nothing to
                // mark it would read as a measurement. It isn't one.
                entry.estimated ? el('span', { class: 'tiny muted', text: ' · estimated' }) : null,
              ]),
              el('span', { class: 'rate', text: Math.round(entry.score) }),
            ])))
          : el('p', { class: 'tiny muted', style: 'margin-top:8px', text: 'Nothing here.' }),
      ]));
    });
    return wrap;
  }

  function effortRow(vc) {
    const effort = vc.effort || {};
    const detail = effort.points === 0
      ? 'Ready to start on this now.'
      : effort.skills && effort.skills.length
        ? `${effort.summary} away: ${effort.skills.map((s) => `${s.name} ${s.from}→${s.to}`).join(', ')}`
        : 'Not enough answers to say what would close the gap.';
    return el('div', { class: 'effort-row' }, [
      el('div', { class: 'meter-label' }, [
        document.createTextNode(vc.name),
        el('span', { class: `pill ${vc.band || 'gap'}`, text: `${Math.round(vc.readiness)}` }),
        estimatedChip(vc.estimated),
        vc.selected ? el('span', { class: 'pill chosen', text: 'Your pick' }) : null,
      ]),
      el('div', { class: 'small muted', text: detail }),
    ]);
  }

  /* ------------------------------------------------------ student view */

  /* -------------------------------------------------- plain-language bits */

  /* Plain word first, the Caarya term after it in small print. Shown once per
     section - repeating "(value construct)" on every row would be noise. */
  const term = (plain, formal) => el('span', {}, [
    document.createTextNode(plain),
    el('span', { class: 'term', text: ` ${formal}` }),
  ]);

  const READY_NOTE = 'Ready starts at 60 out of 100.';

  const GUESSED_NOTE = "We didn't ask you much about this area, so we worked it out from skills "
    + 'it shares with ones you did answer. Treat it as a hint, not a measurement.';

  function heroCard(profile) {
    const report = profile.report;
    const plain = report.plain || {};
    const student = profile.student;
    return el('div', { class: `hero ${report.verdict.code}` }, [
      el('div', { class: 'hero-who' }, [
        document.createTextNode([student.full_name, student.college].filter(Boolean).join(' · ')),
        el('span', { class: 'muted', text: `  Profile #${profile.profile_id} · ${dateOf(profile.created_at)}` }),
      ]),
      el('h1', { class: 'hero-line', text: plain.headline || report.verdict.headline }),
      plain.detail ? el('p', { class: 'hero-detail', text: plain.detail }) : null,
    ]);
  }

  function actionList(report) {
    const steps = report.next_steps || [];
    if (!steps.length) return null;
    const heading = { 1: 'Do this next', 2: 'Do these two things', 3: 'Do these three things' }[steps.length];
    return section(heading || 'Do this next', card(
      el('ol', { class: 'actions' }, steps.map((step) => el('li', {}, [
        el('div', { class: 'action-head' }, [
          el('span', { class: 'action-verb', text: step.kind === 'start' ? 'Start with' : 'Learn' }),
          el('strong', { text: step.title }),
          step.estimated ? el('span', {
            class: 'pill neutral', text: 'we guessed this', title: GUESSED_NOTE,
          }) : null,
        ]),
        el('div', { class: 'small muted', text: step.why }),
      ]))),
    ));
  }

  function standingList(report) {
    // Chosen areas first, then by score - a student wants to find their own
    // pick before comparing it to anything else.
    const ordered = [...report.services].sort((a, b) => {
      if (a.selected !== b.selected) return a.selected ? -1 : 1;
      return (b.fit === null ? -1 : b.fit) - (a.fit === null ? -1 : a.fit);
    });

    return section('Where you stand', card(
      el('p', { class: 'small muted', style: 'margin-bottom:14px' }, [
        term('Each area of work', '(business service)'),
        document.createTextNode(` in this role, scored out of 100 from your own ratings. ${READY_NOTE}`),
      ]),
      ...ordered.map((service) => meter(service.name, service.fit, service.band, [
        service.selected ? el('span', { class: 'pill chosen', text: 'you picked this' }) : null,
        service.estimated ? el('span', {
          class: 'pill neutral', text: 'we guessed this', title: GUESSED_NOTE,
        }) : null,
      ], { readyLine: true, plain: service.band_plain })),
    ));
  }

  function choicesCard(report) {
    return section('What you told us you want', card(
      el('h3', { text: report.role.name }),
      el('div', { class: 'group-head' }, [term('Areas of work you chose', '(business services)')]),
      el('div', { class: 'chips' },
        report.selected.services.map((s) => el('span', { class: 'pill chosen', text: s.name }))),
      el('div', { class: 'group-head' }, [term('Jobs you said you want to own', '(value constructs)')]),
      el('ul', { class: 'list-plain' },
        report.selected.value_constructs.map((vc) => el('li', {}, el('span', { text: vc.name })))),
    ));
  }

  const HOW_IT_WORKS = [
    'Your 1–5 ratings become scores out of 100.',
    'We read each rating against your other answers, so being generous or hard on yourself throughout evens out.',
    'Each job scores 60% on its technical skills and 40% on its people skills.',
    'If one skill the job depends on is far weaker than the rest, it drags the score down instead of averaging away — you can\'t ship an API you can\'t build.',
    'Areas we asked you less about carry less weight, and are marked "we guessed this".',
    'Ready means 60 or more. That is where a company would expect you to start.',
  ];

  function detailDisclosure(report) {
    const verdict = report.verdict;
    return el('details', { class: 'disclosure' }, [
      el('summary', {}, [
        el('strong', { text: 'Show me the numbers' }),
        el('span', { class: 'small muted', text: 'the full reasoning, the scores behind it, and how it was worked out' }),
      ]),
      el('div', { class: 'disclosure-body' }, [
        el('div', { class: `verdict ${verdict.code}` }, [
          el('div', { class: 'tag-line', text: {
            aligned: 'Aligned', partial: 'Partly aligned', redirect: 'Worth reconsidering',
            early: 'Early days', insufficient: 'Incomplete',
          }[verdict.code] || '' }),
          el('h3', { text: verdict.headline }),
          ...verdict.reasoning.map((line) => el('p', { text: line })),
        ]),

        card(
          el('h3', {}, [term('What you want, against what you\'re ready for', '(interest × ability)')]),
          el('p', { class: 'small muted', style: 'margin:4px 0 14px', text:
            'Ready means 60 or more out of 100. Anything marked estimated is worked out from skills it shares with work you did rate.' }),
          gridCard(report.grid),
        ),

        card(
          el('h3', { text: 'How sure we are of each area' }),
          el('p', { class: 'small muted', style: 'margin:4px 0 12px', text:
            'Built from how much of the area you rated, whether you used the whole scale, and whether your projects back up what you claimed. We compare areas using the cautious end of each range, so answering confidently cannot by itself win you a recommendation.' }),
          ...report.services.filter((s) => s.fit !== null).map((service) =>
            meter(service.name, service.fit, service.band,
              [confidenceChip(service.confidence), estimatedChip(service.estimated)])),
        ),

        balanceCard(report),

        card(
          el('h3', { text: 'Every job in this role, and what would close the gap' }),
          ...report.recommended_value_constructs.map(effortRow),
        ),

        el('div', { class: 'grid', style: 'margin-top:16px' }, [
          card(el('h3', { text: 'Your strongest skills' }),
               el('div', { style: 'margin-top:10px' }, skillList(report.strengths, 'No ratings yet.'))),
          card(el('h3', { text: 'Biggest gaps in what you chose' }),
               el('div', { style: 'margin-top:10px' }, skillList(report.gaps, 'Nothing lagging — good place to be.'))),
        ]),

        card(
          el('h3', { text: 'How this was worked out' }),
          el('ul', { class: 'how-list' }, HOW_IT_WORKS.map((line) => el('li', { text: line }))),
        ),
      ]),
    ]);
  }

  /* ------------------------------------------------------ student view */

  function studentView(profile, ctx) {
    const report = profile.report;
    const nodes = [heroCard(profile)];

    nodes.push(actionList(report));
    nodes.push(standingList(report));
    nodes.push(skillMap(report.skill_map));
    nodes.push(choicesCard(report));
    nodes.push(el('section', {}, detailDisclosure(report)));
    nodes.push(followupSection(profile, ctx));

    if (profile.details_complete) {
      nodes.push(section('What the world wants', card(kv([
        ['Industries', profile.world.industries],
        ['Causes', profile.world.causes],
        ['Organisation type', profile.world.company_stage],
        ['Team size', profile.world.team_size],
        ['Rather avoid', profile.world.avoid],
      ]))));

      const motivation = profile.motivation || {};
      if (motivation.why_this_role || motivation.what_to_learn || motivation.proudest_work) {
        nodes.push(section('In your own words', card(
          quote('Why this kind of work', motivation.why_this_role),
          quote('What you want to learn next', motivation.what_to_learn),
          quote("What you're proudest of", motivation.proudest_work),
        )));
      }

      nodes.push(...evidenceSections(profile));

      nodes.push(section('How you like to work', card(
        el('div', { class: 'chips' }, workStyleTags(profile.work_style).map((tag) => el('span', { class: 'pill neutral', text: tag }))),
        el('div', { style: 'margin-top:16px' }, kv([
          ['Open to', profile.availability.engagement_types],
          ['Hours per week', profile.availability.hours_per_week],
          ['Earliest start', dateOf(profile.availability.earliest_start)],
          ['Commitment', profile.availability.commitment_duration],
          ['Notice needed', profile.availability.notice_period],
          ['Unavailable', profile.availability.unavailable_periods],
          ['Work mode', profile.location.work_mode],
          ['Relocation', profile.location.relocate],
          ['Compensation', profile.location.stipend_expectation],
        ])),
      )));
    }

    return nodes.filter(Boolean);
  }


  const quote = (label, text) => (text ? el('div', { style: 'margin-bottom:16px' }, [
    el('div', { class: 'k', text: label }),
    el('p', { style: 'margin-top:4px', text }),
  ]) : null);

  function linkRow(portfolio) {
    const links = Object.entries(portfolio || {})
      .filter(([, value]) => typeof value === 'string' && value.startsWith('http'));
    if (!links.length) return null;
    return el('div', { class: 'chips', style: 'margin-top:14px' },
      links.map(([key, href]) => el('a', { class: 'chip', href, target: '_blank', rel: 'noopener', text: key })));
  }

  function balanceCard(report) {
    const balance = report.balance;
    if (balance.technical === null && balance.transferable === null) return null;
    return card(
      el('h3', { text: 'Technical vs transferable' }),
      el('p', { class: 'small muted', style: 'margin:4px 0 12px',
        text: 'Technical counts for more in the scores above, because it is the harder thing for a company to coach you through quickly.' }),
      meter(`Technical (${balance.technical_count} rated)`, balance.technical, bandOf(balance.technical)),
      meter(`Transferable (${balance.transferable_count} rated)`, balance.transferable, bandOf(balance.transferable)),
    );
  }

  const bandOf = (score) => {
    if (score === null || score === undefined) return 'gap';
    if (score >= 75) return 'strong';
    if (score >= 60) return 'emerging';
    if (score >= 45) return 'stretch';
    return 'gap';
  };

  function evidenceSections(profile) {
    const nodes = [];
    const work = profile.experience.work || [];
    const projects = profile.experience.project || [];
    const competitions = profile.experience.competition || [];
    const leadership = profile.experience.leadership || [];

    if (work.length) {
      nodes.push(section('Experience', card(...work.map((entry) => el('div', { class: 'entry' }, [
        el('h3', { text: entry.title || 'Role' }),
        el('div', { class: 'where', text: [entry.organisation, entry.engagement_type].filter(Boolean).join(' · ') }),
        el('div', { class: 'when', text: [entry.start_date, entry.ongoing ? 'present' : entry.end_date].filter(Boolean).join(' – ') }),
        entry.description ? el('p', { text: entry.description }) : null,
        entry.tech && entry.tech.length ? el('div', { class: 'chips', style: 'margin-top:8px' },
          entry.tech.map((tech) => el('span', { class: 'pill neutral', text: tech }))) : null,
      ])))));
    }

    if (projects.length || competitions.length) {
      nodes.push(section('Projects & proof of work', card(
        ...projects.map((entry) => el('div', { class: 'entry' }, [
          el('h3', {}, [
            document.createTextNode(entry.title || entry.organisation || 'Project'),
            entry.link ? el('a', { href: entry.link, target: '_blank', rel: 'noopener', class: 'small', style: 'margin-left:8px', text: 'link' }) : null,
          ]),
          el('div', { class: 'when', text: [entry.status, entry.team].filter(Boolean).join(' · ') }),
          entry.description ? el('p', { text: entry.description }) : null,
          entry.your_role ? el('div', { class: 'small muted', style: 'margin-top:4px', text: `Built: ${entry.your_role}` }) : null,
          entry.tech && entry.tech.length ? el('div', { class: 'chips', style: 'margin-top:8px' },
            entry.tech.map((tech) => el('span', { class: 'pill neutral', text: tech }))) : null,
        ])),
        ...competitions.map((entry) => el('div', { class: 'entry' }, [
          el('h3', { text: entry.organisation || entry.title || 'Entry' }),
          el('div', { class: 'when', text: [entry.engagement_type, entry.start_date].filter(Boolean).join(' · ') }),
          entry.description ? el('p', { text: entry.description }) : null,
        ])),
      )));
    }

    if (leadership.length) {
      nodes.push(section('Leadership & activities', card(...leadership.map((entry) => el('div', { class: 'entry' }, [
        el('h3', { text: entry.organisation }),
        el('div', { class: 'where', text: [entry.title, entry.people_involved ? `with ${entry.people_involved}` : null].filter(Boolean).join(' · ') }),
        el('div', { class: 'when', text: entry.start_date || '' }),
        entry.description ? el('p', { text: entry.description }) : null,
      ])))));
    }

    const stack = Object.entries(profile.tool_stack || {}).filter(([, tools]) => tools && tools.length);
    const certs = profile.student.certifications || [];
    const languages = profile.student.languages || [];
    if (stack.length || certs.length || languages.length) {
      nodes.push(section('Stack, certifications & languages', card(
        ...stack.flatMap(([group, tools]) => [
          el('div', { class: 'group-head', text: group }),
          el('div', { class: 'chips' }, tools.map((tool) => el('span', { class: 'pill neutral', text: tool }))),
        ]),
        certs.length ? el('div', { class: 'group-head', text: 'Certifications' }) : null,
        certs.length ? el('ul', { class: 'list-plain' }, certs.map((cert) => el('li', {}, [
          el('span', { text: cert.name }),
          el('span', { class: 'rate', text: [cert.issuer, cert.year].filter(Boolean).join(' · ') }),
        ]))) : null,
        languages.length ? el('div', { class: 'group-head', text: 'Languages' }) : null,
        languages.length ? el('div', { class: 'chips' }, languages.map((lang) =>
          el('span', { class: 'pill neutral', text: `${lang.language}${lang.fluency ? ` · ${lang.fluency}` : ''}` }))) : null,
      )));
    }

    return nodes;
  }

  /* ---------------------------------------------------- follow-up form */

  function followupSection(profile, ctx) {
    if (!ctx.schema) return null;          // locked admin view: not the student's to edit
    const phases = ctx.schema.phases.filter((phase) => (phase.stage || 'core') === 'followup');
    if (!phases.length) return null;

    // The confirmation has to survive the repaint that follows a save - writing
    // it to this node directly would land on a element that repaint has already
    // thrown away, and the student would see nothing happen.
    const status = el('div', { class: 'small muted', text: ctx.notice || '' });
    const body = el('div', { class: 'followup' });

    phases.forEach((phase) => {
      const contents = el('div', { class: 'followup-body', hidden: true });
      let built = false;

      const toggle = el('button', {
        type: 'button', class: 'followup-head',
        onclick: () => {
          if (!built) {
            phase.steps.forEach((step) => {
              contents.append(el('div', { class: 'group-head', text: step.title }));
              if (step.subtitle) contents.append(el('p', { class: 'small muted', style: 'margin-bottom:10px', text: step.subtitle }));
              contents.append(renderFollowupStep(step, ctx));
            });
            built = true;
          }
          contents.hidden = !contents.hidden;
          toggle.setAttribute('aria-expanded', String(!contents.hidden));
        },
        'aria-expanded': 'false',
      }, [
        el('div', {}, [
          el('strong', { text: phase.name }),
          el('div', { class: 'small muted', text: phase.blurb || '' }),
        ]),
        el('span', { class: 'followup-chevron', text: '+' }),
      ]);

      body.append(el('div', { class: 'followup-item' }, [toggle, contents]));
    });

    const save = el('button', {
      class: 'btn btn-primary', text: 'Save and update my report',
      onclick: async () => {
        save.disabled = true;
        save.textContent = 'Saving…';
        const before = profile.report.role_fit.confidence;
        try {
          const result = await api.patch(`/api/profile/${profile.profile_id}/details`, ctx.details);
          const after = result.report.role_fit.confidence;
          const fresh = await api.get(`/api/profile/${profile.profile_id}`);
          Object.assign(profile, fresh);
          const moved = Math.round((after - before) * 100);
          ctx.notice = moved
            ? `Saved. Confidence in your scores moved ${moved > 0 ? 'up' : 'down'} ${Math.abs(moved)} points, now that we can check what you claimed against what you've built.`
            : 'Saved.';
          ctx.repaint();
        } catch (error) {
          // No repaint on failure - it would throw away everything they just typed.
          status.textContent = (error.details && error.details[0]) || error.message;
          save.disabled = false;
          save.textContent = 'Save and update my report';
        }
      },
    });

    return section(profile.details_complete ? 'Your profile details' : 'Complete your profile', card(
      el('p', { class: 'muted', text: profile.details_complete
        ? 'Already filled in. Open any section to change it — your scores are recomputed when you save.'
        : 'Your report is done. These are the things a company needs before it can act on it — and because we check what you claimed against what you\'ve built, filling them in replaces the assumption behind every confidence figure above with something real. It can move them up or down.' }),
      el('div', { style: 'margin-top:16px' }, body),
      el('div', { style: 'display:flex;gap:14px;align-items:center;margin-top:18px;flex-wrap:wrap' }, [save, status]),
    ));
  }

  function renderFollowupStep(step, ctx) {
    if (step.kind === 'tool_stack') {
      const values = ctx.details.tool_stack || (ctx.details.tool_stack = {});
      return Fields.renderToolStack(ctx.taxonomy, values, () => {});
    }
    const values = ctx.details[step.id] || (ctx.details[step.id] = {});
    const inner = { taxonomy: ctx.taxonomy, scopes: [], onChange: () => {
      inner.scopes.forEach((scope) => Fields.applyConditions(scope));
    } };
    return Fields.renderFieldsStep(step, values, inner);
  }

  /* ------------------------------------------------------ company view */

  const hasAvailability = (profile) => Boolean(
    profile.availability.hours_per_week
    || (profile.availability.engagement_types || []).length
    || profile.location.work_mode,
  );

  function companyView(profile) {
    const report = profile.report;
    const student = profile.student;
    const topVCs = [...report.value_constructs]
      .filter((vc) => vc.evidenced)
      .sort((a, b) => b.adjusted - a.adjusted)
      .slice(0, 6);

    const stack = Object.values(profile.tool_stack || {}).flat();
    const work = profile.experience.work || [];
    const projects = profile.experience.project || [];

    return [
      card(
        el('div', { class: 'report-header' }, [
          el('div', {}, [
            el('h1', { text: student.full_name }),
            el('p', { class: 'muted', text: [report.role.name, student.college].filter(Boolean).join(' · ') }),
          ]),
          el('div', { style: 'text-align:right' }, [
            report.role_fit.score === null
              ? el('div', { class: 'meter-score', text: '—' })
              : el('div', { class: 'meter-score' },
                  el('div', { class: 'count', 'data-to': String(Math.round(report.role_fit.score)), text: '0' })),
            el('span', { class: `pill ${report.role_fit.band || 'gap'}`, text: report.role_fit.band_label || 'Unscored' }),
            el('div', { style: 'margin-top:6px' }, confidenceChip(report.role_fit.confidence)),
          ]),
        ]),
        // Keyed off whether there is actually anything to match on, not whether
        // the student opened the section - a saved but empty availability block
        // would otherwise vanish silently and look like an oversight.
        hasAvailability(profile) ? el('div', { style: 'margin-top:18px' }, kv([
          ['Available', profile.availability.hours_per_week ? `${profile.availability.hours_per_week} hrs/week` : null],
          ['Open to', profile.availability.engagement_types],
          ['Starts', dateOf(profile.availability.earliest_start)],
          ['Commitment', profile.availability.commitment_duration],
          ['Work mode', profile.location.work_mode],
          ['Location', [student.city, student.state].filter(Boolean).join(', ')],
          ['Relocation', profile.location.relocate],
          ['Compensation', profile.location.stipend_expectation],
          ['Graduating', student.grad_year],
          ['Contact', student.email],
        ])) : el('div', { class: 'note-block', style: 'margin-top:16px' }, [
          el('strong', { text: 'Skills only so far.' }),
          el('p', { class: 'small', style: 'margin-top:4px',
            text: 'This student has completed the skills assessment but not the availability and location section — so there is nothing yet to match them on beyond the scores and evidence below.' }),
        ]),
        linkRow(student.portfolio),
      ),

      section('Where they sit', card(
        el('p', { class: 'small muted', style: 'margin-bottom:12px',
          text: 'What they chose to pursue, against what their ratings support.' }),
        gridCard(report.grid),
      )),

      section('Strongest value constructs', card(
        el('p', { class: 'small muted', style: 'margin-bottom:10px',
          text: 'Self-rated, weighted 60% technical / 40% transferable, with a hard gap in a must-have skill pulling the score down rather than averaging out. Ranked on the cautious figure.' }),
        ...topVCs.map((vc) => meter(vc.name, vc.readiness, vc.band, [
          estimatedChip(vc.estimated),
          confidenceChip(vc.confidence),
        ])),
      )),

      section('Area fit', card(...report.services.map((service) => meter(
        service.name, service.fit, service.band,
        [service.selected ? el('span', { class: 'pill chosen', text: 'Chose this' }) : null,
         estimatedChip(service.estimated)],
      )))),

      // Shown in the candidate's own second person on purpose - this is exactly
      // what they were told, so an interviewer and the student are reading the
      // same thing rather than two differently-worded versions of it.
      section('What we told the candidate', card(
        el('h3', { text: report.verdict.headline }),
        ...report.verdict.reasoning.map((line) => el('p', { class: 'muted', style: 'margin-top:8px', text: line })),
      )),

      report.flags.unevidenced_skills.length ? section('Worth asking about', el('div', { class: 'note-block' }, [
        el('strong', { text: 'Self-rated 4 or 5, but nothing in their history mentions it:' }),
        el('div', { class: 'chips', style: 'margin-top:8px' },
          report.flags.unevidenced_skills.map((skill) => el('span', { class: 'pill neutral', text: `${skill.name} (${skill.rating}/5)` }))),
        el('p', { class: 'tiny muted', style: 'margin-top:10px',
          text: 'Not a red flag on its own — coursework and reading leave no trace in a project list. Good interview questions.' }),
      ])) : null,

      report.flags.response_notes.length ? section('How to read these numbers', el('div', { class: 'note-block' }, [
        el('strong', { text: 'Their answering pattern:' }),
        el('ul', { style: 'margin:8px 0 0; padding-left:18px' },
          report.flags.response_notes.map((note) => el('li', { class: 'small', text: note }))),
        el('p', { class: 'tiny muted', style: 'margin-top:10px',
          text: 'Already reflected in the confidence figures above — noted here so you know why they are lower.' }),
      ])) : null,

      stack.length ? section('Stack', card(el('div', { class: 'chips' },
        stack.map((tool) => el('span', { class: 'pill neutral', text: tool }))))) : null,

      (work.length || projects.length) ? section('Evidence', card(
        ...work.slice(0, 3).map((entry) => el('div', { class: 'entry' }, [
          el('h3', { text: `${entry.title || 'Role'} · ${entry.organisation || ''}` }),
          entry.description ? el('p', { text: entry.description }) : null,
        ])),
        ...projects.slice(0, 3).map((entry) => el('div', { class: 'entry' }, [
          el('h3', {}, [
            document.createTextNode(entry.title || entry.organisation || 'Project'),
            entry.link ? el('a', { href: entry.link, target: '_blank', rel: 'noopener', class: 'small', style: 'margin-left:8px', text: 'link' }) : null,
          ]),
          entry.description ? el('p', { text: entry.description }) : null,
        ])),
      )) : null,

      profile.details_complete ? section('Working style', card(
        el('div', { class: 'chips' }, workStyleTags(profile.work_style).map((tag) => el('span', { class: 'pill neutral', text: tag }))),
        el('div', { style: 'margin-top:14px' }, kv([
          ['Industries', profile.world.industries],
          ['Causes', profile.world.causes],
          ['Org type', profile.world.company_stage],
          ['Team size', profile.world.team_size],
        ])),
      )) : null,
    ].filter(Boolean);
  }

  /* Fills the bars and counts the numbers up once they're on screen.

     Only the report's own data animates - the scores are the thing worth
     drawing an eye to, and a number that lands on 39 reads differently from one
     that was simply printed there. Everything else on the page is the
     stylesheet's entrance animations, which already respect reduced motion. */
  function animateIn(root) {
    const fills = [...root.querySelectorAll('.meter-fill[data-target]')];
    const counts = [...root.querySelectorAll('.count[data-to]')];
    const settle = () => {
      fills.forEach((fill) => { fill.style.width = fill.dataset.target; });
      counts.forEach((node) => { node.textContent = node.dataset.to; });
    };

    const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduce || (!fills.length && !counts.length)) { settle(); return; }

    requestAnimationFrame(() => fills.forEach((fill) => { fill.style.width = fill.dataset.target; }));

    const DURATION = 780;
    const begun = performance.now();
    const step = (now) => {
      const progress = Math.min(1, (now - begun) / DURATION);
      const eased = 1 - ((1 - progress) ** 3);
      counts.forEach((node) => {
        node.textContent = String(Math.round(Number(node.dataset.to) * eased));
      });
      if (progress < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  /* -------------------------------------------------------------- boot */

  async function boot() {
    const container = document.getElementById('report');
    const bootNode = document.getElementById('boot');
    const profileId = window.location.pathname.split('/').filter(Boolean).pop();

    /* The admin serves this same renderer from its own page, locked to the
       company view and reading its own endpoint. An admin reviewing candidates
       should see what a recruiter sees, not the coaching written for the
       student - so when the lock is set there is no way to switch. */
    const lock = window.CAARYA_VIEW_LOCK || null;
    const endpoint = window.CAARYA_PROFILE_ENDPOINT || '/api/profile';

    let profile;
    let taxonomy;
    let schema;
    try {
      profile = await api.get(`${endpoint}/${profileId}`);
      if (!lock) {
        [taxonomy, schema] = await Promise.all([
          api.get('/api/taxonomy'),
          api.get('/api/profile-schema'),
        ]);
      }
    } catch (error) {
      bootNode.textContent = `Couldn't load that profile: ${error.message}`;
      return;
    }

    const params = new URLSearchParams(window.location.search);
    let view = lock || (params.get('view') === 'company' ? 'company' : 'student');

    const toggle = el('div', { class: 'view-toggle no-print' });
    const ctx = {
      taxonomy,
      schema,
      details: JSON.parse(JSON.stringify(profile.details || {})),
      repaint: () => paint(),
    };

    const paint = () => {
      container.replaceChildren();
      container.append(el('div', {
        style: 'display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:22px',
      }, [
        el('div', { class: 'brand' }, [
          el('strong', { text: 'caarya' }),
          el('span', { text: lock ? 'candidate' : 'profile report' }),
        ]),
        el('div', { style: 'display:flex;gap:10px;align-items:center' }, [
          window.CAARYA_BACK_LINK
            ? el('a', { class: 'btn btn-ghost no-print', href: window.CAARYA_BACK_LINK, text: '← All students' })
            : null,
          lock ? null : toggle,
        ]),
      ]));
      (view === 'company' ? companyView(profile) : studentView(profile, ctx)).forEach((node) => container.append(node));
      bootNode.hidden = true;
      container.hidden = false;
      animateIn(container);
    };

    ['student', 'company'].forEach((name) => {
      toggle.append(el('button', {
        type: 'button', text: name === 'student' ? 'Your view' : 'Company view',
        'aria-pressed': view === name,
        onclick: () => {
          view = name;
          const url = new URL(window.location);
          if (name === 'company') url.searchParams.set('view', 'company');
          else url.searchParams.delete('view');
          window.history.replaceState({}, '', url);
          toggle.querySelectorAll('button').forEach((button, index) =>
            button.setAttribute('aria-pressed', ['student', 'company'][index] === name));
          paint();
        },
      }));
    });

    // A closed <details> stays closed on paper whatever the stylesheet says, so
    // open it before printing - a printed report nobody can expand is useless.
    window.addEventListener('beforeprint', () => {
      container.querySelectorAll('details').forEach((node) => { node.open = true; });
    });

    paint();
  }

  boot();
})();
