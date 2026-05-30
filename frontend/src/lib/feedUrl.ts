/** Convert ws://host:port/ws into http://host:port/<path>. Single source of truth
 * for derived URLs (MJPEG, /health, etc.) — keeps host/port in sync with the WS
 * config so the dashboard works on any LAN host. */
export function httpFromWs(wsUrl: string, path: string): string {
  try {
    const u = new URL(wsUrl);
    const scheme = u.protocol === "wss:" ? "https:" : "http:";
    return `${scheme}//${u.host}${path.startsWith("/") ? path : `/${path}`}`;
  } catch {
    return path;
  }
}
