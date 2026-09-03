import { Router } from 'express';
import multer from 'multer';
import path from 'path';
import { randomUUID } from 'crypto';
import { fileURLToPath } from 'url';
import { unlink } from 'fs/promises';
import { getScorer } from '../scorers/index.js';
import { createSession, getSession, updateSession } from '../sessionsStore.js';
import { checkAudioQuality } from '../audioQualityCheck.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const UPLOADS_DIR = path.join(__dirname, '..', '..', 'uploads');

const storage = multer.diskStorage({
  destination: (_req, _file, cb) => cb(null, UPLOADS_DIR),
  filename: (_req, file, cb) => {
    const ext = path.extname(file.originalname) || '.webm';
    cb(null, `${randomUUID()}${ext}`);
  },
});
const upload = multer({ storage });

const router = Router();

// Create a new reading session: submits the recording + reference passage,
// runs it through the active scorer, and returns the automated results.
router.post('/sessions', upload.single('audio'), async (req, res) => {
  const { passageText, language } = req.body;
  if (!req.file || !passageText) {
    return res.status(400).json({ error: 'audio file and passageText are required' });
  }

  try {
    // Cheap, free, local check before spending money on a paid scoring API (or
    // compute time on the local fallback) on an obviously-bad recording.
    const quality = await checkAudioQuality(req.file.path);
    if (!quality.ok) {
      await unlink(req.file.path).catch(() => {});
      return res.status(422).json({ error: quality.reason });
    }

    const scorePassage = getScorer();
    const result = await scorePassage({
      passageText,
      audioFilePath: req.file.path,
      language: language || 'en',
    });

    const session = createSession({
      id: randomUUID(),
      passageText,
      language: language || 'en',
      audioFilename: req.file.filename,
      words: result.words.map((w) => ({ ...w, teacherStatus: null })),
      durationSeconds: result.durationSeconds,
      engine: result.engine,
      status: 'pending_review',
      createdAt: new Date().toISOString(),
      validatedAt: null,
    });

    res.status(201).json(toSessionDto(session));
  } catch (err) {
    console.error('Scoring failed:', err);
    res.status(500).json({ error: 'Scoring failed', detail: err.message });
  }
});

// Fetch a session for teacher review.
router.get('/sessions/:id', (req, res) => {
  const session = getSession(req.params.id);
  if (!session) return res.status(404).json({ error: 'Session not found' });
  res.json(toSessionDto(session));
});

// Teacher submits per-word confirm/override decisions and marks the session validated.
router.patch('/sessions/:id', (req, res) => {
  const { wordOverrides, validated } = req.body;

  const session = updateSession(req.params.id, (s) => {
    if (wordOverrides) {
      for (const [indexKey, teacherStatus] of Object.entries(wordOverrides)) {
        const word = s.words.find((w) => String(w.index) === indexKey);
        if (word) word.teacherStatus = teacherStatus;
      }
    }
    if (validated) {
      s.status = 'validated';
      s.validatedAt = new Date().toISOString();
    }
  });

  if (!session) return res.status(404).json({ error: 'Session not found' });
  res.json(toSessionDto(session));
});

function toSessionDto(session) {
  return {
    id: session.id,
    passageText: session.passageText,
    language: session.language,
    audioUrl: `/uploads/${session.audioFilename}`,
    words: session.words,
    durationSeconds: session.durationSeconds,
    engine: session.engine,
    status: session.status,
    createdAt: session.createdAt,
    validatedAt: session.validatedAt,
  };
}

export default router;
