(function () {
  const POLL_MS = 1000;

  const usbDot = document.getElementById("usbDot");
  const usbLabel = document.getElementById("usbLabel");
  const breadcrumbEl = document.getElementById("breadcrumb");
  const browserEl = document.getElementById("browser");
  const contentHeader = document.getElementById("contentHeader");
  const contentView = document.getElementById("contentView");
  const alarm = document.getElementById("alarm");
  const alarmIcon = document.getElementById("alarmIcon");
  const alarmText = document.getElementById("alarmText");
  const machineList = document.getElementById("machineList");
  const selectedFileName = document.getElementById("selectedFileName");
  const btnSend = document.getElementById("btnSend");
  const sendHint = document.getElementById("sendHint");
  const transferBox = document.getElementById("transferBox");
  const transferTitle = document.getElementById("transferTitle");
  const transferDetail = document.getElementById("transferDetail");
  const progressFill = document.getElementById("progressFill");

  const confirmModal = document.getElementById("confirmModal");
  const confirmText = document.getElementById("confirmText");
  const btnCancelSend = document.getElementById("btnCancelSend");
  const btnConfirmSend = document.getElementById("btnConfirmSend");

  let currentPath = "";
  let selectedFile = null;        // {path, name}
  let selectedMachineId = null;
  let usbConnected = false;
  let sending = false;
  let lastFilesVersion = -1;
  let lastMachinesJson = "";

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

  /* ---------- Explorador (columna izquierda) ---------- */
  async function loadDir(path) {
    let data;
    try {
      const res = await fetch("/api/files?path=" + encodeURIComponent(path));
      data = await res.json();
    } catch (e) {
      return;
    }
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
      if (i !== crumbs.length - 1) {
        btn.addEventListener("click", () => loadDir(c.path));
      }
      breadcrumbEl.appendChild(btn);
    });
  }

  function renderBrowser(data) {
    browserEl.innerHTML = "";

    if (data.dirs.length === 0 && data.files.length === 0) {
      const empty = document.createElement("div");
      empty.className = "empty-hint";
      empty.textContent = "Carpeta vacía.";
      browserEl.appendChild(empty);
      return;
    }

    data.dirs.forEach((d) => {
      const row = document.createElement("div");
      row.className = "entry";
      row.innerHTML = `<span class="icon">📁</span><span class="entry-name">${d.name}</span><span class="icon">›</span>`;
      row.addEventListener("click", () => loadDir(d.path));
      browserEl.appendChild(row);
    });

    data.files.forEach((f) => {
      const row = document.createElement("div");
      row.className = "entry" + (selectedFile && selectedFile.path === f.path ? " selected" : "");
      row.innerHTML = `<span class="icon">📄</span><span class="entry-name">${f.name}</span><span class="entry-size">${formatSize(f.size)}</span>`;
      row.addEventListener("click", () => selectFile(f));
      browserEl.appendChild(row);
    });
  }

  function markSelectedInBrowser() {
    browserEl.querySelectorAll(".entry").forEach((row) => {
      const nameEl = row.querySelector(".entry-name");
      const isFile = row.querySelector(".icon").textContent === "📄";
      const match = isFile && selectedFile && nameEl.textContent === selectedFile.name;
      row.classList.toggle("selected", !!match);
    });
  }

  /* ---------- Contenido (columna centro) ---------- */
  async function selectFile(f) {
    selectedFile = { path: f.path, name: f.name };
    updateSelectedFileUi();
    markSelectedInBrowser();
    await loadContent();
  }

  async function loadContent() {
    if (!selectedFile) {
      contentHeader.textContent = "Contenido";
      contentView.innerHTML = '<span class="placeholder">Toca un programa de la izquierda para ver su contenido.</span>';
      return;
    }
    try {
      const res = await fetch("/api/file?path=" + encodeURIComponent(selectedFile.path));
      if (!res.ok) {
        contentHeader.textContent = selectedFile.name;
        contentView.innerHTML = '<span class="placeholder">El archivo ya no está disponible.</span>';
        return;
      }
      const data = await res.json();
      contentHeader.textContent = data.name;
      contentView.textContent = data.content;
      if (data.truncated) {
        const note = document.createElement("div");
        note.className = "truncated-note";
        note.textContent = "\n… (vista recortada, el archivo se enviará completo)";
        contentView.appendChild(note);
      }
    } catch (e) {
      /* silencioso: se reintenta en el siguiente ciclo si aplica */
    }
  }

  function updateSelectedFileUi() {
    selectedFileName.textContent = selectedFile ? selectedFile.name : "Ninguno";
    updateSendButton();
  }

  /* ---------- Maquinas (columna derecha) ---------- */
  function renderMachines(machines) {
    const json = JSON.stringify(machines);
    if (json !== lastMachinesJson) {
      lastMachinesJson = json;
      machineList.innerHTML = "";
      machines.forEach((m) => {
        const btn = document.createElement("button");
        btn.className = "machine-btn";
        btn.dataset.id = m.id;
        btn.innerHTML = `<span class="machine-name">${m.name}</span><span class="machine-sub">${machineSubLabel(m)}</span>`;
        btn.addEventListener("click", () => selectMachine(m.id));
        machineList.appendChild(btn);
      });
    }
    machineList.querySelectorAll(".machine-btn").forEach((btn) => {
      btn.classList.toggle("selected", btn.dataset.id === selectedMachineId);
    });
  }

  async function selectMachine(id) {
    await fetch("/api/machine/select", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    selectedMachineId = id;
    renderMachines(JSON.parse(lastMachinesJson || "[]"));
    updateSendButton();
  }

  /* ---------- Alarma / estado de conexion ---------- */
  function renderConnection(state) {
    usbConnected = state.usb_connected;
    if (usbConnected) {
      usbDot.classList.add("connected");
      usbLabel.textContent = state.usb_device;
      alarm.classList.add("ok");
      alarmIcon.textContent = "✓";
      alarmText.textContent = "Cable RS232 conectado (" + state.usb_device + ")";
    } else {
      usbDot.classList.remove("connected");
      usbLabel.textContent = "Sin adaptador";
      alarm.classList.remove("ok");
      alarmIcon.textContent = "⚠";
      alarmText.textContent = "Cable RS232 no conectado";
    }
  }

  /* ---------- Boton enviar ---------- */
  function updateSendButton() {
    let hint = "";
    if (!selectedFile) hint = "Selecciona un programa";
    else if (!selectedMachineId) hint = "Selecciona una máquina";
    else if (!usbConnected) hint = "Conecta el cable RS232";
    else if (sending) hint = "Transferencia en curso...";

    btnSend.disabled = !(selectedFile && selectedMachineId && usbConnected && !sending);
    sendHint.textContent = hint;
  }

  /* ---------- Transferencia ---------- */
  function renderTransfer(t) {
    sending = t.status === "sending";
    updateSendButton();

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

  /* ---------- Polling de estado ---------- */
  async function poll() {
    let state;
    try {
      const res = await fetch("/api/state");
      state = await res.json();
    } catch (e) {
      usbLabel.textContent = "Sin conexión al backend";
      return;
    }

    renderConnection(state);
    renderMachines(state.machines);
    if (state.active_machine_id !== selectedMachineId && state.active_machine_id) {
      selectedMachineId = state.active_machine_id;
      renderMachines(state.machines);
    }
    renderTransfer(state.transfer);

    if (state.files_version !== lastFilesVersion) {
      lastFilesVersion = state.files_version;
      await loadDir(currentPath);
      if (selectedFile) await loadContent();
    }
  }

  /* ---------- Envio con confirmacion ---------- */
  btnSend.addEventListener("click", () => {
    if (btnSend.disabled) return;
    confirmText.textContent = `¿Enviar "${selectedFile.name}" a la máquina seleccionada? Esto transmitirá el programa por el puerto serial.`;
    confirmModal.classList.add("visible");
  });

  btnCancelSend.addEventListener("click", () => {
    confirmModal.classList.remove("visible");
  });

  btnConfirmSend.addEventListener("click", async () => {
    confirmModal.classList.remove("visible");
    const res = await fetch("/api/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: selectedFile.path }),
    });
    const data = await res.json();
    if (!data.ok) {
      alert(data.error || "No se pudo iniciar el envío");
    }
    poll();
  });

  /* ---------- Arranque ---------- */
  loadDir("");
  poll();
  setInterval(poll, POLL_MS);
})();
