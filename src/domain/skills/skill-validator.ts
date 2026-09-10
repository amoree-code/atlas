import { skillSchema, type Skill } from "./skill.js";

export function validateSkill(input: unknown): Skill {
  return skillSchema.parse(input);
}
