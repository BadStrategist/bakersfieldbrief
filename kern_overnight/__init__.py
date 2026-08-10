"""The Kern Overnight — scanner-to-newsletter pipeline.

Stages: fetch (Broadcastify feed 14029) → transcribe (ffmpeg + Silero VAD +
faster-whisper) → extract (LLM → incidents JSON) → write (LLM → Markdown
brief) → deliver (briefs/DATE.md for human review).

Run:  python -m kern_overnight.run [YYYY-MM-DD]   (default: last night)
"""
