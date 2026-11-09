---
title: BasaQuest Filipino Scorer
emoji: 🦉
colorFrom: green
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---

Filipino pronunciation scorer for BasaQuest (testing). A wav2vec2 phoneme model
with Goodness-of-Pronunciation scoring. `POST /score` with the passage's words and
a recording; requires the `x-api-key` header. Nothing is stored.
