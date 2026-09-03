import { useEffect, useRef, useState } from 'react';
import { PASSAGES, PASSAGE_VARIANTS } from './passage.js';
import { submitRecording } from './api.js';

const STATUS = {
  IDLE: 'idle',
  RECORDING: 'recording',
  RECORDED: 'recorded',
  SUBMITTING: 'submitting',
};

// Mirrors MIN_DURATION_SECONDS in server/src/audioQualityCheck.js — this is
// just for instant feedback without a network round-trip; the server enforces
// the real check regardless of what the client sends.
const MIN_DURATION_SECONDS = 5;

// Extensions/mime-types accepted by the "upload a recording" picker. The
// server doesn't care about the extension itself — everything goes through
// ffmpeg (browser recordings and the GOP scorer's audio.py both do) — this is
// just to steer the OS file picker toward things that are actually audio.
const UPLOAD_ACCEPT = '.m4a,.mp3,.wav,.webm,.ogg,.aac,audio/*';

export default function ReadingScreen({ onSessionCreated }) {
  const [status, setStatus] = useState(STATUS.IDLE);
  const [seconds, setSeconds] = useState(0);
  const [audioUrl, setAudioUrl] = useState(null);
  const [error, setError] = useState(null);
  const [language, setLanguage] = useState('fil');
  const [variantId, setVariantId] = useState(PASSAGE_VARIANTS.fil[0].id);
  const [source, setSource] = useState(null); // 'recorded' | 'uploaded', once audio exists

  const variants = PASSAGE_VARIANTS[language];
  const passage = variants
    ? variants.find((v) => v.id === variantId) || variants[0]
    : PASSAGES[language];

  const mediaRecorderRef = useRef(null);
  const chunksRef = useRef([]);
  const streamRef = useRef(null);
  const timerRef = useRef(null);
  const audioBlobRef = useRef(null);
  const fileInputRef = useRef(null);
  const probeRef = useRef(null);

  useEffect(() => {
    return () => {
      clearInterval(timerRef.current);
      streamRef.current?.getTracks().forEach((t) => t.stop());
      if (audioUrl) URL.revokeObjectURL(audioUrl);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function resetAudioState() {
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    audioBlobRef.current = null;
    setAudioUrl(null);
    setSeconds(0);
    setError(null);
    setSource(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
    setStatus(STATUS.IDLE);
  }

  function changeLanguage(code) {
    setLanguage(code);
    if (PASSAGE_VARIANTS[code]) setVariantId(PASSAGE_VARIANTS[code][0].id);
  }

  async function startRecording() {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { noiseSuppression: true, echoCancellation: true, autoGainControl: true },
      });
      streamRef.current = stream;
      chunksRef.current = [];

      const recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
        audioBlobRef.current = blob;
        setAudioUrl(URL.createObjectURL(blob));
        setSource('recorded');
        streamRef.current?.getTracks().forEach((t) => t.stop());
      };

      mediaRecorderRef.current = recorder;
      recorder.start();
      setSeconds(0);
      setStatus(STATUS.RECORDING);
      timerRef.current = setInterval(() => setSeconds((s) => s + 1), 1000);
    } catch (err) {
      setError('Could not access the microphone: ' + err.message);
    }
  }

  function stopRecording() {
    mediaRecorderRef.current?.stop();
    clearInterval(timerRef.current);
    setStatus(STATUS.RECORDED);
  }

  function recordAgain() {
    resetAudioState();
  }

  function handleFileSelected(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);

    // Read the file's actual duration client-side (the same instant-feedback
    // gate live recording gets) by loading it into a throwaway <audio>
    // element rather than trusting anything about the file itself.
    const url = URL.createObjectURL(file);
    const probe = new Audio();
    probeRef.current = probe;
    probe.preload = 'metadata';
    probe.src = url;
    probe.addEventListener('loadedmetadata', () => {
      audioBlobRef.current = file;
      setSeconds(Number.isFinite(probe.duration) ? Math.round(probe.duration) : 0);
      setAudioUrl(url);
      setSource('uploaded');
      setStatus(STATUS.RECORDED);
    });
    probe.addEventListener('error', () => {
      URL.revokeObjectURL(url);
      setError('Could not read that file as audio — try a different one.');
    });
  }

  async function handleSubmit() {
    setStatus(STATUS.SUBMITTING);
    setError(null);
    try {
      const session = await submitRecording({
        passageText: passage.text,
        audioBlob: audioBlobRef.current,
        language,
      });
      onSessionCreated(session);
    } catch (err) {
      setError(err.message);
      setStatus(STATUS.RECORDED);
    }
  }

  const mm = String(Math.floor(seconds / 60)).padStart(2, '0');
  const ss = String(seconds % 60).padStart(2, '0');

  return (
    <div className="screen">
      <h1>Reading Proficiency Check</h1>
      <p className="subtitle">
        Pick a passage, then either record yourself reading it aloud or upload an existing recording.
      </p>

      <div className="language-toggle" role="radiogroup" aria-label="Passage language">
        {Object.entries({ fil: 'Filipino', en: 'English' }).map(([code, label]) => (
          <button
            key={code}
            type="button"
            className={`btn btn-small ${language === code ? 'btn-primary' : 'btn-secondary'}`}
            aria-pressed={language === code}
            disabled={status !== STATUS.IDLE}
            onClick={() => changeLanguage(code)}
          >
            {label}
          </button>
        ))}
      </div>

      {variants && (
        <div className="passage-select-row">
          <label htmlFor="passage-variant">Passage</label>
          <select
            id="passage-variant"
            disabled={status !== STATUS.IDLE}
            value={variantId}
            onChange={(e) => setVariantId(e.target.value)}
          >
            {variants.map((v) => (
              <option key={v.id} value={v.id}>
                {v.title}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="passage-card">
        <h2>{passage.title}</h2>
        {passage.description && <p className="passage-description">{passage.description}</p>}
        <p className="passage-text">{renderPassageText(passage.text, passage.errorWords)}</p>
      </div>

      {language !== 'fil' && (
        <p className="engine-note scorer-note">
          Note: the real GOP pronunciation model only supports Filipino. An English passage here will
          only work if the server's scoring engine is set to <code>whisper</code> or <code>mock</code>.
        </p>
      )}

      <div className="recorder-panel">
        <div className="timer" data-recording={status === STATUS.RECORDING}>
          {mm}:{ss}
        </div>

        {status === STATUS.IDLE && (
          <div className="idle-actions">
            <button className="btn btn-primary" onClick={startRecording}>
              ● Start Recording
            </button>
            <div className="or-divider">or</div>
            <label className="btn btn-secondary file-upload-label">
              ⬆ Upload a Recording
              <input
                ref={fileInputRef}
                type="file"
                accept={UPLOAD_ACCEPT}
                onChange={handleFileSelected}
                hidden
              />
            </label>
          </div>
        )}

        {status === STATUS.RECORDING && (
          <button className="btn btn-stop" onClick={stopRecording}>
            ■ Stop Recording
          </button>
        )}

        {(status === STATUS.RECORDED || status === STATUS.SUBMITTING) && (
          <div className="post-recording">
            <p className="source-note">
              {source === 'uploaded' ? '📁 Uploaded file' : '🎙 Live recording'}
            </p>
            <audio controls src={audioUrl} />
            {seconds < MIN_DURATION_SECONDS && (
              <p className="error">
                That recording is only {seconds}s long — too short to be a full passage reading. Please
                {source === 'uploaded' ? ' pick a different file.' : ' record again.'}
              </p>
            )}
            <div className="button-row">
              <button className="btn btn-secondary" onClick={recordAgain} disabled={status === STATUS.SUBMITTING}>
                {source === 'uploaded' ? 'Choose Different Audio' : 'Record Again'}
              </button>
              <button
                className="btn btn-primary"
                onClick={handleSubmit}
                disabled={status === STATUS.SUBMITTING || seconds < MIN_DURATION_SECONDS}
              >
                {status === STATUS.SUBMITTING ? 'Scoring…' : 'Submit for Scoring'}
              </button>
            </div>
          </div>
        )}

        {error && <p className="error">{error}</p>}
      </div>
    </div>
  );
}

/**
 * Renders passage text as plain text, except words listed in `errorWords`
 * (the "with errors" variant's deliberate mistakes) get wrapped in a span so
 * they can be highlighted — matched case-insensitively against each word
 * with surrounding punctuation stripped, so "nangangalang" still matches
 * "nangangalang," or "Nangangalang".
 */
function renderPassageText(text, errorWords) {
  if (!errorWords || errorWords.length === 0) return text;
  const errorSet = new Set(errorWords.map((w) => w.toLowerCase()));

  return text.split(/(\s+)/).map((token, i) => {
    if (/^\s+$/.test(token)) return token;
    const bare = token.replace(/[^\p{L}\p{N}']/gu, '').toLowerCase();
    if (errorSet.has(bare)) {
      return (
        <span className="passage-error-word" key={i}>
          {token}
        </span>
      );
    }
    return token;
  });
}
