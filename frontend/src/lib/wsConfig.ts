/** Single source of truth for the brain's WebSocket address.
 *
 * Both clients subscribe to the laptop "brain" over this WS. The backend binds
 * 0.0.0.0:8000 (backend/run.sh) and the mobile client targets :8000
 * (mobile/Sources/WorldClient.swift), so the dashboard must default to the same
 * port — otherwise it talks to a host nothing serves and the two maps render
 * different (or no) data. `NEXT_PUBLIC_WS_URL` overrides the default for
 * remote-brain / on-LAN setups (e.g. ws://192.168.10.1:8000/ws).
 */
export const DEFAULT_WS_URL = "ws://localhost:8000/ws";

/** Resolve the WS URL the dashboard should connect to. An override wins only
 *  when it is a non-empty, non-whitespace string; otherwise we fall back to the
 *  default so a blank env var can never produce an invalid `ws://` target. */
export function resolveWsUrl(override: string | undefined | null): string {
  const trimmed = override?.trim();
  return trimmed && trimmed.length > 0 ? trimmed : DEFAULT_WS_URL;
}
