(function () {
  const POLL_MS = 1000;

  const $ = (id) => document.getElementById(id);

  // Cabecera / conexion
  const usbDot = $("usbDot");
  const usbLabel = $("usbLabel");
  const alarm = $("alarm");
  const alarmIcon = $("alarmIcon");
  const alarmText = $("alarmText");

  // Explorador
  const breadcrumbEl = $("breadcrumb");
  const browserEl = $("browser");

  // Editor
  const editorFilename = $("editorFilename");
  const editor = $("editor");
  const btnNew = $("btnNew");
  const btnFind = $("btnFind");
  const btnSave = $("btnSave");
  const btnDeleteFile = $("btnDeleteFile");
  const findBar = $("findBar");
  const findInput = $("findInput");
  const replaceInput = $("replaceInput");
  const findCount = $("findCount");
  const btnFindPrev = $("btnFindPrev");
  const btnFindNext = $("btnFindNext");
  const btnReplace = $("btnReplace");
  const btnReplaceAll = $("btnReplaceAll");
  const btnFindClose = $("btnFindClose");

  // Envio
  const machineSelectBtn = $("machineSelectBtn");
  const machineSelectLabel = $("machineSelectLabel");
  const selectedFileName = $("selectedFileName");
  const btnSend = $("btnSend");
  const sendHint = $("sendHint");
  const transferBox = $("transferBox");
  const transferTitle = $("transferTitle");
  const transferDetail = $("transferDetail");
  const progressFill = $("progressFill");

  // Modales
  const machineModal = $("machineModal");
  const machineModalList = $("machineModalList");
  const btnCloseMachineModal = $("btnCloseMachineModal");
  const btnAddMachine = $("btnAddMachine");
  const machineEditModal = $("machineEditModal");
  const machineEditTitle = $("machineEditTitle");
  const mfName = $("mfName");
  const mfBaud = $("mfBaud");
  const mfBytesize = $("mfBytesize");
  const mfParity = $("mfParity");
  const mfStop = $("mfStop");
  const mfFlow = $("mfFlow");
  const mfTerm = $("mfTerm");
  const mfError = $("mfError");
  const btnCancelMachineEdit = $("btnCancelMachineEdit");
  const btnSaveMachineEdit = $("btnSaveMachineEdit");
  const newFileModal = $("newFileModal");
  const newFileDirHint = $("newFileDirHint");
  const newFileName = $("newFileName");
  const newFileError = $("newFileError");
  const btnCancelNewFile = $("btnCancelNewFile");
  const btnCreateNewFile = $("btnCreateNewFile");
  const confirmModal = $("confirmModal");
  const confirmTitle = $("confirmTitle");
  const confirmText = $("confirmText");
  const btnConfirmCancel = $("btnConfirmCancel");
  const btnConfirmOk = $("btnConfirmOk");

  // Estado
  let currentPath = "";
  let selectedFile = null;      // {path, name}
  let selectedMachineId = null;
  let machines = [];
  let usbConnected = false;
  let sending = false;
  let editorDirty = false;
  let lastFilesVersion = -1;
  let editingMachineId = null;
  let confirmCb = null;

  /* ---------- Utilidades ---------- */
  function esc(s) {
    return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  function formatSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function machineSubLabel(m) {
    const flow = m.flow_control === "xonxoff" ? "XON/XOFF" : "RTS/CTS";
    const term = m.line_terminator === "CRLF" ? "CR+LF" : m.line_terminator;
    return `${m.baudrate} baud · ${m.bytesize}${m.parity}${m.stopbits} · ${flow} · ${term}`;
  }

  function openModal(el) { el.classList.add("visible"); }
  function closeModal(el) { el.classList.remove("visible"); }
  function isOpen(el) { return el.classList.contains("visible"); }

  function confirmAction(title, text, okLabel, danger, cb) {
    confirmTitle.textContent = title;
    confirmText.textContent = text;
    btnConfirmOk.textContent = okLabel || "Aceptar";
    btnConfirmOk.className = "btn " + (danger ? "btn-danger" : "btn-primary");
    confirmCb = cb;
    openModal(confirmModal);
  }

  btnConfirmCancel.onclick = () => { closeModal(confirmModal); confirmCb = null; };
  btnConfirmOk.onclick = () => { closeModal(confirmModal); const cb = confirmCb; confirmCb = null; if (cb) cb(); };

  /* ---------- Explorador (izquierda) ---------- */
  async function loadDir(path) {
    let data;
    try {
      data = await (await fetch("/api/files?path=" + encodeURIComponent(path))).json();
    } catch (e) { return; }
    currentPath = data.path;
    renderBreadcrumb(data.breadcrumb);
    renderBrowser(data);
  }

  function renderBreadcrumb(crumbs) {
    breadcrumbEl.innerHTML = "";
    crumbs.forEach((c, i) => {
      if (i > 0) {
        const sep = document.createElement("span");
        sep.className = "crumb-sep";
        sep.textContent = "›";
        breadcrumbEl.appendChild(sep);
      }
      const btn = document.createElement("button");
      btn.className = "crumb" + (i === crumbs.length - 1 ? " current" : "");
      btn.textContent = c.name;
      if (i !== crumbs.length - 1) btn.onclick = () => loadDir(c.path);
      breadcrumbEl.appendChild(btn);
    });
  }

  function renderBrowser(data) {
    browserEl.innerHTML = "";
    if (data.dirs.length === 0 && data.files.length === 0) {
      const e = document.createElement("div");
      e.className = "empty-hint";
      e.textContent = "Carpeta vacía. Crea un programa con ＋ Nuevo.";
      browserEl.appendChild(e);
      return;
    }
    data.dirs.forEach((d) => {
      const row = document.createElement("div");
      row.className = "entry dir";
      row.innerHTML = `<span class="icon">📁</span><span class="entry-name">${esc(d.name)}</span><span class="icon">›</span>`;
      row.onclick = () => loadDir(d.path);
      browserEl.appendChild(row);
    });
    data.files.forEach((f) => {
      const row = document.createElement("div");
      row.className = "entry file" + (selectedFile && selectedFile.path === f.path ? " selected" : "");
      row.dataset.path = f.path;
      row.innerHTML = `<span class="icon">📄</span><span class="entry-name">${esc(f.name)}</span><span class="entry-size">${formatSize(f.size)}</span>`;
      row.onclick = () => selectFile(f);
      browserEl.appendChild(row);
    });
  }

  function markSelected() {
    browserEl.querySelectorAll(".entry.file").forEach((row) => {
      row.classList.toggle("selected", !!(selectedFile && row.dataset.path === selectedFile.path));
    });
  }

  /* ---------- Editor (centro) ---------- */
  function selectFile(f) {
    if (editorDirty) {
      confirmAction(
        "Cambios sin guardar",
        `"${selectedFile ? selectedFile.name : ""}" tiene cambios sin guardar. ¿Descartarlos y abrir "${f.name}"?`,
        "Descartar", true,
        () => doSelectFile(f)
      );
      return;
    }
    doSelectFile(f);
  }

  async function doSelectFile(f) {
    selectedFile = { path: f.path, name: f.name };
    editorDirty = false;
    updateSelectedFileUi();
    markSelected();
    await loadContent();
  }

  async function loadContent() {
    if (!selectedFile) {
      editor.value = "";
      editor.readOnly = false;
      editorFilename.textContent = "Sin archivo";
      editorDirty = false;
      updateEditorButtons();
      return;
    }
    try {
      const res = await fetch("/api/file?path=" + encodeURIComponent(selectedFile.path));
      if (!res.ok) {
        editor.value = "";
        editor.readOnly = true;
        editorFilename.textContent = selectedFile.name + " (no disponible)";
        updateEditorButtons();
        return;
      }
      const data = await res.json();
      editor.value = data.content;
      editorDirty = false;
      if (data.truncated) {
        editor.readOnly = true;
        editorFilename.textContent = data.name + " — muy grande, solo lectura";
      } else {
        editor.readOnly = false;
        editorFilename.textContent = data.name;
      }
      updateEditorButtons();
      updateSendButton();
    } catch (e) { /* reintenta en el siguiente ciclo */ }
  }

  function updateEditorButtons() {
    btnSave.disabled = !(selectedFile && editorDirty && !editor.readOnly);
    btnDeleteFile.disabled = !selectedFile;
  }

  editor.addEventListener("input", () => {
    if (editor.readOnly) return;
    editorDirty = true;
    updateEditorButtons();
    updateSendButton();
  });

  async function saveFile() {
    if (!selectedFile || editor.readOnly) return;
    const res = await fetch("/api/file/save", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: selectedFile.path, content: editor.value }),
    });
    const data = await res.json();
    if (!data.ok) { alert(data.error || "No se pudo guardar"); return; }
    editorDirty = false;
    updateEditorButtons();
    updateSendButton();
    const prev = btnSave.textContent;
    btnSave.textContent = "Guardado ✓";
    setTimeout(() => { btnSave.textContent = prev; }, 1200);
  }

  function deleteFile() {
    if (!selectedFile) return;
    confirmAction(
      "Eliminar programa",
      `¿Eliminar "${selectedFile.name}"? Se borrará de la carpeta compartida.`,
      "Eliminar", true,
      async () => {
        const res = await fetch("/api/file/delete", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: selectedFile.path }),
        });
        const data = await res.json();
        if (!data.ok) { alert(data.error || "No se pudo eliminar"); return; }
        selectedFile = null;
        editorDirty = false;
        editor.value = "";
        editor.readOnly = false;
        editorFilename.textContent = "Sin archivo";
        updateSelectedFileUi();
        updateEditorButtons();
        await loadDir(currentPath);
      }
    );
  }

  btnSave.onclick = saveFile;
  btnDeleteFile.onclick = deleteFile;

  /* ---------- Nuevo programa ---------- */
  btnNew.onclick = () => {
    newFileDirHint.textContent = "En: " + (currentPath || "Programas");
    newFileName.value = "";
    newFileError.textContent = "";
    openModal(newFileModal);
    setTimeout(() => newFileName.focus(), 50);
  };
  btnCancelNewFile.onclick = () => closeModal(newFileModal);
  btnCreateNewFile.onclick = async () => {
    const name = newFileName.value.trim();
    if (!name) { newFileError.textContent = "Escribe un nombre"; return; }
    const res = await fetch("/api/file/new", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dir: currentPath, name }),
    });
    const data = await res.json();
    if (!data.ok) { newFileError.textContent = data.error || "No se pudo crear"; return; }
    closeModal(newFileModal);
    await loadDir(currentPath);
    selectedFile = { path: data.path, name };
    editorDirty = false;
    updateSelectedFileUi();
    markSelected();
    await loadContent();
    editor.focus();
  };
  newFileName.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); btnCreateNewFile.click(); }
  });

  /* ---------- Buscar / reemplazar ---------- */
  function findAll(text, q) {
    const r = [];
    if (!q) return r;
    const H = text.toLowerCase(), N = q.toLowerCase();
    let i = 0;
    while ((i = H.indexOf(N, i)) !== -1) { r.push(i); i += N.length; }
    return r;
  }

  function scrollToSel() {
    const pos = editor.selectionStart;
    const line = editor.value.slice(0, pos).split("\n").length - 1;
    const lh = parseFloat(getComputedStyle(editor).lineHeight) || 18;
    editor.scrollTop = Math.max(0, line * lh - editor.clientHeight / 2);
  }

  function updateFindCount() {
    const q = findInput.value;
    const m = findAll(editor.value, q);
    findCount.textContent = q ? "0/" + m.length : "";
  }

  function gotoMatch(forward) {
    const q = findInput.value;
    const matches = findAll(editor.value, q);
    if (matches.length === 0) { findCount.textContent = q ? "0/0" : ""; return; }
    const cursor = forward ? editor.selectionEnd : editor.selectionStart;
    let idx;
    if (forward) {
      idx = matches.findIndex((m) => m >= cursor);
      if (idx === -1) idx = 0;
    } else {
      idx = -1;
      for (let k = 0; k < matches.length; k++) if (matches[k] < cursor) idx = k;
      if (idx === -1) idx = matches.length - 1;
    }
    const pos = matches[idx];
    editor.focus();
    editor.setSelectionRange(pos, pos + q.length);
    scrollToSel();
    findCount.textContent = (idx + 1) + "/" + matches.length;
  }

  function replaceOne() {
    if (editor.readOnly) return;
    const q = findInput.value;
    if (!q) return;
    const s = editor.selectionStart, e = editor.selectionEnd;
    const sel = editor.value.slice(s, e);
    if (s !== e && sel.toLowerCase() === q.toLowerCase()) {
      editor.setRangeText(replaceInput.value, s, e, "end");
      editorDirty = true;
      updateEditorButtons();
      updateSendButton();
    }
    gotoMatch(true);
  }

  function replaceAll() {
    if (editor.readOnly) return;
    const q = findInput.value;
    if (!q) return;
    const matches = findAll(editor.value, q);
    if (matches.length === 0) { findCount.textContent = "0/0"; return; }
    const rep = replaceInput.value;
    let out = "", last = 0;
    for (const idx of matches) { out += editor.value.slice(last, idx) + rep; last = idx + q.length; }
    out += editor.value.slice(last);
    editor.value = out;
    editorDirty = true;
    updateEditorButtons();
    updateSendButton();
    findCount.textContent = matches.length + " reempl.";
  }

  btnFind.onclick = () => {
    const willShow = !findBar.classList.contains("visible");
    findBar.classList.toggle("visible");
    if (willShow) {
      const sel = editor.value.slice(editor.selectionStart, editor.selectionEnd);
      if (sel && sel.length < 80 && !sel.includes("\n")) findInput.value = sel;
      updateFindCount();
      setTimeout(() => { findInput.focus(); findInput.select(); }, 50);
    }
  };
  btnFindClose.onclick = () => findBar.classList.remove("visible");
  btnFindNext.onclick = () => gotoMatch(true);
  btnFindPrev.onclick = () => gotoMatch(false);
  btnReplace.onclick = replaceOne;
  btnReplaceAll.onclick = replaceAll;
  findInput.addEventListener("input", updateFindCount);
  findInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); gotoMatch(!e.shiftKey); }
  });

  /* ---------- Maquinas (derecha) ---------- */
  function updateMachineSelectLabel() {
    const m = machines.find((x) => x.id === selectedMachineId);
    machineSelectLabel.textContent = m ? m.name : "Seleccionar máquina";
  }

  machineSelectBtn.onclick = () => { renderMachineModalList(); openModal(machineModal); };
  btnCloseMachineModal.onclick = () => closeModal(machineModal);

  function renderMachineModalList() {
    machineModalList.innerHTML = "";
    if (machines.length === 0) {
      const e = document.createElement("div");
      e.className = "machine-modal-empty";
      e.textContent = "No hay máquinas. Agrega una con el botón de abajo.";
      machineModalList.appendChild(e);
      return;
    }
    machines.forEach((m) => {
      const row = document.createElement("div");
      row.className = "machine-row" + (m.id === selectedMachineId ? " selected" : "");
      const pick = document.createElement("button");
      pick.className = "machine-pick";
      pick.innerHTML = `<div class="m-name">${esc(m.name)}</div><div class="m-sub">${esc(machineSubLabel(m))}</div>`;
      pick.onclick = () => selectMachine(m.id);
      const actions = document.createElement("div");
      actions.className = "row-actions";
      const edit = document.createElement("button");
      edit.className = "icon-btn";
      edit.textContent = "✎";
      edit.onclick = () => openMachineEdit(m);
      const del = document.createElement("button");
      del.className = "icon-btn danger";
      del.textContent = "🗑";
      del.onclick = () => deleteMachine(m);
      actions.appendChild(edit);
      actions.appendChild(del);
      row.appendChild(pick);
      row.appendChild(actions);
      machineModalList.appendChild(row);
    });
  }

  async function selectMachine(id) {
    await fetch("/api/machine/select", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    selectedMachineId = id;
    updateMachineSelectLabel();
    updateSendButton();
    closeModal(machineModal);
  }

  function setSelect(sel, value, addIfMissing) {
    value = String(value);
    if (addIfMissing && ![...sel.options].some((o) => o.value === value)) {
      const o = document.createElement("option");
      o.value = value; o.textContent = value;
      sel.appendChild(o);
    }
    sel.value = value;
  }

  function openMachineEdit(m) {
    editingMachineId = m ? m.id : null;
    machineEditTitle.textContent = m ? "Editar máquina" : "Nueva máquina";
    mfName.value = m ? m.name : "";
    setSelect(mfBaud, m ? m.baudrate : 9600, true);
    mfBytesize.value = String(m ? m.bytesize : 8);
    mfParity.value = m ? m.parity : "N";
    mfStop.value = String(m ? m.stopbits : 1);
    mfFlow.value = m ? m.flow_control : "xonxoff";
    mfTerm.value = m ? m.line_terminator : "CRLF";
    mfError.textContent = "";
    openModal(machineEditModal);
  }

  btnAddMachine.onclick = () => openMachineEdit(null);
  btnCancelMachineEdit.onclick = () => closeModal(machineEditModal);

  btnSaveMachineEdit.onclick = async () => {
    const payload = {
      name: mfName.value,
      baudrate: mfBaud.value,
      bytesize: mfBytesize.value,
      parity: mfParity.value,
      stopbits: mfStop.value,
      flow_control: mfFlow.value,
      line_terminator: mfTerm.value,
    };
    if (editingMachineId) payload.id = editingMachineId;
    const res = await fetch("/api/machine/save", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!data.ok) { mfError.textContent = data.error || "No se pudo guardar"; return; }
    closeModal(machineEditModal);
    await refreshMachines();
    if (isOpen(machineModal)) renderMachineModalList();
  };

  function deleteMachine(m) {
    confirmAction(
      "Eliminar máquina",
      `¿Eliminar el perfil "${m.name}"?`,
      "Eliminar", true,
      async () => {
        const res = await fetch("/api/machine/delete", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: m.id }),
        });
        const data = await res.json();
        if (!data.ok) { alert(data.error || "No se pudo eliminar"); return; }
        if (selectedMachineId === m.id) selectedMachineId = null;
        await refreshMachines();
        if (isOpen(machineModal)) renderMachineModalList();
        updateMachineSelectLabel();
        updateSendButton();
      }
    );
  }

  async function refreshMachines() {
    try { machines = await (await fetch("/api/machines")).json(); } catch (e) { return; }
    updateMachineSelectLabel();
  }

  /* ---------- Alarma / conexion ---------- */
  function renderConnection(s) {
    usbConnected = s.usb_connected;
    if (usbConnected) {
      usbDot.classList.add("connected");
      usbLabel.textContent = s.usb_device;
      alarm.classList.add("ok");
      alarmIcon.textContent = "✓";
      alarmText.textContent = "Cable RS232 conectado (" + s.usb_device + ")";
    } else {
      usbDot.classList.remove("connected");
      usbLabel.textContent = "Sin adaptador";
      alarm.classList.remove("ok");
      alarmIcon.textContent = "⚠";
      alarmText.textContent = "Cable RS232 no conectado";
    }
  }

  /* ---------- Envio ---------- */
  function updateSelectedFileUi() {
    selectedFileName.textContent = selectedFile ? selectedFile.name : "Ninguno";
    updateSendButton();
  }

  function updateSendButton() {
    let hint = "";
    if (!selectedFile) hint = "Selecciona un programa";
    else if (editorDirty) hint = "Guarda los cambios antes de enviar";
    else if (!selectedMachineId) hint = "Selecciona una máquina";
    else if (!usbConnected) hint = "Conecta el cable RS232";
    else if (sending) hint = "Transferencia en curso...";

    btnSend.disabled = !(selectedFile && !editorDirty && selectedMachineId && usbConnected && !sending);
    sendHint.textContent = hint;
  }

  btnSend.onclick = () => {
    if (btnSend.disabled) return;
    confirmAction(
      "Confirmar envío",
      `¿Enviar "${selectedFile.name}" a la máquina seleccionada? Se transmitirá por el puerto serial.`,
      "Enviar", false,
      doSend
    );
  };

  async function doSend() {
    const res = await fetch("/api/send", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: selectedFile.path }),
    });
    const data = await res.json();
    if (!data.ok) alert(data.error || "No se pudo iniciar el envío");
    poll();
  }

  function renderTransfer(t) {
    sending = t.status === "sending";
    transferBox.classList.remove("error", "success");
    if (t.status === "idle") {
      transferBox.classList.remove("visible");
      return;
    }
    transferBox.classList.add("visible");
    progressFill.style.width = (t.percent || 0) + "%";
    if (t.status === "sending") {
      transferTitle.textContent = `Enviando ${t.filename} a ${t.machine}...`;
      transferDetail.textContent = `${t.percent}% (${t.bytes_sent} / ${t.total_bytes} bytes)`;
    } else if (t.status === "success") {
      transferBox.classList.add("success");
      transferTitle.textContent = `Envío completado: ${t.filename}`;
      transferDetail.textContent = t.message || "Transferencia exitosa";
    } else if (t.status === "error") {
      transferBox.classList.add("error");
      transferTitle.textContent = `Error enviando ${t.filename || ""}`;
      transferDetail.textContent = t.message || "Ocurrió un error";
    }
  }

  /* ---------- Polling ---------- */
  async function poll() {
    let s;
    try { s = await (await fetch("/api/state")).json(); }
    catch (e) { usbLabel.textContent = "Sin conexión al backend"; return; }

    machines = s.machines;
    selectedMachineId = s.active_machine_id || null;
    renderConnection(s);
    updateMachineSelectLabel();
    if (isOpen(machineModal)) renderMachineModalList();
    renderTransfer(s.transfer);

    if (s.files_version !== lastFilesVersion) {
      lastFilesVersion = s.files_version;
      await loadDir(currentPath);
      if (selectedFile && !editorDirty && document.activeElement !== editor) await loadContent();
    }
    updateSendButton();
  }

  /* ---------- Arranque ---------- */
  loadDir("");
  poll();
  setInterval(poll, POLL_MS);
})();
