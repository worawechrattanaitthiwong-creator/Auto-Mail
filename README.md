# Auto-Mail

เว็บแอปสำหรับงานรายงาน 3 ไฟล์:

1. `TransferOrder_YYYYMMDD...xlsx` → แยกเป็น 7 ไฟล์ตาม logic เดิมใน VBA
2. `PurchaseOrder_YYYYMMDD...xlsx` → แยกเป็น 4 ไฟล์ตาม logic เดิมใน VBA
3. `TransferOrderDiff_YYYYMMDD...xlsx` → ไม่แยกข้อมูล เปลี่ยนชื่อเป็น `TransferOrderDiff_ DD-MM-YYYY Time 19.00.xlsx`

จากนั้นระบบจัด 12 ไฟล์เข้า 6 email jobs และรองรับ To / CC / Subject / Body ที่กำหนดไว้ใน `config/email_jobs.json`.

## Logic ที่ย้ายมาจาก VBA

### TransferOrder → 7 files

กรองปีจาก `Created date` ตามปีที่อ่านจากชื่อไฟล์ แล้วสร้าง:

- `Transfer status = Received`
- `Transfer status = Created`
- `Transfer status = Deleted`
- `Transfer status = Shipped`
- `From warehouse = SCX_FFM` → `Dynamics SCX_FFM Out ...xlsx`
- `To warehouse = SCX_FFM` → `Dynamics SCX_FFM IN ...xlsx`
- `To warehouse = ZZ_CNN` → `Dynamics ZZ_CNN IN ...xlsx`

### PurchaseOrder → 4 files

กรองปีจาก `PurchaseCreatedDateTime` และ `INVENTLOCATIONID`:

- `ZZ_CNN` → `PRT.ZZ_CNN ...xlsx`
- `SCX_WH1` → `Rc.SCX_WH1 ...xlsx`
- `SCX_FFM` → `Rc.SCX_FFM ...xlsx`
- `SCX_XD` → `Rc.SCX_XD ...xlsx`

วันที่สำหรับ output ทั้งหมดอ่านจากชื่อ input (`YYYYMMDD`) จึงไม่ต้องกรอกปีหรือวันที่เอง.

## Email jobs 6 ชุด

Template ใน `config/email_jobs.json` เรียงตามตัวอย่างเมลจริง:

1. Transfer SCX_FFM B2C In/Out + PO SCX_FFM → 3 attachments
2. Transfer ZZ_CNN + PRT.ZZ_CNN → 2 attachments
3. Transfer Shipped + Created + PO SCX_WH1 → 3 attachments
4. Purchase SCX_XD → 1 attachment
5. Transfer Received → 1 attachment
6. Transfer Deleted + TransferOrderDiff → 2 attachments

Subject และ Body ใช้วันที่ `{date_slash}` (`DD/MM/YYYY`) และเวลา `19.00` อัตโนมัติ. ช่อง `to` และ `cc` ยังเว้นว่างไว้จนกว่าจะได้รับรายชื่อผู้รับจริง.

## 3 โหมดการทำงาน

### Process Only

สร้าง output 12 ไฟล์และ ZIP โดยไม่ส่งอีเมล.

### Test Send 6 Emails

กรอกอีเมลทดสอบบนหน้าเว็บ แล้วระบบจะส่ง template ที่เปิดใช้งานทั้ง 6 ฉบับไปที่อีเมลทดสอบเพียงคนเดียว:

- ไม่ใช้ To จริง
- ไม่ใช้ CC จริง
- เติม `[TEST]` หน้า Subject
- ใช้ Body และ attachments จริง เพื่อให้ตรวจสอบก่อนเปิดใช้งาน

### Live Send

ส่งไปยัง To/CC จริงจาก `config/email_jobs.json`. ปุ่ม Live Send จะยังไม่พร้อมใช้งานถ้า email job ใดที่เปิดใช้งานยังไม่มี `to`.

ก่อน Live Send หน้าเว็บมี confirmation เพิ่มอีกชั้น.

## ตั้งค่าเมลส่วนตัว

คัดลอก `.env.example` เป็น `.env` ในเครื่อง/hosting แล้วตั้งค่า SMTP. **ห้าม commit รหัสผ่านหรือ App Password ลง GitHub.**

ตัวอย่าง Gmail:

```env
EMAIL_SEND_ENABLED=true
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-personal-email@gmail.com
SMTP_PASSWORD=your-google-app-password
SMTP_FROM=your-personal-email@gmail.com
SMTP_USE_TLS=true
SMTP_USE_SSL=false
SMTP_MAX_MESSAGE_MB=25
```

สำหรับ Gmail ให้ใช้ App Password (ถ้าบัญชีรองรับ) แทนรหัสผ่านบัญชีปกติ. ระบบจะประเมินขนาดเมลหลัง base64 และหยุดก่อนส่งถ้าเกิน `SMTP_MAX_MESSAGE_MB`.

ถ้าเว็บเปิดผ่านอินเทอร์เน็ต ควรตั้ง `APP_ACCESS_KEY` เพื่อกันบุคคลอื่นกดส่งเมล.

## ตัวอย่าง To / CC

```json
{
  "id": "transfer_received",
  "enabled": true,
  "to": ["person@example.com"],
  "cc": ["manager@example.com"],
  "subject": "อัปเดต Transfer Order lines all Store status Received {date_slash} Time {time}น",
  "body": "เรียน ผู้เกี่ยวข้อง\n...",
  "attachments": ["transfer_status_received"]
}
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

## การใช้งาน

1. เลือก 3 ไฟล์พร้อมกัน
2. ระบบตรวจชื่อและวันที่ของทั้ง 3 ไฟล์
3. กด `Process Only` เพื่อตรวจ output
4. กรอกอีเมลตัวเองแล้วกด `Test Send 6 Emails` เพื่อตรวจ Subject / Body / attachments
5. เมื่อ To/CC จริงและ SMTP พร้อมแล้วจึงใช้ `Live Send`
6. หน้าเว็บแสดง progress และสามารถดาวน์โหลด output ทั้ง 12 ไฟล์เป็น ZIP ได้

## Tests

```bash
pytest -q
```
