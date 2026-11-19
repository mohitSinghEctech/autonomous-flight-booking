import { findFlight } from '../../state/selectors.js';
import { h } from '../dom.js';
import { approvalCard } from './approvalCard.js';
import { day, duration, moneyShort, stops, time } from '../format.js';

/**
 * Shown in the flights pane once a seat is held. No list — just this trip:
 *   status + next action  ·  ticket (flight details)  ·  payment  ·  quiet links
 */

const STAGES = ['Held', 'Payment', 'Confirmed'];

export function tripView(state, { onDecide, onShowFlights, onPay, onSync, onCancel }) {
  const booking = state.booking;
  const flight = findFlight(state, booking.flight_id);
  const busy = state.status.busy || state.approvalSending;

  return h('div', { class: 'trip' },
    state.approval ? approvalCard(state, onDecide) : null,
    statusPanel(state, booking, { onPay, onSync }),
    flight ? ticket(booking, flight) : null,
    paymentCard(state, booking),
    ['held', 'awaiting_payment'].includes(booking.lifecycle) && state.payment?.status !== 'paid' && !state.approval
      ? h('div', { class: 'trip-links' },
          h('button', { class: 'link', type: 'button', disabled: busy, onClick: onShowFlights }, 'Change flight'),
          h('button', { class: 'link danger', type: 'button', disabled: busy, onClick: onCancel }, 'Cancel booking'))
      : null,
  );
}

// ---- 1. where are we, and the one thing to do next --------------------------

function statusPanel(state, booking, { onPay, onSync }) {
  const busy = state.status.busy || Boolean(state.approval);
  const total = moneyShort(booking.total_amount, booking.currency);
  const p = state.payment;

  const view = booking.lifecycle === 'confirmed'
    ? { tone: 'ok', icon: '✓', title: "You're booked!", text: `Payment of ${total} received. Your e-ticket is below.`, step: 3 }
    : booking.lifecycle === 'ticketing_failed' || p?.status === 'paid'
      ? { tone: 'bad', icon: '!', title: 'Paid, ticket not issued',
          text: `Your payment of ${total} was received, but the airline did not issue the ticket. Do not pay again; contact support with ref ${booking.booking_reference}.`, step: 2 }
    : p?.status === 'pending'
      ? { tone: 'warn', icon: '⏳', title: 'Confirming your payment', text: 'Cashfree is confirming the payment. This updates by itself.', step: 1, wait: true }
      : p?.status === 'failed'
        ? { tone: 'bad', icon: '!', title: 'Payment failed', text: `${p.failure_reason ?? 'Nothing was charged.'} Your seat is still held.`, step: 1, action: ['Try again', onPay] }
        : p?.status === 'created'
          ? { tone: 'warn', icon: '💳', title: 'Payment not finished', text: 'Your secure checkout is still open. Resume it to confirm your seat.', step: 1,
              action: ['Resume payment', onPay], extra: ['Already paid? Check status', () => onSync(p.payment_id)] }
          : { tone: 'warn', icon: '⏳', title: 'Seat on hold',
              text: booking.payment_required_by ? `Pay by ${day(booking.payment_required_by)} to keep it${daysLeft(booking.payment_required_by)}` : 'Pay to confirm your seat',
              step: 1, action: [`Pay ${total}`, onPay] };

  const working = state.status.busy && state.status.stage === 'payment';

  return h('section', { class: `trip-status is-${view.tone}` },
    h('div', { class: 'ts-main' },
      h('span', { class: 'ts-icon', 'aria-hidden': 'true' }, view.icon),
      h('div', {},
        h('h3', {}, view.title),
        h('p', {}, view.text)),
      view.action
        ? h('button', { class: 'btn-primary ts-action', type: 'button', disabled: busy, onClick: view.action[1] },
            working ? h('span', { class: 'spinner sm' }) : null, working ? state.status.text : view.action[0])
        : view.wait ? h('span', { class: 'ts-wait' }, h('span', { class: 'spinner' })) : null),
    view.extra
      ? h('button', { class: 'link ts-extra', type: 'button', disabled: busy, onClick: view.extra[1] }, view.extra[0])
      : null,
    h('ol', { class: 'ts-steps' },
      ...STAGES.map((label, i) => h('li', {
        class: i < view.step ? 'is-done' : i === view.step ? 'is-current' : '',
      }, h('i', {}, i < view.step ? '✓' : ''), label))),
  );
}

// ---- 2. the flight, as a ticket ---------------------------------------------

function ticket(booking, f) {
  const confirmed = booking.lifecycle === 'confirmed';
  const passengers = booking.passengers ?? [];

  return h('article', { class: `ticket ${confirmed ? 'is-confirmed' : ''}` },
    h('div', { class: 'tk-main' },
      h('div', { class: 'tk-top' },
        h('div', {},
          h('b', { class: 'tk-airline' }, f.flight_name),
          h('span', { class: 'tk-date' }, `${day(f.departure_datetime)} · ${cap(f.cabin)}`)),
        confirmed ? h('span', { class: 'tk-stamp' }, 'Confirmed')
          : h('span', { class: 'tk-hold' }, booking.lifecycle === 'ticketing_failed' ? 'Not ticketed' : 'On hold')),
      h('div', { class: 'tk-route' },
        h('div', { class: 'tk-end' },
          h('b', {}, time(f.departure_datetime)),
          h('span', {}, f.origin.airport_code),
          h('small', {}, f.origin.airport_name)),
        h('div', { class: 'tk-path' },
          h('small', {}, duration(f.duration_minutes)),
          h('span', { class: 'tk-line' }, h('i', {}, '✈')),
          h('small', { class: f.stops.length ? 'has-stop' : '' }, stops(f))),
        h('div', { class: 'tk-end right' },
          h('b', {}, time(f.arrival_datetime)),
          h('span', {}, f.destination.airport_code),
          h('small', {}, f.destination.airport_name))),
      h('dl', { class: 'tk-facts' },
        fact('Passenger' + (passengers.length > 1 ? 's' : ''), passengers.map((p) => p.name).join(', ') || '—'),
        fact('Cabin', cap(f.cabin)),
        fact('Departs', `${day(f.departure_datetime)}, ${time(f.departure_datetime)}`)),
    ),
    h('div', { class: 'tk-stub' },
      fact('Booking ref', booking.booking_reference, 'ref'),
      fact('Total', moneyShort(booking.total_amount, booking.currency), 'total'),
      h('code', { class: 'tk-id', title: 'Booking ID at the airline provider (Duffel)' }, booking.booking_id)),
  );
}

// ---- 3. payment --------------------------------------------------------------

function paymentCard(state, booking) {
  const p = state.payment;
  const status = !p ? ['Not started', 'none']
    : { created: ['Checkout open', 'warn'], pending: ['Confirming', 'warn'], paid: ['Paid', 'ok'], failed: ['Failed', 'bad'], expired: ['Expired', 'bad'] }[p.status];

  return h('section', { class: 'pay-card' },
    h('h4', {}, 'Payment'),
    row('Status', h('span', { class: `pay-pill is-${status[1]}` }, status[0])),
    row('Amount', moneyShort(p?.amount ?? booking.total_amount, p?.currency ?? booking.currency)),
    row('Provider', state.mock ? 'Cashfree · demo' : 'Cashfree'),
    p ? row('Order ID', h('code', {}, p.payment_id)) : null,
    p?.paid_at ? row('Paid at', new Date(p.paid_at).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })) : null,
  );
}

// ---- helpers -----------------------------------------------------------------

function fact(label, value, cls = '') {
  return h('div', { class: `fact ${cls}` }, h('dt', {}, label), h('dd', {}, value));
}

function row(label, value) {
  return h('div', { class: 'pc-row' }, h('span', {}, label), h('b', {}, value));
}

function daysLeft(iso) {
  const days = Math.ceil((Date.parse(iso) - Date.now()) / 86_400_000);
  if (!Number.isFinite(days)) return '';
  return days <= 0 ? ' · due today' : ` · ${days} day${days === 1 ? '' : 's'} left`;
}

function cap(text) {
  return text ? text[0].toUpperCase() + text.slice(1) : '';
}
