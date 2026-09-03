/**
 * In-memory session store. A prototype stand-in for a database — sessions
 * are lost on server restart, which is fine for proving the pipeline works.
 */
const sessions = new Map();

export function createSession(session) {
  sessions.set(session.id, session);
  return session;
}

export function getSession(id) {
  return sessions.get(id);
}

export function updateSession(id, updater) {
  const session = sessions.get(id);
  if (!session) return undefined;
  updater(session);
  return session;
}
