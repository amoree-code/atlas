import { profileSchema, type Profile } from "./profile.js";

export function validateProfile(input: unknown): Profile {
  return profileSchema.parse(input);
}
