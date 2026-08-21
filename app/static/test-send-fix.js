// Test Send is intentionally independent from the Live Send safety switch.
// This shim keeps the deployed UI compatible while preserving Live Send gating.
(function () {
  function testIsReady() {
    return !!(
      config &&
      config.smtp_configured &&
      settingsLoaded &&
      !settingsDirty &&
      looksLikeEmail(testEmail.value)
    );
  }

  const baseRefreshButtons = refreshButtons;
  refreshButtons = function () {
    baseRefreshButtons();
    const testReady = testIsReady();

    if (validFileSet()) testSend.disabled = !testReady;
    if (bundleRunId) zipTestSend.disabled = !testReady;

    document.querySelectorAll('[data-existing-send="test"]').forEach(button => {
      button.disabled = !testReady;
    });

    if (config && config.smtp_configured && !config.email_send_enabled) {
      configBadge.textContent = 'Test Send พร้อม · Live Send ยังปิดอยู่';
      configBadge.className = 'badge ok';
    }
  };

  sendExisting = async function (runId, mode) {
    if (!runId) return;
    if (mode === 'test' && !testIsReady()) {
      showError('Test Send ยังไม่พร้อม: ตรวจ Test Email และ SMTP');
      return;
    }
    if (mode === 'live' && !(config && config.live_ready)) {
      showError('Live Send ยังไม่พร้อม กรุณาบันทึก To ของเมล 1–6 และเปิด Live Send ก่อน');
      return;
    }
    if (mode === 'live' && !window.confirm('ยืนยัน Live Send ผลลัพธ์ชุดเดิม? ระบบจะส่งไปยัง To/CC จริง')) return;

    setProgress(1, mode === 'test' ? 'กำลังเริ่ม Test Send จากผลลัพธ์เดิม…' : 'กำลังเริ่ม Live Send จากผลลัพธ์เดิม…');
    const form = new FormData();
    form.append('send_mode', mode);
    if (mode === 'test') form.append('test_email', testEmail.value.trim());

    try {
      const response = await fetch(`/api/runs/${runId}/send`, {
        method: 'POST',
        headers: headers(),
        body: form,
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || 'เริ่มส่งอีเมลไม่สำเร็จ');
      poll(runId, false);
    } catch (error) {
      showError(error.message);
    }
  };

  const baseDeliveryLabel = deliveryLabel;
  deliveryLabel = function (value) {
    if (value === 'test_no_attachment') return 'TEST: ไฟล์ใหญ่จึงไม่แนบ';
    return baseDeliveryLabel(value);
  };

  const observer = new MutationObserver(() => refreshButtons());
  if (result) observer.observe(result, { childList: true, subtree: true });

  setTimeout(() => refreshButtons(), 0);
})();
