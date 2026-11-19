/* ─────────────────────────────────────────────────────────────────────────
   Host seam: what the page around the flight UI provides.

   Standalone (this repo): no sign-in. The API runs with AUTH_MODE=demo,
   so every request is the demo user and no token is sent.

   Contract (used by src/main.js):
     ready(): Promise<{ email } | null>   resolves once the user may see the page
     token(): Promise<string | null>      bearer token for the API (optional)
     links:   { label, href?, onClick? }[]  rendered in the header
   ───────────────────────────────────────────────────────────────────────── */

export const host = {
  name: "standalone",

  token: async () => null,

  async ready() {
    return { email: "demo user (AUTH_MODE=demo)" };
  },

  links: [],
};
