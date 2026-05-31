import type { Entity } from "./contracts";

/**
 * SLAM emits one entity per sparse 3D landmark it triangulates. These are
 * useful for SLAM diagnostics but pollute the operator's map and intel views
 * — they're not "things the brain identified", they're features the brain
 * used to localise itself. Filter them out everywhere except the SLAM tab.
 */
export function operationalEntities(entities: Entity[]): Entity[] {
  return entities.filter((e) => !e.id.startsWith("lm_"));
}

/** Reserved world-model id for the operator's designated recon target. Both
 *  maps special-case this id (red reticle + red callout) so the cue stays in
 *  sync across the 2D/3D view toggle. */
export const DESIGNATED_TARGET_ID = "designated_target";

export function isDesignatedTarget(entity: Pick<Entity, "id">): boolean {
  return entity.id === DESIGNATED_TARGET_ID;
}
