from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path
import csv
import io
import os

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

# --- قسم الذكاء الاصطناعي ---
api_key = os.environ.get("GROQ_API_KEY")
if api_key:
    client = Groq(api_key=api_key)
else:
    client = None

class ChatRequest(BaseModel):
    message: str

@app.post("/api/chat")
async def chat_with_ai(request: ChatRequest):
    if not client:
        return {"response": "عذراً، مفتاح الذكاء الاصطناعي (GROQ_API_KEY) غير مضاف في إعدادات Render. يرجى إضافته لتفعيل المحادثة."}

    prompt = f"""
    أنت EasyFlow AI، منصة ذكية لأتمتة المهام.
    المستخدم يقول: "{request.message}"
    
    مهمتك:
    1. افهم طلب المستخدم.
    2. إذا كان يطلب أتمتة، اقترح خطة عمل مقسمة لخطوات واضحة.
    3. إذا كان الطلب يتعلق بملفات CSV أو الجداول، أخبره أنه يمكنه تجربة ذلك فوراً بالنزول إلى قسم "تنظيف ملف CSV" في الصفحة.
    4. إذا كان الطلب غير مدعوم حالياً (مثل إرسال إيميل)، اقترح عليه الفكرة وقل له أنها قيد التطوير.
    
    أجب باللغة العربية، بأسلوب ودود، مختصر، وواضح جداً.
    """
    
    try:
        # استخدام نموذج Llama 3 السريع من جروك
        completion = client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=1024,
        )
        return {"response": completion.choices[0].message.content}
    except Exception as e:
        return {"response": f"حدث خطأ أثناء الاتصال بالذكاء الاصطناعي: {str(e)}"}

# --- محرك تنظيف CSV ---
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

# --- خدمة الواجهة ---
static_dir = Path(__file__).parent
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
