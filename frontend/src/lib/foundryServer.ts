/**
 * Server-only Foundry helpers shared by the /api/foundry routes.
 *
 * SECURITY: reads FOUNDRY_TOKEN from the environment and uses it solely as a
 * Bearer header. These functions run only inside route handlers (server), so
 * the token never reaches the client bundle.
 */

export interface FoundryEnv {
  host: string;
  token: string;
  ontology: string;
}

/** Resolve the core Foundry connection env, or null if not fully configured. */
export function readFoundryEnv(): FoundryEnv | null {
  const host = process.env.FOUNDRY_HOST;
  const token = process.env.FOUNDRY_TOKEN;
  const ontology = process.env.FOUNDRY_ONTOLOGY_RID;
  if (!host || !token || !ontology) return null;
  return { host: host.replace(/\/+$/, ""), token, ontology };
}

interface FoundryObjectsResponse {
  data: Array<Record<string, unknown>>;
}

/** Page one object type from the ontology. Throws on non-2xx. */
export async function fetchObjects(
  env: FoundryEnv,
  objectType: string,
  pageSize: number,
): Promise<Array<Record<string, unknown>>> {
  const url = `${env.host}/api/v2/ontologies/${env.ontology}/objects/${objectType}?pageSize=${pageSize}`;
  const res = await fetch(url, {
    headers: { Authorization: `Bearer ${env.token}` },
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`${objectType} fetch failed: HTTP ${res.status}`);
  }
  const body = (await res.json()) as FoundryObjectsResponse;
  return Array.isArray(body.data) ? body.data : [];
}

function num(v: unknown): number {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string") {
    const n = Number(v);
    return Number.isFinite(n) ? n : 0;
  }
  return 0;
}

function str(v: unknown): string {
  if (typeof v === "string") return v;
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  return "";
}

/**
 * Build a compact, factual context string from the mission + detection-class
 * objects for grounding the AIP language model. Deterministic ordering (by
 * mission id, then class count desc) so the same data yields the same prompt.
 */
export function buildMissionContext(
  missions: Array<Record<string, unknown>>,
  classes: Array<Record<string, unknown>>,
): string {
  const lines: string[] = [];
  lines.push(
    "SkyGuardian recon mission data (read-only, from Palantir Foundry). All counts are detections recorded by the Mavic recon drone.",
  );

  const sortedMissions = [...missions].sort((a, b) =>
    str(a.missionId).localeCompare(str(b.missionId)),
  );

  lines.push("");
  lines.push(`MISSIONS (${sortedMissions.length}):`);
  for (const m of sortedMissions) {
    const id = str(m.missionId) || "unnamed";
    const mc = classes
      .filter((c) => str(c.missionId) === str(m.missionId))
      .sort((a, b) => num(b.count) - num(a.count));
    const dets =
      mc.length > 0
        ? mc.map((c) => `${str(c.label)}=${num(c.count)}`).join(", ")
        : "none";
    lines.push(
      `- ${id}: frames_out=${num(m.framesOut)}, train=${num(m.trainCount)}, val=${num(m.valCount)}, vouched_frames=${num(m.gemmaLabeledCount)}; detections: ${dets}`,
    );
  }

  // Global totals per class label.
  const totals = new Map<string, number>();
  for (const c of classes) {
    const label = str(c.label);
    if (!label) continue;
    totals.set(label, (totals.get(label) ?? 0) + num(c.count));
  }
  const totalLine = [...totals.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([label, n]) => `${label}=${n}`)
    .join(", ");
  lines.push("");
  lines.push(`DETECTION TOTALS (all missions): ${totalLine || "none"}`);

  return lines.join("\n");
}
