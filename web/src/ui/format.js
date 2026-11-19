/**
 * Duffel times are LOCAL airport times with no offset ("2026-10-10T06:58:00").
 * So we slice strings instead of using Date (which would shift timezones),
 * and we never compute duration from dep/arr — that needs duration_minutes.
 */

export function time(iso) {
  return iso ? iso.slice(11, 16) : '--:--';
}

export function day(iso) {
  if (!iso) return '';
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-GB', {
    weekday: 'short', day: '2-digit', month: 'short', timeZone: 'UTC',
  });
}

export function duration(minutes) {
  if (minutes == null) return '—';
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `${h}h ${String(m).padStart(2, '0')}m`;
}

export function money(amount, currency) {
  if (amount == null) return '—';
  try {
    return new Intl.NumberFormat('en-GB', { style: 'currency', currency }).format(amount);
  } catch {
    return `${currency} ${Number(amount).toFixed(2)}`;
  }
}

export function stops(flight) {
  const count = flight.stops?.length ?? 0;
  if (count === 0) return 'Nonstop';
  const via = flight.stops.map((s) => s.airport.airport_code).join(', ');
  return `${count} stop · ${via}`;
}

export function elapsed(fromIso, toIso) {
  const ms = (toIso ? Date.parse(toIso) : Date.now()) - Date.parse(fromIso);
  if (!Number.isFinite(ms) || ms < 0) return '';
  return ms < 10_000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms / 1000)}s`;
}

export function pad2(n) {
  return String(n).padStart(2, '0');
}

export function capitalize(text) {
  return text ? text[0].toUpperCase() + text.slice(1) : '';
}

/** £96 instead of £96.00; keeps pence when there are any. */
export function moneyShort(amount, currency) {
  if (amount == null) return '—';
  const whole = Number.isInteger(Number(amount));
  try {
    return new Intl.NumberFormat('en-GB', {
      style: 'currency', currency, minimumFractionDigits: whole ? 0 : 2, maximumFractionDigits: 2,
    }).format(amount);
  } catch {
    return `${currency} ${amount}`;
  }
}
