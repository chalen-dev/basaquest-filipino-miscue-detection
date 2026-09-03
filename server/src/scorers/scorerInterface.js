/**
 * Contract every pronunciation scorer implementation must satisfy.
 * This file has no code — it exists so the shape below is documented in one
 * place. mockScorer.js implements it today; a future azureScorer.js (see
 * azureScorer.js in this folder) implements the same shape so it can be
 * swapped in via scorers/index.js without any caller changing.
 *
 * @typedef {'correct'|'mispronounced'|'omitted'|'inserted'} WordStatus
 *
 * @typedef {Object} WordResult
 * @property {number} index - position in the reference passage (inserted words use a fractional index, e.g. 2.5, to sit between real words)
 * @property {string} word - the word text (reference word, or the extra word actually heard for 'inserted')
 * @property {WordStatus} status
 * @property {number} confidence - 0-1 confidence score from the scorer
 * @property {number} [startTime] - seconds into the recording where this word was heard, if known. Omitted words were never said, so they have no audio position — callers should treat a missing startTime/endTime as "can't seek to this word."
 * @property {number} [endTime] - end of the word's audio span, in seconds
 *
 * @typedef {Object} ScoreResult
 * @property {WordResult[]} words
 * @property {number} durationSeconds - length of the submitted recording
 * @property {string} engine - name of the engine that produced this result, e.g. "mock" or "azure-speech"
 *
 * @callback ScorePassage
 * @param {Object} params
 * @param {string} params.passageText - the known reference passage
 * @param {string} params.audioFilePath - path to the recorded audio file on disk
 * @param {'en'|'fil'} [params.language] - language the passage is written in; defaults to 'en'. Scorers that are language-aware (e.g. whisperScorer.js, which picks a different underlying model per language) use this; scorers that aren't (mockScorer.js) ignore it.
 * @returns {Promise<ScoreResult>}
 */

export {};
