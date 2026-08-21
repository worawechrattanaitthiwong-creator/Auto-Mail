const input = document.querySelector('#files');
const dropzone = document.querySelector('#dropzone');
const fileGrid = document.querySelector('#fileGrid');
const runSend = document.querySelector('#runSend');
const testSend = document.querySelector('#testSend');
const processOnly = document.querySelector('#processOnly');
const testEmail = document.querySelector('#testEmail');
const progressPanel = document.querySelector('#progressPanel');
const statusText = document.querySelector('#statusText');
const progressValue = document.querySelector('#progressValue');
const progressBar = document.querySelector('#progressBar');
const result = document.querySelector('#result');
const configBadge = document.querySelector('#configBadge');
const autoInboxBadge = document.querySelector('#autoInboxBadge');
const autoInboxDetail = document.querySelector('#autoInboxDetail');
const accessRow = document.querySelector('#accessRow');
const accessKey = document.querySelector('#accessKey');
const settingsBadge = document.querySelector('#settingsBadge');
const emailJobsSettings = document.querySelector('#emailJobsSettings');
const saveEmailSettings = document.querySelector('#saveEmailSettings');
const settingsMessage = document.querySelector('#settingsMessage');

let selectedFiles = [];
let config = null;
let settingsLoaded = false;
let settingsDirty = false;
const ACCESS_KEY_SESSION_KEY = 'auto-mail-access-key';

function restoreAccessKey() {
  try {
    accessKey.value = window.sessionStorage.getItem(ACCESS_KEY_SESSION_KEY) || '';
  } catch (_) {
    accessKey.value = '';
  }
}

function rememberAccessKey() {
  try {
    const value = accessKey.value.trim();
    if (value) window.sessionStorage.setItem(ACCESS_KEY_SESSION_KEY, value);
    else window.sessionStorage.removeItem(ACCESS_KEY_SESSION_KEY);
  } catch (_) {
    // If browser storage is blocked, the app still works; the key just won't survive refresh.
  }
}

function forgetAccessKey() {
  try {
    window.sessionStorage.removeItem(ACCESS_KEY_SESSION_KEY);
  } catch (_) {
    // Ignore storage errors.
  }
}

function escapeHtml(value) {
  return String(value).replace(/[&<>\"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;', "'": '&#039;'
  })[char]);
}

const patterns = [
  ['TransferOrderDiff', /^TransferOrderDiff_\d{8}\d*\.xlsx$/i],
  ['TransferOrder', /^TransferOrder_\d{8}\d*\.xlsx$/i],
  ['PurchaseOrder', /^PurchaseOrder_\d{8}\d*\.xlsx$/i],
];

function classify(name) {
  const found = patterns.find(([, pattern]) => pattern.test(name));
  return found ? found[0] : 'ไม่รู้จัก';
}

function validFileSet() {
  const kinds = new Set(selectedFiles.map(file => classify(file.name)));
  return selectedFiles.length === 3 && ['TransferOrder', 'PurchaseOrder', 'TransferOrderDiff'].every(k => kinds.has(k));
}

function looksLikeEmail(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());
}

function refreshButtons() {
  const valid = validFileSet();
  processOnly.disabled = !valid;
  saveEmailSettings.disabled = !settingsLoaded || !settingsDirty;
  testSend.disabled = !valid || !settingsLoaded || settingsDirty || !looksLikeEmail(testEmail.value) || !(config && config.test_ready);
  runSend.disabled = !valid || !settingsLoaded || settingsDirty || !(config && config.live_ready);
}

function renderFiles() {
  fileGrid.innerHTML = selectedFiles.map(file => {
    const kind = classify(file.name);
    const safeName = escapeHtml(file.name);
    return `<div class="file-card ${kind !== 'ไม่รู้จัก' ? 'good' : ''}">
      <div class="kind">${kind}</div>
      <div class="name" title="${safeName}">${safeName}</div>
    </div>`;
  }).join('');
  refreshButtons();
}

function setFiles(files) {
  selectedFiles = [...files].slice(0, 3);
  renderFiles();
}

function markSettingsDirty() {
  if (!settingsLoaded) return;
  settingsDirty = true;
  settingsBadge.textContent = 'มีการแก้ไข';
  settingsBadge.className = 'badge warn';
  settingsMessage.textContent = 'มีข้อมูลที่ยังไม่ได้บันทึก กรุณากด Save Settings ก่อน Test/Live Send';
  settingsMessage.className = 'settings-message';
  refreshButtons();
}

input.addEventListener('change', () => setFiles(input.files));
testEmail.addEventListener('input', markSettingsDirty);
emailJobsSettings.addEventListener('input', markSettingsDirty);
['dragenter', 'dragover'].forEach(name => dropzone.addEventListener(name, event => {
  event.preventDefault(); dropzone.classList.add('drag');
}));
['dragleave', 'drop'].forEach(name => dropzone.addEventListener(name, event => {
  event.preventDefault(); dropzone.classList.remove('drag');
}));
dropzone.addEventListener('drop', event => setFiles(event.dataTransfer.files));

function headers() {
  const h = {};
  if (accessKey.value) h['X-App-Key'] = accessKey.value;
  return h;
}

function renderInboxStatus() {
  if (!autoInboxBadge || !autoInboxDetail || !config) return;
  const inbox = config.inbox_status || {};

  if (!config.inbox_watch_enabled) {
    autoInboxBadge.textContent = 'ยังไม่เปิด Auto';
    autoInboxBadge.className = 'badge warn';
    autoInboxDetail.textContent = 'Manual Upload ยังใช้ได้ตามปกติ ระหว่างที่ Auto Inbox ยังไม่เปิดใช้งาน';
    return;
  }

  if (!config.inbox_configured || inbox.status === 'error') {
    autoInboxBadge.textContent = 'Auto ต้องตั้งค่าเพิ่ม';
    autoInboxBadge.className = 'badge warn';
    autoInboxDetail.textContent = inbox.last_error || 'ยังตั้งค่า Inbox username/password ไม่ครบ';
    return;
  }

  if (inbox.status === 'waiting_email_config') {
    autoInboxBadge.textContent = 'Inbox พร้อม · รอ Live';
    autoInboxBadge.className = 'badge warn';
    autoInboxDetail.textContent = 'ระบบอ่าน Inbox ได้แล้ว แต่ยังรอ To/CC และการตั้งค่าส่งเมลจริงให้ครบ';
    return;
  }

  if (inbox.status === 'processing') {
    autoInboxBadge.textContent = 'กำลังประมวลผล';
    autoInboxBadge.className = 'badge ok';
    const batch = inbox.last_batch || {};
    autoInboxDetail.textContent = batch.report_date ? `กำลังทำรายงานวันที่ ${batch.report_date}` : 'พบรายงานครบ 3 ไฟล์และเริ่มทำงานแล้ว';
    return;
  }

  autoInboxBadge.textContent = 'Auto Inbox พร้อม';
  autoInboxBadge.className = 'badge ok';
  autoInboxDetail.textContent = inbox.last_scan
    ? `ตรวจ Inbox ล่าสุด ${inbox.last_scan}`
    : 'ระบบจะตรวจ Inbox และรอ TransferOrder / PurchaseOrder / TransferOrderDiff ให้ครบวันเดียวกัน';
}

function renderEmailSettings(settings) {
  testEmail.value = settings.test_email || '';
  emailJobsSettings.innerHTML = (settings.jobs || []).map(job => {
    const toValue = escapeHtml((job.to || []).join('\n'));
    const ccValue = escapeHtml((job.cc || []).join('\n'));
    const attachments = (job.attachments || []).map(escapeHtml).join(', ');
    const state = (job.to || []).length ? `${job.to.length} To` : 'ยังไม่มี To';
    return `<article class="settings-card" data-job-id="${escapeHtml(job.id)}">
      <div class="settings-card-head">
        <div class="settings-card-title">${escapeHtml(job.name)}</div>
        <span class="settings-card-state">${escapeHtml(state)}</span>
      </div>
      <div class="settings-field">
        <label>TO</label>
        <textarea class="job-to" placeholder="ผู้รับหลัก — 1 อีเมลต่อบรรทัด หรือคั่นด้วย ;">${toValue}</textarea>
      </div>
      <div class="settings-field">
        <label>CC</label>
        <textarea class="job-cc" placeholder="CC — 1 อีเมลต่อบรรทัด หรือคั่นด้วย ;">${ccValue}</textarea>
      </div>
      <div class="settings-meta"><strong>Subject:</strong> ${escapeHtml(job.subject || '')}<br><strong>ไฟล์:</strong> ${attachments || '-'}</div>
    </article>`;
  }).join('') || '<div class="settings-placeholder">ไม่พบ Email Job</div>';
}

async function loadEmailSettings() {
  if (config && config.access_key_required && !accessKey.value) {
    settingsLoaded = false;
    settingsBadge.textContent = 'รอ Access key';
    settingsBadge.className = 'badge warn';
    settingsMessage.textContent = 'กรอก Access key เพื่อโหลดและแก้ไขผู้รับเมล';
    settingsMessage.className = 'settings-message';
    emailJobsSettings.innerHTML = '<div class="settings-placeholder">กรอก Access key ก่อน</div>';
    refreshButtons();
    return;
  }

  settingsBadge.textContent = 'กำลังโหลด…';
  settingsBadge.className = 'badge';
  try {
    const response = await fetch('/api/email-settings', { headers: headers() });
    const payload = await response.json();
    if (response.status === 401) {
      forgetAccessKey();
      accessKey.value = '';
    }
    if (!response.ok) throw new Error(payload.detail || 'โหลด Email Settings ไม่สำเร็จ');
    renderEmailSettings(payload);
    settingsLoaded = true;
    settingsDirty = false;
    settingsBadge.textContent = 'บันทึกแล้ว';
    settingsBadge.className = 'badge ok';
    settingsMessage.textContent = 'ระบบจะใช้ Test Email และ To/CC ชุดนี้กับการส่งครั้งถัดไป';
    settingsMessage.className = 'settings-message ok';
    refreshButtons();
  } catch (error) {
    settingsLoaded = false;
    settingsDirty = false;
    settingsBadge.textContent = 'โหลดไม่ได้';
    settingsBadge.className = 'badge warn';
    settingsMessage.textContent = error.message;
    settingsMessage.className = 'settings-message error';
    refreshButtons();
  }
}

function collectEmailSettings() {
  const jobs = [...emailJobsSettings.querySelectorAll('.settings-card')].map(card => ({
    id: card.dataset.jobId,
    to: card.querySelector('.job-to').value,
    cc: card.querySelector('.job-cc').value,
  }));
  return { test_email: testEmail.value.trim(), jobs };
}

async function saveSettings() {
  if (!settingsLoaded) return;
  if (testEmail.value.trim() && !looksLikeEmail(testEmail.value)) {
    settingsMessage.textContent = 'Test Email ไม่ถูกต้อง';
    settingsMessage.className = 'settings-message error';
    return;
  }

  saveEmailSettings.disabled = true;
  settingsBadge.textContent = 'กำลังบันทึก…';
  settingsBadge.className = 'badge';
  try {
    const response = await fetch('/api/email-settings', {
      method: 'PUT',
      headers: { ...headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify(collectEmailSettings()),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || 'บันทึก Email Settings ไม่สำเร็จ');
    renderEmailSettings(payload);
    settingsDirty = false;
    settingsBadge.textContent = 'บันทึกแล้ว';
    settingsBadge.className = 'badge ok';
    settingsMessage.textContent = 'บันทึก Test Email และผู้รับเมล 1–6 เรียบร้อย';
    settingsMessage.className = 'settings-message ok';
    await loadConfig(false);
    refreshButtons();
  } catch (error) {
    settingsBadge.textContent = 'บันทึกไม่สำเร็จ';
    settingsBadge.className = 'badge warn';
    settingsMessage.textContent = error.message;
    settingsMessage.className = 'settings-message error';
    refreshButtons();
  }
}

async function loadConfig(loadSettings = true) {
  try {
    const response = await fetch('/api/config-status');
    config = await response.json();
    if (!response.ok) throw new Error(config.detail || 'อ่านสถานะระบบไม่สำเร็จ');
    accessRow.hidden = !config.access_key_required;
    renderInboxStatus();

    const driveText = config.drive_fallback_enabled && config.drive_configured
      ? ' · Drive fallback พร้อม'
      : ` · แนบตรง ≤ ${config.direct_attachment_max_mb || 20} MB`;

    if (config.live_ready) {
      configBadge.textContent = `Live พร้อมส่ง · ${config.jobs_enabled} jobs${driveText}`;
      configBadge.className = 'badge ok';
    } else if (config.test_ready) {
      configBadge.textContent = `Test พร้อม · Live รอ To (${config.jobs_with_recipients}/${config.jobs_enabled})${driveText}`;
      configBadge.className = 'badge warn';
    } else {
      configBadge.textContent = 'Email ยังไม่พร้อม · ตั้งค่า SMTP ก่อน';
      configBadge.className = 'badge warn';
    }

    if (loadSettings) await loadEmailSettings();
    refreshButtons();
  } catch (error) {
    configBadge.textContent = 'อ่านสถานะระบบไม่สำเร็จ';
    configBadge.className = 'badge warn';
    settingsMessage.textContent = error.message;
    settingsMessage.className = 'settings-message error';
  }
}

async function startRun(sendMode) {
  result.className = 'result';
  result.innerHTML = '';
  progressPanel.hidden = false;
  progressPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  statusText.textContent = 'กำลังอัปโหลดไฟล์…';
  progressValue.textContent = '0%';
  progressBar.style.width = '0%';
  runSend.disabled = true;
  testSend.disabled = true;
  processOnly.disabled = true;

  const form = new FormData();
  selectedFiles.forEach(file => form.append('files', file));
  form.append('send_mode', sendMode);
  if (sendMode === 'test') form.append('test_email', testEmail.value.trim());

  try {
    const response = await fetch('/api/runs', { method: 'POST', headers: headers(), body: form });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || 'อัปโหลดไม่สำเร็จ');
    poll(payload.id);
  } catch (error) {
    showError(error.message);
    renderFiles();
  }
}

function deliveryLabel(value) {
  if (value === 'drive_link') return 'Drive link';
  return 'ไฟล์แนบ';
}

async function poll(runId) {
  try {
    const response = await fetch(`/api/runs/${runId}`, { headers: headers() });
    const state = await response.json();
    if (!response.ok) throw new Error(state.detail || 'อ่านสถานะไม่สำเร็จ');
    statusText.textContent = state.message;
    progressValue.textContent = `${state.progress}%`;
    progressBar.style.width = `${state.progress}%`;

    if (state.status === 'completed') {
      const items = state.outputs.map(name => `<li>${escapeHtml(name)}</li>`).join('');
      let sendSummary = '';
      if (state.send_mode === 'test') sendSummary = ` · ทดสอบส่ง ${state.emails.length} ฉบับไปที่ ${escapeHtml(state.test_email || '')}`;
      if (state.send_mode === 'live') sendSummary = ` · ส่งจริง ${state.emails.length} ฉบับ`;

      const emailRows = (state.emails || []).map(email => {
        const driveNames = (email.drive_links || []).map(item => item.name).join(', ');
        const extra = driveNames ? ` · Link: ${escapeHtml(driveNames)}` : '';
        return `<li>${escapeHtml(email.name || email.id)} — ${deliveryLabel(email.delivery)}${extra}</li>`;
      }).join('');
      const emailBlock = emailRows ? `<h3>รูปแบบการส่ง</h3><ul>${emailRows}</ul>` : '';

      result.className = 'result success';
      result.innerHTML = `<strong>สำเร็จ</strong> · ได้ไฟล์ ${state.outputs.length} ไฟล์${sendSummary}
        ${emailBlock}
        <h3>Output files</h3>
        <ul class="output-list">${items}</ul>
        <a href="/api/runs/${runId}/download" data-download="${runId}">ดาวน์โหลดไฟล์ทั้งหมด (.zip)</a>`;
      const link = result.querySelector('a');
      link.addEventListener('click', event => {
        if (accessKey.value) {
          event.preventDefault();
          fetch(link.href, { headers: headers() }).then(r => r.blob()).then(blob => {
            const url = URL.createObjectURL(blob); const a = document.createElement('a');
            a.href = url; a.download = `Auto-Mail-${runId}.zip`; a.click(); URL.revokeObjectURL(url);
          });
        }
      });
      renderFiles();
      loadConfig(false);
      return;
    }
    if (state.status === 'failed') {
      showError(state.error || 'งานไม่สำเร็จ');
      renderFiles();
      loadConfig(false);
      return;
    }
    setTimeout(() => poll(runId), 1500);
  } catch (error) {
    showError(error.message);
    renderFiles();
  }
}

function showError(message) {
  statusText.textContent = 'เกิดข้อผิดพลาด';
  result.className = 'result error';
  result.textContent = message;
}

accessKey.addEventListener('change', () => {
  rememberAccessKey();
  loadEmailSettings();
});
accessKey.addEventListener('keydown', event => {
  if (event.key === 'Enter') {
    event.preventDefault();
    accessKey.blur();
  }
});
saveEmailSettings.addEventListener('click', saveSettings);
runSend.addEventListener('click', () => {
  if (window.confirm('ยืนยัน Live Send? ระบบจะส่งไปยัง To/CC จริงที่บันทึกไว้สำหรับเมล 1–6')) startRun('live');
});
testSend.addEventListener('click', () => startRun('test'));
processOnly.addEventListener('click', () => startRun('none'));
restoreAccessKey();
loadConfig();
