const input = document.querySelector('#files');
const dropzone = document.querySelector('#dropzone');
const fileGrid = document.querySelector('#fileGrid');
const runSend = document.querySelector('#runSend');
const processOnly = document.querySelector('#processOnly');
const progressPanel = document.querySelector('#progressPanel');
const statusText = document.querySelector('#statusText');
const progressValue = document.querySelector('#progressValue');
const progressBar = document.querySelector('#progressBar');
const result = document.querySelector('#result');
const configBadge = document.querySelector('#configBadge');
const accessRow = document.querySelector('#accessRow');
const accessKey = document.querySelector('#accessKey');

let selectedFiles = [];
let config = null;

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

function renderFiles() {
  fileGrid.innerHTML = selectedFiles.map(file => {
    const kind = classify(file.name);
    const safeName = escapeHtml(file.name);
    return `<div class="file-card ${kind !== 'ไม่รู้จัก' ? 'good' : ''}">
      <div class="kind">${kind}</div>
      <div class="name" title="${safeName}">${safeName}</div>
    </div>`;
  }).join('');
  const kinds = new Set(selectedFiles.map(file => classify(file.name)));
  const valid = selectedFiles.length === 3 && ['TransferOrder', 'PurchaseOrder', 'TransferOrderDiff'].every(k => kinds.has(k));
  runSend.disabled = !valid;
  processOnly.disabled = !valid;
}

function setFiles(files) {
  selectedFiles = [...files].slice(0, 3);
  renderFiles();
}

input.addEventListener('change', () => setFiles(input.files));
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

async function loadConfig() {
  const response = await fetch('/api/config-status');
  config = await response.json();
  accessRow.hidden = !config.access_key_required;
  if (config.email_send_enabled && config.smtp_configured && config.jobs_enabled && config.jobs_with_recipients === config.jobs_enabled) {
    configBadge.textContent = `Email พร้อมส่ง · ${config.jobs_enabled} jobs`;
    configBadge.className = 'badge ok';
  } else {
    configBadge.textContent = `Email ยังไม่พร้อม · ${config.jobs_enabled}/${config.jobs_total} jobs เปิดใช้`;
    configBadge.className = 'badge warn';
  }
}

async function startRun(sendEmail) {
  result.className = 'result';
  result.innerHTML = '';
  progressPanel.hidden = false;
  progressPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  statusText.textContent = 'กำลังอัปโหลดไฟล์…';
  progressValue.textContent = '0%';
  progressBar.style.width = '0%';
  runSend.disabled = true;
  processOnly.disabled = true;

  const form = new FormData();
  selectedFiles.forEach(file => form.append('files', file));
  form.append('send_email', sendEmail ? 'true' : 'false');

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
      result.className = 'result success';
      result.innerHTML = `<strong>สำเร็จ</strong> · ได้ไฟล์ ${state.outputs.length} ไฟล์${state.send_email ? ` · ส่ง ${state.emails.length} อีเมล` : ''}
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
      return;
    }
    if (state.status === 'failed') {
      showError(state.error || 'งานไม่สำเร็จ');
      renderFiles();
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

runSend.addEventListener('click', () => startRun(true));
processOnly.addEventListener('click', () => startRun(false));
loadConfig();
