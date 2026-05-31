/**
 * Server-side bridge to a published Palantir Foundry AIP Logic / query
 * function. Takes a natural-language question and executes the configured
 * ontology query, returning a coerced string answer.
 *
 * SECURITY: FOUNDRY_TOKEN is read here (server only) and used only as a Bearer
 * header. It never leaves this module and never reaches the client bundle.
 *
 * Activation: set FOUNDRY_AIP_FUNCTION (plus FOUNDRY_HOST / FOUNDRY_TOKEN /
 * FOUNDRY_ONTOLOGY_RID) to the apiName of the published AIP query function.
 * When unset, the route reports { configured: false } so the client falls back
 * to its local responder.
 */

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

  const host = process.env.FOUNDRY_HOST;
  const token = process.env.FOUNDRY_TOKEN;
  const ontology = process.env.FOUNDRY_ONTOLOGY_RID;
  const fn = process.env.FOUNDRY_AIP_FUNCTION;

  if (!host || !token || !ontology || !fn) {
    return Response.json({ configured: false });
  }

  const trimmedHost = host.replace(/\/+$/, "");
  const url = `${trimmedHost}/api/v2/ontologies/${ontology}/queries/${fn}/execute`;

  try {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ parameters: { question } }),
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
