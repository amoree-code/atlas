const DEFAULT_SKILLS = ["core-thinking", "verification"] as const;

export function defaultSkillNames(_role: string): string[] {
  return [...DEFAULT_SKILLS];
}
