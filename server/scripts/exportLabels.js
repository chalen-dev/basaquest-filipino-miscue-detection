/**
 * Bundles every validated session into one folder you can zip and upload:
 *
 *   export/
 *     all_labels.csv   one row per word (open in Excel to check the labels)
 *     manifest.json    one entry per recording
 *     audio/<id>.<ext> the recordings
 *
 * Usage: node scripts/exportLabels.js [outputDir]   (default: ./export)
 *
 * A word's final_status is the teacher's decision, or the scorer's verdict
 * for words the teacher didn't touch (the teacher validated the whole
 * session, so untouched words are confirmed as the scorer called them).
 */
import fs from 'fs';
import path from 'path';
import { SESSIONS_DIR, LABELS_FILENAME } from '../src/sessionsStore.js';

const outDir = path.resolve(process.argv[2] || 'export');

const CSV_COLUMNS = [
  'session_id', 'speaker_id', 'grade', 'device', 'language', 'engine',
  'word_index', 'word', 'scorer_status', 'scorer_confidence',
  'final_status', 'heard', 'start_time', 'end_time',
];

function csvCell(value) {
  const text = value == null ? '' : String(value);
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

if (!fs.existsSync(SESSIONS_DIR)) {
  console.log(`No sessions found at ${SESSIONS_DIR}`);
  process.exit(0);
}

const audioOutDir = path.join(outDir, 'audio');
fs.mkdirSync(audioOutDir, { recursive: true });

const rows = [CSV_COLUMNS.join(',')];
const manifest = [];
let skipped = 0;

for (const entry of fs.readdirSync(SESSIONS_DIR, { withFileTypes: true })) {
  if (!entry.isDirectory()) continue;
  const dir = path.join(SESSIONS_DIR, entry.name);
  let session;
  try {
    session = JSON.parse(fs.readFileSync(path.join(dir, LABELS_FILENAME), 'utf8'));
  } catch {
    skipped++;
    continue;
  }
  if (session.status !== 'validated') {
    skipped++;
    continue;
  }

  const audioOutName = `${session.id}${path.extname(session.audioFilename)}`;
  fs.copyFileSync(path.join(dir, session.audioFilename), path.join(audioOutDir, audioOutName));

  const speaker = session.speaker || {};
  for (const w of [...session.words].sort((a, b) => a.index - b.index)) {
    rows.push(
      [
        session.id, speaker.speakerId, speaker.grade, speaker.device, session.language, session.engine,
        w.index, w.word, w.status, w.confidence,
        w.teacherStatus ?? w.status, w.heard, w.startTime, w.endTime,
      ].map(csvCell).join(',')
    );
  }

  manifest.push({
    sessionId: session.id,
    audio: `audio/${audioOutName}`,
    speaker,
    language: session.language,
    engine: session.engine,
    durationSeconds: session.durationSeconds,
    passageText: session.passageText,
    validatedAt: session.validatedAt,
  });
}

fs.writeFileSync(path.join(outDir, 'all_labels.csv'), rows.join('\n') + '\n');
fs.writeFileSync(path.join(outDir, 'manifest.json'), JSON.stringify(manifest, null, 2));

console.log(`Exported ${manifest.length} validated session(s) to ${outDir}` + (skipped ? ` (${skipped} skipped: unvalidated or unreadable)` : ''));
