// Thin fetch wrapper around the backend's reading-assessment endpoints.
// Vite's dev proxy (vite.config.js) forwards /api and /uploads to the
// Express server, so these can stay relative paths.

export async function submitRecording({ passageText, audioBlob, language, speaker = {} }) {
  const form = new FormData();
  form.append('passageText', passageText);
  form.append('language', language || 'en');
  form.append('speakerId', speaker.speakerId || '');
  form.append('grade', speaker.grade || '');
  form.append('device', speaker.device || '');
  // audioBlob is either a MediaRecorder Blob (no .name, always webm) or a
  // File the user picked to upload (has its own .name/extension) — pass the
  // real filename through so the server (and, for the GOP scorer, ffmpeg)
  // sees the actual container format instead of assuming webm for everything.
  form.append('audio', audioBlob, audioBlob.name || 'recording.webm');

  const res = await fetch('/api/sessions', { method: 'POST', body: form });
  if (!res.ok) throw new Error((await safeJson(res))?.error || 'Failed to submit recording');
  return res.json();
}

export async function fetchSession(id) {
  const res = await fetch(`/api/sessions/${id}`);
  if (!res.ok) throw new Error('Failed to fetch session');
  return res.json();
}

export async function validateSession(id, { wordOverrides, heard, validated }) {
  const res = await fetch(`/api/sessions/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ wordOverrides, heard, validated }),
  });
  if (!res.ok) throw new Error('Failed to update session');
  return res.json();
}

async function safeJson(res) {
  try {
    return await res.json();
  } catch {
    return null;
  }
}
