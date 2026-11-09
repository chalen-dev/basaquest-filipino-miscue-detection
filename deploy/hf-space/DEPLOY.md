# Deploying the Filipino scorer to a Hugging Face Space (testing)

What this deploys: `models/final-model-v2` (wav2vec2 phoneme model) with the GOP
scorer, behind `POST /score`. It runs on the free CPU Space (2 vCPU, 16 GB).
Expect roughly the length of the recording, or a bit more, to score it
(a 34 s recording took ~24 s on a desktop CPU; the free Space is slower).

## One time

1. Make a Hugging Face account and create a **write** access token
   (Settings -> Access Tokens). Keep it to yourself.
2. Install the uploader and log in. The login prompts for the token, so it never
   goes in a file or a chat:

   ```powershell
   pip install -U huggingface_hub
   hf auth login
   ```

3. Choose an API key for the scorer: any long random string. It is what
   `basaquest-scoring` will send, and the Space refuses requests without it.

## Build and upload

```powershell
# from the repo root
powershell -File deploy\hf-space\prepare.ps1        # builds deploy\hf-space\build (1.2 GB)

hf repos create YOUR-USERNAME/basaquest-filipino-scorer --repo-type space --space-sdk docker --private
hf upload YOUR-USERNAME/basaquest-filipino-scorer deploy\hf-space\build . --repo-type space
```

Then, on the Space's page -> Settings -> **Variables and secrets** -> New secret:
name `GOP_API_KEY`, value = the key from step 3. The Space builds and starts by
itself (first build takes several minutes; the log is on the Space page). When it
says "Running", its address is
`https://YOUR-USERNAME-basaquest-filipino-scorer.hf.space`.

The Space is private, so only your account can see its files (the model weights
included). Calls to it need two things: the `x-api-key`, and a Hugging Face **read**
token as a bearer token (Settings -> Access Tokens -> create a token with Read access;
that one is for the server, not your login token). Do not put either in the Space's
files; keep the key as the secret above.

## Point the scoring service at it

On Render, in the `basaquest-scoring` service's Environment:

| name | value |
| --- | --- |
| `GOP_SERVICE_URL` | `https://YOUR-USERNAME-basaquest-filipino-scorer.hf.space` |
| `GOP_API_KEY` | the key from step 3 |
| `GOP_HF_TOKEN` | the Hugging Face read token (needed because the Space is private) |

Save, and Render redeploys. Filipino passages in Reading Coach then score through it.

## Notes

- A free Space goes to sleep after a while unused; the first request after that
  waits for it to wake (a minute or two).
- Swap models: `prepare.ps1 -Model final-model-child-augmented-v1 -Calibration calibration-child-augmented.json`,
  then upload again.
- `calibration.json` for `final-model-v2` was measured on one adult recording, so
  expect it to flag more words than it should. Re-run `gop/calibrate.py` against
  this model before trusting the flags.
