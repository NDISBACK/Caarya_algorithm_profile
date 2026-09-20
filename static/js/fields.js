/* Renders form fields from data/profile_schema.json.

   Nothing here knows what a question means - it only knows field types. Adding a
   question to the schema is enough to make it appear, validate and persist. */

const Fields = (() => {
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
    for (const child of [].concat(children)) {
      if (child) node.append(child);
    }
    return node;
  };

  /* Reference lists that aren't part of the taxonomy - states and colleges.
     Set once at boot by whoever loads the page; absent is fine, the combobox
     just has nothing to suggest and behaves as a plain text field. */
  let reference = {};
  const setReference = (data) => { reference = data || {}; };

  const optionsFor = (field, ctx) => {
    if (field.options) return field.options;
    const source = field.options_from;
    if (!source) return [];
    return source.split('.').reduce((acc, key) => (acc || {})[key],
      { taxonomy: ctx.taxonomy, institutions: reference }) || [];
  };

  /* Options may be plain strings or {name, state} - one shape from here on. */
  const asOption = (option) => (typeof option === 'string'
    ? { value: option, hint: '' }
    : { value: option.name, hint: option.state || '' });

  const labelFor = (field) => {
    if (!field.label) return null;
    const parts = [document.createTextNode(field.label)];
    if (field.optional_note) parts.push(el('span', { class: 'optional', text: ` · ${field.optional_note}` }));
    return el('label', { class: 'lbl', for: field._domId }, parts);
  };

  /* ------------------------------------------------------------ controls */

  function buildControl(field, values, ctx) {
    const commit = (value) => {
      if (value === '' || value === null || (Array.isArray(value) && !value.length)) delete values[field.id];
      else values[field.id] = value;
      ctx.onChange(field);
    };
    const current = values[field.id];

    switch (field.type) {
      case 'textarea': {
        const input = el('textarea', {
          id: field._domId, rows: field.rows || 3, maxlength: field.maxlength,
          placeholder: field.placeholder, oninput: (e) => { commit(e.target.value); updateCounter(); },
        });
        input.value = current || '';
        const counter = field.maxlength ? el('div', { class: 'counter' }) : null;
        const updateCounter = () => {
          if (counter) counter.textContent = `${input.value.length}/${field.maxlength}`;
        };
        updateCounter();
        return [input, counter];
      }

      case 'select': {
        const select = el('select', { id: field._domId, onchange: (e) => commit(e.target.value) }, [
          el('option', { value: '', text: field.placeholder || 'Select…' }),
          ...optionsFor(field, ctx).map((option) => el('option', { value: option, text: option })),
        ]);
        select.value = current || '';
        return select;
      }

      /* A text box with suggestions under it. Anything may be typed: the list
         is there to save typing and to keep spellings consistent, not to
         limit the answer - no list of colleges is ever complete, and a
         student at one that isn't on it still has to be able to finish. */
      case 'combobox': {
        const all = optionsFor(field, ctx).map(asOption);
        const wrap = el('div', { class: 'combo' });
        const list = el('ul', {
          class: 'combo-list', role: 'listbox', hidden: true,
          id: `${field._domId}-list`,
        });
        const input = el('input', {
          type: 'text', id: field._domId, class: 'combo-input',
          placeholder: field.placeholder || 'Start typing…',
          maxlength: field.maxlength, autocomplete: 'off',
          role: 'combobox', 'aria-expanded': false, 'aria-autocomplete': 'list',
          'aria-controls': `${field._domId}-list`,
        });
        input.value = current === undefined ? '' : current;

        let matches = [];
        let cursor = -1;

        /* Raising the list is not enough on its own. Its z-index only orders it
           inside its own .field; a later .field is a separate box in the
           parent's stacking order and paints over the whole of an earlier one,
           z-index:30 descendant and all - which is why the list appeared to be
           see-through when it was in fact being drawn under the fields below
           it. So every ancestor up to the step is raised while it is open. */
        const lift = (on) => {
          let node = wrap;
          while (node && !node.classList.contains('step')) {
            node.classList.toggle('combo-open', on);
            node = node.parentElement;
          }
        };

        const close = () => {
          list.hidden = true;
          input.setAttribute('aria-expanded', 'false');
          lift(false);
          cursor = -1;
        };

        const paintCursor = () => {
          [...list.children].forEach((node, index) => {
            node.classList.toggle('is-cursor', index === cursor);
            node.setAttribute('aria-selected', String(index === cursor));
          });
          if (cursor >= 0 && list.children[cursor]) {
            list.children[cursor].scrollIntoView({ block: 'nearest' });
          }
        };

        const choose = (value) => {
          input.value = value;
          commit(value);
          close();
          input.focus();
        };

        const open = () => {
          const query = input.value.trim().toLowerCase();
          /* Ranked, not merely filtered: a prefix match is almost always the
             one being typed, so "Madras" puts Madras Institute of Technology
             above "Indian Institute of Technology Madras". Capped at 50 -
             nobody scrolls past that, and 500 nodes per keystroke is felt. */
          matches = all
            .map((option) => {
              const name = option.value.toLowerCase();
              if (!query) return { option, rank: 0 };
              if (name.startsWith(query)) return { option, rank: 0 };
              if (name.includes(` ${query}`)) return { option, rank: 1 };
              if (name.includes(query)) return { option, rank: 2 };
              return null;
            })
            .filter(Boolean)
            .sort((a, b) => a.rank - b.rank)
            .slice(0, 50)
            .map((hit) => hit.option);

          list.replaceChildren(...matches.map((option, index) => el('li', {
            class: 'combo-option', role: 'option', 'aria-selected': false,
            // mousedown, not click: blur fires first on a click and would
            // close the list out from under the pointer.
            onmousedown: (event) => { event.preventDefault(); choose(option.value); },
            onmouseenter: () => { cursor = index; paintCursor(); },
          }, [
            el('span', { class: 'combo-name', text: option.value }),
            option.hint ? el('span', { class: 'combo-hint', text: option.hint }) : null,
          ])));

          const exact = matches.length === 1
            && matches[0].value.toLowerCase() === query;
          list.hidden = !matches.length || exact;
          input.setAttribute('aria-expanded', String(!list.hidden));
          lift(!list.hidden);
          cursor = -1;
        };

        input.addEventListener('input', () => { commit(input.value); open(); });
        input.addEventListener('focus', open);
        input.addEventListener('blur', close);
        input.addEventListener('keydown', (event) => {
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            if (list.hidden) { open(); return; }
            event.preventDefault();
            const step = event.key === 'ArrowDown' ? 1 : -1;
            cursor = (cursor + step + matches.length + 1) % (matches.length + 1) - 1;
            if (cursor < 0) cursor = step === 1 ? 0 : matches.length - 1;
            paintCursor();
          } else if (event.key === 'Enter') {
            if (!list.hidden && cursor >= 0) {
              event.preventDefault();
              choose(matches[cursor].value);
            }
          } else if (event.key === 'Escape') {
            if (!list.hidden) { event.stopPropagation(); close(); }
          }
        });

        wrap.append(input, list);
        return wrap;
      }

      case 'multiselect': {
        const options = optionsFor(field, ctx);
        const wrap = el('div', { class: 'chips' });
        const selected = new Set(current || []);
        const paint = () => {
          wrap.querySelectorAll('.chip').forEach((chip) => {
            const on = selected.has(chip.dataset.value);
            chip.setAttribute('aria-pressed', on);
            chip.disabled = !on && field.max && selected.size >= field.max;
          });
        };
        options.forEach((option) => {
          wrap.append(el('button', {
            type: 'button', class: 'chip', 'data-value': option, text: option,
            onclick: () => {
              if (selected.has(option)) selected.delete(option);
              else if (!field.max || selected.size < field.max) selected.add(option);
              commit([...selected]);
              paint();
            },
          }));
        });
        paint();
        return wrap;
      }

      case 'tags': {
        const wrap = el('div', { class: 'tag-input' });
        const tags = [...(current || [])];
        const input = el('input', {
          type: 'text', id: field._domId, placeholder: field.placeholder || 'Type and press Enter',
          onkeydown: (event) => {
            if (event.key === 'Enter' || event.key === ',') {
              event.preventDefault();
              const value = input.value.trim().replace(/,$/, '');
              if (value && !tags.includes(value)) { tags.push(value); commit([...tags]); paint(); }
              input.value = '';
            } else if (event.key === 'Backspace' && !input.value && tags.length) {
              tags.pop(); commit([...tags]); paint();
            }
          },
          onblur: () => {
            const value = input.value.trim();
            if (value && !tags.includes(value)) { tags.push(value); commit([...tags]); paint(); input.value = ''; }
          },
        });
        const paint = () => {
          wrap.querySelectorAll('.tag').forEach((tag) => tag.remove());
          tags.forEach((tag, index) => {
            wrap.insertBefore(el('span', { class: 'tag' }, [
              document.createTextNode(tag),
              el('button', {
                type: 'button', text: '×', 'aria-label': `Remove ${tag}`,
                onclick: () => { tags.splice(index, 1); commit([...tags]); paint(); },
              }),
            ]), input);
          });
        };
        wrap.append(input);
        paint();
        return wrap;
      }

      case 'checkbox': {
        const input = el('input', {
          type: 'checkbox', id: field._domId,
          onchange: (e) => { values[field.id] = e.target.checked; ctx.onChange(field); },
        });
        input.checked = Boolean(current);
        return el('div', { class: 'checkbox' }, [input, el('label', { for: field._domId, text: field.label })]);
      }

      case 'slider_pair': {
        const input = el('input', {
          type: 'range', min: 0, max: 100, step: 5, id: field._domId,
          oninput: (e) => { values[field.id] = Number(e.target.value); ctx.onChange(field); },
        });
        input.value = current === undefined ? 50 : current;
        return el('div', { class: 'slider-pair' }, [
          el('div', { class: 'poles' }, [
            el('span', { text: field.poles[0] }),
            el('span', { text: field.poles[1] }),
          ]),
          input,
        ]);
      }

      case 'repeater':
        return buildRepeater(field, values, ctx);

      default: {
        const input = el('input', {
          type: field.type || 'text', id: field._domId, placeholder: field.placeholder,
          maxlength: field.maxlength, min: field.min, max: field.max,
          oninput: (e) => commit(e.target.value),
        });
        input.value = current === undefined ? '' : current;
        return input;
      }
    }
  }

  /* ----------------------------------------------------------- repeater */

  /* Adding or removing an entry touches only that entry.

     This used to rebuild every row on each change, which threw away the DOM the
     student was typing into - the caret jumped out and the whole block flashed.
     Entries are now removed by identity rather than by a captured index, so the
     rest of the list can be left alone. */
  function buildRepeater(field, values, ctx) {
    const entries = values[field.id] || (values[field.id] = []);
    const list = el('div');
    const empty = el('div', { class: 'empty-note', text: 'Nothing here yet — add one if you have it, or move on.' });

    const label = field.item_label || 'Item';

    const refreshChrome = () => {
      [...list.children].forEach((node, index) => {
        const heading = node.querySelector('header span');
        if (heading) heading.textContent = `${label} ${index + 1}`;
      });
      empty.hidden = entries.length > 0;
      addButton.disabled = Boolean(field.max_items && entries.length >= field.max_items);
    };

    const buildItem = (entry) => {
      const grid = el('div', { class: 'grid' });
      const scope = { container: grid, fields: field.fields, values: entry };
      field.fields.forEach((sub) => grid.append(renderField(sub, entry, ctx, field.id)));
      applyConditions(scope);
      ctx.scopes.push(scope);

      const item = el('div', { class: 'repeater-item' }, [
        el('header', {}, [
          el('span', {}),
          el('button', {
            type: 'button', class: 'btn-quiet', text: 'Remove',
            onclick: () => {
              const at = entries.indexOf(entry);
              if (at >= 0) entries.splice(at, 1);
              item.remove();
              ctx.onChange(field);
              refreshChrome();
            },
          }),
        ]),
        grid,
      ]);
      return item;
    };

    const addButton = el('button', {
      type: 'button', class: 'btn btn-ghost', text: field.add_label || 'Add',
      onclick: () => {
        const entry = {};
        entries.push(entry);
        list.append(buildItem(entry));
        ctx.onChange(field);
        refreshChrome();
        const first = list.lastElementChild.querySelector('input, textarea, select');
        if (first) first.focus();
      },
    });

    entries.forEach((entry) => list.append(buildItem(entry)));
    refreshChrome();
    return el('div', {}, [empty, list, addButton]);
  }

  /* -------------------------------------------------------------- field */

  let domIdCounter = 0;

  function renderField(field, values, ctx, prefix = '') {
    field._domId = `f-${prefix}-${field.id}-${domIdCounter++}`;
    const wrapper = el('div', {
      class: `field ${field.width === 'full' || field.type === 'repeater' ? 'full' : ''}`,
      'data-field': field.id,
    });

    if (field.type !== 'checkbox' && field.label) wrapper.append(labelFor(field));
    [].concat(buildControl(field, values, ctx)).forEach((node) => node && wrapper.append(node));
    if (field.help) wrapper.append(el('div', { class: 'help', text: field.help }));
    wrapper.append(el('div', { class: 'err' }));
    return wrapper;
  }

  /* --------------------------------------------------------- conditions */

  function conditionMet(condition, values) {
    const value = values[condition.field];
    if ('equals' in condition) return value === condition.equals;
    if ('not_in' in condition) return !condition.not_in.includes(value === undefined ? '' : value);
    if ('in' in condition) return condition.in.includes(value);
    return true;
  }

  function applyConditions(scope) {
    scope.fields.forEach((field) => {
      const wrapper = scope.container.querySelector(`[data-field="${field.id}"]`);
      if (!wrapper) return;
      let visible = true;
      if (field.show_if) visible = conditionMet(field.show_if, scope.values);
      if (field.hide_if) visible = visible && !conditionMet(field.hide_if, scope.values);
      wrapper.hidden = !visible;
      wrapper._hiddenByCondition = !visible;
    });
  }

  /* --------------------------------------------------------- validation */

  const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
  const PHONE = /^[\d+][\d\s\-()]{6,19}$/;

  function isBlank(value) {
    if (value === undefined || value === null) return true;
    if (typeof value === 'string') return value.trim() === '';
    if (Array.isArray(value)) return value.length === 0;
    return false;
  }

  function validateField(field, values) {
    if (field.show_if && !conditionMet(field.show_if, values)) return null;
    if (field.hide_if && conditionMet(field.hide_if, values)) return null;

    const value = values[field.id];
    const label = field.label || field.id;

    if (field.type === 'repeater') {
      for (const [index, entry] of (value || []).entries()) {
        for (const sub of field.fields) {
          const message = validateField(sub, entry);
          if (message) return `${field.item_label || 'Item'} ${index + 1}: ${message}`;
        }
      }
      return null;
    }

    if (isBlank(value)) return field.required ? `${label} is required` : null;

    if (field.type === 'multiselect') {
      if (field.min && value.length < field.min) return `${label}: choose at least ${field.min}`;
      if (field.max && value.length > field.max) return `${label}: choose at most ${field.max}`;
    }
    if (field.type === 'email' && !EMAIL.test(String(value).trim())) return `${label}: that doesn't look like an email`;
    if (field.type === 'tel' && !PHONE.test(String(value).trim())) return `${label}: that doesn't look like a phone number`;
    if (field.type === 'url' && !/^https?:\/\//i.test(String(value).trim())) return `${label}: links need to start with http:// or https://`;
    if (field.type === 'number') {
      const number = Number(value);
      if (Number.isNaN(number)) return `${label}: expected a number`;
      if (field.min !== undefined && number < field.min) return `${label}: must be ${field.min} or more`;
      if (field.max !== undefined && number > field.max) return `${label}: must be ${field.max} or less`;
    }
    return null;
  }

  function validateStep(step, values) {
    const problems = [];
    for (const field of step.fields || []) {
      const message = validateField(field, values);
      if (message) problems.push({ fieldId: field.id, message });
    }
    return problems;
  }

  function showErrors(container, problems) {
    container.querySelectorAll('.field').forEach((wrapper) => wrapper.classList.remove('invalid'));
    problems.forEach(({ fieldId, message }) => {
      const wrapper = container.querySelector(`[data-field="${fieldId}"]`);
      if (!wrapper) return;
      wrapper.classList.add('invalid');
      const slot = wrapper.querySelector('.err');
      if (slot) slot.textContent = message;
    });
    const first = container.querySelector('.field.invalid');
    if (first) first.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  /* The tool-stack picker is its own step kind rather than a field type: it
     renders straight from the taxonomy's groups, which no field definition
     knows about. Shared, because the wizard used to own it and the follow-up
     form on the report page needs exactly the same thing. */
  function renderToolStack(taxonomy, values, onChange) {
    const wrap = el('div', { class: 'card' });
    Object.entries(taxonomy.tool_stack || {}).forEach(([group, tools]) => {
      const selected = values[group] || (values[group] = []);
      wrap.append(el('div', { class: 'group-head', text: group }));
      const chips = el('div', { class: 'chips', 'data-group': group });
      tools.forEach((tool) => {
        const chip = el('button', {
          type: 'button', class: 'chip', text: tool, 'aria-pressed': selected.includes(tool),
          onclick: () => {
            const index = selected.indexOf(tool);
            if (index >= 0) selected.splice(index, 1);
            else selected.push(tool);
            chip.setAttribute('aria-pressed', selected.includes(tool));
            onChange();
          },
        });
        chips.append(chip);
      });
      wrap.append(chips);
    });
    return wrap;
  }

  /* Purely visual: groups a field-step's inputs into labelled sub-cards
     instead of one flat grid, for the steps where that reads better. Field
     ids not listed fall into the last group. Nothing about validation,
     persistence, or field order changes - this only decides which card a
     field's wrapper lands in. */
  const FIELD_GROUPS = {
    identity: [
      { label: 'Profile', hint: 'How you want to appear at the top of your profile.', fields: ['full_name', 'preferred_name'] },
      { label: 'Contact', hint: 'Ways recruiters and collaborators can reach you.', fields: ['email', 'phone'] },
      { label: 'Education & experience', hint: 'Where you studied and what hands-on experience you already have.', fields: ['city', 'state', 'college', 'degree', 'branch', 'current_year', 'graduation_year'] },
    ],
  };

  function renderFieldsStep(step, values, ctx) {
    const groups = FIELD_GROUPS[step.id];
    const scope = { container: null, fields: step.fields, values };
    ctx.scopes = [scope];

    if (!groups) {
      const grid = el('div', { class: 'grid' });
      scope.container = grid;
      step.fields.forEach((field) => grid.append(renderField(field, values, ctx)));
      applyConditions(scope);
      return el('div', { class: 'card' }, grid);
    }

    const byId = new Map(step.fields.map((field) => [field.id, field]));
    const placed = new Set();
    const wrap = el('div', { class: 'card field-groups' });
    scope.container = wrap;

    groups.forEach((group) => {
      const groupFields = group.fields.map((id) => byId.get(id)).filter(Boolean);
      groupFields.forEach((field) => placed.add(field.id));
      if (!groupFields.length) return;
      const grid = el('div', { class: 'grid' });
      groupFields.forEach((field) => grid.append(renderField(field, values, ctx)));
      wrap.append(el('div', { class: 'field-group' }, [
        el('div', { class: 'field-group-head' }, [
          el('h3', { text: group.label }),
          group.hint ? el('p', { text: group.hint }) : null,
        ]),
        grid,
      ]));
    });

    const leftover = step.fields.filter((field) => !placed.has(field.id));
    if (leftover.length) {
      const grid = el('div', { class: 'grid' });
      leftover.forEach((field) => grid.append(renderField(field, values, ctx)));
      wrap.append(el('div', { class: 'field-group' }, grid));
    }

    applyConditions(scope);
    return wrap;
  }

  return { el, renderFieldsStep, renderToolStack, renderField, validateStep, showErrors,
           applyConditions, optionsFor, setReference };
})();

/* A top-level const in a classic script never lands on window, and report.js
   and admin.js both look for it there. */
window.Fields = Fields;
