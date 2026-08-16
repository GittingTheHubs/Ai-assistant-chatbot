# RUNBOOK — งานแก้ Product Dataset (TJ / Dev 2)

คู่มือจับมือทำ ตั้งแต่เครื่องเปล่าจนส่งงานเข้า GitHub
ทำตามลำดับ **ห้ามข้าม** ถ้าติดตรงไหนหยุดแล้วถามก่อน

เวลาที่ใช้ทั้งหมด: ประมาณ 3–4 ชั่วโมง (ส่วนใหญ่คือนั่งรอเครื่องประมวลผล)

---

## ภาพรวม: มึงกำลังทำอะไร

บริษัทส่ง `products_cleaned.xlsx` มาให้ ซึ่งข้อมูลเละ 3 แบบ:

| ปัญหา | ความรุนแรง |
|---|---|
| Product Category ใช้ไม่ได้ 558 จาก 720 ตัว (77%) | หนัก |
| ราคา 986 แถวเป็นค่าปลอม 1110 บาท และราคาจริง 245 แถวหายไป | **หนักที่สุด** |
| ไม่มี Keywords / Summary / Best For ให้ AI ใช้ค้นหา | หนัก |

งานมึงคือแปลงมันเป็นไฟล์ที่ AI ค้นเจอ โดยทำ 3 ขั้น:

```
products_export_1.csv          (ต้นฉบับดิบจาก Shopify — ข้อมูลครบ)
        |
        |  build_dataset.py          ขั้น 1: ล้างข้อมูล ฟรี ไม่ใช้ AI
        v
products_base.csv              (720 แถว ราคาถูกต้อง HTML หายแล้ว)
        |
        |  enrich_products.py        ขั้น 2: ให้ AI เติมคอลัมน์
        v
products_enriched.csv          (+ Category, Keywords, Summary, Best For ...)
        |
        |  vector_v2.py              ขั้น 3: ยัดเข้า vector DB
        v
แชทบอทตอบเก่งขึ้น
```

**จุดสำคัญ:** เราไม่แก้ `products_cleaned.xlsx` แต่สร้างใหม่จาก
`products_export_1.csv` ที่อยู่ใน repo อยู่แล้ว เพราะ CSV ตัวนั้นข้อมูลครบกว่า
ไฟล์ xlsx ที่บริษัทให้มา (ราคาจริงอยู่ในนั้น)

---

## PHASE 0 — ติดตั้งเครื่องมือ (ทำครั้งเดียว)

### 0.1 ลง Git และ GitHub Desktop

1. โหลด Git: https://git-scm.com/downloads → กด Next รัวๆ ค่าเริ่มต้นใช้ได้หมด
2. โหลด GitHub Desktop: https://desktop.github.com
3. เปิด GitHub Desktop → ล็อกอินด้วยบัญชีที่หัวหน้าเชิญมา

> ทำไมต้อง GitHub Desktop: มึงจะได้ไม่ต้องพิมพ์คำสั่ง git เลยสักตัว
> กดปุ่มเอาหมด เหมาะกับคนที่ไม่เคยใช้

### 0.2 Clone repo ลงเครื่อง

ใน GitHub Desktop → `File` → `Clone Repository` → แท็บ `GitHub.com`
→ เลือก `GittingTheHubs/Ai-assistant-chatbot` → `Clone`

**จด path ที่มันเซฟไว้** ปกติคือ:
```
C:\Users\<ชื่อมึง>\Documents\GitHub\Ai-assistant-chatbot
```

### 0.3 ลง Python

ถ้ายังไม่มี โหลดจาก https://www.python.org/downloads
**ตอนติดตั้งต้องติ๊ก `Add Python to PATH`** ไม่งั้นคำสั่งจะไม่ทำงาน

เช็คว่าได้แล้ว เปิด PowerShell พิมพ์:
```powershell
python --version
```
ต้องขึ้นเลขเวอร์ชัน ถ้าขึ้น error แปลว่าลืมติ๊ก PATH → ลงใหม่

### 0.4 ลง Ollama

โหลดจาก https://ollama.com/download ติดตั้งแล้วเปิดทิ้งไว้ (มันจะอยู่ใน system tray)

จากนั้นโหลดโมเดล 2 ตัว ใน PowerShell:
```powershell
ollama pull qwen2.5:3b
ollama pull mxbai-embed-large
```
รวมกันประมาณ 2–3 GB นั่งรอ

---

## PHASE 1 — เตรียม environment ในโฟลเดอร์ repo

เปิด PowerShell แล้ว `cd` เข้าโฟลเดอร์ repo:
```powershell
cd "$env:USERPROFILE\Documents\GitHub\Ai-assistant-chatbot"
```

สร้าง virtual environment (กล่องแยกสำหรับ library ของโปรเจกต์นี้):
```powershell
python -m venv venv
venv\Scripts\activate
```

**ถ้าเห็น `(venv)` ขึ้นหน้าบรรทัด = ถูกแล้ว**
ถ้าขึ้น error เรื่อง execution policy ให้รันอันนี้ก่อนแล้วลองใหม่:
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

ลง library:
```powershell
pip install -r requirements.txt
```

> ทุกครั้งที่เปิด PowerShell ใหม่ ต้อง `cd` เข้าโฟลเดอร์ แล้ว
> `venv\Scripts\activate` ก่อนเสมอ ไม่งั้นจะหา library ไม่เจอ

---

## PHASE 2 — จดหลักฐาน "ก่อนแก้" (อย่าข้าม)

**นี่คือขั้นที่จะทำให้หัวหน้าเห็นค่างานมึง** ถ้าไม่มี before ก็พิสูจน์ไม่ได้ว่า after ดีขึ้น

รันของเดิม:
```powershell
python main.py
```
ครั้งแรกมันจะ embed 720 ตัว กินเวลา 10–30 นาที ปล่อยไว้

พอขึ้น `Ask your question` ให้ถาม 8 คำถามนี้ **แล้วก๊อปคำตอบเก็บใส่ไฟล์ Word/Notepad**:

1. `แนะนำ antivirus สำหรับออฟฟิศเล็กๆ`
2. `มีระบบเก็บ log ตาม พรบ. คอมพิวเตอร์ไหม`
3. `M Cloud รุ่น S ราคาเท่าไหร่`
4. `ต้องการ software ที่ติดตั้ง on-premise`
5. `recommend firewall for enterprise`
6. `โปรแกรมป้องกันข้อมูลรั่วไหล`
7. `Safetica คืออะไร`
8. `มี solution อะไรบ้างสำหรับหน่วยงานราชการ`

ตั้งชื่อไฟล์ `before_after.md` หัวข้อ "BEFORE"

> ข้อ 3 สำคัญมาก — ตอนนี้มันจะตอบราคาผิดแน่นอน เพราะราคาจริง
> 260–59,920 บาท หายไปจาก xlsx อันนี้คือหลักฐานบั๊กที่มึงจะเอาไปเสนอ

พิมพ์ `q` เพื่อออก

---

## PHASE 3 — ขั้น 1: ล้างข้อมูล (ฟรี ไม่ใช้ AI)

เอาไฟล์ที่กุทำให้ 4 ไฟล์วางในโฟลเดอร์ repo:
`build_dataset.py`, `enrich_products.py`, `vector_v2.py`, `requirements.txt`

รัน:
```powershell
python build_dataset.py
```

ควรขึ้นประมาณนี้:
```
Loaded 1707 raw rows / 720 handles

Wrote products_base.csv: 720 products
  with real variants : 39
  variant rows kept  : 245
  empty description  : 4
  deployment detected: 300
  median desc length : 420
```

**ถ้าตัวเลขไม่ตรงนี้ หยุด แล้วถามก่อน**

สิ่งที่สคริปต์นี้ทำเสร็จให้แล้ว (จากงาน 10 ข้อ):
- ข้อ 7 Deployment — เดาจากคีย์เวิร์ดได้ 300 ตัว
- ข้อ 10 Clean Brand Names — `zoom`/`ZOOm` → `Zoom`, `vmware` → `VMware`,
  `Sonicwall` → `SonicWall`, `bittitan` → `BitTitan`, `eset nod32` → `ESET NOD32`
- ยุบ 1706 แถวเหลือ 720 แถว 1 สินค้า/แถว
- แปลง HTML เป็น plain text
- **กู้ราคาจริง 245 แถวที่หายไป**

เปิด `products_base.csv` ด้วย Excel ดูสัก 2 นาที ให้แน่ใจว่าหน้าตาโอเค
(ถ้าภาษาไทยเป็นตัวยึกยือ ให้เปิดผ่าน Excel → Data → From Text/CSV → เลือก UTF-8)

---

## PHASE 4 — ขั้น 2: ให้ AI เติมคอลัมน์

### 4.1 เลือก engine

เปิด `enrich_products.py` ดูบรรทัดบนๆ:

```python
BACKEND = "ollama"          # <-- ollama | openai | anthropic
OLLAMA_MODEL = "qwen2.5:7b"
LIMIT = 5                   # 5 = test run. Set to 0 to process all 720.
```

| ตัวเลือก | ราคา | คุณภาพภาษาไทย | เวลา 720 ตัว |
|---|---|---|---|
| `ollama` + qwen2.5:3b | ฟรี | แย่ | ~2 ชม. |
| `ollama` + qwen2.5:7b | ฟรี (ต้องมี RAM 8GB+) | พอใช้ | ~4 ชม. |
| `openai` gpt-4o-mini | **~12 บาท** | ดี | ~30 นาที |
| `anthropic` | ~40 บาท | ดีสุด | ~40 นาที |

**กุแนะนำ `openai`** 12 บาทถูกกว่าข้าวมื้อเดียว และคุณภาพต่างกันเยอะ
ถ้าต้องฟรีจริงๆ ให้ `ollama pull qwen2.5:7b` ก่อน

ถ้าเลือก openai: สร้างไฟล์ชื่อ `.env` ในโฟลเดอร์ repo ใส่บรรทัดเดียว
```
OPENAI_API_KEY=sk-xxxxxxxx
```
ไฟล์ `.env` อยู่ใน .gitignore แล้ว **จะไม่ถูก push ขึ้น GitHub** ปลอดภัย

### 4.2 ทดสอบ 5 ตัวก่อน

`LIMIT = 5` ตั้งไว้ให้แล้ว รันเลย:
```powershell
python enrich_products.py
```

เปิด `products_enriched.csv` ดูว่า 5 แถวแรกหน้าตาโอเคไหม เช็คว่า:
- `Category` ต้องเป็น `SIEM, Log Management` **ไม่ใช่** `Electronics > Networking`
- `Keywords` ต้องมีทั้งไทยและอังกฤษ
- `Summary_TH` ต้องเป็นภาษาไทยที่อ่านรู้เรื่อง 1–2 ประโยค

**ถ้าผลไม่โอเค ส่งตัวอย่างมาให้กุดู กุจะแก้ prompt ให้ อย่าเพิ่งรัน 720 ตัว**

### 4.3 รันจริงทั้ง 720

พอใจแล้วแก้เป็น:
```python
LIMIT = 0
```
แล้วรันใหม่:
```powershell
python enrich_products.py
```

นั่งรอได้เลย **ถ้าเน็ตหลุดหรือเผลอปิดหน้าต่าง ไม่เป็นไร** สคริปต์เก็บ cache
ไว้ใน `enrich_cache.jsonl` ทุกตัว รันใหม่มันไปต่อจากตัวที่ค้าง ไม่เริ่มใหม่

ตอนจบจะบอกว่าเติมได้กี่ตัว:
```
Wrote products_enriched.csv: 720 rows
  Category       filled: 720/720
  Best_For       filled: 720/720
  ...
```

ถ้ามีตัวที่ fail ให้รันซ้ำอีกรอบ มันจะลองเฉพาะตัวที่ยังไม่มี

---

## PHASE 5 — ขั้น 3: เปิดใช้ของใหม่

แก้ `main.py` บรรทัดที่ 3 จาก:
```python
from vector import retriever
```
เป็น:
```python
from vector_v2 import retriever
```

รัน:
```powershell
python main.py
```

มันจะ embed ใหม่ (อีก 10–30 นาที) แล้ว**ถาม 8 คำถามเดิมซ้ำ**
เก็บคำตอบใส่ `before_after.md` หัวข้อ "AFTER"

นี่คือของที่มึงจะเอาไปเสนอหัวหน้า

---

## PHASE 6 — ส่งงานเข้า GitHub

**ห้าม push ใส่ main ตรงๆ เด็ดขาด**

ใน GitHub Desktop:

1. `Current Branch` → `New Branch` → ตั้งชื่อ `tj/fix-product-dataset` → `Create Branch`
2. มันจะขึ้นรายการไฟล์ที่เปลี่ยนทางซ้าย ติ๊กเฉพาะที่ควรส่ง:
   - ✅ `build_dataset.py`, `enrich_products.py`, `vector_v2.py`
   - ✅ `requirements.txt`, `RUNBOOK_TJ.md`, `before_after.md`
   - ✅ `products_base.csv`, `products_enriched.csv`
   - ✅ `main.py` (ที่แก้ import)
   - ❌ **อย่าติ๊ก** `.env`, `venv/`, `chroma_v2_db/`, `enrich_cache.jsonl`
3. ช่อง Summary ล่างซ้าย พิมพ์: `Fix product dataset: rebuild from Shopify CSV + AI enrichment`
4. กด `Commit to tj/fix-product-dataset`
5. กด `Publish branch` ปุ่มใหญ่ข้างบน
6. กด `Create Pull Request` มันจะเปิดเว็บให้ → เขียนคำอธิบาย → `Create pull request`

### ข้อความที่ควรเขียนใน Pull Request

```
สรุปงานแก้ product dataset

พบปัญหาเพิ่มจากที่มอบหมาย:
- products_cleaned.xlsx มีราคาปลอม 1110 บาทใน 986 แถว
- ราคาจริง 245 แถวหายไป เช่น M Cloud มี 10 ระดับราคา
  260-59,920 บาท แต่ใน xlsx เหลือค่าเดียว
  ทำให้บอทตอบคำถามเรื่องราคาผิดทั้งหมด

จึงสร้าง dataset ใหม่จาก products_export_1.csv ต้นฉบับแทน

งานที่ทำตามที่มอบหมาย:
1. Fix Categories       -> AI สร้างใหม่เป็น technical domain
2. Best For             -> เพิ่มแล้ว
3. Keywords             -> เพิ่มแล้ว ไทย+อังกฤษ
4. Product Type         -> เพิ่มแล้ว
5. Alternatives         -> คำนวณจากสินค้าในร้านจริงเท่านั้น
                           ไม่ให้ AI เดา กันแนะนำของที่เราไม่ได้ขาย
6. Summary              -> เพิ่มแล้ว ไทย+อังกฤษ
7. Deployment           -> เพิ่มแล้ว
8. Org Size             -> เพิ่มแล้ว
9. Main Features        -> เพิ่มแล้ว
10. Clean Brand Names   -> เพิ่มแล้ว

ปรับ vector store ด้วย (vector_v2.py) เพราะของเดิม embed
description 28,000 ตัวอักษรทั้งก้อน ทำให้ signal จม
ผลเปรียบเทียบ before/after อยู่ใน before_after.md
```

---

## เรื่องที่ควรคุยกับทีม

1. **บั๊กราคา 1110** — บอกให้เร็วที่สุด เพราะถ้าทีมทำ demo ให้ mon.co.th ดู
   แล้วบอทตอบราคาผิด จะเสียหาย
2. **embedding model เป็นภาษาอังกฤษ** — `mxbai-embed-large` รองรับไทยไม่ดี
   ตอนนี้แก้ด้วยการใส่ keyword 2 ภาษา แต่ระยะยาวควรเปลี่ยนเป็น
   `bge-m3` ซึ่งรองรับหลายภาษา (`ollama pull bge-m3`)
3. **stack เปลี่ยนจากแผนเดิม** — repo ใช้ LangChain + Ollama + Chroma
   ไม่ใช่ Flowise + GPT-4o-mini ตามที่วางไว้ตอน idea presentation
   ต้องเคลียร์ก่อนเขียนเอกสาร Technology Selection

---

## ถ้าติด error

| อาการ | แก้ยังไง |
|---|---|
| `python is not recognized` | ลง Python ใหม่ ติ๊ก Add to PATH |
| `venv\Scripts\activate` ไม่ทำงาน | รัน `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `ModuleNotFoundError` | ลืม `venv\Scripts\activate` หรือลืม `pip install -r requirements.txt` |
| `connection refused` ตอนรัน ollama | Ollama ไม่ได้เปิด เช็ค system tray |
| `model not found` | ลืม `ollama pull` |
| ภาษาไทยเป็นตัวยึกยือใน Excel | เปิดผ่าน Data → From Text/CSV → UTF-8 |
| รันช้ามาก / ค้าง | ปกติ ปล่อยไว้ ถ้าเกิน 1 ชม.ไม่ขยับค่อยถาม |

ติดตรงไหนที่ไม่อยู่ในตารางนี้ ก๊อป error มาถามได้เลย
