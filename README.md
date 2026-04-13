# ATS Resume Analyzer (COMPANY PROJECT) 

A local, privacy-first ATS tool. Uploads stay in-memory — nothing is stored.

## Prerequisites
- Python 3.10+
- Node.js 18+
- Ollama installed (https://ollama.com)

---

## Step 1 — Set up Ollama

```bash
# Pull the phi model (one-time, ~4GB download)
ollama pull phi

# Start Ollama (keep this terminal open, or it runs as a service automatically)
ollama serve
```

Verify Ollama is working:
```bash
curl http://localhost:11434/api/tags
# Should list "phi" in the response
```

Want a different model? Try these free options:
```bash
ollama pull llama3       # Meta's Llama 3 (better but slower)
ollama pull phi3         # Microsoft Phi-3 (fast, small)
ollama pull gemma2       # Google Gemma 2
```
Then change `OLLAMA_MODEL = "phi"` in backend/main.py to your chosen model.

---

## Step 2 — Backend Setup

```bash
# Go into the backend folder
cd backend

# Create a Python virtual environment (keeps things clean)
python -m venv venv

# Activate it
# On Windows:
venv\Scripts\activate
# On Mac/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start the backend server
python main.py
```

You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000
```

Test it:
```bash
curl http://localhost:8000/health
```

---

## Step 3 — Frontend Setup

Open a NEW terminal window (keep backend running):

```bash
# Go into the frontend folder
cd frontend

# Install Node.js packages
npm install

# Start the development server
npm run dev
```

You should see:
```
VITE v5.x.x  ready in xxx ms
➜  Local:   http://localhost:5173/
```

Open your browser to: **http://localhost:5173**

---

## How to use

1. Upload a resume (PDF, DOCX, or TXT)
2. Paste the job description
3. Click "Analyze Resume"
4. Wait 15–60 seconds (Ollama processes locally)
5. See the verdict: HIRE / MAYBE / NO_HIRE

**Refresh the page = all data gone.** Nothing is stored anywhere.

---

## Changing the AI Model

In `backend/main.py`, find this line:
```python
OLLAMA_MODEL = "phi"
```
Change `"phi"` to any model you've pulled with `ollama pull`.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "Cannot connect to Ollama" | Run `ollama serve` in a terminal |
| "Model not found" | Run `ollama pull phi` |
| Analysis takes forever | Try a smaller model like `phi3` |
| PDF text is empty | The PDF might be image-only (scanned). Convert it to text first. |
| CORS error in browser | Make sure backend is on port 8000 |
