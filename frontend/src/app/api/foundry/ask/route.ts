/**
 * Server-side bridge to a published Palantir Foundry AIP Logic / query
 * function. Takes a natural-language question, fetches the live mission +
 * detection-class objects, builds a compact data context, and executes the
 * configured ontology query with BOTH the question and that context so the
 * AIP language model has real data to ground its answer on.
 *
 * SECURITY: FOUNDRY_TOKEN is read here (server only) and used only as a Bearer
 * header. It never leaves this module and never reaches the client bundle.
 *
 * Activation: set FOUNDRY_AIP_FUNCTION (plus FOUNDRY_HOST / FOUNDRY_TOKEN /
 * FOUNDRY_ONTOLOGY_RID) to the apiName of the published AIP query function.
 * The function must accept two string inputs: `question` and `context`. When
 * FOUNDRY_AIP_FUNCTION is unset, the route reports { configured: false } so the
 * client falls back to its local responder.
 */

import {
  buildMissionContext,
  fetchObjects,
  readFoundryEnv,
} from "@/lib/foundryServer";

export const dynamic = "force-dynamic";
export const revalidate = 0;

interface AskRequestBody {
  question?: unknown;
}

/** Foundry query execute response: { value: <result> }. */
interface QueryExecuteResponse {
  value?: unknown;
}

function coerceAnswer(value: unknown): string {
  if (typeof value === "string") return value;
  if (value == null) return "";
  return JSON.stringify(value);
}

export async function POST(req: Request): Promise<Response> {
  let question = "";
  try {
    const body = (await req.json()) as AskRequestBody;
    if (typeof body.question === "string") {
      question = body.question.trim();
    }
  } catch {
    // Malformed body -> treat as empty question below.
  }

  const env = readFoundryEnv();
  const fn = process.env.FOUNDRY_AIP_FUNCTION;

  if (!env || !fn) {
    return Response.json({ configured: false });
  }

  // Ground the model with the live ontology data. If the object fetch fails we
  // still call the function (with empty context) and let it degrade.
  let context = "";
  try {
    const [missions, classes] = await Promise.all([
      fetchObjects(env, "CaptureMission", 100),
      fetchObjects(env, "DetectionClass", 200),
    ]);
    context = buildMissionContext(missions, classes);
  } catch {
    context = "";
  }

  const url = `${env.host}/api/v2/ontologies/${env.ontology}/queries/${fn}/execute`;

  try {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ parameters: { question, context } }),
      cache: "no-store",
    });

    if (!res.ok) {
      return Response.json({
        configured: true,
        error: `AIP execute failed: HTTP ${res.status}`,
        source: "aip",
      });
    }

    const body = (await res.json()) as QueryExecuteResponse;
    return Response.json({
      configured: true,
      answer: coerceAnswer(body.value),
      source: "aip",
    });
  } catch (exc) {
    const message = exc instanceof Error ? exc.message : String(exc);
    return Response.json({ configured: true, error: message, source: "aip" });
  }
}
