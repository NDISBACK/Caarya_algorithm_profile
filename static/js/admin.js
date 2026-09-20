/* The admin panel: four CRUD tables over data/taxonomy.json.

   The file these edit is the same one the student form reads, so every save
   here is live for the next student who loads it - that's what the "Preview as
   a student" link is for.

   Two rules the UI exists to make obvious:
     - an id never changes, so renaming is safe and re-parenting isn't offered
     - deleting something students were scored on archives it instead, and the
       dialog says so before you commit. */

(() => {
  const el = (tag, attrs = {}, children = []) => {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (value === null || value === undefined || value === false) continue;
      if (key.startsWith('aria-') && typeof value === 'boolean') { node.setAttribute(key, String(value)); continue; }
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = value;
      else if (key.startsWith('on')) node.addEventListener(key.slice(2).toLowerCase(), value);
      else node.setAttribute(key, value === true ? '' : value);
    }
    for (const child of [].concat(children)) if (child) node.append(child);
    return node;
  };

  const state = {
    data: null,            // { taxonomy, usage, skill_value_constructs, warnings }
    students: null,
    tab: 'roles',
    open: null,            // { kind, id } - the row showing in the drawer
    search: { roles: '', services: '', vcs: '', skills: '', students: '' },
    filter: { vcs: '', skills: '', services: '', students: '' },  // parent / type / college
    notice: null,
  };

  const dom = {
    panel: document.getElementById('panel'),
    tabs: document.getElementById('tabs'),
    notice: document.getElementById('notice'),
  };

  /* ------------------------------------------------------------- the data */

  const tax = () => state.data.taxonomy;
  const roles = () => tax().roles || [];
  const skills = () => tax().skills || {};

  /* Flattened views. The tables are flat, so the parent is carried on each row
     rather than implied by nesting - that's the whole point of the redesign. */
  const allServices = () => roles().flatMap((role) =>
    (role.business_services || []).map((service) => ({ ...service, role })));

  const allVcs = () => allServices().flatMap((service) =>
    (service.value_constructs || []).map((vc) => ({ ...vc, service })));

  const allSkills = () => Object.entries(skills())
    .map(([id, skill]) => ({ ...skill, id }))
    .sort((a, b) => a.name.localeCompare(b.name));

  const usage = (bucket, id) => (state.data.usage[bucket] || {})[id] || 0;
  const vcsOfSkill = (id) => state.data.skill_value_constructs[id] || [];

  const find = {
    role: (id) => roles().find((r) => r.id === id),
    service: (id) => allServices().find((s) => s.id === id),
    vc: (id) => allVcs().find((v) => v.id === id),
    skill: (id) => allSkills().find((s) => s.id === id),
  };

  /* -------------------------------------------------------------- pieces */

  const countCell = (n, singular, plural = `${singular}s`) =>
    el('span', { class: n ? '' : 'muted', text: `${n} ${n === 1 ? singular : plural}` });

  const usageCell = (bucket, id) => {
    const n = usage(bucket, id);
    return el('span', {
      class: `pill ${n ? 'neutral' : 'quiet'}`,
      text: n ? `${n}` : '—',
      title: n ? `${n} student profile${n > 1 ? 's' : ''} reference this` : 'No student references this yet',
    });
  };

  const archivedChip = (entity) => (entity.archived
    ? el('span', { class: 'pill stretch', text: 'archived', title: 'Hidden from the student form' })
    : null);

  /* Clicking a parent cell jumps to that parent's table, filtered - which is
     what stops four flat tables feeling like four separate spreadsheets. */
  const parentLink = (label, tabName, filterKey, filterValue) => el('button', {
    class: 'cell-link', text: label, title: `Show in ${tabName}`,
    onclick: (event) => {
      event.stopPropagation();
      state.tab = tabName;
      state.filter[tabName] = filterValue;
      state.open = null;
      render();
    },
  });

  function notify(message, kind = 'ok') {
    dom.notice.replaceChildren(el('div', { class: `alert alert-${kind === 'ok' ? 'ok' : 'error'}`, text: message }));
    if (kind === 'ok') setTimeout(() => dom.notice.replaceChildren(), 4000);
  }

  async function run(action, successMessage) {
    try {
      const result = await action();
      await load();
      if (successMessage) notify(typeof successMessage === 'function' ? successMessage(result) : successMessage);
      return result;
    } catch (error) {
      notify((error.details && error.details[0]) || error.message, 'error');
      return null;
    }
  }

  /* ------------------------------------------------------ delete / archive */

  function confirmRemove(kind, bucket, entity) {
    const n = usage(bucket, entity.id);
    const body = n
      ? `${entity.name} is referenced by ${n} student profile${n > 1 ? 's' : ''}. `
        + 'It will be archived: hidden from the student form, but their reports keep working.'
      : `${entity.name} isn't referenced by any student profile, so it will be deleted permanently.`;

    const dialog = el('div', { class: 'confirm-backdrop', onclick: (e) => { if (e.target === dialog) dialog.remove(); } }, [
      el('div', { class: 'confirm card' }, [
        el('h3', { text: n ? `Archive ${entity.name}?` : `Delete ${entity.name}?` }),
        el('p', { class: 'muted', style: 'margin-top:8px', text: body }),
        el('div', { class: 'confirm-actions' }, [
          el('button', { class: 'btn btn-ghost', text: 'Cancel', onclick: () => dialog.remove() }),
          el('button', {
            class: 'btn btn-primary', text: n ? 'Archive it' : 'Delete permanently',
            onclick: async () => {
              dialog.remove();
              state.open = null;
              await run(() => api.del(`/api/admin/${bucket}/${entity.id}`), (r) => r.message);
            },
          }),
        ]),
      ]),
    ]);
    document.body.append(dialog);
  }

  /* --------------------------------------------------------------- tables */

  /* Each tab opens with what you are looking at and how much of it there is -
     landing straight on a table gives no sense of scale or place. */
  function pageHead(title, blurb, counts) {
    return el('header', { class: 'admin-head' }, [
      el('div', {}, [
        el('h1', { text: title }),
        el('p', { class: 'small muted', text: blurb }),
      ]),
      el('div', { class: 'admin-counts' }, counts.filter(Boolean).map(([value, label]) =>
        el('div', { class: 'count-tile' }, [
          el('strong', { text: String(value) }),
          el('span', { text: label }),
        ]))),
    ]);
  }

  /* Search on the left, filters beside it, creating on the right - the three
     are different jobs and used to sit in one undifferentiated row. */
  function toolbar(key, placeholder, filters, create) {
    const input = el('input', {
      type: 'search', placeholder, value: state.search[key],
      oninput: (e) => { state.search[key] = e.target.value; repaintTable(); },
    });
    return el('div', { class: 'admin-toolbar' }, [
      el('div', { class: 'toolbar-find' }, [input, ...(filters || []).filter(Boolean)]),
      create ? el('div', { class: 'toolbar-create' }, create) : null,
    ]);
  }

  const emptyState = (title, hint) => el('div', { class: 'empty-state' }, [
    el('strong', { text: title }),
    el('p', { class: 'small muted', text: hint }),
  ]);

  function clearFilter(key, label) {
    if (!state.filter[key]) return null;
    return el('button', {
      class: 'chip', 'aria-pressed': true,
      text: `${label} ✕`,
      onclick: () => { state.filter[key] = ''; render(); },
    });
  }

  const matches = (row, query) => !query
    || `${row.name} ${row.id} ${row.tagline || ''} ${row.description || ''}`.toLowerCase().includes(query.toLowerCase());

  /* `secondary` columns are the ones worth losing first on a narrow screen -
     a long tagline makes every row three times taller and pushes the counts,
     which are the point of the table, off the side. */
  const columnClass = (column) =>
    `${column.narrow ? 'narrow' : ''} ${column.secondary ? 'hide-narrow' : ''}`.trim();

  function table(columns, rows, { kind, bucket, empty, hint }) {
    if (!rows.length) return el('div', { class: 'card' }, emptyState(empty, hint || 'Add one above.'));

    return el('div', { class: 'card table-card' }, el('table', { class: 'admin-table rows-clickable' }, [
      el('thead', {}, el('tr', {}, [...columns.map((c) => el('th', { class: columnClass(c), text: c.label })), el('th', { class: 'narrow' })])),
      el('tbody', {}, rows.map((row) => el('tr', {
        class: row.archived ? 'is-archived' : '',
        tabindex: '0',
        onclick: () => { state.open = { kind, id: row.id }; render(); },
        onkeydown: (e) => { if (e.key === 'Enter') { state.open = { kind, id: row.id }; render(); } },
      }, [
        // data-label is what the header row becomes below 700px, where each
        // row is a card and there is no thead to read the column names from.
        ...columns.map((c, index) => el('td', {
          class: `${columnClass(c)} ${index === 0 ? 'cell-title' : ''}`.trim(),
          'data-label': c.label,
        }, c.cell(row))),
        el('td', { class: 'narrow cell-actions' }, el('button', {
          class: 'btn-quiet danger', text: 'Delete',
          onclick: (e) => { e.stopPropagation(); confirmRemove(kind, bucket, row); },
        })),
      ]))),
    ]));
  }

  function rolesTable() {
    const rows = roles().filter((r) => matches(r, state.search.roles));
    const services = allServices().length;
    return el('div', {}, [
      pageHead('Roles', 'What a student can be hired to do. Everything else hangs off these.',
               [[roles().length, 'roles'], [services, 'business services'], [allVcs().length, 'value constructs']]),
      toolbar('roles', 'Search roles…', [],
              inlineCreate('New role…', (name) => run(() => api.post('/api/admin/roles', { name }), `Added ${name}`))),
      table([
        { label: 'Role', cell: (r) => el('span', { class: 'cell-name' }, [el('strong', { text: r.name }), archivedChip(r)]) },
        { label: 'Tagline', cell: (r) => el('span', { class: 'muted small', text: r.tagline || '—' }), secondary: true },
        { label: 'Business services', narrow: true,
          cell: (r) => countCell((r.business_services || []).length, 'service') },
        { label: 'Value constructs', narrow: true,
          cell: (r) => countCell((r.business_services || []).reduce((n, s) => n + (s.value_constructs || []).length, 0), 'job', 'jobs') },
        { label: 'Students', narrow: true, cell: (r) => usageCell('roles', r.id) },
      ], rows, { kind: 'role', bucket: 'roles', empty: 'No roles yet. Add one above.' }),
    ]);
  }

  function servicesTable() {
    const rows = allServices()
      .filter((s) => !state.filter.services || s.role.id === state.filter.services)
      .filter((s) => matches(s, state.search.services));
    const filtered = state.filter.services ? find.role(state.filter.services) : null;

    return el('div', {}, [
      pageHead('Business services', 'The areas of work inside a role. A student picks one to three.',
               [[allServices().length, 'in total'], [rows.length, 'shown']]),
      toolbar('services', 'Search business services…',
              [filtered ? clearFilter('services', filtered.name) : null],
              createWithParent('service', 'roles', 'Role')),
      table([
        { label: 'Business service', cell: (s) => el('span', { class: 'cell-name' }, [el('strong', { text: s.name }), archivedChip(s)]) },
        { label: 'Role', cell: (s) => parentLink(s.role.name, 'roles', 'roles', '') },
        { label: 'Tagline', cell: (s) => el('span', { class: 'muted small', text: s.tagline || '—' }), secondary: true },
        { label: 'Value constructs', narrow: true, cell: (s) => countCell((s.value_constructs || []).length, 'job', 'jobs') },
        { label: 'Students', narrow: true, cell: (s) => usageCell('services', s.id) },
      ], rows, { kind: 'service', bucket: 'services',
        empty: 'No business services here yet.' }),
    ]);
  }

  function vcsTable() {
    const rows = allVcs()
      .filter((v) => !state.filter.vcs || v.service.id === state.filter.vcs)
      .filter((v) => matches(v, state.search.vcs));
    const filtered = state.filter.vcs ? find.service(state.filter.vcs) : null;

    const unscorable = allVcs().filter((v) => !(v.technical_skills || []).length).length;
    return el('div', {}, [
      pageHead('Value constructs', 'The concrete pieces of work a student is scored against.',
               [[allVcs().length, 'in total'], [rows.length, 'shown'],
                unscorable ? [unscorable, 'with no technical skill'] : null]),
      toolbar('vcs', 'Search value constructs…',
              [filtered ? clearFilter('vcs', filtered.name) : null],
              createWithParent('vc', 'services', 'Business service')),
      table([
        { label: 'Value construct', cell: (v) => el('span', { class: 'cell-name' }, [el('strong', { text: v.name }), archivedChip(v)]) },
        { label: 'Business service', cell: (v) => parentLink(v.service.name, 'services', 'services', v.service.role.id) },
        { label: 'Technical', narrow: true, cell: (v) => skillCount(v.technical_skills, 'technical') },
        { label: 'Transferable', narrow: true, cell: (v) => skillCount(v.transferable_skills, 'transferable') },
        { label: 'Students', narrow: true, cell: (v) => usageCell('vcs', v.id) },
      ], rows, { kind: 'vc', bucket: 'vcs', empty: 'No value constructs here yet.' }),
    ]);
  }

  /* A value construct with no technical skills can't really be scored, so the
     count says so rather than quietly reading "0". */
  function skillCount(list, kind) {
    const n = (list || []).length;
    if (n) return el('span', { text: String(n) });
    return el('span', { class: 'pill gap', text: 'none', title: `No ${kind} skills attached — this job can't be scored properly` });
  }

  function skillsTable() {
    const type = state.filter.skills;
    const rows = allSkills()
      .filter((s) => !type || s.type === type)
      .filter((s) => matches(s, state.search.skills));

    const typeFilter = ['', 'technical', 'transferable'].map((value) => el('button', {
      class: 'chip', 'aria-pressed': type === value,
      text: value === '' ? `All (${allSkills().length})`
        : `${value === 'technical' ? 'Technical' : 'Transferable'} (${allSkills().filter((s) => s.type === value).length})`,
      onclick: () => { state.filter.skills = value; render(); },
    }));

    const orphans = allSkills().filter((s) => !vcsOfSkill(s.id).length).length;
    return el('div', {}, [
      pageHead('Skills', 'One shared library. A skill used by several value constructs is what lets us say something about work a student never picked.',
               [[allSkills().filter((s) => s.type === 'technical').length, 'technical'],
                [allSkills().filter((s) => s.type === 'transferable').length, 'transferable'],
                orphans ? [orphans, 'attached to nothing'] : null]),
      toolbar('skills', 'Search skills…', typeFilter, createSkill()),
      table([
        { label: 'Skill', cell: (s) => el('span', { class: 'cell-name' }, [
            el('strong', { text: s.name }), archivedChip(s),
            el('div', { class: 'tiny muted', text: s.hint || '' }),
          ]) },
        { label: 'Type', narrow: true, cell: (s) => el('span', {
            class: `pill ${s.type === 'technical' ? 'emerging' : 'neutral'}`, text: s.type }) },
        { label: 'Used by', secondary: true, cell: (s) => {
            const jobs = vcsOfSkill(s.id);
            if (!jobs.length) return el('span', { class: 'pill gap', text: 'no value construct',
              title: 'Not attached to anything, so no student will ever be asked about it' });
            return el('span', { class: 'muted small',
              text: `${jobs.length} — ${jobs.map((j) => j.name).slice(0, 2).join(', ')}${jobs.length > 2 ? '…' : ''}` });
          } },
        { label: 'Rated by', narrow: true, cell: (s) => usageCell('skills', s.id) },
      ], rows, { kind: 'skill', bucket: 'skills', empty: 'No skills match that.' }),
    ]);
  }

  /* Built from the profiles that exist, not from data/institutions.json: the
     list there is only a suggestion set, and what matters here is which
     colleges have actually sent students. */
  const collegesInUse = () => [...new Set((state.students || [])
    .map((row) => (row.college || '').trim())
    .filter(Boolean))].sort((a, b) => a.localeCompare(b));

  const studentMatches = (row, query) => {
    if (!query) return true;
    const q = query.toLowerCase();
    return [row.full_name, row.college, row.state, row.city, row.role_id, row.verdict]
      .some((value) => (value || '').toLowerCase().includes(q));
  };

  function studentsTable() {
    const all = state.students || [];
    const college = state.filter.students;
    const rows = all
      .filter((row) => !college || (row.college || '').trim() === college)
      .filter((row) => studentMatches(row, state.search.students));

    const head = pageHead('Students', 'Everyone who has completed the form. Opening one shows it exactly as a company would see it.',
                          [[all.length, 'profiles'], [collegesInUse().length, 'colleges']]);
    if (!all.length) {
      return el('div', {}, [head, el('div', { class: 'card' },
        emptyState('No completed profiles yet', 'They appear here as soon as a student finishes the form.'))]);
    }

    const collegePicker = el('select', {
      class: 'filter-select',
      onchange: (e) => { state.filter.students = e.target.value; render(); },
    }, [
      el('option', { value: '', text: `All colleges (${collegesInUse().length})` }),
      ...collegesInUse().map((name) => el('option', {
        value: name, text: `${name} (${all.filter((r) => (r.college || '').trim() === name).length})`,
      })),
    ]);
    collegePicker.value = college;

    const bar = toolbar('students', 'Search name, college, city…', [collegePicker]);

    if (!rows.length) {
      return el('div', {}, [head, bar, el('div', { class: 'card' },
        emptyState('Nothing matches that', 'Try a different search, or clear the college filter.'))]);
    }

    return el('div', {}, [head, bar, el('div', { class: 'card table-card' }, [
      el('table', { class: 'admin-table' }, [
        el('thead', {}, el('tr', {}, ['Student', 'College', 'Role', 'Fit', 'Verdict', ''].map((h) => el('th', { text: h })))),
        el('tbody', {}, rows.map((row) => el('tr', {
          class: 'is-clickable',
          onclick: () => { window.location.href = `/students/${row.id}`; },
        }, [
          el('td', { class: 'cell-title', 'data-label': 'Student', text: row.full_name || '—' }),
          el('td', { 'data-label': 'College' }, [
            el('div', { text: row.college || '—' }),
            row.state ? el('div', { class: 'small muted', text: row.state }) : null,
          ]),
          el('td', { 'data-label': 'Role', text: row.role_id || '—' }),
          el('td', { 'data-label': 'Fit', text: row.role_fit === null || row.role_fit === undefined ? '—' : Math.round(row.role_fit) }),
          el('td', { 'data-label': 'Verdict' }, el('span', { class: 'pill neutral', text: row.verdict || '—' })),
          el('td', { class: 'cell-actions' }, el('a', { class: 'cell-link', href: `/students/${row.id}`, text: 'view' })),
        ]))),
      ])])]);
  }

  /* --------------------------------------------------------------- create */

  function inlineCreate(placeholder, onAdd) {
    const input = el('input', { type: 'text', placeholder,
      onkeydown: (e) => { if (e.key === 'Enter') submit(); } });
    const submit = () => {
      const value = input.value.trim();
      if (value) { input.value = ''; onAdd(value); }
    };
    return el('div', { class: 'inline-add' }, [input, el('button', { class: 'btn btn-primary', text: 'Add', onclick: submit })]);
  }

  /* A flat table loses the parent the old tree implied, so creating asks for
     one - pre-selected to whatever the table is filtered to. */
  function createWithParent(kind, parentBucket, parentLabel) {
    const parents = kind === 'service' ? roles() : allServices();
    if (!parents.length) return el('span', { class: 'muted small', text: `Add a ${parentLabel.toLowerCase()} first` });

    const preselected = kind === 'service' ? state.filter.services : state.filter.vcs;
    const select = el('select', {}, parents.map((p) => el('option', { value: p.id, text: p.name })));
    select.value = preselected || parents[0].id;

    return el('div', { class: 'inline-add' }, [
      select,
      inlineCreate(kind === 'service' ? 'New business service…' : 'New value construct…', (name) => {
        const payload = kind === 'service'
          ? { role_id: select.value, name }
          : { service_id: select.value, name };
        return run(() => api.post(`/api/admin/${kind === 'service' ? 'services' : 'vcs'}`, payload), `Added ${name}`);
      }),
    ]);
  }

  function createSkill() {
    const select = el('select', {}, [
      el('option', { value: 'technical', text: 'Technical' }),
      el('option', { value: 'transferable', text: 'Transferable' }),
    ]);
    if (state.filter.skills) select.value = state.filter.skills;
    return el('div', { class: 'inline-add' }, [
      select,
      inlineCreate('New skill…', (name) =>
        run(() => api.post('/api/admin/skills', { name, type: select.value }), `Created ${name}`)),
    ]);
  }

  /* ---------------------------------------------------------- the drawer */

  const saveLater = (() => {
    let timer = null;
    return (fn) => { clearTimeout(timer); timer = setTimeout(fn, 600); };
  })();

  function field(label, value, onInput, { textarea = false, placeholder = '', help = '' } = {}) {
    const control = el(textarea ? 'textarea' : 'input', {
      type: textarea ? null : 'text', rows: textarea ? 3 : null, placeholder,
      oninput: (e) => onInput(e.target.value),
    });
    control.value = value || '';
    return el('div', { class: 'field full' }, [
      el('label', { class: 'lbl', text: label }),
      control,
      help ? el('div', { class: 'help', text: help }) : null,
    ]);
  }

  function editableFields(bucket, entity, definitions) {
    const draft = {};
    return definitions.map(([key, label, opts]) => field(label, entity[key], (value) => {
      draft[key] = value;
      saveLater(() => run(() => api.patch(`/api/admin/${bucket}/${entity.id}`, { ...draft }), 'Saved'));
    }, opts || {}));
  }

  function drawerFor(kind, id) {
    const entity = find[kind] && find[kind](id);
    if (!entity) return null;

    const bucket = { role: 'roles', service: 'services', vc: 'vcs', skill: 'skills' }[kind];
    const n = usage(bucket, id);

    const body = el('div', { class: 'drawer-body' });
    if (kind === 'role') {
      body.append(el('div', { class: 'grid' }, editableFields('roles', entity, [
        ['name', 'Name'], ['tagline', 'Tagline'], ['description', 'Description', { textarea: true }],
      ])));
      body.append(relatedLink(`${(entity.business_services || []).length} business services`,
        'services', 'services', entity.id));
    } else if (kind === 'service') {
      body.append(el('div', { class: 'grid' }, editableFields('services', entity, [
        ['name', 'Name'], ['tagline', 'Tagline'],
      ])));
      body.append(relatedLink(`${(entity.value_constructs || []).length} value constructs`,
        'vcs', 'vcs', entity.id));
    } else if (kind === 'skill') {
      body.append(el('div', { class: 'grid' }, editableFields('skills', entity, [
        ['name', 'Name'], ['hint', 'Hint shown to the student', { textarea: true }],
      ])));
      const jobs = vcsOfSkill(id);
      body.append(el('div', { class: 'drawer-note' }, [
        el('strong', { text: `Type: ${entity.type}` }),
        el('p', { class: 'small muted', style: 'margin-top:6px',
          text: "A skill's type can't be changed — value constructs already rely on it." }),
        el('p', { class: 'small', style: 'margin-top:10px', text: jobs.length
          ? `Attached to: ${jobs.map((j) => j.name).join(', ')}`
          : 'Not attached to any value construct yet, so no student will be asked about it.' }),
      ]));
    } else if (kind === 'vc') {
      body.append(el('div', { class: 'grid' }, editableFields('vcs', entity, [
        ['name', 'Name'], ['description', 'What the student would actually do', { textarea: true }],
      ])));
      body.append(skillPicker(entity, 'technical'));
      body.append(skillPicker(entity, 'transferable'));
    }

    return el('div', { class: 'drawer-backdrop', onclick: (e) => { if (e.target.classList.contains('drawer-backdrop')) closeDrawer(); } }, [
      el('aside', { class: 'drawer', role: 'dialog', 'aria-label': `Edit ${entity.name}` }, [
        el('header', { class: 'drawer-head' }, [
          el('div', {}, [
            el('h2', { text: entity.name }),
            el('div', {}, [
              el('code', { class: 'id-chip', text: entity.id, title: 'Permanent id — student profiles reference it' }),
              archivedChip(entity),
            ]),
            el('p', { class: 'tiny muted', style: 'margin-top:8px', text: n
              ? `${n} student profile${n > 1 ? 's' : ''} reference this`
              : 'No student references this yet' }),
          ]),
          el('button', { class: 'btn-quiet', text: '✕', 'aria-label': 'Close', onclick: closeDrawer }),
        ]),
        body,
        el('footer', { class: 'drawer-foot' }, [
          entity.archived
            ? el('button', { class: 'btn btn-ghost', text: 'Restore',
                onclick: () => run(() => api.post(`/api/admin/${bucket}/${entity.id}/restore`, {}), `${entity.name} is live again`) })
            : el('button', { class: 'btn btn-ghost danger', text: 'Delete…',
                onclick: () => confirmRemove(kind, bucket, entity) }),
          el('span', { class: 'tiny muted', text: 'Changes save as you type.' }),
        ]),
      ]),
    ]);
  }

  const relatedLink = (label, tabName, filterKey, filterValue) => el('button', {
    class: 'btn btn-ghost', style: 'margin-top:16px', text: `View ${label} →`,
    onclick: () => { state.tab = tabName; state.filter[filterKey] = filterValue; state.open = null; render(); },
  });

  function skillPicker(vc, type) {
    const key = type === 'technical' ? 'technical_skills' : 'transferable_skills';
    const chosen = [...(vc[key] || [])];

    /* The endpoint replaces both lists, so each picker has to send the other
       one too - and it must read it fresh at save time. Sending the copy this
       picker captured when it was built would silently wipe whatever the other
       picker saved in the meantime. */
    const persist = () => run(() => {
      const current = find.vc(vc.id) || vc;
      return api.put(`/api/admin/vcs/${vc.id}/skills`, {
        technical_skills: type === 'technical' ? chosen : (current.technical_skills || []),
        transferable_skills: type === 'transferable' ? chosen : (current.transferable_skills || []),
      });
    }, 'Skills updated');

    const pool = allSkills().filter((s) => s.type === type && !s.archived);
    const search = el('input', { type: 'search', placeholder: `Search ${type} skills…`, oninput: () => paint() });
    const options = el('div', { class: 'skill-options' });
    const selected = el('div', { class: 'chips', style: 'margin-bottom:10px' });

    const paint = () => {
      selected.replaceChildren(...chosen.map((id) => el('span', { class: 'tag' }, [
        document.createTextNode((skills()[id] || {}).name || id),
        el('button', { type: 'button', text: '×', 'aria-label': `Remove ${id}`,
          onclick: () => { chosen.splice(chosen.indexOf(id), 1); paint(); persist(); } }),
      ])));
      if (!chosen.length) selected.append(el('span', { class: 'muted small', text: 'None attached yet.' }));

      const query = search.value.trim().toLowerCase();
      options.replaceChildren(...pool
        .filter((s) => !chosen.includes(s.id) && (!query || s.name.toLowerCase().includes(query)))
        .slice(0, 12)
        .map((s) => el('button', { type: 'button', class: 'chip',
          onclick: () => { chosen.push(s.id); paint(); persist(); } }, [
          document.createTextNode(s.name),
          el('span', { class: 'tiny muted', text: ` · ${vcsOfSkill(s.id).length}` }),
        ])));
    };
    paint();

    return el('div', { class: 'drawer-section' }, [
      el('h3', { text: type === 'technical' ? 'Technical skills' : 'Transferable skills' }),
      el('p', { class: 'small muted', style: 'margin:4px 0 12px',
        text: type === 'technical'
          ? 'Weighted 60% of this value construct’s score, and the weakest one drags the rest down.'
          : 'Weighted 40% of this value construct’s score.' }),
      selected, search, options,
      el('div', { style: 'margin-top:12px' }, inlineCreate(`Create a new ${type} skill…`, async (name) => {
        const made = await run(() => api.post('/api/admin/skills', { name, type }), `Created ${name}`);
        if (made) { chosen.push(made.id); persist(); }
      })),
    ]);
  }

  function closeDrawer() {
    state.open = null;
    render();
  }

  /* ---------------------------------------------------------------- shell */

  const TABS = [
    ['roles', 'Roles'], ['services', 'Business Services'],
    ['vcs', 'Value Constructs'], ['skills', 'Skills'], ['students', 'Students'],
  ];

  const VIEWS = {
    roles: rolesTable, services: servicesTable, vcs: vcsTable,
    skills: skillsTable, students: studentsTable,
  };

  // Only the table card is repainted while typing in a search box, so the input
  // keeps focus and the caret doesn't jump.
  //
  // This used to look for a .table-host wrapper that no view ever rendered, so
  // every search box was a silent no-op. It now swaps the card in place - the
  // first .card in the panel is always the current view's, since the drawer is
  // appended after it.
  function repaintTable() {
    const current = dom.panel.querySelector('.card');
    if (!current) { render(); return; }
    const fresh = VIEWS[state.tab]();
    current.replaceWith(fresh.querySelector('.card') || fresh);
  }

  function render() {
    dom.tabs.replaceChildren(...TABS.map(([id, label]) => el('button', {
      type: 'button', text: label, 'aria-pressed': state.tab === id,
      onclick: () => { state.tab = id; state.open = null; render(); },
    })));

    const warnings = (state.data && state.data.warnings) || [];
    const banner = warnings.length ? el('div', { class: 'note-block', style: 'margin-bottom:18px' }, [
      el('strong', { text: `${warnings.length} thing${warnings.length > 1 ? 's' : ''} worth tidying:` }),
      el('ul', { style: 'margin:8px 0 0; padding-left:18px' },
        warnings.map((w) => el('li', { class: 'small', text: w }))),
    ]) : null;

    const drawer = state.open ? drawerFor(state.open.kind, state.open.id) : null;

    dom.panel.replaceChildren(...[banner, VIEWS[state.tab](), drawer].filter(Boolean));
    syncHash();
  }

  /* The open row lives in the URL, so a link can point at one thing. */
  function syncHash() {
    const next = state.open ? `#${state.open.kind}/${state.open.id}` : `#${state.tab}`;
    if (window.location.hash !== next) window.history.replaceState({}, '', next);
  }

  function readHash() {
    const raw = decodeURIComponent(window.location.hash.replace(/^#/, ''));
    if (!raw) return;
    const [head, id] = raw.split('/');
    if (VIEWS[head] && !id) { state.tab = head; return; }
    const tabFor = { role: 'roles', service: 'services', vc: 'vcs', skill: 'skills' };
    if (tabFor[head] && id) {
      state.tab = tabFor[head];
      state.open = { kind: head, id };
    }
  }

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && state.open) closeDrawer();
  });

  let hashRead = false;

  /* The student app is a separate program on its own port now, so where it
     lives is configuration rather than a relative link. */
  async function pointAtStudentApp() {
    const link = document.getElementById('student-link');
    if (!link) return;
    try {
      const config = await api.get('/api/admin/config');
      if (config.student_url) link.href = config.student_url;
    } catch (error) { /* the default in the markup is a fine fallback */ }
  }

  async function load() {
    state.data = await api.get('/api/admin/taxonomy');
    if (!hashRead) { readHash(); hashRead = true; }
    try {
      state.students = (await api.get('/api/admin/profiles')).profiles;
    } catch (error) { state.students = []; }
    render();
  }

  pointAtStudentApp();

  load().catch((error) => {
    dom.panel.replaceChildren(el('div', { class: 'alert alert-error', text: error.message }));
  });
})();
