import { useState } from 'react';
import ReadingScreen from './ReadingScreen.jsx';
import TeacherReviewScreen from './TeacherReviewScreen.jsx';
import './App.css';

export default function App() {
  const [session, setSession] = useState(null);

  return (
    <div className="app">
      <header className="app-header">BasaQuest — Reading Proficiency Pipeline Prototype</header>
      {session ? (
        <TeacherReviewScreen session={session} onStartOver={() => setSession(null)} />
      ) : (
        <ReadingScreen onSessionCreated={setSession} />
      )}
    </div>
  );
}
