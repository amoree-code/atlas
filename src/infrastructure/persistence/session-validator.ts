import { sessionSchema, type Session } from "../../domain/sessions/session.js";

export function validateSession(input: unknown): Session {
  return sessionSchema.parse(input);
}
