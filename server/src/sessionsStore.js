/**
 * File-backed session store. Each session lives in its own folder under
 * server/data/sessions/<id>/:
 *
 *   audio.<ext>    the recording
 *   labels.json    the passage, the scorer's per-word verdicts, the teacher's
 *                  decisions, and who/what/when — everything needed to reuse
 *                  the recording later as labeled evaluation or training data
 *
 * Sessions are kept in memory for fast reads and written through to disk on
 * every change, then reloaded at startup so a server restart loses nothing.
 * server/data/ is gitignored (the root .gitignore covers any `data/` dir) —
 * these are recordings of children and must not end up in the repo.
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
export const SESSIONS_DIR = path.join(__dirname, '..', 'data', 'sessions');
export const LABELS_FILENAME = 'labels.json';

const sessions = new Map();

loadFromDisk();

function loadFromDisk() {
  if (!fs.existsSync(SESSIONS_DIR)) return;
  for (const entry of fs.readdirSync(SESSIONS_DIR, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const labelsPath = path.join(SESSIONS_DIR, entry.name, LABELS_FILENAME);
    try {
      const session = JSON.parse(fs.readFileSync(labelsPath, 'utf8'));
      sessions.set(session.id, session);
    } catch (err) {
      console.warn(`Skipping unreadable session folder ${entry.name}: ${err.message}`);
    }
  }
}

function persist(session) {
  const dir = path.join(SESSIONS_DIR, session.id);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, LABELS_FILENAME), JSON.stringify(session, null, 2));
}

// audioSourcePath is where multer dropped the upload; it is moved into the
// session's own folder so the recording and its labels stay together.
export function createSession(session, { audioSourcePath }) {
  const dir = path.join(SESSIONS_DIR, session.id);
  fs.mkdirSync(dir, { recursive: true });
  const audioFilename = `audio${path.extname(audioSourcePath) || '.webm'}`;
  fs.renameSync(audioSourcePath, path.join(dir, audioFilename));

  const stored = { ...session, audioFilename };
  sessions.set(stored.id, stored);
  persist(stored);
  return stored;
}

export function getSession(id) {
  return sessions.get(id);
}

export function updateSession(id, updater) {
  const session = sessions.get(id);
  if (!session) return undefined;
  updater(session);
  persist(session);
  return session;
}
