/**
 * THE CONTRACT between UI and API — code form of docs/api-contract.md.
 * Mirrors flight_booking app/api/events.py. Change all three together and bump CONTRACT_VERSION.
 *
 * Every SSE message looks like:
 *   id: 42
 *   event: flights.results
 *   data: {"search_id": "...", "query": {...}, "flights": [...]}
 */

/** Major must match the server's (sent in session.snapshot). Minor = additive changes only. */
export const CONTRACT_VERSION = '1.1';

export const EVENTS = Object.freeze({
  SESSION_SNAPSHOT: 'session.snapshot', // full state; first event on every (re)connect
  STATUS: 'status',                     // { busy, stage, text }
  TURN_STARTED: 'turn.started',         // { turn_id, title }
  TURN_COMPLETED: 'turn.completed',     // { turn_id, outcome }
  STEP: 'step',                         // upsert by id (partial updates allowed)
  MESSAGE: 'message',                   // upsert by id
  FLIGHTS_RESULTS: 'flights.results',   // { search_id, query, flights[] }
  FLIGHTS_SELECTED: 'flights.selected', // { flight_id, by: 'ai'|'user', reason }
  APPROVAL_REQUIRED: 'approval.required',
  APPROVAL_RESOLVED: 'approval.resolved', // { approval_id, decision }
  PASSENGER_REQUIRED: 'passenger.required', // { request_id, needed, travellers, existing[], fields[], message }
  PASSENGER_RESOLVED: 'passenger.resolved', // v1.1 { request_id, decision, passengers[] }
  BOOKING_UPDATED: 'booking.updated',   // Booking | null
  PAYMENT_UPDATED: 'payment.updated',   // Payment | null
  ERROR: 'error',                       // { code, message, recoverable }
});

export const EVENT_TYPES = Object.values(EVENTS);

/** status.stage values. */
export const STAGES = Object.freeze([
  'idle', 'thinking', 'searching', 'loading_passengers', 'pricing',
  'awaiting_approval', 'booking', 'payment', 'error',
]);

/** Booking lifecycle, in order. 'cancelled' and 'expired' are terminal and shown separately. */
export const LIFECYCLE = ['awaiting_approval', 'held', 'awaiting_payment', 'confirmed'];

/** Payment status as the UI sees it. Only the SERVER moves a payment to paid/failed. */
export const PAYMENT_STATUS = Object.freeze(['created', 'pending', 'paid', 'failed', 'expired']);

/** error.code values (HTTP error bodies and the SSE error event). */
export const ERROR_CODES = Object.freeze([
  'validation_error', 'unauthenticated', 'forbidden', 'session_not_found',
  'turn_in_progress', 'approval_not_pending', 'approval_already_resolved',
  'flight_not_found', 'no_active_booking', 'booking_not_payable', 'payment_not_found',
  'provider_unavailable', 'provider_error', 'rate_limited', 'contract_mismatch', 'internal_error',
  // v1.2 PLANNED (account REST, §16) — backend not implemented
  'booking_not_found', 'booking_not_cancellable', 'passenger_not_found', 'passenger_in_use',
]);

/**
 * v1.2 – PLANNED, backend not implemented (docs/api-contract.md §16).
 * Account REST: plain request/response, no SSE, never starts an agent turn.
 * CONTRACT_VERSION stays '1.1' until the backend ships these and events.py is bumped too.
 */
export const ACCOUNT_ENDPOINTS = Object.freeze({
  LIST_BOOKINGS: 'GET /bookings?limit&cursor',     // 200 Page<BookingSummary>
  GET_BOOKING: 'GET /bookings/{id}',               // 200 BookingDetail · 404 booking_not_found
  CANCEL_BOOKING: 'POST /bookings/{id}/cancel',    // 200 BookingDetail · 409 booking_not_cancellable
  LIST_PASSENGERS: 'GET /passengers',              // 200 {items: PassengerProfile[]}
  CREATE_PASSENGER: 'POST /passengers',            // 201 PassengerProfile · 422 validation_error
  GET_PASSENGER: 'GET /passengers/{id}',           // 200 PassengerProfile · 404 passenger_not_found
  UPDATE_PASSENGER: 'PATCH /passengers/{id}',      // 200 PassengerProfile · 422
  DELETE_PASSENGER: 'DELETE /passengers/{id}',     // 204 · bookings keep their copy
  GET_ME: 'GET /me',                               // 200 Me
  UPDATE_ME: 'PATCH /me',                          // 200 Me · 422
});

/** Every lifecycle a saved booking can show in the account list (v1.2 adds ticketing_failed to the UI). */
export const BOOKING_LIFECYCLES = Object.freeze([
  'held', 'awaiting_payment', 'confirmed', 'cancelled', 'expired', 'ticketing_failed',
]);

/**
 * @typedef {{airport_code: string, airport_name: string}} Airport
 *
 * @typedef {object} Flight            // = app.models.Flight (+ duration_minutes)
 * @property {string} flight_id         // provider offer id; only valid until expires_at
 * @property {string} flight_name
 * @property {Airport} origin
 * @property {Airport} destination
 * @property {string} departure_datetime   // LOCAL airport time, no offset: "2026-10-10T06:58:00"
 * @property {string} arrival_datetime
 * @property {number} price             // total for all passengers, 2 dp
 * @property {string} currency          // ISO 4217
 * @property {string} cabin
 * @property {number} [duration_minutes]
 * @property {string} [expires_at]      // UTC, "…Z"
 * @property {{airport: Airport}[]} stops
 *
 * @typedef {object} Step
 * @property {string} id
 * @property {string} turn_id
 * @property {'llm'|'tool'|'provider'|'db'|'approval'|'system'} kind
 * @property {string} [tool]            // e.g. 'search_flights'
 * @property {string} title             // plain language: 'Searching flights'
 * @property {string} [detail]
 * @property {'running'|'waiting'|'done'|'failed'|'skipped'} status
 * @property {string} [started_at]      // UTC
 * @property {string} [ended_at]
 *
 * @typedef {object} Approval
 * @property {string} approval_id
 * @property {'book'|'change'|'cancel'} kind
 * @property {string} flight_id
 * @property {Flight} flight
 * @property {{id: string, name: string}[]} passengers
 * @property {number} total_amount
 * @property {string} currency
 * @property {string} message
 * @property {string} [expires_at]      // UTC; after this the server resolves it as 'expired'
 *
 * @typedef {object} Booking           // = app.models.Booking (+ flight_id, passengers)
 * @property {string} booking_id       // PROVIDER id (Duffel ord_...) — never our DB uuid
 * @property {string} booking_reference
 * @property {'held'|'awaiting_payment'|'confirmed'|'cancelled'|'expired'|'ticketing_failed'} lifecycle
 * @property {number} total_amount
 * @property {string} currency
 * @property {string|null} payment_required_by   // UTC
 * @property {string} flight_id
 * @property {{id: string, name: string}[]} [passengers]
 *
 * @typedef {object} Checkout          // what the browser needs to open the provider's payment UI
 * @property {'cashfree'|'mock'} provider
 * @property {'sandbox'|'production'} mode
 * @property {string} payment_session_id   // Cashfree payment_session_id (never a secret)
 * @property {string} [expires_at]
 *
 * @typedef {object} PassengerRequest
 * @property {string} request_id
 * @property {number} needed
 * @property {number} travellers
 * @property {{id: string, name: string, title: string|null, given_name: string, family_name: string, gender: string|null, born_on: string|null, email: string|null, phone_number: string|null, complete: boolean}[]} existing
 * @property {string[]} fields          // title, given_name, family_name, gender, born_on, email, phone_number
 * @property {string} message
 *
 * @typedef {object} Payment
 * @property {string} payment_id       // provider order id (Cashfree order_id)
 * @property {'created'|'pending'|'paid'|'failed'|'expired'} status
 * @property {number} amount
 * @property {string} currency
 * @property {Checkout|null} [checkout]   // present while status is created/pending
 * @property {string} [failure_reason]
 * @property {string} [paid_at]
 */

/**
 * ---- v1.2 PLANNED account shapes (§16) ----
 *
 * @typedef {object} BookingSummary
 * @property {string} id                // OUR booking uuid — the account API's path id
 * @property {string|null} booking_id   // provider id (Duffel ord_...), same meaning as Booking.booking_id
 * @property {string} booking_reference
 * @property {'held'|'awaiting_payment'|'confirmed'|'cancelled'|'expired'|'ticketing_failed'} lifecycle
 * @property {number} total_amount
 * @property {string} currency
 * @property {string|null} payment_required_by   // UTC
 * @property {string} created_at        // UTC
 * @property {Flight} flight            // rebuilt from the booking's flight snapshot (duration/stops may be empty)
 *
 * @typedef {BookingSummary & {
 *   passengers: {id: string, given_name: string, family_name: string}[],
 *   payment: {payment_id: string, status: 'created'|'pending'|'paid'|'failed'|'expired', amount: number, currency: string, paid_at?: string}|null
 * }} BookingDetail                    // payment has no checkout block here
 *
 * @typedef {object} PassengerProfile
 * @property {string} id
 * @property {'mr'|'ms'|'mrs'|'miss'|'dr'|null} title
 * @property {string} given_name
 * @property {string} family_name
 * @property {'m'|'f'|null} gender
 * @property {string|null} born_on     // YYYY-MM-DD
 * @property {string|null} email
 * @property {string|null} phone_number   // E.164
 * @property {boolean} complete        // all seven fields present (the provider needs them)
 * @property {number} booking_count
 *
 * @typedef {object} Me
 * @property {string} id
 * @property {string} given_name
 * @property {string} family_name
 * @property {string|null} email       // from the token, read-only
 *
 * @typedef {{items: object[], next_cursor: string|null}} Page
 */

/**
 * A transport is what the UI talks to:
 *   LiveTransport  (api/transport.js)      -> real FastAPI + SSE
 *
 * @typedef {object} Transport
 * @property {() => Promise<string>} openSession
 * @property {(threadId: string, onEvent: Function, onConnection: Function) => void} connect
 * @property {(text: string, clientId: string) => Promise<void>} sendMessage
 * @property {(approvalId: string, decision: 'approved'|'rejected') => Promise<void>} sendApproval
 * @property {(flightId: string) => Promise<void>} selectFlight
 * @property {() => Promise<void>} startPayment
 * @property {(paymentId: string) => Promise<void>} syncPayment
 * @property {() => Promise<void>} cancelBooking
 * @property {(requestId: string, body: {decision: 'provided'|'cancelled', passengers: object[], selected?: {id: string, details: object|null, update_saved: boolean}[]}) => Promise<void>} submitPassengers
 */
