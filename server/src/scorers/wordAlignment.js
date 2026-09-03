/**
 * Word-level alignment between a reference passage and a hypothesis transcript,
 * using the same edit-distance approach behind Word Error Rate (WER) computation.
 * This is what lets a plain ASR transcript (which is all Whisper produces) be turned
 * into per-word correct/mispronounced/omitted/inserted flags — Whisper itself has no
 * notion of a "reference passage" or per-word accuracy, only what it thinks was said.
 */

function normalize(word) {
  return word.toLowerCase().replace(/[^\p{L}\p{N}']/gu, '');
}

/** Character-level edit distance, used to judge how close a substitution was. */
export function levenshtein(a, b) {
  const dp = Array.from({ length: a.length + 1 }, () => new Array(b.length + 1).fill(0));
  for (let i = 0; i <= a.length; i++) dp[i][0] = i;
  for (let j = 0; j <= b.length; j++) dp[0][j] = j;
  for (let i = 1; i <= a.length; i++) {
    for (let j = 1; j <= b.length; j++) {
      dp[i][j] =
        a[i - 1] === b[j - 1] ? dp[i - 1][j - 1] : 1 + Math.min(dp[i - 1][j - 1], dp[i - 1][j], dp[i][j - 1]);
    }
  }
  return dp[a.length][b.length];
}

/**
 * Aligns two word lists and returns an ordered list of edit operations:
 * 'match' (same word), 'substitute' (different word at the same position),
 * 'delete' (reference word missing from the hypothesis — an omission), or
 * 'insert' (extra hypothesis word not in the reference).
 */
export function alignWords(referenceWords, hypothesisWords) {
  const ref = referenceWords.map(normalize);
  const hyp = hypothesisWords.map(normalize);
  const n = ref.length;
  const m = hyp.length;

  const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = 0; i <= n; i++) dp[i][0] = i;
  for (let j = 0; j <= m; j++) dp[0][j] = j;
  for (let i = 1; i <= n; i++) {
    for (let j = 1; j <= m; j++) {
      dp[i][j] =
        ref[i - 1] === hyp[j - 1]
          ? dp[i - 1][j - 1]
          : 1 + Math.min(dp[i - 1][j - 1], dp[i - 1][j], dp[i][j - 1]);
    }
  }

  const ops = [];
  let i = n;
  let j = m;
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && ref[i - 1] === hyp[j - 1] && dp[i][j] === dp[i - 1][j - 1]) {
      ops.unshift({
        type: 'match',
        refWord: referenceWords[i - 1],
        hypWord: hypothesisWords[j - 1],
        refIndex: i - 1,
        hypIndex: j - 1,
      });
      i--;
      j--;
    } else if (i > 0 && j > 0 && dp[i][j] === dp[i - 1][j - 1] + 1) {
      ops.unshift({
        type: 'substitute',
        refWord: referenceWords[i - 1],
        hypWord: hypothesisWords[j - 1],
        refIndex: i - 1,
        hypIndex: j - 1,
      });
      i--;
      j--;
    } else if (i > 0 && dp[i][j] === dp[i - 1][j] + 1) {
      ops.unshift({ type: 'delete', refWord: referenceWords[i - 1], refIndex: i - 1 });
      i--;
    } else {
      ops.unshift({ type: 'insert', hypWord: hypothesisWords[j - 1], hypIndex: j - 1 });
      j--;
    }
  }
  return ops;
}

/**
 * Turns alignment ops into the WordResult[] shape the rest of the app expects
 * (see scorerInterface.js). Confidence for substitutions is derived from string
 * similarity between the reference and hypothesis word — a substitution against
 * a near-identical spelling ("wich" for "which") reads as a plausible genuine
 * mispronunciation, while a wildly different word more likely means Whisper simply
 * misheard the passage. This is a proxy, not a real pronunciation score.
 *
 * `hypothesisTimings`, if given, is a per-hypothesis-word array of { start, end }
 * (seconds), parallel to the hypothesisWords passed into alignWords. It's used to
 * stamp startTime/endTime onto any result that came from an actual hypothesis word
 * (match/substitute/insert) so the UI can seek the recording to that moment.
 * 'omitted' words have no hypothesis word — there's no audio position for a word
 * that was never said — so they're left without a timing.
 */
export function opsToWordResults(ops, hypothesisTimings) {
  const results = [];
  let baseIndex = -1;
  let insertRun = 0;

  for (const op of ops) {
    const timing = hypothesisTimings && op.hypIndex != null ? hypothesisTimings[op.hypIndex] : undefined;

    if (op.type === 'match') {
      baseIndex = op.refIndex;
      insertRun = 0;
      results.push({ index: baseIndex, word: op.refWord, status: 'correct', confidence: 0.9, ...timing });
    } else if (op.type === 'substitute') {
      baseIndex = op.refIndex;
      insertRun = 0;
      const dist = levenshtein(op.refWord.toLowerCase(), op.hypWord.toLowerCase());
      const maxLen = Math.max(op.refWord.length, op.hypWord.length, 1);
      const similarity = 1 - dist / maxLen;
      results.push({
        index: baseIndex,
        word: op.refWord,
        status: 'mispronounced',
        confidence: round(0.3 + similarity * 0.6),
        ...timing,
      });
    } else if (op.type === 'delete') {
      baseIndex = op.refIndex;
      insertRun = 0;
      results.push({ index: baseIndex, word: op.refWord, status: 'omitted', confidence: 0.3 });
    } else if (op.type === 'insert') {
      insertRun += 1;
      results.push({
        index: baseIndex + insertRun / (insertRun + 1),
        word: op.hypWord,
        status: 'inserted',
        confidence: 0.5,
        ...timing,
      });
    }
  }

  return results;
}

function round(n) {
  return Math.round(n * 100) / 100;
}
