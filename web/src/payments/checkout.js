import { h } from '../ui/dom.js';
import { moneyShort } from '../ui/format.js';

/**
 * Mount the payment provider's own checkout UI inside `container`.
 *
 * Resolves with what the BROWSER saw — never proof of payment:
 *   { outcome: 'submitted' }   user finished the provider's form
 *   { outcome: 'error', message }
 * Only the backend (webhook or /sync) may mark a payment paid.
 *
 * Cashfree: JS SDK v3, inline mode (redirectTarget = our element), so WE decide
 * when the sheet closes — after the backend says "paid".
 * Docs: https://www.cashfree.com/docs/payments/online/web/redirect
 */

const CASHFREE_SDK = 'https://sdk.cashfree.com/js/v3/cashfree.js';
let sdk;

export async function mountCheckout(container, payment, { onMockResult } = {}) {
  const { checkout } = payment;

  if (checkout.provider === 'mock') return mockCheckout(container, payment, onMockResult);

  const Cashfree = await loadCashfree();
  const cashfree = Cashfree({ mode: checkout.mode });          // 'sandbox' | 'production'
  const result = await cashfree.checkout({
    paymentSessionId: checkout.payment_session_id,
    redirectTarget: container,
  });

  if (result?.error) return { outcome: 'error', message: result.error.message };
  return { outcome: 'submitted' };
}

function loadCashfree() {
  sdk ??= new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = CASHFREE_SDK;
    script.onload = () => (window.Cashfree ? resolve(window.Cashfree) : reject(new Error('Cashfree SDK missing')));
    script.onerror = () => { sdk = null; reject(new Error('Could not load the Cashfree checkout. Check your connection.')); };
    document.head.append(script);
  });
  return sdk;
}

/** Demo stand-in for Cashfree's UI. No card data is collected. */
function mockCheckout(container, payment, onMockResult) {
  return new Promise((resolve) => {
    const finish = (outcome) => {
      container.querySelectorAll('button').forEach((b) => { b.disabled = true; });
      onMockResult?.(outcome);                 // the mock "provider" now notifies the backend
      resolve({ outcome: 'submitted' });
    };

    container.replaceChildren(
      h('div', { class: 'mock-checkout' },
        h('div', { class: 'mc-brand' }, h('b', {}, 'Cashfree'), h('span', {}, 'demo checkout')),
        h('div', { class: 'mc-amount' }, moneyShort(payment.amount, payment.currency)),
        h('div', { class: 'mc-order' }, `Order ${payment.payment_id}`),
        h('div', { class: 'mc-methods' },
          h('span', { class: 'is-on' }, 'Card'), h('span', {}, 'UPI'), h('span', {}, 'Netbanking')),
        h('div', { class: 'mc-card' }, h('span', {}, '•••• •••• •••• 1111'), h('span', {}, '12/30')),
        h('button', { class: 'mc-pay', type: 'button', onClick: () => finish('paid') },
          `Pay ${moneyShort(payment.amount, payment.currency)}`),
        h('button', { class: 'mc-fail', type: 'button', onClick: () => finish('failed') }, 'Simulate a declined payment'),
        h('p', { class: 'mc-note' }, 'Demo only — in production this box is Cashfree’s real checkout.'),
      ),
    );
  });
}
