FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn
RUN printf 'from fastapi import FastAPI\napp = FastAPI()\n@app.get("/")\ndef root(): return {"status": "coming soon"}\n' > main.py
CMD exec uvicorn main:app --host 0.0.0.0 --port $PORT
