import { scorePassage as mockScorePassage } from './mockScorer.js';
import { scorePassage as azureScorePassage } from './azureScorer.js';
import { scorePassage as whisperScorePassage } from './whisperScorer.js';
import { scorePassage as gopScorePassage } from './gopScorer.js';

const ENGINES = {
  mock: mockScorePassage,
  azure: azureScorePassage,
  whisper: whisperScorePassage,
  gop: gopScorePassage,
};

/**
 * Returns the active scorer's scorePassage function, selected by the
 * SCORER_ENGINE env var (defaults to "mock"). This is the only place that
 * needs to change to switch scorers — every caller just does
 * `await getScorer()({ passageText, audioFilePath })`. "whisper" is a real,
 * fully local implementation (see whisperScorer.js); "gop" runs the real,
 * calibrated phoneme-level model via gopScorer.js (Filipino only); "azure"
 * is still a stub.
 */
export function getScorer() {
  const engine = process.env.SCORER_ENGINE || 'mock';
  const scorePassage = ENGINES[engine];
  if (!scorePassage) {
    throw new Error(`Unknown SCORER_ENGINE "${engine}". Valid options: ${Object.keys(ENGINES).join(', ')}`);
  }
  return scorePassage;
}
