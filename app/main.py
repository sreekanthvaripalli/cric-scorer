from fastapi import FastAPI

app = FastAPI(title="Cric-Scorer API")

@app.get("/health")
def health():
    return {"status": "ok"}
