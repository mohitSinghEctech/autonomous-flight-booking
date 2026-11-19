import { h } from '../dom.js';
import { day, moneyShort, time } from '../format.js';
import { ROUTES, emptyState, errorState, loadingState, screenHead, statusPill } from './shared.js';

/** All of the user's bookings, newest first, 20 per page (GET /api/bookings). */
export function bookingsScreen({ api, close }) {
  const list = h('ul', { class: 'acct-list', 'aria-label': 'Bookings' });
  const body = h('div', { class: 'acct-body' }, loadingState('Loading your bookings…'));
  const more = h('button', { class: 'chip acct-more', type: 'button', hidden: true }, 'Load more');
  let cursor = null;

  more.addEventListener('click', () => load(cursor));
  load(null);

  return h('section', { class: 'acct-screen', 'aria-label': 'My bookings' },
    screenHead('My bookings', 'Every trip you held or booked with ATLAS'),
    body);

  async function load(from) {
    more.disabled = true;
    try {
      const page = await api.listBookings(from);
      cursor = page.next_cursor ?? null;

      if (!from && page.items.length === 0) {
        body.replaceChildren(emptyState('No bookings yet', 'Ask ATLAS to find a flight and your bookings will show up here.',
          h('button', { class: 'btn-primary', type: 'button', onClick: close }, 'Back to chat')));
        return;
      }

      list.append(...page.items.map(bookingRow));
      more.hidden = !cursor;
      body.replaceChildren(list, more);
    } catch (error) {
      body.replaceChildren(errorState(error, 'GET /api/bookings', () => {
        body.replaceChildren(loadingState());
        load(from);
      }));
    } finally {
      more.disabled = false;
    }
  }
}

function bookingRow(booking) {
  const f = booking.flight;
  return h('li', {},
    h('a', { class: 'acct-row', href: ROUTES.booking(booking.id) },
      h('div', { class: 'acct-row-main' },
        h('b', { class: 'acct-route' }, `${f.origin.airport_code} → ${f.destination.airport_code}`),
        h('span', { class: 'acct-row-sub' },
          `${day(f.departure_datetime)} · ${time(f.departure_datetime)} · ${f.flight_name}`),
      ),
      h('div', { class: 'acct-row-side' },
        statusPill(booking.lifecycle),
        h('span', { class: 'acct-ref' }, booking.booking_reference),
        h('b', { class: 'acct-amount' }, moneyShort(booking.total_amount, booking.currency)),
      ),
    ));
}
