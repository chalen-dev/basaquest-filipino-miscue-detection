/**
 * Placeholder for the real scorer, backed by Azure AI Speech's pronunciation
 * assessment API. Implements the same contract as mockScorer.js (see
 * scorerInterface.js) so swapping SCORER_ENGINE=azure in scorers/index.js is
 * the only change needed anywhere in the app.
 *
 * Not implemented in this prototype. To wire it up for real:
 *   1. npm install microsoft-cognitiveservices-speech-sdk
 *   2. Send audioFilePath + passageText to Azure's pronunciation assessment
 *      endpoint (reference text mode), which does the word alignment for you.
 *   3. Map Azure's per-word ErrorType (None/Mispronunciation/Omission/Insertion)
 *      onto our WordStatus values and AccuracyScore onto confidence (0-1).
 *
 * @type {import('./scorerInterface.js').ScorePassage}
 */
export async function scorePassage({ passageText, audioFilePath, language }) {
  throw new Error(
    'azureScorer is not implemented yet — set SCORER_ENGINE=mock, or implement this function against Azure Speech.'
  );
}
