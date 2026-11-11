

import csv
import io
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

app = FastAPI(
    title="EasyFlow AI Engine",
    description="Simple automation engine for everyone",
    version="0.2.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "X-Rows-Original",
        "X-Rows-Output",
        "X-Rows-Removed",
        "X-Duplicates-Removed"
    ]
)

@app.get("/")
def home():
    return {
        "name": "EasyFlow AI",
        "version": "0.2.0",
        "status": "running",
        "message": "Automation engine is ready"
    }

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.post("/api/csv/clean")
async def clean_csv(file: UploadFile = File(...)):

    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail="Please upload a CSV file"
        )

    content = await file.read()

    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail="Maximum file size is 10 MB"
        )

    if not content:
        raise HTTPException(
            status_code=400,
            detail="The uploaded file is empty"
        )

    text = None

    for encoding in ["utf-8-sig", "cp1256", "latin-1"]:
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue

    try:
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
    except csv.Error:
        raise HTTPException(
            status_code=400,
            detail="Invalid CSV file"
        )

    if not rows:
        raise HTTPException(
            status_code=400,
            detail="No data found"
        )

    headers = [cell.strip() for cell in rows[0]]

    if not any(headers):
        raise HTTPException(
            status_code=400,
            detail="CSV header is missing"
        )

    original_count = max(0, len(rows) - 1)
    cleaned_rows = []
    seen = set()
    duplicates_removed = 0
    empty_rows_removed = 0

    for row in rows[1:]:

        cleaned = [cell.strip() for cell in row]

        if not any(cleaned):
            empty_rows_removed += 1
            continue

        key = tuple(cleaned)

        if key in seen:
            duplicates_removed += 1
            continue

        seen.add(key)
        cleaned_rows.append(cleaned)

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(headers)
    writer.writerows(cleaned_rows)

    result = output.getvalue().encode("utf-8-sig")

    total_removed = (
        empty_rows_removed + duplicates_removed
    )

    return StreamingResponse(
        io.BytesIO(result),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition":
                'attachment; filename="easyflow_cleaned.csv"',
            "X-Rows-Original": str(original_count),
            "X-Rows-Output": str(len(cleaned_rows)),
            "X-Rows-Removed": str(total_removed),
            "X-Duplicates-Removed": str(duplicates_removed)
        }
    )
