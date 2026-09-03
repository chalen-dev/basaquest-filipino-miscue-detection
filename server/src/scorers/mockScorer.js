import { randomUUID } from 'crypto';

/**
 * Mock implementation of the ScorePassage contract (see scorerInterface.js).
 * Returns plausible-but-fake word-level results so the rest of the pipeline
 * (teacher review, validation) can be built and tested before a real
 * pronunciation API is wired up. Ignores the actual audio content entirely.
 *
 * @type {import('./scorerInterface.js').ScorePassage}
 */
export async function scorePassage({ passageText, audioFilePath, language }) {
  void language; // mock ignores language entirely — every passage gets the same fake treatment
  const words = passageText
    .trim()
    .split(/\s+/)
    .filter(Boolean);

  const results = [];

  words.forEach((word, index) => {
    const roll = Math.random();
    let status;
    if (roll < 0.78) status = 'correct';
    else if (roll < 0.9) status = 'mispronounced';
    else status = 'omitted';

    results.push({
      index,
      word,
      status,
      confidence: fakeConfidence(status),
    });

    // Occasionally simulate the reader inserting an extra word not in the passage.
    if (Math.random() < 0.06) {
      results.push({
        index: index + 0.5,
        word: FILLER_WORDS[Math.floor(Math.random() * FILLER_WORDS.length)],
        status: 'inserted',
        confidence: fakeConfidence('inserted'),
      });
    }
  });

  const durationSeconds = await estimateDuration(audioFilePath);

  // Fake-but-plausible per-word timing, spread evenly across the recording, so the
  // teacher review screen's "jump to this word" control is testable without needing
  // the real Whisper engine. Omitted words were never said, so they get none.
  const perWord = durationSeconds / Math.max(results.length, 1);
  results.forEach((result, i) => {
    if (result.status === 'omitted') return;
    result.startTime = round(i * perWord);
    result.endTime = round((i + 1) * perWord);
  });

  return {
    words: results,
    durationSeconds,
    engine: 'mock',
    _sessionToken: randomUUID(), // unused, just illustrates a mock-only field a real API might return
  };
}

function fakeConfidence(status) {
  switch (status) {
    case 'correct':
      return round(0.85 + Math.random() * 0.15);
    case 'mispronounced':
      return round(0.4 + Math.random() * 0.35);
    case 'omitted':
      return round(0.2 + Math.random() * 0.2);
    case 'inserted':
      return round(0.5 + Math.random() * 0.3);
    default:
      return 0.5;
  }
}

function round(n) {
  return Math.round(n * 100) / 100;
}

const FILLER_WORDS = ['um', 'uh', 'the', 'like', 'so'];

async function estimateDuration(audioFilePath) {
  try {
    const { statSync } = await import('fs');
    const { size } = statSync(audioFilePath);
    // Rough placeholder estimate (mock only) — not a real audio duration calc.
    return Math.max(1, Math.round(size / 16000));
  } catch {
    return 0;
  }
}
