(function () {
  const POLL_MS = 1000;

  const $ = (id) => document.getElementById(id);

  // Cabecera / conexion
  const ipBadge = $("ipBadge");
  const alarm = $("alarm");
  const alarmIcon = $("alarmIcon");
  const alarmText = $("alarmText");

  // WiFi
  const btnWifi = $("btnWifi");
  const wifiModal = $("wifiModal");
  const wifiCurrent = $("wifiCurrent");
  const btnWifiScan = $("btnWifiScan");
  const wifiList = $("wifiList");
  const wifiError = $("wifiError");
  const btnCloseWifi = $("btnCloseWifi");

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
  const portSelectBtn = $("portSelectBtn");
  const portSelectLabel = $("portSelectLabel");
  const portModal = $("portModal");
  const portModalList = $("portModalList");
  const btnClosePortModal = $("btnClosePortModal");
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
  const mfDtr = $("mfDtr");
  const mfRts = $("mfRts");
  const mfDrip = $("mfDrip");
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

  // Editor con resaltado
  const editorBackdrop = $("editorBackdrop");
  const editorHighlight = $("editorHighlight");
  const editorGutter = $("editorGutter");
  const editorError = $("editorError");
  const editorErrorTitle = $("editorErrorTitle");
  const editorErrorDetail = $("editorErrorDetail");

  // Expandir columnas + herramientas avanzadas
  const btnExpandFiles = $("btnExpandFiles");
  const btnExpandEditor = $("btnExpandEditor");
  const btnRenumber = $("btnRenumber");
  const btnStripN = $("btnStripN");
  const btnGotoLine = $("btnGotoLine");

  // Buscador de archivos
  const fileSearchModal = $("fileSearchModal");
  const fsSearch = $("fsSearch");
  const fsClose = $("fsClose");
  const fsHint = $("fsHint");
  const fsResults = $("fsResults");
  const fsBreadcrumb = $("fsBreadcrumb");

  // Prompt generico (renumerar / ir a linea)
  const promptModal = $("promptModal");
  const promptTitle = $("promptTitle");
  const promptFields = $("promptFields");
  const promptError = $("promptError");
  const btnPromptCancel = $("btnPromptCancel");
  const btnPromptOk = $("btnPromptOk");

  // Teclado flotante QWERTY
  const floatKeyboard = $("floatKeyboard");
  const floatKbBar = $("floatKbBar");
  const floatKbClose = $("floatKbClose");
  const floatKbKeys = $("floatKbKeys");

  // Teclado G-code
  const btnKeyboard = $("btnKeyboard");
  const actionPanel = $("actionPanel");
  const keyboardPanel = $("keyboardPanel");
  const keyboard = $("keyboard");
  const kbTarget = $("kbTarget");
  const btnCloseKeyboard = $("btnCloseKeyboard");

  // Estado
  let currentPath = "";
  let selectedFile = null;      // {path, name}
  let selectedMachineId = null;
  let machines = [];
  let devices = [];              // [{path, desc}] puertos conectados
  let activeDevice = null;       // puerto elegido para enviar
  let activeDeviceDesc = null;
  let usbConnected = false;
  let sending = false;
  let editorDirty = false;
  let lastFilesVersion = -1;
  let editingMachineId = null;
  let confirmCb = null;
  let activeField = null;   // campo de texto que recibe las teclas (editor o busqueda)
  let keyboardOn = false;   // el teclado se activa/desactiva con un boton, no solo

  /* ---------- Utilidades ---------- */
  function esc(s) {
    return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  const ICON_FOLDER =
    '<svg class="ficon folder" viewBox="0 0 24 24"><path fill="currentColor" d="M10 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-8l-2-2z"/></svg>';
  const ICON_FILE =
    '<svg class="ficon file" viewBox="0 0 24 24"><path fill="currentColor" d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z"/><path fill="#141821" d="M14 2v6h6"/></svg>';

  function formatSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function formatDateTime(sec) {
    if (!sec) return "";
    const d = new Date(sec * 1000);
    const p = (n) => String(n).padStart(2, "0");
    return `${p(d.getDate())}/${p(d.getMonth() + 1)}/${String(d.getFullYear()).slice(2)} ${p(d.getHours())}:${p(d.getMinutes())}`;
  }

  function machineSubLabel(m) {
    const flow = m.flow_control === "xonxoff" ? "XON/XOFF" : "RTS/CTS";
    const term = m.line_terminator === "CRLF" ? "CR+LF" : m.line_terminator;
    const drip = m.dripfeed ? " · goteo" : "";
    return `${m.baudrate} baud · ${m.bytesize}${m.parity}${m.stopbits} · ${flow} · ${term}${drip}`;
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
      row.innerHTML = `${ICON_FOLDER}<span class="entry-name">${esc(d.name)}</span><span class="icon">›</span>`;
      row.onclick = () => loadDir(d.path);
      browserEl.appendChild(row);
    });
    data.files.forEach((f) => {
      const row = document.createElement("div");
      row.className = "entry file" + (selectedFile && selectedFile.path === f.path ? " selected" : "");
      row.dataset.path = f.path;
      row.innerHTML = `${ICON_FILE}<span class="entry-name">${esc(f.name)}</span><span class="entry-meta"><span class="entry-date">${formatDateTime(f.mtime)}</span><span class="entry-size">${formatSize(f.size)}</span></span>`;
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

  // Muestra u oculta el overlay de error del editor. Usado cuando el archivo
  // no es texto legible (binario, UTF-16, etc.) o dejo de existir.
  function setEditorError(title, detail) {
    if (title) {
      editorErrorTitle.textContent = title;
      editorErrorDetail.textContent = detail || "";
      editorError.hidden = false;
    } else {
      editorError.hidden = true;
    }
  }

  async function loadContent() {
    if (!selectedFile) {
      editor.value = "";
      editor.readOnly = false;
      editorFilename.textContent = "Sin archivo";
      editorDirty = false;
      setEditorError(null);
      updateHighlight();
      updateEditorButtons();
      updateSendButton();
      return;
    }
    try {
      const res = await fetch("/api/file?path=" + encodeURIComponent(selectedFile.path));

      // Archivo binario o codificado de forma que el editor no puede
      // mostrar. El backend devuelve 415 con { binary: true, name }.
      if (res.status === 415) {
        const data = await res.json().catch(() => ({}));
        editor.value = "";
        editor.readOnly = true;
        editorDirty = false;
        editorFilename.textContent = (data.name || selectedFile.name) + " — incompatible";
        setEditorError("Archivo incompatible",
          "Este archivo no es texto y no se puede mostrar ni editar desde el panel.");
        updateHighlight();
        updateEditorButtons();
        updateSendButton();
        return;
      }

      if (!res.ok) {
        editor.value = "";
        editor.readOnly = true;
        editorFilename.textContent = selectedFile.name + " (no disponible)";
        setEditorError("Archivo no disponible", "No se pudo leer el archivo desde la carpeta compartida.");
        updateHighlight();
        updateEditorButtons();
        updateSendButton();
        return;
      }
      const data = await res.json();
      editor.value = data.content;
      editor.scrollTop = 0;
      editorDirty = false;
      setEditorError(null);
      if (data.truncated) {
        editor.readOnly = true;
        editorFilename.textContent = data.name + " — muy grande, solo lectura";
      } else {
        editor.readOnly = false;
        editorFilename.textContent = data.name;
      }
      updateHighlight();
      updateEditorButtons();
      updateSendButton();
    } catch (e) { /* reintenta en el siguiente ciclo */ }
  }

  function updateEditorButtons() {
    btnSave.disabled = !(selectedFile && editorDirty && !editor.readOnly);
    btnDeleteFile.disabled = !selectedFile;
  }

  editor.addEventListener("input", () => {
    updateHighlight();
    if (editor.readOnly) return;
    editorDirty = true;
    updateEditorButtons();
    updateSendButton();
  });

  editor.addEventListener("scroll", () => {
    editorBackdrop.scrollTop = editor.scrollTop;
    editorBackdrop.scrollLeft = editor.scrollLeft;
    editorGutter.scrollTop = editor.scrollTop;
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
    btnSave.textContent = "✓";
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
        setEditorError(null);
        updateHighlight();
        setKeyboard(false);
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
    showFloatKeyboard(newFileName);
    setTimeout(() => newFileName.focus(), 50);
  };
  btnCancelNewFile.onclick = () => { closeModal(newFileModal); hideFloatKeyboard(); };
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
    hideFloatKeyboard();
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
      updateHighlight();
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
    updateHighlight();
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
      setKeyboard(true);           // buscar requiere escribir: se enciende el teclado
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
    mfDtr.checked = m ? !!m.dtr : false;
    mfRts.checked = m ? !!m.rts : false;
    mfDrip.checked = m ? !!m.dripfeed : false;
    mfError.textContent = "";
    openModal(machineEditModal);
  }

  btnAddMachine.onclick = () => openMachineEdit(null);
  btnCancelMachineEdit.onclick = () => { closeModal(machineEditModal); hideFloatKeyboard(); };

  btnSaveMachineEdit.onclick = async () => {
    const payload = {
      name: mfName.value,
      baudrate: mfBaud.value,
      bytesize: mfBytesize.value,
      parity: mfParity.value,
      stopbits: mfStop.value,
      flow_control: mfFlow.value,
      line_terminator: mfTerm.value,
      dtr: mfDtr.checked,
      rts: mfRts.checked,
      dripfeed: mfDrip.checked,
    };
    if (editingMachineId) payload.id = editingMachineId;
    const res = await fetch("/api/machine/save", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!data.ok) { mfError.textContent = data.error || "No se pudo guardar"; return; }
    closeModal(machineEditModal);
    hideFloatKeyboard();
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

  /* ---------- Puerto(s) / alarma / conexion ---------- */
  function renderConnection(s) {
    devices = s.usb_devices || [];
    activeDevice = s.active_device || null;
    activeDeviceDesc = s.active_device_desc || null;
    usbConnected = devices.length > 0;

    alarm.classList.remove("ok", "warn");
    if (!usbConnected) {
      alarmIcon.textContent = "⚠";
      alarmText.textContent = "Cable RS232 no conectado";
    } else if (!activeDevice) {
      // Varios adaptadores conectados y ninguno elegido todavia.
      alarm.classList.add("warn");
      alarmIcon.textContent = "⚠";
      alarmText.textContent = "Elige a qué puerto enviar (" + devices.length + " conectados)";
    } else {
      const desc = activeDeviceDesc ? " · " + activeDeviceDesc : "";
      alarm.classList.add("ok");
      alarmIcon.textContent = "✓";
      alarmText.textContent = "Conectado en " + activeDevice + desc;
    }
    updatePortSelectLabel();
    if (isOpen(portModal)) renderPortModalList();
  }

  function updatePortSelectLabel() {
    if (!usbConnected) {
      portSelectLabel.textContent = "Sin puerto";
    } else if (activeDevice) {
      portSelectLabel.textContent = activeDevice + (activeDeviceDesc ? " · " + activeDeviceDesc : "");
    } else {
      portSelectLabel.textContent = "Elegir puerto (" + devices.length + ")";
    }
  }

  portSelectBtn.onclick = () => { renderPortModalList(); openModal(portModal); };
  btnClosePortModal.onclick = () => closeModal(portModal);

  function renderPortModalList() {
    portModalList.innerHTML = "";
    if (devices.length === 0) {
      const e = document.createElement("div");
      e.className = "machine-modal-empty";
      e.textContent = "No hay adaptadores conectados.";
      portModalList.appendChild(e);
      return;
    }
    devices.forEach((d) => {
      const row = document.createElement("div");
      row.className = "machine-row" + (d.path === activeDevice ? " selected" : "");
      const pick = document.createElement("button");
      pick.className = "machine-pick";
      pick.innerHTML = `<div class="m-name">${esc(d.path)}</div><div class="m-sub">${esc(d.desc || "adaptador USB-serial")}</div>`;
      pick.onclick = () => selectDevice(d.path);
      row.appendChild(pick);
      portModalList.appendChild(row);
    });
  }

  async function selectDevice(path) {
    await fetch("/api/device/select", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    activeDevice = path;
    updatePortSelectLabel();
    updateSendButton();
    closeModal(portModal);
  }

  /* ---------- Envio ---------- */
  function updateSelectedFileUi() {
    selectedFileName.textContent = selectedFile ? selectedFile.name : "Ninguno";
    updateSendButton();
  }

  function updateSendButton() {
    // Mientras transmite, el mismo boton sirve para CANCELAR.
    if (sending) {
      btnSend.textContent = "CANCELAR";
      btnSend.classList.add("cancel");
      btnSend.disabled = false;
      sendHint.textContent = "Enviando… toca para cancelar";
      return;
    }
    btnSend.textContent = "ENVIAR";
    btnSend.classList.remove("cancel");

    let hint = "";
    if (!selectedFile) hint = "Selecciona un programa";
    else if (editor.readOnly && editorError && !editorError.hidden) hint = "Archivo incompatible — no se puede enviar";
    else if (editorDirty) hint = "Guarda los cambios antes de enviar";
    else if (!selectedMachineId) hint = "Selecciona una máquina";
    else if (!usbConnected) hint = "Conecta el cable RS232";
    else if (!activeDevice) hint = "Elige a qué puerto enviar";

    btnSend.disabled = !(selectedFile && !editorDirty && !editor.readOnly && selectedMachineId && usbConnected && activeDevice);
    sendHint.textContent = hint;
  }

  btnSend.onclick = () => {
    if (sending) {           // en curso -> cancelar
      confirmAction(
        "Cancelar envío",
        "¿Cancelar la transferencia en curso? La máquina puede quedar con el programa incompleto.",
        "Cancelar envío", true,
        cancelSend
      );
      return;
    }
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

  async function cancelSend() {
    try { await fetch("/api/send/cancel", { method: "POST" }); } catch (e) { /* noop */ }
    poll();
  }

  function renderTransfer(t) {
    sending = t.status === "sending";
    transferBox.classList.remove("error", "success", "cancelled");
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
    } else if (t.status === "cancelled") {
      transferBox.classList.add("cancelled");
      transferTitle.textContent = `Envío cancelado: ${t.filename || ""}`;
      transferDetail.textContent = t.message || "Cancelado por el usuario";
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
    catch (e) { ipBadge.textContent = "Sin conexión"; return; }

    machines = s.machines;
    selectedMachineId = s.active_machine_id || null;
    ipBadge.textContent = s.ip ? "IP: " + s.ip : "IP: —";
    const wifiOn = !!s.wifi_ssid;
    btnWifi.classList.toggle("on", wifiOn);
    btnWifi.classList.toggle("off", !wifiOn);
    btnWifi.title = wifiOn ? "WiFi: " + s.wifi_ssid : "WiFi desconectado — configurar";
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

  /* ---------- Resaltado de sintaxis del G-code ---------- */
  function wordClass(L) {
    if (L === "G") return "g-g";
    if (L === "M") return "g-m";
    if ("XYZABCUVW".indexOf(L) !== -1) return "g-axis";
    if ("IJKR".indexOf(L) !== -1) return "g-arc";
    if (L === "F" || L === "S") return "g-fs";
    if ("THD".indexOf(L) !== -1) return "g-tool";
    if (L === "N") return "g-n";
    if (L === "O") return "g-o";
    return "g-oth";
  }

  function highlightGcode(text) {
    let out = "";
    let i = 0;
    const n = text.length;
    while (i < n) {
      const c = text[i];
      if (c === "(") {                       // comentario ( ... )
        let j = text.indexOf(")", i);
        if (j === -1) j = n - 1;
        out += '<span class="g-cmt">' + esc(text.slice(i, j + 1)) + "</span>";
        i = j + 1;
      } else if (c === "%") {                 // marca de inicio/fin de cinta
        out += '<span class="g-pct">%</span>';
        i++;
      } else if (/[A-Za-z]/.test(c)) {        // palabra: letra + numero
        let j = i + 1;
        if (text[j] === "-" || text[j] === "+") j++;
        while (j < n && /[0-9.]/.test(text[j])) j++;
        out += '<span class="' + wordClass(c.toUpperCase()) + '">' + esc(text.slice(i, j)) + "</span>";
        i = j;
      } else {
        out += esc(c);
        i++;
      }
    }
    return out;
  }

  function updateHighlight() {
    editorHighlight.innerHTML = highlightGcode(editor.value);
    editorBackdrop.scrollTop = editor.scrollTop;
    editorBackdrop.scrollLeft = editor.scrollLeft;
    updateGutter();
  }

  function updateGutter() {
    const lines = editor.value.split("\n").length;
    let out = "";
    for (let i = 1; i <= lines; i++) out += i + "\n";
    editorGutter.textContent = out;
    editorGutter.scrollTop = editor.scrollTop;
  }

  /* ---------- Teclado G-code (tercera columna) ---------- */
  // Solo los caracteres que se usan en programas CNC / G-code: letras de
  // direccion, digitos (en distribucion tipo numpad), punto, signo,
  // parentesis de comentario y simbolos de macro (# [ ] = %). Nada mas.
  function keyEl(key) {
    const b = document.createElement("button");
    b.className = "kb-key";
    if (typeof key === "string") {
      b.textContent = key;
      if (/^[A-Za-z]$/.test(key)) b.classList.add(wordClass(key.toUpperCase()));
      else if (/^[0-9]$/.test(key)) b.classList.add("g-num");
    } else {
      b.textContent = key.l;
      b.classList.add("kb-action");
      if (key.w) b.style.flex = String(key.w);
    }
    b.addEventListener("pointerdown", (e) => { e.preventDefault(); pressKey(key); });
    return b;
  }

  function rowEl(keys) {
    const r = document.createElement("div");
    r.className = "kb-row";
    keys.forEach((k) => r.appendChild(keyEl(k)));
    return r;
  }

  function colEl(rows, cls, flex) {
    const c = document.createElement("div");
    c.className = "kb-col" + (cls ? " " + cls : "");
    if (flex) c.style.flex = String(flex);
    rows.forEach((row) => c.appendChild(rowEl(row)));
    return c;
  }

  function buildKeyboard() {
    keyboard.innerHTML = "";

    // Letras de direccion (todas las que pueden aparecer en G-code)
    keyboard.appendChild(colEl([
      ["G", "M", "N", "O", "X", "Y", "Z"],
      ["A", "B", "C", "U", "V", "W", "H"],
      ["I", "J", "K", "R", "F", "S", "T"],
      ["P", "Q", "D", "L", "E"],
    ], "", 4));

    // Zona inferior: numpad (izquierda) + simbolos (derecha)
    const bottom = document.createElement("div");
    bottom.className = "kb-bottom";
    bottom.appendChild(colEl([
      ["7", "8", "9"],
      ["4", "5", "6"],
      ["1", "2", "3"],
      [".", "0", "-"],
    ], "kb-numpad"));
    bottom.appendChild(colEl([
      ["(", ")", "/"],
      ["+", "=", "%"],
      ["#", "[", "]"],
      [":", { a: "back", l: "⌫" }, { a: "enter", l: "↵" }],
    ], "kb-symbols"));
    keyboard.appendChild(bottom);

    // Fila de espacio + cursor
    keyboard.appendChild(colEl([
      [{ a: "space", l: "espacio", w: 3 }, { a: "left", l: "◀" }, { a: "right", l: "▶" }],
    ], "", 1));
  }

  function insertAtCaret(el, text) {
    const s = el.selectionStart != null ? el.selectionStart : el.value.length;
    const e = el.selectionEnd != null ? el.selectionEnd : el.value.length;
    el.setRangeText(text, s, e, "end");
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function backspaceField(el) {
    let s = el.selectionStart, e = el.selectionEnd;
    if (s === e) { if (s === 0) return; s = s - 1; }
    el.setRangeText("", s, e, "end");
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function moveCaret(el, d) {
    const p = Math.max(0, Math.min(el.value.length, (el.selectionStart || 0) + d));
    el.setSelectionRange(p, p);
    if (el === editor) scrollToSel();
  }

  function pressKey(key) {
    if (!activeField) activeField = editor;
    const editingReadonly = activeField === editor && editor.readOnly;
    if (typeof key === "string") {
      if (editingReadonly) return;
      insertAtCaret(activeField, key);
      return;
    }
    switch (key.a) {
      case "space": if (!editingReadonly) insertAtCaret(activeField, " "); break;
      case "back": if (!editingReadonly) backspaceField(activeField); break;
      case "enter":
        if (activeField === editor) { if (!editingReadonly) insertAtCaret(editor, "\n"); }
        else gotoMatch(true);
        break;
      case "left": moveCaret(activeField, -1); break;
      case "right": moveCaret(activeField, 1); break;
    }
  }

  // El teclado se activa/desactiva con un boton; ya no aparece solo al tocar
  // el texto (asi se puede ver y hacer scroll de un programa sin que estorbe).
  function setKeyboard(on) {
    keyboardOn = on;
    if (on) {
      actionPanel.style.display = "none";
      keyboardPanel.classList.add("visible");
      document.body.classList.add("kb-active");
      btnKeyboard.classList.add("active");
      kbTarget.textContent =
        activeField === findInput ? "Buscar" :
        activeField === replaceInput ? "Reemplazar" : "Editando programa";
    } else {
      keyboardPanel.classList.remove("visible");
      actionPanel.style.display = "";
      document.body.classList.remove("kb-active");
      btnKeyboard.classList.remove("active");
    }
  }

  btnKeyboard.onclick = () => setKeyboard(!keyboardOn);
  btnCloseKeyboard.onclick = () => setKeyboard(false);

  // Los focus solo registran a que campo van las teclas y actualizan la
  // etiqueta; NO abren el teclado (eso lo controla el boton).
  editor.addEventListener("focus", () => { activeField = editor; if (keyboardOn) kbTarget.textContent = "Editando programa"; });
  findInput.addEventListener("focus", () => { activeField = findInput; if (keyboardOn) kbTarget.textContent = "Buscar"; });
  replaceInput.addEventListener("focus", () => { activeField = replaceInput; if (keyboardOn) kbTarget.textContent = "Reemplazar"; });

  buildKeyboard();

  /* ---------- Expandir editor + herramientas avanzadas (tipo NCeditor) ---------- */
  let contentExpanded = false;
  function setContentExpanded(on) {
    contentExpanded = on;
    document.body.classList.toggle("content-expanded", on);
    btnExpandEditor.textContent = on ? "⤡" : "⤢";
    updateGutter();
  }
  btnExpandEditor.onclick = () => setContentExpanded(!contentExpanded);

  function applyEditorTransform(fn) {
    if (editor.readOnly) return;
    const lines = editor.value.split("\n");
    editor.value = fn(lines).join("\n");
    editor.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function stripLineNumbers() {
    applyEditorTransform((lines) => lines.map((l) => l.replace(/^(\s*)N\d+\s?/i, "$1")));
  }

  function renumberLines(start, step) {
    let num = start;
    applyEditorTransform((lines) => lines.map((l) => {
      const t = l.trim();
      if (t === "" || t.startsWith("%")) return l;         // vacias y % intactas
      const stripped = l.replace(/^(\s*)N\d+\s?/i, "$1");
      const m = stripped.match(/^(\s*)([\s\S]*)$/);
      const line = m[1] + "N" + num + (m[2] ? " " + m[2] : "");
      num += step;
      return line;
    }));
  }

  function gotoLine(n) {
    const lines = editor.value.split("\n");
    n = Math.max(1, Math.min(lines.length, n));
    let pos = 0;
    for (let i = 0; i < n - 1; i++) pos += lines[i].length + 1;
    editor.focus();
    editor.setSelectionRange(pos, pos);
    scrollToSel();
  }

  btnStripN.onclick = () => {
    if (!selectedFile || editor.readOnly) return;
    confirmAction("Quitar números de línea", "¿Quitar los N° de todas las líneas del programa?", "Quitar", false, stripLineNumbers);
  };
  btnRenumber.onclick = () => {
    if (!selectedFile || editor.readOnly) return;
    openPrompt("Renumerar líneas", [
      { id: "start", label: "Inicio (N)", value: "10" },
      { id: "step", label: "Incremento", value: "10" },
    ], (v) => {
      const start = parseInt(v.start, 10), step = parseInt(v.step, 10);
      if (!(start >= 0) || !(step > 0)) return "Valores inválidos";
      renumberLines(start, step);
    });
  };
  btnGotoLine.onclick = () => {
    openPrompt("Ir a línea", [{ id: "line", label: "Número de línea", value: "" }], (v) => {
      const n = parseInt(v.line, 10);
      if (!(n >= 1)) return "Número inválido";
      gotoLine(n);
    });
  };

  /* ---------- Prompt generico ---------- */
  let promptCb = null;
  function openPrompt(title, fields, onOk) {
    promptTitle.textContent = title;
    promptError.textContent = "";
    promptFields.innerHTML = "";
    fields.forEach((f) => {
      const lab = document.createElement("label");
      lab.textContent = f.label;
      const inp = document.createElement("input");
      inp.type = "text";
      inp.inputMode = "none";
      inp.autocomplete = "off";
      inp.value = f.value != null ? f.value : "";
      inp.dataset.id = f.id;
      inp.addEventListener("focus", () => showFloatKeyboard(inp));
      lab.appendChild(inp);
      promptFields.appendChild(lab);
    });
    promptCb = onOk;
    openModal(promptModal);
    const first = promptFields.querySelector("input");
    if (first) setTimeout(() => first.focus(), 50);
  }
  btnPromptCancel.onclick = () => { closeModal(promptModal); hideFloatKeyboard(); promptCb = null; };
  btnPromptOk.onclick = () => {
    const vals = {};
    promptFields.querySelectorAll("input").forEach((i) => { vals[i.dataset.id] = i.value; });
    if (promptCb) {
      const err = promptCb(vals);
      if (err) { promptError.textContent = err; return; }
    }
    closeModal(promptModal);
    hideFloatKeyboard();
    promptCb = null;
  };

  /* ---------- Buscador / navegador de archivos (columna expandida) ---------- */
  let fsTimer = null;
  let fsPath = "";
  btnExpandFiles.onclick = () => {
    fsSearch.value = "";
    fsPath = currentPath;      // arranca en la carpeta que ya se veia
    openModal(fileSearchModal);
    fsBrowse(fsPath);
    // Estilo Finder: el explorador navegable aparece primero. El input de
    // busqueda NO se enfoca solo, asi no se abre el teclado flotante sin
    // que el usuario lo pida. Si quiere buscar, toca el input.
  };

  // Cierra el modal de busqueda y, con el, el teclado flotante (por si
  // estaba abierto). Usado por el boton Cerrar y por el click fuera del panel.
  function closeFileSearchModal() {
    closeModal(fileSearchModal);
    hideFloatKeyboard();
  }
  fsClose.onclick = closeFileSearchModal;

  // Click fuera del panel (sobre el overlay oscuro) cierra el modal.
  fileSearchModal.addEventListener("click", (e) => {
    if (e.target === fileSearchModal) closeFileSearchModal();
  });

  // ESC tambien cierra el modal (y el teclado, por si quedo abierto).
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && isOpen(fileSearchModal)) closeFileSearchModal();
  });
  fsSearch.addEventListener("focus", () => showFloatKeyboard(fsSearch));
  fsSearch.addEventListener("input", () => {
    clearTimeout(fsTimer);
    fsTimer = setTimeout(fsUpdate, 200);
  });

  function fsUpdate() {
    if (fsSearch.value.trim()) doFileSearch();
    else fsBrowse(fsPath);
  }

  // Modo navegacion: muestra carpetas y archivos de una carpeta, navegable.
  async function fsBrowse(path) {
    let data;
    try { data = await (await fetch("/api/files?path=" + encodeURIComponent(path))).json(); }
    catch (e) { return; }
    fsPath = data.path;
    fsBreadcrumb.style.display = "";
    fsHint.style.display = "none";
    renderFsBreadcrumb(data.breadcrumb);

    fsResults.innerHTML = "";
    if (data.dirs.length === 0 && data.files.length === 0) {
      fsHint.style.display = "";
      fsHint.textContent = "Carpeta vacía.";
      return;
    }
    data.dirs.forEach((d) => {
      const row = document.createElement("div");
      row.className = "fs-row";
      row.innerHTML = `${ICON_FOLDER}<div class="fs-col"><div class="fs-name">${esc(d.name)}</div></div><div class="fs-size">›</div>`;
      row.onclick = () => fsBrowse(d.path);
      fsResults.appendChild(row);
    });
    data.files.forEach((f) => {
      const row = document.createElement("div");
      row.className = "fs-row";
      row.innerHTML = `${ICON_FILE}<div class="fs-col"><div class="fs-name">${esc(f.name)}</div><div class="fs-path">${formatDateTime(f.mtime)}</div></div><div class="fs-size">${formatSize(f.size)}</div>`;
      row.onclick = () => pickSearchResult({ path: f.path, name: f.name, dir: fsPath, size: f.size });
      fsResults.appendChild(row);
    });
  }

  function renderFsBreadcrumb(crumbs) {
    fsBreadcrumb.innerHTML = "";
    crumbs.forEach((c, i) => {
      if (i > 0) {
        const sep = document.createElement("span");
        sep.className = "crumb-sep";
        sep.textContent = "›";
        fsBreadcrumb.appendChild(sep);
      }
      const btn = document.createElement("button");
      btn.className = "crumb" + (i === crumbs.length - 1 ? " current" : "");
      btn.textContent = c.name;
      if (i !== crumbs.length - 1) btn.onclick = () => fsBrowse(c.path);
      fsBreadcrumb.appendChild(btn);
    });
  }

  // Modo busqueda: resultados recursivos por nombre en todas las carpetas.
  async function doFileSearch() {
    const q = fsSearch.value.trim();
    if (!q) { fsBrowse(fsPath); return; }
    let results;
    try { results = await (await fetch("/api/search?q=" + encodeURIComponent(q))).json(); }
    catch (e) { return; }
    fsBreadcrumb.style.display = "none";
    renderSearchResults(results);
  }

  function renderSearchResults(results) {
    fsResults.innerHTML = "";
    if (results.length === 0) {
      fsHint.style.display = "";
      fsHint.textContent = "Sin resultados.";
      return;
    }
    fsHint.style.display = "none";
    results.forEach((r) => {
      const row = document.createElement("div");
      row.className = "fs-row";
      const folder = r.dir ? r.dir : "Programas";
      row.innerHTML = `${ICON_FILE}<div class="fs-col"><div class="fs-name">${esc(r.name)}</div><div class="fs-path">📁 ${esc(folder)} · ${formatDateTime(r.mtime)}</div></div><div class="fs-size">${formatSize(r.size)}</div>`;
      row.onclick = () => pickSearchResult(r);
      fsResults.appendChild(row);
    });
  }

  function pickSearchResult(r) {
    hideFloatKeyboard();
    if (editorDirty) {
      confirmAction("Cambios sin guardar", `Hay cambios sin guardar. ¿Descartarlos y abrir "${r.name}"?`, "Descartar", true, () => doPickSearch(r));
      return;
    }
    doPickSearch(r);
  }

  async function doPickSearch(r) {
    selectedFile = { path: r.path, name: r.name };
    editorDirty = false;
    await loadDir(r.dir || "");   // navega el explorador a la carpeta del archivo
    updateSelectedFileUi();
    markSelected();
    await loadContent();
    closeModal(fileSearchModal);
  }

  /* ---------- Teclado QWERTY flotante y arrastrable ---------- */
  let floatTarget = null;
  let floatShift = false;
  const FK_ROWS = [
    ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
    ["Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P"],
    ["A", "S", "D", "F", "G", "H", "J", "K", "L"],
    ["Z", "X", "C", "V", "B", "N", "M", "_", "-"],
  ];

  function buildFloatKeyboard() {
    floatKbKeys.innerHTML = "";
    // Cada tecla se suscribe a mousedown/touchstart/pointerdown para que
    // ninguna variante de evento quede sin prevenir. El preventDefault evita
    // que el navegador mueva el foco al boton (que es focusable por
    // naturaleza) y lo saque del input que estamos editando.
    const press = (fn) => (e) => { e.preventDefault(); fn(e); };
    FK_ROWS.forEach((row) => {
      const r = document.createElement("div");
      r.className = "fk-row";
      row.forEach((ch) => {
        const b = document.createElement("button");
        b.type = "button";          // fuera de un form, pero por si acaso
        b.tabIndex = -1;            // las teclas no participan en el foco
        b.className = "fk-key";
        b.textContent = ch;
        b.dataset.char = ch;
        const fn = press(() => fkPress(ch));
        b.addEventListener("pointerdown", fn);
        b.addEventListener("mousedown", fn);
        b.addEventListener("touchstart", fn, { passive: false });
        r.appendChild(b);
      });
      floatKbKeys.appendChild(r);
    });
    const r = document.createElement("div");
    r.className = "fk-row";
    const mk = (label, cls, fn) => {
      const b = document.createElement("button");
      b.type = "button";
      b.tabIndex = -1;
      b.className = "fk-key " + cls;
      b.textContent = label;
      const handler = press(fn);
      b.addEventListener("pointerdown", handler);
      b.addEventListener("mousedown", handler);
      b.addEventListener("touchstart", handler, { passive: false });
      return b;
    };
    r.appendChild(mk("⇧", "action shift-key", toggleShift));
    r.appendChild(mk(".", "", () => fkInsert(".")));
    r.appendChild(mk("espacio", "wide", () => fkInsert(" ")));
    r.appendChild(mk("⌫", "action", fkBackspace));
    r.appendChild(mk("↵", "action", fkEnter));
    floatKbKeys.appendChild(r);
  }

  // El Enter del teclado flotante envia el formulario del modal activo
  // (asi no hay que alcanzar el boton si el teclado lo tapa).
  function fkEnter() {
    if (floatTarget === newFileName) { btnCreateNewFile.click(); return; }
    if (floatTarget === mfName) { btnSaveMachineEdit.click(); return; }
    if (floatTarget && floatTarget.closest && floatTarget.closest("#promptModal")) { btnPromptOk.click(); return; }
    hideFloatKeyboard();
  }

  function fkPress(ch) {
    if (/[A-Za-z]/.test(ch)) ch = floatShift ? ch.toLowerCase() : ch.toUpperCase();
    fkInsert(ch);
  }
  function fkInsert(text) {
    const el = floatTarget;
    if (!el) return;
    const s = el.selectionStart != null ? el.selectionStart : el.value.length;
    const e = el.selectionEnd != null ? el.selectionEnd : el.value.length;
    el.setRangeText(text, s, e, "end");
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }
  function fkBackspace() {
    const el = floatTarget;
    if (!el) return;
    let s = el.selectionStart, e = el.selectionEnd;
    if (s === e) { if (s === 0) return; s = s - 1; }
    el.setRangeText("", s, e, "end");
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }
  function toggleShift() {
    floatShift = !floatShift;
    floatKbKeys.querySelectorAll(".fk-key").forEach((k) => {
      if (k.dataset.char && /[A-Za-z]/.test(k.dataset.char)) {
        k.textContent = floatShift ? k.dataset.char.toLowerCase() : k.dataset.char.toUpperCase();
      }
    });
    const sk = floatKbKeys.querySelector(".shift-key");
    if (sk) sk.classList.toggle("active", floatShift);
  }

  function showFloatKeyboard(target) {
    floatTarget = target;
    floatKeyboard.classList.add("visible");
    document.body.classList.add("float-kb-active");
  }
  function hideFloatKeyboard() {
    floatKeyboard.classList.remove("visible");
    document.body.classList.remove("float-kb-active");
    floatTarget = null;
  }
  floatKbClose.onclick = hideFloatKeyboard;

  // Arrastrar el teclado flotante por su barra
  (function enableFloatDrag() {
    let dragging = false, offX = 0, offY = 0;
    floatKbBar.addEventListener("pointerdown", (e) => {
      // Si el pointerdown ocurre en el boton de cerrar (o cualquier hijo),
      // NO iniciar el arrastre: el setPointerCapture de la barra se comería
      // el click del boton y la X no cerraria el teclado.
      if (e.target.closest("#floatKbClose")) return;
      dragging = true;
      const rect = floatKeyboard.getBoundingClientRect();
      offX = e.clientX - rect.left;
      offY = e.clientY - rect.top;
      floatKeyboard.style.transform = "none";
      floatKeyboard.style.left = rect.left + "px";
      floatKeyboard.style.top = rect.top + "px";
      floatKeyboard.style.bottom = "auto";
      floatKbBar.setPointerCapture(e.pointerId);
    });
    floatKbBar.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      let x = e.clientX - offX, y = e.clientY - offY;
      x = Math.max(0, Math.min(window.innerWidth - floatKeyboard.offsetWidth, x));
      y = Math.max(0, Math.min(window.innerHeight - floatKeyboard.offsetHeight, y));
      floatKeyboard.style.left = x + "px";
      floatKeyboard.style.top = y + "px";
    });
    const stop = () => { dragging = false; };
    floatKbBar.addEventListener("pointerup", stop);
    floatKbBar.addEventListener("pointercancel", stop);
  })();

  // Cualquier pointerdown que caiga en el area del teclado (tecla, gap o
  // fondo del panel) NO debe robar el foco del input que estamos editando.
  // El navegador, al recibir un pointerdown en un area NO interactiva (un
  // hueco entre teclas, el padding del panel, etc.), puede decidir mover el
  // foco o dispar un blur del input activo, y eso es lo que hacia que al
  // escribir se "saliera" del texto. Excluimos la barra (para no interferir
  // con el drag) y el boton X (que tiene su propio onclick).
  const swallow = (e) => {
    if (e.target.closest("#floatKbClose")) return;
    if (e.target.closest("#floatKbBar")) return;
    e.preventDefault();
  };
  floatKbKeys.addEventListener("pointerdown", swallow);
  floatKbKeys.addEventListener("mousedown", swallow);
  floatKbKeys.addEventListener("touchstart", swallow, { passive: false });

  buildFloatKeyboard();

  // Campos de nombre (modales) que usan el teclado flotante
  [newFileName, mfName].forEach((inp) => {
    inp.addEventListener("focus", () => showFloatKeyboard(inp));
  });

  /* ---------- WiFi ---------- */
  btnWifi.onclick = () => {
    wifiError.textContent = "";
    openModal(wifiModal);
    refreshWifiStatus();
    scanWifi();
  };
  btnCloseWifi.onclick = () => { closeModal(wifiModal); hideFloatKeyboard(); };
  btnWifiScan.onclick = scanWifi;

  async function refreshWifiStatus() {
    try {
      const s = await (await fetch("/api/wifi/status")).json();
      wifiCurrent.textContent = s.ssid
        ? "Conectado a: " + s.ssid + (s.ip ? " (" + s.ip + ")" : "")
        : "Sin red WiFi";
    } catch (e) { /* noop */ }
  }

  async function scanWifi() {
    wifiList.innerHTML = '<div class="wifi-loading">Buscando redes…</div>';
    let nets;
    try { nets = await (await fetch("/api/wifi/scan")).json(); }
    catch (e) { wifiList.innerHTML = '<div class="wifi-loading">No se pudo buscar redes.</div>'; return; }
    renderWifiList(nets);
  }

  function renderWifiList(nets) {
    wifiList.innerHTML = "";
    if (!nets || nets.length === 0) {
      wifiList.innerHTML = '<div class="wifi-loading">No se encontraron redes.</div>';
      return;
    }
    nets.forEach((n) => {
      const row = document.createElement("div");
      row.className = "wifi-row";
      const lock = n.secure ? "🔒 " : "";
      row.innerHTML = `<span class="wifi-ssid">${lock}${esc(n.ssid)}</span><span class="wifi-sig">${n.signal}%</span>`;
      row.onclick = () => connectToNetwork(n);
      wifiList.appendChild(row);
    });
  }

  function connectToNetwork(n) {
    if (n.secure) {
      openPrompt("Contraseña de " + n.ssid, [{ id: "pass", label: "Contraseña" }], (v) => {
        if (!v.pass) return "Escribe la contraseña";
        doWifiConnect(n.ssid, v.pass);
      });
    } else {
      doWifiConnect(n.ssid, "");
    }
  }

  async function doWifiConnect(ssid, password) {
    wifiError.textContent = "Conectando a " + ssid + "…";
    let data;
    try {
      const res = await fetch("/api/wifi/connect", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ssid, password }),
      });
      data = await res.json();
    } catch (e) { wifiError.textContent = "No se pudo conectar (sin respuesta)"; return; }
    if (!data.ok) { wifiError.textContent = data.error || "No se pudo conectar"; return; }
    wifiError.textContent = "Conectado ✓";
    refreshWifiStatus();
  }

  /* ---------- Arranque ---------- */
  loadDir("");
  poll();
  setInterval(poll, POLL_MS);
})();
