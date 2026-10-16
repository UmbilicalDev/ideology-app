from fastapi import FastAPI

app = FastAPI(title="ideology-app")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
