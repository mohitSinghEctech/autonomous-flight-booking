import { CONTRACT_VERSION } from './contract.js';

/**
 * Plain HTTP calls (docs/api-contract.md §3 and §16).
 * Session writes return 202; results arrive over SSE. Account calls (§16) return their data directly.
 * Failures come back as { error: { code, message, retryable } } and are thrown as ApiError.
 */

export class ApiError extends Error {
  constructor(status, { code = 'http_error', message, retryable = false } = {}) {
    super(message ?? `Request failed (${status})`);
    this.status = status;
    this.code = code;
    this.retryable = retryable;
  }
}

export class ApiClient {
  /** @param {string} baseUrl  @param {() => Promise<string|null>} [getToken] */
  constructor(baseUrl, getToken = async () => null) {
    this.baseUrl = baseUrl;
    this.getToken = getToken;
  }

  /** One place for headers, auth and the error shape. body = undefined -> no request body. */
  async request(method, path, body) {
    const token = await this.getToken();
    let response;

    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        method,
        headers: {
          ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
          'X-Contract-Version': CONTRACT_VERSION,
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
    } catch {
      // also what a CORS preflight rejection looks like (e.g. PATCH/DELETE not allowed yet)
      throw new ApiError(0, { code: 'network_error', message: 'Could not reach the flight service.', retryable: true });
    }

    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new ApiError(response.status, payload.error ?? { message: `${response.status} ${path}` });
    }

    return response.status === 204 ? null : response.json();
  }

  post(path, body = {}) {
    return this.request('POST', path, body);
  }

  get(path) {
    return this.request('GET', path);
  }

  patch(path, body) {
    return this.request('PATCH', path, body);
  }

  delete(path) {
    return this.request('DELETE', path);
  }

  createSession() {
    return this.post('/sessions');                                            // 201 { thread_id }
  }

  sendMessage(threadId, text, clientId) {
    return this.post(`/sessions/${threadId}/messages`, { text, client_id: clientId });   // 202 { turn_id }
  }

  sendApproval(threadId, approvalId, decision) {
    return this.post(`/sessions/${threadId}/approvals/${approvalId}`, { decision });     // 202
  }

  selectFlight(threadId, flightId) {
    return this.post(`/sessions/${threadId}/flight-selection`, { flight_id: flightId }); // 202 { turn_id }
  }

  startPayment(threadId) {
    return this.post(`/sessions/${threadId}/payments`);                                  // 202 -> payment.updated
  }

  syncPayment(threadId, paymentId) {
    return this.post(`/sessions/${threadId}/payments/${paymentId}/sync`);                // 202 -> payment.updated
  }

  cancelBooking(threadId) {
    return this.post(`/sessions/${threadId}/booking/cancel`);                            // 202 -> approval.required
  }

  submitPassengers(threadId, requestId, body) {
    return this.post(`/sessions/${threadId}/passenger-requests/${requestId}`, body);      // 202 -> passenger.resolved
  }

  // ---- account REST (contract v1.2, PLANNED — backend not implemented yet) ----
  // Plain request/response: these read and edit saved data, they never start an agent turn.

  listBookings(cursor = null) {
    const q = cursor ? `&cursor=${encodeURIComponent(cursor)}` : '';
    return this.get(`/bookings?limit=20${q}`);                                    // 200 { items, next_cursor }
  }

  getBooking(id) {
    return this.get(`/bookings/${encodeURIComponent(id)}`);                       // 200 BookingDetail
  }

  cancelBookingById(id) {
    return this.post(`/bookings/${encodeURIComponent(id)}/cancel`);               // 200 BookingDetail
  }

  listPassengers() {
    return this.get('/passengers');                                               // 200 { items }
  }

  getPassenger(id) {
    return this.get(`/passengers/${encodeURIComponent(id)}`);                     // 200 PassengerProfile
  }

  createPassenger(body) {
    return this.post('/passengers', body);                                        // 201 PassengerProfile
  }

  updatePassenger(id, body) {
    return this.patch(`/passengers/${encodeURIComponent(id)}`, body);             // 200 PassengerProfile
  }

  deletePassenger(id) {
    return this.delete(`/passengers/${encodeURIComponent(id)}`);                  // 204
  }

  getMe() {
    return this.get('/me');                                                       // 200 Me
  }

  updateMe(body) {
    return this.patch('/me', body);                                               // 200 Me
  }

  async streamUrl(threadId) {
    // EventSource cannot send headers, so the token rides in the query string (§2).
    const token = await this.getToken();
    const q = token ? `?access_token=${encodeURIComponent(token)}` : '';
    return `${this.baseUrl}/sessions/${threadId}/stream${q}`;
  }
}
