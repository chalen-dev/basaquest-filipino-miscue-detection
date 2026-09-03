import { execFile } from 'child_process';
import { promisify } from 'util';
import path from 'path';
import os from 'os';
import { randomUUID } from 'crypto';
import { fileURLToPath } from 'url';
import { readFile, unlink } from 'fs/promises';

const execFileAsync = promisify(execFile);
const __dirname = path.dirname(fileURLToPath(import.meta.url));
// server/src/scorers -> repo root
const REPO_ROOT = path.join(__dirname, '..', '..', '..');
const GOP_DIR = path.join(REPO_ROOT, 'gop');

// All three of these can be overridden with env vars — see the README's
// "GOP scorer" section — but default to exactly the paths used in the
// manual `HOW TO RUN.txt` workflow, so the website reproduces the same
// results already verified from the command line.
const PYTHON = process.env.GOP_PYTHON || path.join(GOP_DIR, '.venv', 'Scripts', 'python.exe');
const MODEL_DIR =
  process.env.GOP_MODEL_DIR || path.join(REPO_ROOT, 'models', 'final-model-child-augmented-v1');
const CALIBRATION =
  process.env.GOP_CALIBRATION || path.join(GOP_DIR, 'calibration-child-augmented.json');

/**
 * Wraps `gop/score_recording.py` (the real, calibrated GOP scorer — see
 * gop/basaquest_gop/scorer.py) behind the same ScorePassage contract as
 * mock/whisper/azure, so it can be selected via SCORER_ENGINE=gop with no
 * other code changes (see scorers/index.js).
 *
 * This shells out to a *separate* Python process per request rather than
 * reimplementing scoring in JS or keeping a Python process warm. That means
 * every request pays the ~15-20s model-load cost on top of actual scoring
 * time (measured ~0.5x realtime) — a 40s recording takes roughly 30-40s
 * total. That's real, user-visible latency, not a bug: the alternative
 * (a long-lived Python worker process) would remove it but is a bigger
 * change than this prototype's scope called for. If that latency becomes a
 * problem, that's the fix to reach for.
 *
 * score_passage()'s return shape (gop/basaquest_gop/scorer.py) already
 * matches scorerInterface.js's { words, durationSeconds, engine } field for
 * field, plus additive `phonemes` (per-word) and top-level `calibration`
 * fields the interface doesn't require — callers that only know the
 * documented shape (TeacherReviewScreen.jsx) simply ignore the extras.
 *
 * @type {import('./scorerInterface.js').ScorePassage}
 */
export async function scorePassage({ passageText, audioFilePath, language = 'en' }) {
  if (language !== 'fil') {
    throw new Error(
      'The GOP scorer only supports Filipino ("fil") passages — its acoustic model was built from ' +
        'the Filipino phoneme inventory only (see gop/basaquest_gop/scorer.py). Pick a Filipino ' +
        'passage, or switch SCORER_ENGINE to "whisper" or "mock" to score English.'
    );
  }

  const jsonOutPath = path.join(os.tmpdir(), `gop-${randomUUID()}.json`);
  try {
    await execFileAsync(
      PYTHON,
      [
        'score_recording.py',
        '--audio',
        audioFilePath,
        '--passage',
        passageText,
        '--model-dir',
        MODEL_DIR,
        '--calibration',
        CALIBRATION,
        '--json',
        jsonOutPath,
      ],
      {
        cwd: GOP_DIR,
        maxBuffer: 1024 * 1024 * 32,
        // Model load + scoring comfortably fits inside 3 minutes on the
        // hardware this has been tested on; a hang (missing model files,
        // etc.) should fail loudly instead of leaving the request hanging.
        timeout: 3 * 60 * 1000,
      }
    );

    const raw = await readFile(jsonOutPath, 'utf-8');
    return JSON.parse(raw);
  } catch (err) {
    // execFile's error carries stderr from the Python process — the actual
    // reason (missing venv, wrong model path, etc.) is far more useful than
    // the generic "Command failed" message.
    const detail = err.stderr ? String(err.stderr).trim() : err.message;
    throw new Error(`GOP scoring failed: ${detail}`);
  } finally {
    await unlink(jsonOutPath).catch(() => {});
  }
}
