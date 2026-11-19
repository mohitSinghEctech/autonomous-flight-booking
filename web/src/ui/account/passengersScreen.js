import { h } from '../dom.js';
import { day } from '../format.js';
import { ROUTES, emptyState, errorState, fullName, loadingState, screenHead } from './shared.js';

/** Saved travellers (GET /api/passengers). ATLAS picks from these when you book. */
export function passengersScreen({ api }) {
  const add = h('a', { class: 'btn-primary acct-link-btn', href: ROUTES.newPassenger }, '+ Add passenger');
  const body = h('div', { class: 'acct-body' }, loadingState('Loading passengers…'));
  load();

  return h('section', { class: 'acct-screen', 'aria-label': 'Passengers' },
    screenHead('Passengers', 'People you book for. ATLAS uses these details when it holds a flight.', add),
    body);

  async function load() {
    try {
      const { items } = await api.listPassengers();
      body.replaceChildren(items.length
        ? h('ul', { class: 'acct-list', 'aria-label': 'Saved passengers' }, ...items.map(passengerRow))
        : emptyState('No passengers yet', 'Add yourself and anyone you travel with, so booking is one tap.'));
    } catch (error) {
      body.replaceChildren(errorState(error, 'GET /api/passengers', () => {
        body.replaceChildren(loadingState());
        load();
      }));
    }
  }
}

function passengerRow(p) {
  return h('li', {},
    h('a', { class: 'acct-row', href: ROUTES.passenger(p.id) },
      h('div', { class: 'acct-row-main' },
        h('b', {}, fullName(p)),
        h('span', { class: 'acct-row-sub' }, [p.email, p.phone_number].filter(Boolean).join(' · ') || 'Details missing'),
      ),
      h('div', { class: 'acct-row-side' },
        p.born_on ? h('span', { class: 'acct-row-sub' }, `Born ${day(p.born_on)}`) : null,
        p.complete === false ? h('span', { class: 'acct-pill', dataset: { status: 'held' } }, 'Incomplete') : null,
      ),
    ));
}
