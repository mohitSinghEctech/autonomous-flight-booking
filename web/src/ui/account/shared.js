import { h } from '../dom.js';

/**
 * Small pieces every account screen uses: routes, the three data states
 * (loading / empty / error) and the status pill.
 *
 * Account data comes from plain REST calls (contract §16, v1.2 PLANNED).
 * Until the backend has them, every call fails — the error state says so.
 */

// ---- routes (location.hash, so Back works and screens can be bookmarked) --------

export const ROUTES = {
  bookings: '#account/bookings',
  booking: (id) => `#account/bookings/${encodeURIComponent(id)}`,
  passengers: '#account/passengers',
  newPassenger: '#account/passengers/new',
  passenger: (id) => `#account/passengers/${encodeURIComponent(id)}`,
  profile: '#account/profile',
};

/** '#account/bookings/abc' -> { screen: 'booking', id: 'abc' }; anything else -> null (not in account). */
export function parseRoute(hash) {
  const [root, section, id] = hash.replace(/^#/, '').split('/').map(decodeURIComponent);
  if (root !== 'account') return null;

  if (section === 'passengers') {
    if (id === 'new') return { screen: 'newPassenger' };
    return id ? { screen: 'passenger', id } : { screen: 'passengers' };
  }
  if (section === 'profile') return { screen: 'profile' };
  return id ? { screen: 'booking', id } : { screen: 'bookings' };
}

// ---- data states --------------------------------------------------------------------

export function loadingState(text = 'Loading…') {
  return h('div', { class: 'acct-state', role: 'status' }, h('span', { class: 'acct-spinner', 'aria-hidden': 'true' }), text);
}

export function emptyState(title, text, ...actions) {
  return h('div', { class: 'acct-state' },
    h('h3', {}, title),
    h('p', {}, text),
    actions.length ? h('div', { class: 'acct-actions' }, ...actions) : null);
}

/** Codes the planned endpoints use for "that id isn't yours / doesn't exist". */
const REAL_NOT_FOUND = ['booking_not_found', 'passenger_not_found'];

/**
 * True when the endpoint itself is missing, not the record:
 *  - 404 from FastAPI's catch-all (it reports code 'session_not_found', message 'Not Found')
 *  - 405 (path exists for another method)
 *  - status 0: network error, or the CORS preflight refused PATCH/DELETE
 */
export function isNotAvailable(error) {
  if (error?.status === 0 || error?.status === 405) return true;
  return error?.status === 404 && !REAL_NOT_FOUND.includes(error.code);
}

/** endpoint = 'GET /api/bookings' — shown so it's obvious what the backend still needs. */
export function errorState(error, endpoint, retry) {
  const missing = isNotAvailable(error);
  return h('div', { class: 'acct-state is-error', role: 'alert' },
    h('h3', {}, missing ? 'Not available yet' : 'Something went wrong'),
    h('p', {}, missing
      ? 'This screen needs an API endpoint the backend doesn\'t have yet (contract v1.2, planned):'
      : error.message),
    missing ? h('code', { class: 'acct-endpoint' }, endpoint) : null,
    retry ? h('div', { class: 'acct-actions' }, h('button', { class: 'chip', type: 'button', onClick: retry }, '⟳ Try again')) : null);
}

/** The message to put next to a form after a failed write. */
export function writeErrorText(error, endpoint) {
  return isNotAvailable(error) ? `Not available yet: the backend has no ${endpoint} (contract v1.2, planned).` : error.message;
}

// ---- display ------------------------------------------------------------------------

const STATUS_LABEL = {
  held: 'Held',
  awaiting_payment: 'Awaiting payment',
  confirmed: 'Confirmed',
  cancelled: 'Cancelled',
  expired: 'Expired',
  ticketing_failed: 'Ticketing failed',
};

export function statusPill(lifecycle) {
  return h('span', { class: 'acct-pill', dataset: { status: lifecycle } }, STATUS_LABEL[lifecycle] ?? lifecycle);
}

export function screenHead(title, sub, ...right) {
  return h('header', { class: 'acct-head' },
    h('div', {}, h('h2', { class: 'acct-title', tabindex: '-1' }, title), sub ? h('p', { class: 'pane-sub' }, sub) : null),
    right.length ? h('div', { class: 'acct-actions' }, ...right) : null);
}

/** UTC timestamp -> "15 Oct 2026, 14:05" in the viewer's own time zone. */
export function dateTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' });
}

export function fullName(p) {
  return [p.given_name, p.family_name].filter(Boolean).join(' ') || p.name || 'Unnamed';
}
