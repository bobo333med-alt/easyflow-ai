from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import csv
import io

app = FastAPI(title="EasyFlow AI", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "X-Rows-Original",
        "X-Rows-Output",
        "X-Rows-Removed",
        "X-Duplicates-Removed",
        "X-Rows-Empty-Removed",
    ],
)

MAX_SIZE = 10 * 1024 * 1024  # 10 ميغابايت


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/api/csv/clean")
async def clean_csv(file: UploadFile = File(...)):
    # 1) التحقق من الصيغة
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="الملف يجب أن يكون بصيغة CSV")

    raw = await file.read()

    # 2) التحقق من الحجم
    if len(raw) == 0:
        raise HTTPException(status_code=400, detail="الملف فارغ")
    if len(raw) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="حجم الملف يتجاوز 10 ميغابايت")

    # 3) قراءة المحتوى مع دعم الترميزات الشائعة
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("latin-1")
        except Exception:
            raise HTTPException(status_code=400, detail="تعذر قراءة ترميز الملف")

    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise HTTPException(status_code=400, detail="لا توجد بيانات في الملف")

    header = rows[0]
    data = rows[1:]
    original_count = len(data)

    # 4) إزالة الصفوف الفارغة
    non_empty = [r for r in data if any(cell.strip() for cell in r)]
    empty_removed = original_count - len(non_empty)

    # 5) إزالة الصفوف المكررة
    seen = set()
    unique = []
    duplicates_removed = 0
    for r in non_empty:
        key = tuple(cell.strip() for cell in r)
        if key in seen:
            duplicates_removed += 1
        else:
            seen.add(key)
            unique.append(r)

    output_count = len(unique)
    removed_total = original_count - output_count

    # 6) بناء ملف CSV النظيف
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    writer.writerows(unique)
    body = out.getvalue().encode("utf-8-sig")

    headers = {
        "Content-Disposition": 'attachment; filename="easyflow_cleaned.csv"',
        "X-Rows-Original": str(original_count),
        "X-Rows-Output": str(output_count),
        "X-Rows-Removed": str(removed_total),
        "X-Rows-Empty-Removed": str(empty_removed),
        "X-Duplicates-Removed": str(duplicates_removed),
    }

    return StreamingResponse(io.BytesIO(body), media_type="text/csv", headers=headers)


# 7) خدمة الواجهة من نفس الخادم (يجب أن يكون هذا آخر سطر في الملف)
static_dir = Path(__file__).parent
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
