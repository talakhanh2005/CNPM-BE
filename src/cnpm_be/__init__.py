def main() -> None:
    import uvicorn

    uvicorn.run("cnpm_be.main:app", host="0.0.0.0", port=8000)
