# Auto-Mail

เว็บแอปสำหรับงานรายงานรอบ **19.00** โดยรับไฟล์ต้นทาง 3 ชนิด:

1. `TransferOrder_YYYYMMDD...xlsx` → แยกเป็น 7 ไฟล์ตาม logic เดิมใน VBA
2. `PurchaseOrder_YYYYMMDD...xlsx` → แยกเป็น 4 ไฟล์ตาม logic เดิมใน VBA
3. `TransferOrderDiff_YYYYMMDD...xlsx` → ไม่แยกข้อมูล เปลี่ยนชื่อเป็น `TransferOrderDiff_ DD-MM-YYYY Time 19.00.xlsx`

จากนั้นระบบจัด output 12 ไฟล์เข้า 6 email jobs พร้อม To / CC / Subject / Body ตาม `config/email_jobs.json`.

> รอบ 09.00 ไม่อยู่ใน automation นี้และส่งเองตาม workflow เดิม

## Output time

ชื่อไฟล์, Subject และ Body ของรอบอัตโนมัติใช้เวลา `19.00` ทั้งหมด โดยวันที่อ่านจากชื่อไฟล์ต้นทาง (`YYYYMMDD`).

## TransferOrder → 7 files

กรองปีจาก `Created date` แล้วสร้าง:

- `Transfer status = Received`
- `Transfer status = Created`
- `Transfer status = Deleted`
- `Transfer status = Shipped`
- `From warehouse = SCX_FFM` → `Dynamics SCX_FFM Out ...xlsx`
- `To warehouse = SCX_FFM` → `Dynamics SCX_FFM IN ...xlsx`
- `To warehouse = ZZ_CNN` → `Dynamics ZZ_CNN IN ...xlsx`

## PurchaseOrder → 4 files

กรองปีจาก `PurchaseCreatedDateTime` และ `INVENTLOCATIONID`:

- `ZZ_CNN` → `PRT.ZZ_CNN ...xlsx`
- `SCX_WH1` → `Rc.SCX_WH1 ...xlsx`
- `SCX_FFM` → `Rc.SCX_FFM ...xlsx`
- `SCX_XD` → `Rc.SCX_XD ...xlsx`

## Email jobs 6 ชุด

1. Transfer SCX_FFM B2C In/Out + PO SCX_FFM → 3 files
2. Transfer ZZ_CNN + PRT.ZZ_CNN → 2 files
3. Transfer Shipped + Created + PO SCX_WH1 → 3 files
4. Purchase SCX_XD → 1 file
5. Transfer Received → 1 file
6. Transfer Deleted + TransferOrderDiff → 2 files

Subject/Body ใช้ `{date_slash}` (`DD/MM/YYYY`) และ `{time}` (`19.00`).

## Hybrid delivery: แนบได้ให้แนบ / ใหญ่เกินให้เป็นลิงก์

ระบบพยายามแนบ `.xlsx` โดยตรงก่อนเสมอ และใช้ค่า `DIRECT_ATTACHMENT_MAX_MB` เป็นเพดาน **ขนาดอีเมลโดยประมาณหลัง Base64/MIME** ไม่ใช่แค่ขนาดไฟล์ดิบ.

ค่าเริ่มต้น:

```env
DIRECT_ATTACHMENT_MAX_MB=20
```

ถ้าเมลหนึ่งมีหลายไฟล์และเกินเพดาน ระบบจะย้ายไฟล์ที่ใหญ่ที่สุดไป Google Drive ทีละไฟล์จนส่วนที่เหลือปลอดภัยต่อการแนบ ดังนั้นเมลหนึ่งฉบับสามารถเป็นได้ 3 แบบ:

- `attachment` — ทุกไฟล์แนบตรง
- `hybrid` — บางไฟล์แนบตรง + บางไฟล์เป็น Drive link
- `drive_link` — ทุกไฟล์ในฉบับนั้นเป็น Drive link

สำหรับขนาดไฟล์ตัวอย่างปัจจุบัน `Rc.SCX_XD` ประมาณ 24.5 MiB จะถูกส่งเป็น Drive link เมื่อใช้ threshold 20 MB ส่วนชุดอื่นยังแนบตรงตามปกติ.

### Google Drive fallback

Drive fallback ปิดไว้เป็นค่าเริ่มต้นจนกว่าจะตั้ง OAuth ของ Gmail กลาง:

```env
DRIVE_FALLBACK_ENABLED=true
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REFRESH_TOKEN=...
GOOGLE_DRIVE_FOLDER_ID=...
GOOGLE_DRIVE_SHARE_MODE=anyone_with_link
```

`anyone_with_link` ใช้ง่ายที่สุดสำหรับผู้รับภายนอก แต่หมายความว่าใครก็ตามที่มี URL สามารถเปิดไฟล์ได้ จึงควรใช้ Gmail/Drive กลางเฉพาะงานนี้และโฟลเดอร์เฉพาะรายงาน.

หาก Drive fallback ยังไม่ถูกตั้งค่าและพบไฟล์เกิน threshold ระบบจะ **หยุดก่อนส่ง** แทนการส่งไม่ครบชุด.

## 3 โหมดการทำงาน

### Process Only

สร้าง output 12 ไฟล์และ ZIP โดยไม่ส่งอีเมล.

### Test Send 6 Emails

กรอกอีเมลทดสอบบนหน้าเว็บ แล้วระบบส่งทั้ง 6 template ไปที่อีเมลนั้นเพียงคนเดียว:

- ไม่ใช้ To จริง
- ไม่ใช้ CC จริง
- เติม `[TEST]` หน้า Subject
- ใช้ Body และไฟล์/Drive link แบบเดียวกับการส่งจริง

### Live Send

ส่ง To/CC จริงตาม `config/email_jobs.json`. หน้าเว็บจะไม่เปิด Live Send จนกว่า job ที่เปิดใช้งานทุกชุดจะมี To และมี confirmation ก่อนส่ง.

## ตั้งค่า Gmail สำหรับส่งเมล

เก็บค่าลับใน `.env` หรือ Hosting Secrets เท่านั้น **ห้าม commit password / App Password / OAuth token ลง GitHub**.

```env
EMAIL_SEND_ENABLED=true
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-central-mail@gmail.com
SMTP_PASSWORD=your-google-app-password
SMTP_FROM=your-central-mail@gmail.com
SMTP_USE_TLS=true
SMTP_USE_SSL=false
```

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

เปิด `http://localhost:8000`.

## Docker

```bash
docker build -t auto-mail .
docker run --env-file .env -p 8000:8000 auto-mail
```

## Planned next step

เพิ่ม central Gmail inbox watcher: ตรวจเมล Transfer Order / Purchase Order / Transfer Order Diff, รอครบ 3 รายงานของวันเดียวกัน, ดาวน์โหลด attachment, ประมวลผล 12 ไฟล์ และส่ง 6 เมลรอบ 19.00 อัตโนมัติ โดยยังเก็บ manual upload เป็น fallback.

## Tests

```bash
pytest -q
```
