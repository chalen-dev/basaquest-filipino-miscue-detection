import { useMemo, useRef, useState } from 'react';
import { validateSession } from './api.js';

const STATUS_OPTIONS = ['correct', 'mispronounced', 'omitted', 'inserted'];

const STATUS_LABEL = {
  correct: 'Correct',
  mispronounced: 'Mispronounced',
  omitted: 'Omitted',
  inserted: 'Inserted',
};

export default function TeacherReviewScreen({ session, onStartOver }) {
  const [words, setWords] = useState(session.words);
  const [review, setReview] = useState(() => {
    const initial = {};
    for (const w of session.words) {
      if (w.status !== 'correct') {
        initial[w.index] = { finalStatus: w.status, reviewed: false };
      }
    }
    return initial;
  });
  const [validated, setValidated] = useState(session.status === 'validated');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const audioRef = useRef(null);
  const stopAtHandlerRef = useRef(null);
  const [playingWordIndex, setPlayingWordIndex] = useState(null);

  const flagged = useMemo(
    () => [...words].filter((w) => w.status !== 'correct').sort((a, b) => a.index - b.index),
    [words]
  );
  const orderedWords = useMemo(() => [...words].sort((a, b) => a.index - b.index), [words]);

  const reviewedCount = Object.values(review).filter((r) => r.reviewed).length;
  const allReviewed = flagged.length === 0 || reviewedCount === flagged.length;

  function setFinalStatus(index, finalStatus) {
    setReview((prev) => ({ ...prev, [index]: { finalStatus, reviewed: true } }));
  }

  function confirmAsIs(index, autoStatus) {
    setReview((prev) => ({ ...prev, [index]: { finalStatus: autoStatus, reviewed: true } }));
  }

  // Small buffer around the word's exact timestamps — Whisper's word boundaries can be
  // a touch tight, and a hair of context on each side makes the clip easier to judge.
  const CHUNK_PADDING = 0.15;

  function playWordChunk(wordIndex, startTime, endTime) {
    const audio = audioRef.current;
    if (!audio) return;

    if (stopAtHandlerRef.current) {
      const { timeupdate, pause } = stopAtHandlerRef.current;
      audio.removeEventListener('timeupdate', timeupdate);
      audio.removeEventListener('pause', pause);
      stopAtHandlerRef.current = null;
    }

    const clipEnd = endTime + CHUNK_PADDING;
    const handleTimeUpdate = () => {
      if (audio.currentTime >= clipEnd) {
        audio.pause();
      }
    };
    const handlePause = () => {
      audio.removeEventListener('timeupdate', handleTimeUpdate);
      audio.removeEventListener('pause', handlePause);
      stopAtHandlerRef.current = null;
      setPlayingWordIndex((current) => (current === wordIndex ? null : current));
    };

    stopAtHandlerRef.current = { timeupdate: handleTimeUpdate, pause: handlePause };
    audio.addEventListener('timeupdate', handleTimeUpdate);
    audio.addEventListener('pause', handlePause);

    audio.currentTime = Math.max(0, startTime - CHUNK_PADDING);
    setPlayingWordIndex(wordIndex);
    audio.play();
  }

  async function handleValidate() {
    setSaving(true);
    setError(null);
    try {
      const wordOverrides = Object.fromEntries(
        Object.entries(review).map(([index, r]) => [index, r.finalStatus])
      );
      const updated = await validateSession(session.id, { wordOverrides, validated: true });
      setWords(updated.words);
      setValidated(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="screen">
      <h1>Teacher Review</h1>
      <p className="subtitle">
        Listen to the recording, follow along, and confirm or correct each flagged word before validating.
      </p>

      <audio ref={audioRef} controls src={session.audioUrl} className="review-audio" />

      <div className="passage-card">
        <p className="passage-text">
          {orderedWords.map((w) => (
            <WordSpan key={`${w.index}-${w.word}`} word={w} />
          ))}
        </p>
        <p className="engine-note">
          Scored by engine: <code>{session.engine}</code>
          {session.language && (
            <>
              {' '}
              (<code>{session.language}</code>)
            </>
          )}{' '}
          — estimated duration {session.durationSeconds}s
        </p>
      </div>

      {flagged.length === 0 ? (
        <p className="all-correct">No words were flagged — every word was read correctly.</p>
      ) : (
        <div className="flag-review">
          <h2>
            Flagged Words ({reviewedCount}/{flagged.length} reviewed)
          </h2>
          {flagged.map((w) => (
            <div className={`flag-row status-${w.status}`} key={`${w.index}-${w.word}`}>
              <div className="flag-row-main">
                <span className="flag-word">"{w.word}"</span>
                <span className={`badge badge-${w.status}`}>{STATUS_LABEL[w.status]}</span>
                <span className="confidence">confidence {Math.round(w.confidence * 100)}%</span>
                {review[w.index]?.reviewed && <span className="reviewed-tick">✓ reviewed</span>}
              </div>
              <div className="flag-row-controls">
                {w.startTime != null ? (
                  <button
                    className="btn btn-small btn-secondary"
                    onClick={() => playWordChunk(w.index, w.startTime, w.endTime)}
                  >
                    {playingWordIndex === w.index ? '▶ Playing…' : `▶ Play ${w.startTime.toFixed(1)}s–${w.endTime.toFixed(1)}s`}
                  </button>
                ) : (
                  <span className="no-audio-note" title="This word was never heard in the recording, so there's no audio moment to play">
                    no audio (omitted)
                  </span>
                )}
                <button
                  className="btn btn-small btn-secondary"
                  disabled={validated}
                  onClick={() => confirmAsIs(w.index, w.status)}
                >
                  Confirm as {STATUS_LABEL[w.status]}
                </button>
                <select
                  disabled={validated}
                  value={review[w.index]?.finalStatus ?? w.status}
                  onChange={(e) => setFinalStatus(w.index, e.target.value)}
                >
                  {STATUS_OPTIONS.map((opt) => (
                    <option key={opt} value={opt}>
                      Override: {STATUS_LABEL[opt]}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          ))}
        </div>
      )}

      {error && <p className="error">{error}</p>}

      {validated ? (
        <div className="validated-banner">
          ✓ Results validated. This session is final.
          <button className="btn btn-secondary" onClick={onStartOver}>
            Start New Session
          </button>
        </div>
      ) : (
        <div className="button-row">
          <button className="btn btn-secondary" onClick={onStartOver} disabled={saving}>
            Discard &amp; Start Over
          </button>
          <button className="btn btn-primary" onClick={handleValidate} disabled={!allReviewed || saving}>
            {saving ? 'Saving…' : 'Validate Results'}
          </button>
        </div>
      )}
    </div>
  );
}

function WordSpan({ word }) {
  if (word.status === 'inserted') {
    return <span className="word word-inserted"> +{word.word}</span>;
  }
  if (word.status === 'omitted') {
    return <span className="word word-omitted"> {word.word}</span>;
  }
  if (word.status === 'mispronounced') {
    return <span className="word word-mispronounced"> {word.word}</span>;
  }
  return <span className="word"> {word.word}</span>;
}
