import { activeBooking, cheapestId, findFlight, rowMark, sortedFlights } from '../../state/selectors.js';
import { h, replay } from '../dom.js';
import { tripView } from './tripView.js';
import { approvalCard } from './approvalCard.js';
import { passengerForm } from './passengerForm.js';
import { createJourneyBar } from './journeyBar.js';
import { day, duration, moneyShort, stops, time } from '../format.js';

const SORTS = [['price', 'Cheapest'], ['departure', 'Earliest'], ['duration', 'Fastest']];

const MARK_LABEL = { pick: 'ATLAS pick', chosen: 'Your choice', pending: 'Awaiting your OK', booked: 'Booked' };

/**
 * Left pane, two modes:
 *   list  — route + sort · the ONE flight that matters now · all flights
 *   trip  — once a seat is held: status, ticket, payment (no list)
 */
export function createFlightsPane(root, { onChoose, onSort, onShowFlights, onDecide, onPay, onSync, onCancel, onPassengers }) {
  const title = h('h2', { class: 'pane-title' }, 'Flights');
  const sub = h('p', { class: 'pane-sub' }, 'Results appear here');
  const sortButtons = SORTS.map(([key, label]) =>
    h('button', { class: 'seg-btn', type: 'button', dataset: { sort: key }, onClick: () => onSort(key) }, label));
  const seg = h('div', { class: 'seg', role: 'group', 'aria-label': 'Sort flights' }, ...sortButtons);
  const toggle = h('button', { class: 'pane-toggle', type: 'button' });
  const trip = h('div', { class: 'trip-slot' });

  const feature = h('div', { class: 'feature-slot' });
  const listLabel = h('div', { class: 'list-label' });
  const list = h('ul', { class: 'flist' });
  const searching = h('div', { class: 'searching' });
  const empty = emptyState();
  const body = h('div', { class: 'pane-body' }, trip, feature, searching, listLabel, list, empty);

  const journey = createJourneyBar();   // this trip's progress, between the header and the content

  root.append(h('header', { class: 'pane-head' }, h('div', {}, title, sub), h('div', { class: 'head-right' }, seg, toggle)), journey.el, body);

  let showList = false;
  toggle.addEventListener('click', () => onShowFlights(!showList));

  let rows = new Map();

  function renderRows(state) {
    const cheapest = cheapestId(state.flights);
    rows = new Map();
    list.replaceChildren(...sortedFlights(state).map((f) => {
      const row = flightRow(f, f.flight_id === cheapest, onChoose);
      rows.set(f.flight_id, row);
      return row;
    }));
  }

  function markRows(state) {
    for (const [id, row] of rows) {
      const mark = rowMark(state, id);
      row.className = `frow ${mark ? `is-${mark}` : ''}`;
      row.querySelector('.f-mark').textContent = mark ? MARK_LABEL[mark] : '';
      const choose = row.querySelector('.f-choose');
      choose.hidden = Boolean(mark);
      choose.disabled = isBusy(state);
    }
  }

  return {
    update(state, prev) {
      journey.update(state);
      const booking = activeBooking(state);
      const tripMode = Boolean(booking) && !state.showFlights;
      showList = state.showFlights;
      root.classList.toggle('is-trip', tripMode);

      // toggle between "your trip" and "all flights" once something is booked
      toggle.hidden = !booking || (tripMode && !state.flights.length);
      toggle.textContent = tripMode ? 'Other flights' : '← Back to your trip';

      if (tripMode) {
        if (state.booking !== prev.booking || state.payment !== prev.payment || state.status !== prev.status
          || state.flights !== prev.flights || state.mock !== prev.mock || state.showFlights !== prev.showFlights
          || state.approval !== prev.approval || state.approvalSending !== prev.approvalSending) {
          trip.replaceChildren(tripView(state, { onDecide, onPay, onSync, onCancel, onShowFlights: () => onShowFlights(true) }));
          if (state.approval && !prev.approval) body.scrollTo({ top: 0, behavior: 'smooth' });
          const f = state.flights.find((x) => x.flight_id === booking.flight_id) ?? state.search;
          title.textContent = 'Your trip';
          sub.textContent = f?.origin
            ? `${f.origin.airport_code} → ${f.destination.airport_code} · ${day(f.departure_datetime)} · Ref ${booking.booking_reference}`
            : `Ref ${booking.booking_reference}`;
        }
        if (state.booking !== prev.booking && prev.booking?.lifecycle !== booking.lifecycle) {
          body.scrollTo({ top: 0, behavior: 'smooth' });
          const panel = trip.querySelector('.trip-status');
          if (panel) replay(panel, 'pulse-in');
        }
        seg.hidden = true;
        return;
      }
      trip.replaceChildren();
      if (prev.showFlights !== state.showFlights || (prev.booking && !booking)) prev = { ...prev, search: undefined, flights: undefined, sort: undefined };

      const q = state.search;
      if (q !== prev.search || state.flights !== prev.flights) {
        title.textContent = q ? `${q.origin} → ${q.destination}` : 'Flights';
        sub.textContent = q
          ? `${day(q.date + 'T00:00')} · ${q.passengers} adult${q.passengers > 1 ? 's' : ''} · ${cap(q.cabin)} · ${state.flights.length} flights`
          : 'Results appear here';
        listLabel.textContent = state.flights.length ? 'All flights' : '';
      }

      if (state.flights !== prev.flights || state.sort !== prev.sort) renderRows(state);

      if (state.flights !== prev.flights || state.sort !== prev.sort || state.selection !== prev.selection
        || state.approval !== prev.approval || state.booking !== prev.booking || state.status !== prev.status
        || state.approvalSending !== prev.approvalSending || state.passengerRequest !== prev.passengerRequest) {
        markRows(state);
        feature.replaceChildren(featureCard(state, onChoose, onDecide, onPassengers) ?? '');
      }

      // a new pick or booking: bring the featured card into view and pulse it
      if ((state.selection !== prev.selection && state.selection) || (state.booking !== prev.booking && state.booking)
        || (state.approval && !prev.approval) || (state.passengerRequest && !prev.passengerRequest)) {
        body.scrollTo({ top: 0, behavior: 'smooth' });
        const card = feature.firstElementChild;
        if (card) replay(card, 'pulse-in');
      }

      if (state.sort !== prev.sort) {
        sortButtons.forEach((b) => b.classList.toggle('is-active', b.dataset.sort === state.sort));
      }

      const isSearching = state.status.busy && state.status.stage === 'searching';
      if (isSearching) searching.replaceChildren(...searchingState(state.status.text));
      root.classList.toggle('is-searching', isSearching);
      root.classList.toggle('is-empty', state.flights.length === 0);
      seg.hidden = state.flights.length === 0;
    },
  };
}

// ---- pieces -------------------------------------------------------------------

function flightRow(f, isCheapest, onChoose) {
  return h('li', { class: 'frow', dataset: { flightId: f.flight_id } },
    h('span', { class: 'air-badge', style: `--hue: ${hue(f.flight_name)}` }, initials(f.flight_name)),
    h('div', { class: 'f-air' }, h('b', {}, f.flight_name), h('small', {}, cap(f.cabin))),
    h('div', { class: 'f-times' },
      h('b', {}, `${time(f.departure_datetime)} – ${time(f.arrival_datetime)}`),
      h('small', {}, `${f.origin.airport_code} → ${f.destination.airport_code}`)),
    h('div', { class: 'f-dur' },
      h('b', {}, duration(f.duration_minutes)),
      h('small', { class: f.stops.length ? 'has-stop' : '' }, stops(f))),
    h('div', { class: 'f-price' },
      h('b', {}, moneyShort(f.price, f.currency)),
      isCheapest ? h('small', { class: 'cheapest' }, 'Cheapest') : h('small', {}, 'per adult')),
    h('div', { class: 'f-end' },
      h('span', { class: 'f-mark' }),
      h('button', { class: 'f-choose', type: 'button', onClick: () => onChoose(f.flight_id) }, 'Choose')),
  );
}

/** The single most important flight right now, or nothing. */
function featureCard(state, onChoose, onDecide, onPassengers) {
  if (state.passengerRequest) return passengerForm(state, onPassengers);   // needs the user first
  if (state.approval) return approvalCard(state, onDecide);   // needs the user: nothing else matters

  // an active booking is shown by tripView; here only the pick (or a cancelled note)
  const sel = state.selection;
  if (sel && sel.flight_id === activeBooking(state)?.flight_id) return null;   // already your trip
  const justCancelled = state.booking?.lifecycle === 'cancelled' && (!sel || sel.flight_id === state.booking.flight_id);
  if (justCancelled || !sel) {
    return state.booking?.lifecycle === 'cancelled'
      ? h('article', { class: 'feature note' }, 'Booking cancelled. Nothing was charged. Choose another flight below or ask ATLAS.')
      : null;
  }

  const f = findFlight(state, sel.flight_id);
  if (!f) return null;
  const pending = state.approval?.flight_id === sel.flight_id;

  return h('article', { class: `feature pick ${pending ? 'is-pending' : ''}` },
    h('div', { class: 'feature-top' },
      h('span', { class: 'feature-kicker' }, sel.by === 'user' ? 'Your choice' : 'ATLAS recommends'),
      sel.reason ? h('span', { class: 'reason' }, sel.reason) : null),
    flightSummary(f),
    h('div', { class: 'feature-foot' },
      state.status.busy && state.status.stage === 'booking'
        ? h('span', { class: 'holding' }, h('span', { class: 'spinner sm' }), state.status.text)
        : pending
          ? h('span', { class: 'await' }, 'Waiting for your OK in the chat')
          : h('button', { class: 'btn-primary', type: 'button', disabled: isBusy(state), onClick: () => onChoose(f.flight_id) }, 'Book this flight'),
      h('b', { class: 'feature-price' }, moneyShort(f.price, f.currency))),
  );
}

function flightSummary(f) {
  return h('div', { class: 'summary' },
    h('span', { class: 'air-badge lg', style: `--hue: ${hue(f.flight_name)}` }, initials(f.flight_name)),
    h('div', { class: 'sum-main' },
      h('b', {}, f.flight_name),
      h('span', {}, `${day(f.departure_datetime)} · ${cap(f.cabin)}`)),
    h('div', { class: 'sum-leg' },
      h('div', {}, h('b', {}, time(f.departure_datetime)), h('small', {}, f.origin.airport_code)),
      h('div', { class: 'sum-path' }, h('small', {}, duration(f.duration_minutes)), h('i'), h('small', {}, stops(f))),
      h('div', {}, h('b', {}, time(f.arrival_datetime)), h('small', {}, f.destination.airport_code))),
  );
}

function searchingState(text) {
  return [
    h('div', { class: 'searching-text' }, h('span', { class: 'spinner' }), text),
    ...Array.from({ length: 5 }, () => h('div', { class: 'skeleton' })),
  ];
}

function emptyState() {
  return h('div', { class: 'empty' },
    h('div', { class: 'empty-art', 'aria-hidden': 'true' },
      h('span', { class: 'empty-orbit' }), h('span', { class: 'empty-plane' }, '✈')),
    h('h3', {}, 'Where to?'),
    h('p', {}, 'Tell ATLAS in the chat. It searches, picks the best option and asks before booking anything.'),
  );
}

// ---- small helpers ------------------------------------------------------------

function isBusy(state) {
  return state.status.busy || state.approvalSending;
}

function initials(name) {
  return name.split(/\s+/).map((w) => w[0]).join('').slice(0, 2).toUpperCase();
}

function hue(name) {
  let n = 0;
  for (const c of name) n = (n * 31 + c.charCodeAt(0)) % 360;
  return n;
}

function cap(text) {
  return text ? text[0].toUpperCase() + text.slice(1) : '';
}
