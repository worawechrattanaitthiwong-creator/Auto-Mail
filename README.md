# Auto-Mail

เว็บแอปสำหรับงานรายงาน 3 ไฟล์:

1. `TransferOrder_YYYYMMDD...xlsx` → แยกเป็น 7 ไฟล์ตาม logic เดิมใน VBA
2. `PurchaseOrder_YYYYMMDD...xlsx` → แยกเป็น 4 ไฟล์ตาม logic เดิมใน VBA
3. `TransferOrderDiff_YYYYMMDD...xlsx` → ไม่แยกข้อมูล เปลี่ยนชื่อเป็น `TransferOrderDiff_ DD-MM-YYYY Time 09.00.xlsx`

จากนั้นระบบสามารถจัด 12 ไฟล์เข้า 6 email jobs แล้วส่ง To / CC / Subject / Body ที่กำหนดไว้ใน `config/email_jobs.json`.

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

ชื่อ status files ยังคงคำว่า `Tranfer order lines Status ...` ตามชื่อเดิมใน VBA เพื่อความเข้ากันได้กับงานเดิม.

### PurchaseOrder → 4 files

กรองปีจาก `PurchaseCreatedDateTime` และ `INVENTLOCATIONID`:

- `ZZ_CNN` → `PRT.ZZ_CNN ...xlsx`
- `SCX_WH1` → `Rc.SCX_WH1 ...xlsx`
- `SCX_FFM` → `Rc.SCX_FFM ...xlsx`
- `SCX_XD` → `Rc.SCX_XD ...xlsx`

วันที่สำหรับ output ทั้งหมดอ่านจากชื่อ input (`YYYYMMDD`) จึงไม่ต้องกรอกปีหรือวันที่เอง.

## Email jobs

มี template 6 ชุดใน `config/email_jobs.json` ตามกลุ่มไฟล์แนบของ VBA เดิม แต่ตั้ง `enabled: false` และเว้น `to` / `cc` ไว้ก่อนเพื่อไม่ให้ส่งผิดคน.

เมื่อพร้อมใช้งาน ให้ใส่ผู้รับ เช่น:

```json
{
  "id": "transfer_received",
  "enabled": true,
  "to": ["person@example.com"],
  "cc": ["manager@example.com"],
  "subject": "Transfer Order lines all Store status Received {date} Time {time}",
  "body": "Dear Team,\n\n...",
  "attachments": ["transfer_status_received"]
}
```

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
3. กด `Process Only` เมื่อต้องการทดสอบโดยไม่ส่งเมล
4. กด `Run & Send Emails` เมื่อตั้งค่า SMTP และผู้รับครบแล้ว
5. หน้าเว็บแสดง progress และสามารถดาวน์โหลด output ทั้ง 12 ไฟล์เป็น ZIP ได้

## Tests

```bash
pytest -q
```
