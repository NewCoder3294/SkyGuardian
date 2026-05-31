/**
 * Server-side Foundry bridge. Reads mission + detection-class objects from a
 * Palantir Foundry ontology and returns them to the Data page.
 *
 * SECURITY: FOUNDRY_TOKEN is read here (server only) and used only as a Bearer
 * header. It is never returned to the client and never reaches the client
 * bundle — only the resolved object data crosses the wire.
 */

import { fetchObjects, readFoundryEnv } from "@/lib/foundryServer";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET(): Promise<Response> {
  const env = readFoundryEnv();
  if (!env) {
    return Response.json({ configured: false });
  }

  try {
    const [missions, classes] = await Promise.all([
      fetchObjects(env, "CaptureMission", 100),
      fetchObjects(env, "DetectionClass", 200),
    ]);
    return Response.json({ configured: true, missions, classes });
  } catch (exc) {
    const message = exc instanceof Error ? exc.message : String(exc);
    return Response.json({ configured: true, error: message });
  }
}
