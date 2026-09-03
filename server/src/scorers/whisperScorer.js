import { execFile } from 'child_process';
import { promisify } from 'util';
import { readFileSync, unlinkSync } from 'fs';
import path from 'path';
import os from 'os';
import { randomUUID } from 'crypto';
import ffmpegPath from 'ffmpeg-static';
import wavefilePkg from 'wavefile';
import { alignWords, opsToWordResults } from './wordAlignment.js';

const { WaveFile } = wavefilePkg;

const execFileAsync = promisify(execFile);

// A single multilingual model shared by both languages, rather than a
// dedicated model per language. Two whisper-small-class models loaded at once
// measured ~4.5-5GB combined in testing — too much for the 6-8GB, often
// Celeron/Pentium/i3-class laptops these are meant to run on. Whisper's
// multilingual checkpoints (no .en suffix) are trained on English too — it
// was the majority language in Whisper's original training data — so
// multilingual whisper-small is already strong on English, not just
// "acceptable." The English-only .en checkpoints do have a small accuracy
// edge on English specifically (per OpenAI's own published benchmarks), but
// the gap is modest, and halving steady-state memory on the actual target
// hardware matters more here than that small edge.
const MODEL_ID = 'Xenova/whisper-small';

// Without this, transformers.js's Node/CPU backend defaults to downloading and
// running full fp32 weights — several times larger and slower than necessary
// (this is what made the earlier tiny.en/base.en downloads take several
// minutes each). 'q8' (8-bit quantized) is a good speed/accuracy balance on
// CPU and is what the smaller, quantized onnx files on the model repo are for.
const DTYPE = 'q8';

// Passed as the `language` generation option so Whisper decodes directly in the
// known language instead of running (and possibly getting wrong) auto-detection
// first. Value is Whisper's own language name, from openai/whisper's tokenizer
// LANGUAGES table (english / tagalog), not an ISO code.
const WHISPER_LANGUAGE = {
  en: 'english',
  fil: 'tagalog',
};

let transcriberPromise = null;
function getTranscriber() {
  // Loaded once and reused across requests and both languages — the
  // download/init on the very first call is the "on-device model" being
  // fetched; every call after that, in either language, is fully offline.
  if (!transcriberPromise) {
    transcriberPromise = import('@huggingface/transformers').then(({ pipeline }) =>
      pipeline('automatic-speech-recognition', MODEL_ID, { dtype: DTYPE })
    );
  }
  return transcriberPromise;
}

/**
 * Local, offline scorer using OpenAI's Whisper model (run via transformers.js/ONNX,
 * no cloud calls after the model is first downloaded). This is the manuscript's
 * "on-device, lower-confidence fallback" path for when the cloud pronunciation
 * service (Azure, see azureScorer.js) is unreachable.
 *
 * Important distinction from azureScorer.js: Whisper only transcribes audio to
 * text — it has no notion of pronunciation accuracy. Word-level correct /
 * mispronounced / omitted / inserted flags here come entirely from aligning
 * Whisper's transcript against the known passage text (see wordAlignment.js),
 * the same edit-distance technique behind Word Error Rate. A word Whisper's
 * own language model "autocorrects" to the expected word will read as correct
 * even if it was mispronounced — a real accuracy gap versus a purpose-built
 * pronunciation-assessment API, and part of why this path is the fallback and
 * not the default.
 *
 * Whisper's word-level timestamps (return_timestamps: 'word') are carried through
 * as each WordResult's startTime/endTime, letting the teacher review screen seek
 * the recording straight to a flagged word. Omitted words have no timestamp —
 * there's no audio moment for a word that was never said.
 *
 * One shared multilingual model handles both languages (see MODEL_ID above);
 * `language` ('en' or 'fil', default 'en') only selects which language Whisper
 * is told to decode in, via the `language` generation option (WHISPER_LANGUAGE).
 *
 * @type {import('./scorerInterface.js').ScorePassage}
 */
export async function scorePassage({ passageText, audioFilePath, language = 'en' }) {
  const wavPath = path.join(os.tmpdir(), `${randomUUID()}.wav`);
  try {
    // MediaRecorder output (webm/opus) -> 16kHz mono PCM WAV, what Whisper expects.
    await execFileAsync(ffmpegPath, ['-y', '-i', audioFilePath, '-ac', '1', '-ar', '16000', wavPath]);

    const wav = new WaveFile(readFileSync(wavPath));
    wav.toBitDepth('32f');
    const samples = wav.getSamples(false, Float32Array);
    const sampleRate = wav.fmt.sampleRate;
    const durationSeconds = Math.round(samples.length / sampleRate);

    const transcriber = await getTranscriber();
    const output = await transcriber(samples, {
      sampling_rate: sampleRate,
      return_timestamps: 'word',
      language: WHISPER_LANGUAGE[language] || WHISPER_LANGUAGE.en,
      // Whisper's model architecture has a fixed 30-second input window. Without
      // chunk_length_s, transformers.js doesn't split longer audio at all (its
      // default is 0 = no chunking), so anything past ~30s gets truncated/mishandled
      // by the model — this produced exactly what showed up in testing: a dropped
      // run of words and a degenerate startTime===endTime timestamp sitting right at
      // the 30s mark, plus cascading misalignment in the words around it. A passage
      // reading easily runs past 30s, so this isn't an edge case for this app.
      // stride_length_s gives each chunk a few seconds of overlap so a word spoken
      // right at a chunk boundary isn't cut in half and dropped by either chunk.
      chunk_length_s: 30,
      stride_length_s: 5,
    });

    // chunks carries per-word timestamps; falls back to the whitespace split (no
    // timings) if a future model/config ever returns plain text instead.
    const chunks = (output.chunks || []).filter((c) => c.text.trim().length > 0);
    const hypothesisWords = chunks.length
      ? chunks.map((c) => c.text.trim())
      : (output.text || '').trim().split(/\s+/).filter(Boolean);
    const hypothesisTimings = chunks.map((c) => ({ startTime: c.timestamp[0], endTime: c.timestamp[1] }));
    const referenceWords = passageText.trim().split(/\s+/).filter(Boolean);

    const ops = alignWords(referenceWords, hypothesisWords);
    const words = opsToWordResults(ops, hypothesisTimings.length ? hypothesisTimings : undefined);

    return { words, durationSeconds, engine: 'whisper-local' };
  } finally {
    try {
      unlinkSync(wavPath);
    } catch {
      // best-effort cleanup of the temp wav
    }
  }
}
