import { type Session, sessionSchema } from "../../domain/sessions/session.js";

export function validateSession(input: unknown): Session {
  return sessionSchema.parse(input);
}
