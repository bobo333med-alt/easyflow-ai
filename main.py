from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path
import csv
import io
import os
import sqlite3
from datetime import datetime

# إعداد الذكاء الاصطناعي (Groq)
from groq import Groq

app = FastAPI(title="EasyFlow AI", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "X-Rows-Original", "X-Rows-Output", "X-Rows-Removed", 
        "X-Duplicates-Removed", "X-Rows-Empty-Removed",
    ],
)

# --- إعداد قاعدة البيانات (SQLite) ---
DB_FILE = "easyflow.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_type TEXT,
                    status TEXT,
                    details TEXT,
                    timestamp TEXT
                 )''')
    conn.commit()
    conn.close()

init_db()

def log_execution(task_type, status, details):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO executions (task_type, status, details, timestamp) VALUES (?, ?, ?, ?)",
              (task_type, status, details, now))
    conn.commit()
    conn.close()

# --- قسم الذكاء الاصطناعي (Groq) ---
api_key = os.environ.get("GROQ_API_KEY")
client = Groq(api_key=api_key) if api_key else None

class ChatRequest(BaseModel):
    message: str

@app.post("/api/chat")
async def chat_with_ai(request: ChatRequest):
    if not client:
        return {"response": "عذراً، مفتاح الذكاء الاصطناعي (GROQ_API_KEY) غير مضاف في إعدادات Render."}

    prompt = f"""
    أنت EasyFlow AI، منصة ذكية لأتمتة المهام.
    المستخدم يقول: "{request.message}"
    1. افهم طلب المستخدم.
    2. إذا كان يطلب أتمتة، اقترح خطة عمل مقسمة لخطوات واضحة.
    3. إذا كان الطلب يتعلق بملفات CSV أو الجداول، أخبره أنه يمكنه تجربة ذلك فوراً بالنزول إلى قسم "تنظيف ملف CSV" في الصفحة.
    أجب باللغة العربية، بأسلوب ودود، مختصر، وواضح جداً.
    """
    try:
        completion = client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=1024,
        )
        log_execution("محادثة ذكية", "ناجحة", f"طلب المستخدم: {request.message[:50]}...")
        return {"response": completion.choices[0].message.content}
    except Exception as e:
        return {"response": f"حدث خطأ أثناء الاتصال بالذكاء الاصطناعي: {str(e)}"}


# --- محرك تنظيف CSV (تم تحديثه ليكون ذكياً) ---
MAX_SIZE = 10 * 1024 * 1024

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.post("/api/csv/clean")
async def clean_csv(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="الملف يجب أن يكون بصيغة CSV")
    
    raw = await file.read()
    if len(raw) == 0:
        raise HTTPException(status_code=400, detail="الملف فارغ")
    if len(raw) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="حجم الملف يتجاوز 10 ميغابايت")

    # 1. اكتشاف الترميز (Encoding) تلقائياً ليدعم الفرنسية والعربية
    text = None
    for enc in ["utf-8-sig", "utf-8", "cp1252", "latin-1"]:
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    
    if text is None:
        raise HTTPException(status_code=400, detail="تعذر قراءة ترميز الملف")

    # 2. اكتشاف الفاصلة تلقائياً (فاصلة عادية أو منقوطة) ليدعم إعدادات Excel الفرنسية
    try:
        # نستخدم أول 1024 حرف لاكتشاف الفاصل
        dialect = csv.Sniffer().sniff(text[:1024])
        delimiter = dialect.delimiter
    except csv.Error:
        # إذا فشل الاكتشاف، نستخدم الفاصلة المنقوطة كافتراضي (لأن جهازك فرنسي)
        delimiter = ';' if ';' in text[:1024] else ','

    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    if not rows:
        raise HTTPException(status_code=400, detail="لا توجد بيانات في الملف")

    header = rows[0]
    data = rows[1:]
    original_count = len(data)

    non_empty = [r for r in data if any(cell.strip() for cell in r)]
    empty_removed = original_count - len(non_empty)

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

    # نعيد بناء الملف بالفاصلة العادية أو المنقوطة حسب ما اكتشفناه
    out = io.StringIO()
    writer = csv.writer(out, delimiter=delimiter)
    writer.writerow(header)
    writer.writerows(unique)
    body = out.getvalue().encode("utf-8-sig")

    details = f"أصلية: {original_count} | محذوفة: {removed_total} | مكررة: {duplicates_removed}"
    log_execution("تنظيف CSV", "ناجحة", details)

    headers = {
        "Content-Disposition": 'attachment; filename="easyflow_cleaned.csv"',
        "X-Rows-Original": str(original_count),
        "X-Rows-Output": str(output_count),
        "X-Rows-Removed": str(removed_total),
        "X-Rows-Empty-Removed": str(empty_removed),
        "X-Duplicates-Removed": str(duplicates_removed),
    }

    return StreamingResponse(io.BytesIO(body), media_type="text/csv", headers=headers)

# --- مسارات الإحصائيات والسجل ---
@app.get("/api/stats")
def get_stats():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM executions WHERE task_type='تنظيف CSV'")
    csv_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM executions")
    total_count = c.fetchone()[0]
    conn.close()
    return {
        "total_executions": total_count,
        "csv_cleaned": csv_count,
        "success_rate": "100%" if total_count > 0 else "—"
    }

@app.get("/api/history")
def get_history():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT task_type, status, details, timestamp FROM executions ORDER BY id DESC LIMIT 10")
    rows = c.fetchall()
    conn.close()
    return [{"task": r[0], "status": r[1], "details": r[2], "time": r[3]} for r in rows]

# --- خدمة الواجهة ---
static_dir = Path(__file__).parent
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
