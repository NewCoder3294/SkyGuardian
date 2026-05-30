/** Classes that trigger the threat alert. Defense-relevant items only;
 *  bystanders / equipment (helmet, backpack) are filtered out so the popup
 *  doesn't fire on benign detections. Match against label lowercased. */
export const THREAT_CLASSES: ReadonlySet<string> = new Set([
  "gun",
  "rifle",
  "handgun",
  "pistol",
  "knife",
  "machete",
  "weapon",
  "bomb",
  "explosive device",
  "grenade",
  "ied",
]);

export function isThreat(label: string): boolean {
  return THREAT_CLASSES.has(label.toLowerCase());
}
