import { execFile } from 'child_process';
import { promisify } from 'util';
import ffmpegPath from 'ffmpeg-static';

const execFileAsync = promisify(execFile);

// Below this, a recording is almost certainly an accidental click or immediate
// stop, not a real passage attempt — even the shortest Grade 1 passage takes
// longer than this to read aloud.
const MIN_DURATION_SECONDS = 5;

// ffmpeg's volumedetect reports mean_volume in dBFS (0 = loudest possible, more
// negative = quieter). Real speech in a normal classroom recording typically
// lands well above this; a mean this low usually means the mic wasn't
// picking up speech at all (muted, held away, permission granted to the wrong
// device). This is a heuristic, not a calibrated measurement — may need
// tuning against real classroom mic/room conditions.
const SILENCE_MEAN_VOLUME_DB = -45;

/**
 * Runs a cheap, local, free check on a recording — duration and average
 * volume via ffmpeg — before it's handed to any scorer. This exists to catch
 * obviously-bad recordings (too short, effectively silent) before spending
 * money on a paid scoring API (Azure) or compute time on the local Whisper
 * fallback, and applies uniformly regardless of which scorer is active,
 * since it runs in the route handler, not inside a specific scorer.
 *
 * @param {string} audioFilePath
 * @returns {Promise<{ ok: true } | { ok: false, reason: string }>}
 */
export async function checkAudioQuality(audioFilePath) {
  let stderr;
  try {
    // -f null discards the actual output; we only want the stats ffmpeg logs
    // to stderr. Doesn't require decoding to WAV first — works on the raw upload.
    ({ stderr } = await execFileAsync(ffmpegPath, [
      '-i',
      audioFilePath,
      '-af',
      'volumedetect',
      '-f',
      'null',
      '-',
    ]));
  } catch (err) {
    // ffmpeg's -f null run still exits with the stats on stderr even though
    // execFile treats a non-zero exit as an error for some inputs; recover the
    // stats from the error object if present rather than treating it as fatal.
    stderr = err.stderr;
    if (!stderr) {
      return { ok: false, reason: 'Could not read the recording — it may be corrupted. Please try recording again.' };
    }
  }

  const durationMatch = stderr.match(/Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)/);
  const durationSeconds = durationMatch
    ? Number(durationMatch[1]) * 3600 + Number(durationMatch[2]) * 60 + Number(durationMatch[3])
    : null;

  if (durationSeconds != null && durationSeconds < MIN_DURATION_SECONDS) {
    return {
      ok: false,
      reason: `That recording is only ${durationSeconds.toFixed(1)}s long — too short to be a full passage reading. Please record again.`,
    };
  }

  const volumeMatch = stderr.match(/mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB/);
  const meanVolumeDb = volumeMatch ? Number(volumeMatch[1]) : null;

  if (meanVolumeDb != null && meanVolumeDb < SILENCE_MEAN_VOLUME_DB) {
    return {
      ok: false,
      reason: "That recording sounds silent — no speech was picked up. Check your microphone and record again.",
    };
  }

  return { ok: true };
}
