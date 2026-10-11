# Deployment — GitHub + Render

## Why not GitHub Pages?

The project is a FastAPI application with server-side Python/ML code. GitHub Pages only publishes static files and does not run Python/FastAPI server code. Use GitHub as the source repository and Render as the web host.

## 1. Push to GitHub

```powershell
git init
git branch -M main
git add .
git commit -m "Initial AfterCode TrustGraph release"
git remote add origin https://github.com/<YOUR_USERNAME>/india-candle-ai-aftercode.git
git push -u origin main
```

## 2. Deploy on Render

Use **New → Blueprint** and connect the GitHub repository. Render will read `render.yaml`.

Or create a Web Service manually with:

- Build: `pip install -r requirements.txt`
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Health check: `/api/health`

## 3. Important runtime behavior

- The live market provider is Yahoo Finance when reachable.
- `ALLOW_FALLBACK=false` keeps the public deployment honest: if Yahoo data is unavailable, the API reports the data-service problem instead of silently presenting synthetic data as live.
- Do not commit `.env`, API keys, cookies, or personal credentials.

## 4. After deployment

Open the Render URL and verify:

- `/` loads the application
- `/api/health` returns HTTP 200
- stock search works
- stock analysis works for a supported Yahoo symbol
- repository health works
- public GitHub cloning works for a public repository

## 5. Auto deploys

When the GitHub branch connected to Render receives a new commit, Render can automatically redeploy the service.
