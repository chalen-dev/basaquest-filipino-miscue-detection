import express from 'express';
import cors from 'cors';
import path from 'path';
import { fileURLToPath } from 'url';
import assessmentRoutes from './routes/assessment.js';
import { SESSIONS_DIR } from './sessionsStore.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = process.env.PORT || 4000;

const app = express();
app.use(cors());
app.use(express.json());
app.use('/uploads', express.static(path.join(__dirname, '..', 'uploads')));
app.use('/api/session-files', express.static(SESSIONS_DIR));
app.use('/api', assessmentRoutes);

app.get('/api/health', (_req, res) => res.json({ ok: true }));

app.listen(PORT, () => {
  console.log(`BasaQuest reading-assessment server listening on http://localhost:${PORT}`);
});
