# Auto-Mail

เว็บแอปสำหรับงานรายงานรอบ **19.00** โดยมี **2 ช่องทางรับข้อมูล** ที่ใช้ processor และ email templates ชุดเดียวกัน:

1. **Auto Inbox** — ตรวจเมลกลางอัตโนมัติและรอรายงานของวันเดียวกันให้ครบ 3 ชนิด
2. **Manual Upload** — ผู้ใช้แนบไฟล์ 3 ไฟล์บนหน้าเว็บเอง ใช้เป็นช่องทางหลักหรือ fallback ได้ตลอด

ไฟล์ต้นทาง 3 ชนิดคือ:

1. `TransferOrder_YYYYMMDD...xlsx` → แยกเป็น 7 ไฟล์ตาม logic เดิมใน VBA
2. `PurchaseOrder_YYYYMMDD...xlsx` → แยกเป็น 4 ไฟล์ตาม logic เดิมใน VBA
3. `TransferOrderDiff_YYYYMMDD...xlsx` → ไม่แยกข้อมูล เปลี่ยนชื่อเป็น `TransferOrderDiff_ DD-MM-YYYY Time 19.00.xlsx`

จากนั้นระบบจัด output 12 ไฟล์เข้า 6 email jobs.

> รอบ 09.00 ไม่อยู่ใน automation นี้และส่งเองตาม workflow เดิม

## Email Settings บนหน้าเว็บ

ผู้ใช้กำหนดผู้รับได้เองโดยไม่ต้องแก้โค้ด:

- `Test Email` — ผู้รับสำหรับ Test Send ทั้ง 6 ฉบับ
- Email 1–6 — แต่ละชุดมีช่อง `TO` และ `CC`
- รองรับหลายอีเมล โดยคั่นด้วย `;`, `,` หรือขึ้นบรรทัดใหม่
- กด **Save Settings** แล้ว Test Send / Live Send / Auto Inbox จะใช้ค่าที่บันทึกไว้ชุดเดียวกัน
- Subject, Body และการจับคู่ไฟล์ยังมาจาก `config/email_jobs.json` เพื่อป้องกันการแก้ template โดยไม่ตั้งใจ

ค่าผู้รับถูกบันทึกเป็น runtime data ที่ `data/email_settings.json` (หรือใต้ `AUTO_MAIL_DATA_DIR`) และ `data/` ถูก ignore จาก GitHub จึงไม่ commit รายชื่อผู้รับจริงลง public repository.

สำหรับ production ควรผูก `AUTO_MAIL_DATA_DIR` กับ persistent disk/volume เพื่อให้ Settings, Inbox state และ run data ไม่หายเมื่อ container restart:

```env
AUTO_MAIL_DATA_DIR=/var/data/auto-mail
```

## 2 ช่องทางรับรายงาน

### 1) Auto Inbox

Watcher ตรวจ Inbox ของเมลกลางและจับ attachment ตามชื่อ `TransferOrder`, `PurchaseOrder`, `TransferOrderDiff` เมื่อครบทั้ง 3 ชนิดของวันเดียวกันจึงเริ่มประมวลผลและ Live Send อัตโนมัติ.

ข้อจำกัด: ผู้ให้บริการอีเมลอาจปฏิเสธเมลต้นทางที่มีไฟล์ใหญ่มาก เช่น PurchaseOrder ประมาณ 40 MB. ถ้าเมลนั้นเข้า Inbox ไม่ได้ ให้ใช้ Manual Upload แทนในวันนั้น โดยไม่ต้องเปลี่ยน logic การประมวลผลหรือการส่งออก.

### 2) Manual Upload

หน้าเว็บรับไฟล์ 3 ไฟล์พร้อมกัน ตรวจชนิดและวันที่จากชื่อไฟล์ แล้วให้เลือก `Process Only`, `Test Send 6 Emails`, หรือ `Live Send`. ช่องทางนี้ใช้งานได้แม้ Auto Inbox ปิดอยู่หรือไฟล์ต้นทางใหญ่เกินข้อจำกัดของอีเมล.

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

## การส่งไฟล์: แนบทั้งหมด หรือเป็นลิงก์ทั้งหมด

ระบบตัดสินใจ **ทีละอีเมล** และมีเพียง 2 รูปแบบเท่านั้น:

- `attachment` — ถ้าขนาดรวมส่งได้ จะแนบ `.xlsx` **ทุกไฟล์ของอีเมลนั้น**
- `drive_link` — ถ้าขนาดรวมใหญ่เกินเกณฑ์ จะ **ไม่แนบไฟล์เลย** และอัปโหลด **ทุกไฟล์ของอีเมลนั้น** ไป Google Drive พร้อมใส่ลิงก์ทั้งหมดในข้อความ

ไม่มีโหมดผสมไฟล์แนบ + Drive link ในอีเมลฉบับเดียว.

ระบบใช้ `DIRECT_ATTACHMENT_MAX_MB` เป็นเพดานขนาดอีเมลโดยประมาณหลัง Base64/MIME ไม่ใช่แค่ขนาดไฟล์ดิบ:

```env
DIRECT_ATTACHMENT_MAX_MB=20
```

สำหรับขนาดไฟล์ตัวอย่างปัจจุบัน `Rc.SCX_XD` ประมาณ 24.5 MiB จะใช้ Drive link ส่วนอีก 5 email groups ยังแนบไฟล์ตรงตามปกติ หากในอนาคตกลุ่มใดรวมกันเกิน threshold ทั้งกลุ่มนั้นจะเปลี่ยนเป็น Drive link ทั้งหมด.

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

`anyone_with_link` ใช้ง่ายสำหรับผู้รับภายนอก แต่หมายความว่าใครก็ตามที่มี URL สามารถเปิดไฟล์ได้ จึงควรใช้ Gmail/Drive กลางเฉพาะงานนี้และโฟลเดอร์เฉพาะรายงาน.

หาก Drive fallback ยังไม่ถูกตั้งค่าและมี email group เกิน threshold ระบบจะ **หยุดก่อนส่ง** แทนการส่งไม่ครบชุด.

## 3 โหมดการทำงานจาก Manual Upload

### Process Only

สร้าง output 12 ไฟล์และ ZIP โดยไม่ส่งอีเมล.

### Test Send 6 Emails

ใช้ `Test Email` ที่บันทึกไว้ในหน้า Email Settings แล้วส่งทั้ง 6 template ไปที่อีเมลนั้นเพียงคนเดียว:

- ไม่ใช้ To จริง
- ไม่ใช้ CC จริง
- เติม `[TEST]` หน้า Subject
- ใช้กฎ attachment / Drive link แบบเดียวกับ Live Send

### Live Send

ส่ง To/CC ของ Email 1–6 ที่บันทึกไว้บนหน้าเว็บ. ปุ่ม Live Send จะยังไม่พร้อมถ้า job ที่เปิดใช้งานชุดใดยังไม่มี `TO` และมี confirmation ก่อนส่ง.

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

`TEST_EMAIL_DEFAULT` เป็นค่าเริ่มต้นก่อนบันทึกผ่านหน้าเว็บครั้งแรกเท่านั้น และควรตั้งค่าจริงใน hosting secret:

```env
TEST_EMAIL_DEFAULT=
```

## Gmail Inbox watcher

```env
INBOX_WATCH_ENABLED=true
INBOX_HOST=imap.gmail.com
INBOX_PORT=993
INBOX_USERNAME=your-central-mail@gmail.com
INBOX_PASSWORD=your-google-app-password
INBOX_FOLDER=INBOX
INBOX_POLL_SECONDS=60
INBOX_SCAN_LIMIT=200
INBOX_MAX_REPORT_AGE_DAYS=3
INBOX_ALLOWED_SENDERS=your-company-email@example.com
```

เพื่อความปลอดภัย ควรใส่ `INBOX_ALLOWED_SENDERS` เป็นอีเมลบริษัทที่ใช้ส่งรายงานจริง ระบบใช้ `BODY.PEEK[]` จึงไม่จำเป็นต้อง mark เมลเป็น read และมี state file ป้องกันการหยิบ batch เดิมมาส่งซ้ำหลัง restart.

Watcher จะยังไม่เริ่ม Auto Send จนกว่า `EMAIL_SEND_ENABLED=true`, SMTP พร้อม และ email job ที่เปิดใช้ทุกชุดมีผู้รับ `TO` ครบ. ควรรัน production ด้วย **1 application worker** เพื่อไม่ให้มี watcher หลายตัวใน instance เดียวกัน.

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

## Tests

```bash
pytest -q
```
