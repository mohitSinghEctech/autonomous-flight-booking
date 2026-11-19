import { mountCheckout } from '../../payments/checkout.js';
import { h } from '../dom.js';
import { moneyShort } from '../format.js';

const SYNC_AFTER_MS = 8000;   // no webhook yet? ask the backend to check with Cashfree itself

/**
 * The payment window. Phases (driven by SERVER events, not by the checkout's own result):
 *
 *   starting    POST /payments sent, waiting for payment.updated{checkout}
 *   checkout    provider UI mounted (Cashfree, or the demo stand-in)
 *   confirming  user finished the form; waiting for the backend to hear from Cashfree
 *   success     payment.updated{status:'paid'} -> brief tick, then the sheet closes itself
 *   failed      payment.updated{status:'failed'} -> Try again / Close
 */
export function createPaymentSheet({ onPay, onSync, onMockResult }) {
  const title = h('h3', {}, 'Secure payment');
  const amount = h('b', { class: 'ps-amount' });
  const view = h('div', { class: 'ps-view' });
  const host = h('div', { class: 'ps-checkout' });
  const closeBtn = h('button', { class: 'ps-close', type: 'button', 'aria-label': 'Close payment' }, '✕');

  const sheet = h('div', { class: 'ps-backdrop', hidden: true },
    h('section', { class: 'ps-sheet', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Payment' },
      h('header', { class: 'ps-head' },
        h('span', { class: 'ps-lock', 'aria-hidden': 'true' }, '🔒'),
        h('div', {}, title, h('small', {}, 'Processed by Cashfree')),
        amount, closeBtn),
      view, host));
  document.body.append(sheet);

  let open = false;
  let phase = 'closed';
  let mountedFor = null;        // payment_id whose checkout is mounted
  let syncTimer = null;
  let current = null;           // latest state

  closeBtn.addEventListener('click', () => close());
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && open && phase !== 'confirming') close(); });

  function show(next) {
    phase = next;
    sheet.dataset.phase = next;
    const p = current?.payment;
    closeBtn.hidden = next === 'confirming' || next === 'success';
    host.hidden = next !== 'checkout';

    const views = {
      starting: () => [spinnerLine('Opening secure checkout…')],
      checkout: () => [],
      confirming: () => [
        spinnerLine('Confirming your payment with Cashfree…'),
        h('p', { class: 'ps-hint' }, 'Keep this window open. It closes by itself once the payment is confirmed.'),
        syncTimer === 'fired'
          ? h('button', { class: 'ps-secondary', type: 'button', onClick: () => p && onSync(p.payment_id) }, 'Check again')
          : null,
      ],
      success: () => [h('div', { class: 'ps-done' }, h('span', { class: 'ps-tick' }, '✓'), h('h4', {}, 'Payment received'), h('p', {}, 'Your booking is confirmed.'))],
      failed: () => [
        h('div', { class: 'ps-done is-bad' }, h('span', { class: 'ps-tick' }, '!'), h('h4', {}, 'Payment failed'),
          h('p', {}, p?.failure_reason ?? 'The payment did not go through. Nothing was charged.')),
        h('div', { class: 'ps-actions' },
          h('button', { class: 'ps-secondary', type: 'button', onClick: () => close() }, 'Close'),
          h('button', { class: 'ps-primary', type: 'button', onClick: () => { mountedFor = null; onPay(); } }, 'Try again')),
      ],
    };
    view.replaceChildren(...(views[next]?.() ?? []));
  }

  async function mount(payment) {
    mountedFor = payment.payment_id;
    host.replaceChildren();
    show('checkout');
    try {
      const result = await mountCheckout(host, payment, { onMockResult: (outcome) => onMockResult?.(payment.payment_id, outcome) });
      if (!open || mountedFor !== payment.payment_id) return;
      if (result.outcome === 'error') {
        view.replaceChildren(h('p', { class: 'ps-error' }, result.message));
        return;
      }
      waitForServer(payment.payment_id);
    } catch (error) {
      view.replaceChildren(h('p', { class: 'ps-error' }, error.message));
    }
  }

  /** The browser's word is not enough. Wait for the backend; nudge it if the webhook is slow. */
  function waitForServer(paymentId) {
    if (['success', 'failed'].includes(phase)) return;
    show('confirming');
    clearTimeout(syncTimer);
    syncTimer = setTimeout(() => {
      if (phase !== 'confirming') return;
      onSync(paymentId);
      syncTimer = 'fired';
      show('confirming');
    }, SYNC_AFTER_MS);
  }

  function close() {
    open = false;
    phase = 'closed';
    clearTimeout(syncTimer);
    syncTimer = null;
    mountedFor = null;
    host.replaceChildren();
    sheet.hidden = true;
    document.body.classList.remove('sheet-open');
  }

  return {
    /** Called by the Pay / Resume buttons, before POST /payments. */
    open() {
      open = true;
      sheet.hidden = false;
      document.body.classList.add('sheet-open');
      const p = current?.payment;
      if (p?.checkout && p.status === 'created') {
        if (mountedFor !== p.payment_id) mount(p);       // resume an open checkout
      } else if (p?.status === 'pending') {
        waitForServer(p.payment_id);
      } else {
        show('starting');                                 // new payment on its way
      }
    },

    update,
  };

  function update(state, prev) {
    current = state;
    const p = state.payment;
    amount.textContent = p ? moneyShort(p.amount, p.currency) : '';
    if (!open || p === prev.payment) return;

    if (!p) return;
    if (p.status === 'paid') {
      show('success');
      clearTimeout(syncTimer);
      setTimeout(() => { if (phase === 'success') close(); }, 1600);   // the window closes itself
    } else if (p.status === 'failed' || p.status === 'expired') {
      clearTimeout(syncTimer);
      show('failed');
    } else if (p.status === 'pending') {
      waitForServer(p.payment_id);
    } else if (p.status === 'created' && p.checkout && mountedFor !== p.payment_id) {
      mount(p);
    }
  }
}

function spinnerLine(text) {
  return h('div', { class: 'ps-wait' }, h('span', { class: 'spinner' }), text);
}
