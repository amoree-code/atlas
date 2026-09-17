import { access } from "node:fs/promises";
import { atlasPath } from "../../paths.js";
import { openSessionStore } from "../../infrastructure/persistence/session-store.js";

export async function runMigrateCommand(apply: boolean): Promise<void> {
  const database = atlasPath("system", "sessions", "sessions.sqlite");
  const exists = await access(database).then(() => true, () => false);
  if (!apply) {
    console.log(JSON.stringify({ applyRequired: true, databaseExists: exists, action: "atlas migrate --apply", note: "Applying opens the session database and runs idempotent schema migrations." }, null, 2));
    return;
  }
  const store = await openSessionStore();
  try { console.log(JSON.stringify({ migrated: true, integrity: store.integrityCheck() }, null, 2)); }
  finally { store.close(); }
}
