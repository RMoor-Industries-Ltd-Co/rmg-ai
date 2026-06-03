# RMG AI

Isolated AI systems for the RMG ecosystem, owned by **PIAAR** (the software sector).
Decoupled from the RMG Creator OS codebase — the Creator OS gateway consumes these
services over an API.

- **`allen/`** — A.L.L.E.N: speech-enabled company LLM. Writes **brand-voice scripts**
  (HOOK → BODY → CTA) and can speak ("Express" via ElevenLabs) / listen ("Listen" via
  Whisper). Drafts are written to **Google Docs** for human approval, then the Creator OS
  gateway pulls the approved script into the production pipeline.
- **`allie/`** — A.L.L.I.E: investigator/research agent (RSS, deep research, personal
  library) that grounds ALLEN. *Planned.*

## Run (ALLEN)
```bash
uv venv && uv pip install -e .
cp .env.example .env        # set ANTHROPIC_API_KEY (+ reuse ELEVENLABS/GDRIVE keys)
uv run uvicorn allen.main:app --port 8090 --reload
```

## API (ALLEN)
| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | readiness (llm/tts/stt/docs) |
| GET | `/brands` | known brand voices |
| POST | `/draft` | `{brand, topic, persona?, output_kind?, allie_context?, write_doc?}` → brand-voice script (+ Google Doc draft) |
| POST | `/speak` | `{text, voice_id?}` → mp3 (ALLEN's voice; default COM Coach Rahm) |
| POST | `/listen` | multipart audio → `{text}` (Whisper STT; optional) |

## Pipeline integration
`/draft` writes a **Google Doc draft** in the scripts folder for review. Once approved,
the RMG Creator OS gateway pulls the final script → ElevenLabs voice → HeyGen avatar
video → Story Director / Social Manager. (See RMG Creator OS contracts 04, 08, 12.)

## Config
LLM is provider-abstracted (`allen/llm.py`); default **Anthropic Claude** (set
`ANTHROPIC_MODEL` to the current model). Speech reuses the Creator OS **ElevenLabs**
key; Docs reuse the Creator OS **rclone Drive OAuth**. See `.env.example`.
