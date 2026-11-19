/**
 * The UI talks to the API; served by the API itself at /web/ it uses the same origin.
 * In PROVIDER_MODE=offline the API answers with local stand-ins (no internet needed).
 *   index.html                       -> API at <same origin>/api (http://localhost:8000/api)
 *   index.html?api=https://host/api  -> another API
 *   index.html?theme=abyss-teal      -> pick a theme (else: last saved, else graphite-silver)
 */
const params = new URLSearchParams(location.search);

export const API_BASE = params.get('api') || (location.protocol.startsWith('http') ? `${location.origin}/api` : 'http://localhost:8000/api');
export const THEME = params.get('theme');
