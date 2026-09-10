import { DatabaseSync } from "node:sqlite";
import { mkdir } from "node:fs/promises";
import { atlasPath } from "../../paths.js";
import { assertValidStatusTransition, type Session, type SessionEvent, type SessionStatus } from "../../domain/sessions/session.js";
import { validateSession } from "./session-validator.js";

type SessionRow = Omit<Session, "sessionId" | "providerSessionId" | "parentSessionId" | "profileIdentity" | "workingDirectory" | "resumeData" | "createdAt" | "updatedAt"> & {
  session_id: string;
  provider_session_id: string | null;
  parent_session_id: string | null;
  profile_identity: string;
  working_directory: string;
  created_at: string;
  updated_at: string;
  resume_data: string | null;
};

export class SessionStore {
  private readonly database: DatabaseSync;

  constructor(databaseFile = atlasPath("sessions", "sessions.sqlite")) {
    this.database = new DatabaseSync(databaseFile);
    this.database.exec(`
      PRAGMA journal_mode = WAL;
      CREATE TABLE IF NOT EXISTS sessions (
        session_id TEXT PRIMARY KEY,
        provider TEXT NOT NULL,
        provider_session_id TEXT,
        parent_session_id TEXT,
        profile TEXT NOT NULL,
        profile_identity TEXT NOT NULL DEFAULT '',
        working_directory TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        resume_data TEXT
      );
      CREATE TABLE IF NOT EXISTS session_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
        type TEXT NOT NULL,
        data TEXT NOT NULL,
        created_at TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS session_links (
        parent_session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
        child_session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
        PRIMARY KEY (parent_session_id, child_session_id)
      );
      CREATE INDEX IF NOT EXISTS session_events_session_id ON session_events(session_id);
      CREATE INDEX IF NOT EXISTS session_links_parent_id ON session_links(parent_session_id);
    `);
    this.migrateProfileIdentityColumn();
  }

  // CREATE TABLE IF NOT EXISTS does not add columns to a table that already exists, so a
  // database created before profile identity existed needs this column added explicitly.
  private migrateProfileIdentityColumn(): void {
    const columns = this.database.prepare("PRAGMA table_info(sessions)").all() as Array<{ name: string }>;
    if (!columns.some((column) => column.name === "profile_identity")) {
      this.database.exec("ALTER TABLE sessions ADD COLUMN profile_identity TEXT NOT NULL DEFAULT ''");
    }
  }

  create(input: Omit<Session, "createdAt" | "updatedAt" | "status"> & { status?: SessionStatus }): Session {
    const now = new Date().toISOString();
    const session = validateSession({ ...input, status: input.status ?? "created", createdAt: now, updatedAt: now });
    this.database.prepare(`
      INSERT INTO sessions (session_id, provider, provider_session_id, parent_session_id, profile,
        profile_identity, working_directory, status, created_at, updated_at, resume_data)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).run(session.sessionId, session.provider, session.providerSessionId, session.parentSessionId,
      session.profile, session.profileIdentity, session.workingDirectory, session.status, now, now, session.resumeData);

    if (session.parentSessionId) {
      this.database.prepare("INSERT INTO session_links (parent_session_id, child_session_id) VALUES (?, ?)")
        .run(session.parentSessionId, session.sessionId);
    }
    return session;
  }

  get(sessionId: string): Session | null {
    const row = this.database.prepare("SELECT * FROM sessions WHERE session_id = ?").get(sessionId) as SessionRow | undefined;
    return row ? this.toSession(row) : null;
  }

  updateStatus(sessionId: string, status: SessionStatus, resumeData?: string | null): void {
    const current = this.get(sessionId);
    if (!current) throw new Error(`Session not found: ${sessionId}`);
    assertValidStatusTransition(current.status, status);
    this.database.prepare("UPDATE sessions SET status = ?, resume_data = COALESCE(?, resume_data), updated_at = ? WHERE session_id = ?")
      .run(status, resumeData ?? null, new Date().toISOString(), sessionId);
  }

  updateProviderSessionId(sessionId: string, providerSessionId: string): void {
    this.database.prepare("UPDATE sessions SET provider_session_id = ?, updated_at = ? WHERE session_id = ?")
      .run(providerSessionId, new Date().toISOString(), sessionId);
  }

  list(): Session[] {
    return (this.database.prepare("SELECT * FROM sessions ORDER BY created_at DESC").all() as SessionRow[])
      .map((row) => this.toSession(row));
  }

  appendEvent(sessionId: string, type: string, data: string): SessionEvent {
    const createdAt = new Date().toISOString();
    const result = this.database.prepare("INSERT INTO session_events (session_id, type, data, created_at) VALUES (?, ?, ?, ?)")
      .run(sessionId, type, data, createdAt);
    return { eventId: Number(result.lastInsertRowid), sessionId, type, data, createdAt };
  }

  listEvents(sessionId: string): SessionEvent[] {
    return this.database.prepare("SELECT event_id, session_id, type, data, created_at FROM session_events WHERE session_id = ? ORDER BY event_id")
      .all(sessionId).map((row) => {
        const event = row as { event_id: number; session_id: string; type: string; data: string; created_at: string };
        return { eventId: event.event_id, sessionId: event.session_id, type: event.type, data: event.data, createdAt: event.created_at };
      });
  }

  close(): void {
    this.database.close();
  }

  private toSession(row: SessionRow): Session {
    return validateSession({
      sessionId: row.session_id,
      provider: row.provider,
      providerSessionId: row.provider_session_id,
      parentSessionId: row.parent_session_id,
      profile: row.profile,
      profileIdentity: row.profile_identity,
      workingDirectory: row.working_directory,
      status: row.status,
      createdAt: row.created_at,
      updatedAt: row.updated_at,
      resumeData: row.resume_data,
    });
  }
}

export async function openSessionStore(): Promise<SessionStore> {
  await mkdir(atlasPath("sessions"), { recursive: true });
  return new SessionStore();
}
