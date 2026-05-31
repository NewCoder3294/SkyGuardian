/**
 * Foundry Data — client types, fetch helper, and pure aggregation/query
 * helpers over the mission + detection-class objects served by the
 * /api/foundry route. No side effects in the helpers (no Date/random) so they
 * stay deterministic and testable.
 */

export interface CaptureMission {
  missionId: string;
  classes: string;
  framesOut: number;
  trainCount: number;
  valCount: number;
  droppedCorrupt: number;
  droppedDuplicate: number;
  recordsInvalid: number;
  gemmaCount: number;
  gemmaLabeledCount: number;
  confirmCount: number;
  rejectCount: number;
  correctCount: number;
  createdT: string;
  datasetRid: string;
}

export interface DetectionClass {
  classKey: string;
  missionId: string;
  label: string;
  count: number;
  train: number;
  val: number;
}

export interface FoundryData {
  configured: boolean;
  error?: string;
  missions: CaptureMission[];
  classes: DetectionClass[];
}

/** Raw Foundry object shape — props may arrive as unknown until narrowed. */
type RawObject = Record<string, unknown>;

function asString(v: unknown): string {
  if (typeof v === "string") return v;
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  return "";
}

function asNumber(v: unknown): number {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string") {
    const n = Number(v);
    return Number.isFinite(n) ? n : 0;
  }
  return 0;
}

function toMission(o: RawObject): CaptureMission {
  return {
    missionId: asString(o.missionId),
    classes: asString(o.classes),
    framesOut: asNumber(o.framesOut),
    trainCount: asNumber(o.trainCount),
    valCount: asNumber(o.valCount),
    droppedCorrupt: asNumber(o.droppedCorrupt),
    droppedDuplicate: asNumber(o.droppedDuplicate),
    recordsInvalid: asNumber(o.recordsInvalid),
    gemmaCount: asNumber(o.gemmaCount),
    gemmaLabeledCount: asNumber(o.gemmaLabeledCount),
    confirmCount: asNumber(o.confirmCount),
    rejectCount: asNumber(o.rejectCount),
    correctCount: asNumber(o.correctCount),
    createdT: asString(o.createdT),
    datasetRid: asString(o.datasetRid),
  };
}

function toClass(o: RawObject): DetectionClass {
  return {
    classKey: asString(o.classKey),
    missionId: asString(o.missionId),
    label: asString(o.label),
    count: asNumber(o.count),
    train: asNumber(o.train),
    val: asNumber(o.val),
  };
}

interface RawFoundryResponse {
  configured: boolean;
  error?: string;
  missions?: RawObject[];
  classes?: RawObject[];
}

/** Client fetch helper — GETs the server route and narrows the payload. */
export async function fetchData(): Promise<FoundryData> {
  const res = await fetch("/api/foundry", { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  const body = (await res.json()) as RawFoundryResponse;
  if (!body.configured) {
    return { configured: false, missions: [], classes: [] };
  }
  return {
    configured: true,
    error: body.error,
    missions: Array.isArray(body.missions) ? body.missions.map(toMission) : [],
    classes: Array.isArray(body.classes) ? body.classes.map(toClass) : [],
  };
}

// ---- pure aggregation helpers --------------------------------------------

export interface ClassTotal {
  label: string;
  total: number;
}

/** Summed detection count per class label, sorted desc. */
export function detectionsByClass(classes: DetectionClass[]): ClassTotal[] {
  const byLabel = new Map<string, number>();
  for (const c of classes) {
    if (!c.label) continue;
    byLabel.set(c.label, (byLabel.get(c.label) ?? 0) + c.count);
  }
  return [...byLabel.entries()]
    .map(([label, total]) => ({ label, total }))
    .sort((a, b) => b.total - a.total);
}

export interface DataTotals {
  missionCount: number;
  totalDetections: number;
  distinctClasses: number;
  vouchedFrames: number;
}

export function totals(
  missions: CaptureMission[],
  classes: DetectionClass[],
): DataTotals {
  const distinct = new Set<string>();
  let totalDetections = 0;
  for (const c of classes) {
    if (c.label) distinct.add(c.label);
    totalDetections += c.count;
  }
  let vouchedFrames = 0;
  for (const m of missions) vouchedFrames += m.gemmaLabeledCount;
  return {
    missionCount: missions.length,
    totalDetections,
    distinctClasses: distinct.size,
    vouchedFrames,
  };
}

/** Classes belonging to one mission, sorted desc by count. */
export function classesForMission(
  classes: DetectionClass[],
  missionId: string,
): DetectionClass[] {
  return classes
    .filter((c) => c.missionId === missionId)
    .sort((a, b) => b.count - a.count);
}

// ---- deterministic local query responder ---------------------------------

function fmt(n: number): string {
  return n.toLocaleString("en-US");
}

function summarizeMission(
  mission: CaptureMission,
  classes: DetectionClass[],
): string {
  const mc = classesForMission(classes, mission.missionId);
  const labels =
    mc.length > 0
      ? mc.map((c) => `${c.label} ${fmt(c.count)}`).join(", ")
      : mission.classes || "no classes recorded";
  return `${mission.missionId.toUpperCase()}: ${labels} · ${fmt(mission.framesOut)} frames out (train ${fmt(mission.trainCount)} / val ${fmt(mission.valCount)}) · ${fmt(mission.gemmaLabeledCount)} vouched frames.`;
}

/**
 * Answer a small set of natural-language patterns over the loaded data.
 * Case-insensitive, pure, deterministic. Returns a single tactical line.
 */
export function answerData(
  query: string,
  missions: CaptureMission[],
  classes: DetectionClass[],
): string {
  const q = query.trim().toLowerCase();
  if (!q) {
    return helpLine(classes);
  }

  const labels = [...new Set(classes.map((c) => c.label).filter(Boolean))];
  const missionIds = missions.map((m) => m.missionId).filter(Boolean);

  // biggest / largest mission -> highest framesOut
  if (/(biggest|largest)\b.*\bmission|mission\b.*(biggest|largest)/.test(q)) {
    if (missions.length === 0) return "No missions loaded.";
    const top = [...missions].sort((a, b) => b.framesOut - a.framesOut)[0];
    return `Largest mission is ${top.missionId.toUpperCase()} at ${fmt(top.framesOut)} frames out (${fmt(top.gemmaLabeledCount)} vouched).`;
  }

  // most / least <classname>
  const mostLeast = q.match(/\b(most|least|fewest|highest|lowest)\b/);
  if (mostLeast) {
    const matchedLabel = labels.find((l) => q.includes(l.toLowerCase()));
    if (matchedLabel) {
      const rows = classes.filter(
        (c) => c.label.toLowerCase() === matchedLabel.toLowerCase(),
      );
      if (rows.length === 0) {
        return `No detections of "${matchedLabel}" in the loaded missions.`;
      }
      const wantLeast = /least|fewest|lowest/.test(mostLeast[1]);
      const sorted = [...rows].sort((a, b) =>
        wantLeast ? a.count - b.count : b.count - a.count,
      );
      const top = sorted[0];
      const verb = wantLeast ? "fewest" : "most";
      return `${top.missionId.toUpperCase()} has the ${verb} ${matchedLabel} (${fmt(top.count)}).`;
    }
  }

  // total / how many <classname>
  if (/\b(total|how many|count of)\b/.test(q)) {
    const matchedLabel = labels.find((l) => q.includes(l.toLowerCase()));
    if (matchedLabel) {
      const rows = classes.filter(
        (c) => c.label.toLowerCase() === matchedLabel.toLowerCase(),
      );
      const sum = rows.reduce((n, c) => n + c.count, 0);
      const where = rows
        .filter((c) => c.count > 0)
        .map((c) => c.missionId.toUpperCase())
        .join(", ");
      return `${fmt(sum)} ${matchedLabel} across ${rows.length} mission${rows.length === 1 ? "" : "s"}${where ? ` (${where})` : ""}.`;
    }
  }

  // summarize <missionId> OR any mention of a mission name in the query.
  // A mission name appearing at all is a strong enough signal to summarize it.
  const matchedMission =
    missionIds.find((id) => q.includes(id.toLowerCase())) ?? null;
  if (matchedMission) {
    const mission = missions.find((m) => m.missionId === matchedMission);
    if (mission) return summarizeMission(mission, classes);
  }

  return helpLine(classes);
}

function helpLine(classes: DetectionClass[]): string {
  const sample = detectionsByClass(classes)[0]?.label ?? "vehicle";
  return `Ask: "most ${sample}", "total ${sample}", "summarize <mission>", or "biggest mission".`;
}
