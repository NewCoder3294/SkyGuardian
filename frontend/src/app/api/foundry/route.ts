/**
 * Server-side Foundry bridge. Reads mission + detection-class objects from a
 * Palantir Foundry ontology and returns them to the Data page.
 *
 * SECURITY: FOUNDRY_TOKEN is read here (server only) and used only as a Bearer
 * header. It is never returned to the client and never reaches the client
 * bundle — only the resolved object data crosses the wire.
 */

export const dynamic = "force-dynamic";
export const revalidate = 0;

interface FoundryObjectsResponse {
  data: Array<Record<string, unknown>>;
}

async function fetchObjects(
  host: string,
  ontology: string,
  token: string,
  objectType: string,
  pageSize: number,
): Promise<Array<Record<string, unknown>>> {
  const url = `${host}/api/v2/ontologies/${ontology}/objects/${objectType}?pageSize=${pageSize}`;
  const res = await fetch(url, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`${objectType} fetch failed: HTTP ${res.status}`);
  }
  const body = (await res.json()) as FoundryObjectsResponse;
  return Array.isArray(body.data) ? body.data : [];
}

export async function GET(): Promise<Response> {
  const host = process.env.FOUNDRY_HOST;
  const token = process.env.FOUNDRY_TOKEN;
  const ontology = process.env.FOUNDRY_ONTOLOGY_RID;

  if (!host || !token || !ontology) {
    return Response.json({ configured: false });
  }

  const trimmedHost = host.replace(/\/+$/, "");

  try {
    const [missions, classes] = await Promise.all([
      fetchObjects(trimmedHost, ontology, token, "CaptureMission", 100),
      fetchObjects(trimmedHost, ontology, token, "DetectionClass", 200),
    ]);
    return Response.json({ configured: true, missions, classes });
  } catch (exc) {
    const message = exc instanceof Error ? exc.message : String(exc);
    return Response.json({ configured: true, error: message });
  }
}
