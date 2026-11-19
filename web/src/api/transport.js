import { ApiClient } from './client.js';
import { CONTRACT_VERSION, EVENTS, EVENT_TYPES } from './contract.js';

const THREAD_KEY = 'atlas.thread_id';

/**
 * Real backend: POST for actions, one long-lived EventSource for everything back.
 *
 * Stability rules (docs/api-contract.md §4):
 *  - EventSource reconnects by itself and sends Last-Event-ID; the server replays what we missed.
 *  - Event ids increase per thread, so anything <= the last id we applied is a duplicate: skip it.
 *  - The first event after (re)connect is session.snapshot; its contract_version must match ours.
 *  - The stream's token rides in its URL and expires after an hour. When the browser gives up
 *    (401 -> CLOSED) we reconnect ourselves with a fresh token, backing off up to 30 s.
 *  - The saved thread id is per signed-in user: the server answers 404 for someone else's thread.
 */
export class LiveTransport {
  constructor(baseUrl, { getToken } = {}) {
    this.api = new ApiClient(baseUrl, getToken);
    this.threadId = null;
    this.source = null;
    this.lastId = 0;
    this.retryDelay = 1000;
  }

  /** atlas.thread_id.<firebase uid>, so two people on one browser never share a conversation. */
  async threadKey() {
    const token = await this.api.getToken();
    return `${THREAD_KEY}.${tokenSubject(token) ?? 'anonymous'}`;
  }

  async openSession() {
    const key = await this.threadKey();
    const saved = safeGet(key);
    if (saved) {
      this.threadId = saved;
      return saved;
    }

    const { thread_id } = await this.api.createSession();
    safeSet(key, thread_id);
    this.threadId = thread_id;
    return thread_id;
  }

  async connect(threadId, onEvent, onConnection) {
    onConnection('connecting');

    this.source?.close();
    const source = new EventSource(await this.api.streamUrl(threadId));   // fresh token every time
    this.source = source;

    source.onopen = () => {
      this.retryDelay = 1000;
      onConnection('online');
    };
    source.onerror = () => {
      if (source.readyState !== EventSource.CLOSED) {
        onConnection('reconnecting');            // the browser retries by itself (network blip)
        return;
      }
      // the browser gave up (e.g. 401 with an expired token): try again with a new URL
      onConnection('reconnecting');
      const delay = this.retryDelay;
      this.retryDelay = Math.min(this.retryDelay * 2, 30000);
      setTimeout(() => {
        if (this.source === source) this.connect(threadId, onEvent, onConnection);
      }, delay);
    };

    for (const type of EVENT_TYPES) {
      source.addEventListener(type, (message) => {
        const id = Number(message.lastEventId);
        if (id && id <= this.lastId && type !== EVENTS.SESSION_SNAPSHOT) return;   // replayed duplicate
        if (id) this.lastId = id;

        const data = JSON.parse(message.data);

        if (type === EVENTS.SESSION_SNAPSHOT && major(data.contract_version) !== major(CONTRACT_VERSION)) {
          onEvent({ type: EVENTS.ERROR, id: null, data: {
            code: 'contract_mismatch', recoverable: false,
            message: `This page speaks contract ${CONTRACT_VERSION}, the server speaks ${data.contract_version}. Reload after both are updated.`,
          } });
          source.close();
          this.source = null;                    // stops the reconnect loop: this one is fatal
          return;
        }

        onEvent({ type, id: message.lastEventId, data });
      });
    }
  }

  sendMessage(text, clientId) {
    return this.api.sendMessage(this.threadId, text, clientId);
  }

  sendApproval(approvalId, decision) {
    return this.api.sendApproval(this.threadId, approvalId, decision);
  }

  selectFlight(flightId) {
    return this.api.selectFlight(this.threadId, flightId);
  }

  startPayment() {
    return this.api.startPayment(this.threadId);
  }

  syncPayment(paymentId) {
    return this.api.syncPayment(this.threadId, paymentId);
  }

  cancelBooking() {
    return this.api.cancelBooking(this.threadId);
  }

  submitPassengers(requestId, body) {
    return this.api.submitPassengers(this.threadId, requestId, body);
  }
}

/** The uid inside a Firebase ID token (not verified here — the server does that). */
function tokenSubject(token) {
  try {
    const payload = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(atob(payload)).sub ?? null;
  } catch {
    return null;
  }
}

function major(version) {
  return String(version ?? '0').split('.')[0];
}

function safeGet(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}

function safeSet(key, value) {
  try { localStorage.setItem(key, value); } catch { /* private mode: fine */ }
}
