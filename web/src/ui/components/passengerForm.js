import { h } from '../dom.js';

export const TITLES = [['mr', 'Mr'], ['ms', 'Ms'], ['mrs', 'Mrs'], ['miss', 'Miss'], ['dr', 'Dr']];

let cached = { id: null, el: null };

export function passengerForm(state, onSubmit) {
  const request = state.passengerRequest;
  if (!request) {
    cached = { id: null, el: null };
    return null;
  }

  if (cached.id !== request.request_id) {
    cached = { id: request.request_id, el: build(request, onSubmit) };
  }

  cached.el.classList.toggle('is-sending', state.approvalSending);
  cached.el.querySelectorAll('button, input[type="checkbox"]').forEach((b) => { b.disabled = state.approvalSending; });
  return cached.el;
}

function build(request, onSubmit) {
  const travellers = request.travellers ?? request.needed;
  const saved = request.existing ?? [];
  const picks = new Map();
  const error = h('p', { class: 'pf-error', role: 'alert' });
  const newList = h('div', { class: 'pf-new-list' });
  const counter = h('span', { class: 'pp-counter' });

  for (const p of saved) {
    if (p.complete && picks.size < travellers - request.needed) picks.set(p.id, { details: null, update_saved: false });
  }

  const savedList = h('ul', { class: 'pp-list' }, ...saved.map(row));

  function row(p) {
    const box = h('input', { type: 'checkbox', checked: picks.has(p.id), 'aria-label': `Select ${p.name}` });
    const name = h('b', {}, p.name);
    const meta = h('small', {}, summary(p));
    const tag = h('span', { class: 'pp-tag' });
    const li = h('li', { class: 'pp-row' },
      h('label', { class: 'pp-pick' }, box, h('span', { class: 'pp-who' }, name, meta)),
      tag,
      h('button', { type: 'button', class: 'pp-edit', onClick: () => openEditor(p, refresh) }, 'Edit'));

    box.addEventListener('change', () => {
      if (box.checked) picks.set(p.id, picks.get(p.id) ?? { details: null, update_saved: false });
      else picks.delete(p.id);
      refresh();
    });

    function refresh() {
      const pick = picks.get(p.id);
      const details = pick?.details;
      box.checked = Boolean(pick);
      name.textContent = details ? `${details.given_name} ${details.family_name}` : p.name;
      meta.textContent = summary(details ?? p);
      tag.textContent = details ? (pick.update_saved ? 'Will update saved' : 'This trip only') : (p.complete ? '' : 'Needs details');
      li.classList.toggle('is-picked', Boolean(pick));
      updateCounter();
    }

    li.refresh = refresh;
    queueMicrotask(refresh);
    return li;
  }

  function openEditor(p, refresh) {
    const current = picks.get(p.id);
    const values = current?.details ?? p;
    const update = h('input', { type: 'checkbox', name: 'update_saved' });
    const message = h('p', { class: 'pf-error', role: 'alert' });
    const fields = passengerFields(values);

    const close = () => { backdrop.remove(); document.body.classList.remove('sheet-open'); };

    const form = h('form', { class: 'pf-form pp-editor', novalidate: true },
      h('fieldset', { class: 'pf-person' }, h('legend', {}, 'Travel details for this booking'), fields),
      h('label', { class: 'pp-update' }, update, h('span', {}, 'Update details saved for this passenger')),
      message,
      h('div', { class: 'ap-actions' },
        h('button', { class: 'ap-no', type: 'button', onClick: close }, 'Cancel'),
        h('button', { class: 'ap-yes', type: 'submit' }, 'Save')));

    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const details = readPassenger(form);
      const problem = validatePassengers([details]);
      message.textContent = problem ?? '';
      if (problem) return;
      picks.set(p.id, { details, update_saved: update.checked });
      close();
      refresh();
    });

    const backdrop = h('div', { class: 'ps-backdrop', onClick: (e) => { if (e.target === backdrop) close(); } },
      h('section', { class: 'ps-sheet pp-sheet passenger-request', role: 'dialog', 'aria-modal': 'true', 'aria-label': `Edit ${p.name}` },
        h('div', { class: 'ap-head' }, h('span', { class: 'ap-kicker' }, 'Passenger details'), h('h3', {}, p.name)),
        form));

    document.body.append(backdrop);
    document.body.classList.add('sheet-open');
    fields.querySelector('input, select')?.focus();
  }

  function addNew() {
    const block = h('fieldset', { class: 'pf-person pf-new' },
      h('legend', {}, 'New passenger'),
      passengerFields(),
      h('button', { type: 'button', class: 'pp-remove', onClick: () => { block.remove(); updateCounter(); } }, 'Remove'));
    newList.append(block);
    updateCounter();
  }

  function chosenCount() {
    return picks.size + newList.querySelectorAll('fieldset').length;
  }

  function updateCounter() {
    counter.textContent = `${chosenCount()} of ${travellers} selected`;
    counter.classList.toggle('is-done', chosenCount() === travellers);
  }

  for (let i = 0; i < request.needed; i += 1) addNew();

  const form = h('form', { class: 'pf-form', novalidate: true },
    saved.length ? h('div', { class: 'pp-section' }, h('h4', {}, 'Saved passengers'), savedList) : null,
    newList,
    h('button', { type: 'button', class: 'pp-add', onClick: addNew }, '+ Add new passenger'),
    error,
    h('div', { class: 'ap-actions' },
      h('button', { class: 'ap-no', type: 'button', onClick: () => onSubmit(request.request_id, { decision: 'cancelled', passengers: [] }) }, 'Not now'),
      h('button', { class: 'ap-yes', type: 'submit' }, 'Continue')));

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const passengers = [...newList.querySelectorAll('fieldset')].map(readPassenger);
    const problem = checkChoice(passengers);
    error.textContent = problem ?? '';
    if (problem) return;
    const selected = [...picks].map(([id, pick]) => ({ id, details: pick.details, update_saved: Boolean(pick.details && pick.update_saved) }));
    onSubmit(request.request_id, { decision: 'provided', selected, passengers });
  });

  function checkChoice(passengers) {
    if (chosenCount() !== travellers) return `Choose exactly ${travellers} passenger${travellers > 1 ? 's' : ''} (${chosenCount()} selected).`;
    for (const [id, pick] of picks) {
      const p = saved.find((s) => s.id === id);
      if (!pick.details && p && !p.complete) return `${p.name} is missing travel details. Tap Edit to add them.`;
    }
    return validatePassengers(passengers);
  }

  return h('section', { class: 'approval passenger-request', 'aria-label': 'Choose passengers' },
    h('div', { class: 'ap-head' },
      h('span', { class: 'ap-kicker' }, 'Needs your input'),
      h('h3', {}, `Who is travelling?`),
      counter),
    h('p', { class: 'ap-note' }, request.message),
    form,
  );
}

function summary(p) {
  const parts = [p.born_on, p.email, p.phone_number].filter(Boolean);
  return parts.length ? parts.join(' · ') : 'No travel details yet';
}

/**
 * The seven fields the provider needs, as a .pf-grid. Shared with the account editor,
 * which passes saved values in. Field names = NewPassenger in events.py.
 */
export function passengerFields(values = {}) {
  const v = (name) => values[name] ?? '';
  return h('div', { class: 'pf-grid' },
    field('Title', select('title', v('title'), TITLES)),
    field('First name', h('input', { name: 'given_name', required: true, autocomplete: 'given-name', maxlength: '100', value: v('given_name') })),
    field('Last name', h('input', { name: 'family_name', required: true, autocomplete: 'family-name', maxlength: '100', value: v('family_name') })),
    field('Gender', select('gender', v('gender'), [['f', 'Female'], ['m', 'Male']])),
    field('Date of birth', h('input', { name: 'born_on', type: 'date', required: true, max: new Date().toISOString().slice(0, 10), value: v('born_on') })),
    field('Email', h('input', { name: 'email', type: 'email', required: true, autocomplete: 'email', value: v('email') })),
    field('Phone (with country code)', h('input', {
      name: 'phone_number', type: 'tel', required: true, placeholder: '+1 201 555 0123', autocomplete: 'tel', value: v('phone_number'),
    })),
  );
}

function select(name, current, options) {
  return h('select', { name, required: true },
    ...options.map(([value, label]) => h('option', { value, selected: value === current }, label)));
}

function field(label, input) {
  return h('label', { class: 'pf-field' }, h('span', {}, label), input);
}

/** Read one block of passengerFields() (any element that contains them). */
export function readPassenger(fieldset) {
  const value = (name) => fieldset.querySelector(`[name="${name}"]`).value.trim();
  return {
    title: value('title'),
    given_name: value('given_name'),
    family_name: value('family_name'),
    gender: value('gender'),
    born_on: value('born_on'),
    email: value('email'),
    phone_number: value('phone_number').replace(/[\s-]/g, ''),
  };
}

/** Same rules as the server (events.py NewPassenger), so most mistakes never leave the browser. */
export function validatePassengers(passengers) {
  for (const [i, p] of passengers.entries()) {
    const who = passengers.length > 1 ? `Passenger ${i + 1}: ` : '';
    if (!p.given_name || !p.family_name) return `${who}first and last name are required.`;
    if (!p.born_on) return `${who}date of birth is required.`;
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(p.email)) return `${who}enter a valid email.`;
    if (!/^\+[1-9]\d{7,14}$/.test(p.phone_number)) return `${who}phone must start with + and the country code, e.g. +12015550123.`;
  }
  return null;
}
