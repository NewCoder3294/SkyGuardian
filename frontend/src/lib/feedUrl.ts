/** Convert ws://host:port/ws into http://host:port/<path>. Single source of truth
 * for derived URLs (MJPEG, /health, etc.) — keeps host/port in sync with the WS
 * config so the dashboard works on any LAN host.
 *
 * Empty path → bare origin (no trailing slash). Avoids the double-slash bug
 * (`http://host//video/source`) that bit the SourceSelector. */
export function httpFromWs(wsUrl: string, path: string): string {
  try {
    const u = new URL(wsUrl);
    const scheme = u.protocol === "wss:" ? "https:" : "http:";
    const origin = `${scheme}//${u.host}`;
    if (!path) return origin;
    return `${origin}${path.startsWith("/") ? path : `/${path}`}`;
  } catch {
    return path;
  }
}
