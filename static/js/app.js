(function () {
  const POLL_MS = 1000;

  const screens = {
    noUsb: document.getElementById("screen-no-usb"),
    selectMachine: document.getElementById("screen-select-machine"),
    main: document.getElementById("screen-main"),
  };

  const usbDot = document.getElementById("usbDot");
  const usbLabel = document.getElementById("usbLabel");
  const usbDeviceLabel = document.getElementById("usbDeviceLabel");
  const machineGrid = document.getElementById("machineGrid");
  const fileList = document.getElementById("fileList");
  const activeMachineName = document.getElementById("activeMachineName");
  const activeMachineParams = document.getElementById("activeMachineParams");
  const selectedFileName = document.getElementById("selectedFileName");
  const btnSend = document.getElementById("btnSend");
  const btnChangeMachine = document.getElementById("btnChangeMachine");
  const transferBox = document.getElementById("transferBox");
  const transferTitle = document.getElementById("transferTitle");
  const transferDetail = document.getElementById("transferDetail");
  const progressFill = document.getElementById("progressFill");

  const confirmModal = document.getElementById("confirmModal");
  const confirmText = document.getElementById("confirmText");
  const btnCancelSend = document.getElementById("btnCancelSend");
  const btnConfirmSend = document.getElementById("btnConfirmSend");

  let selectedFile = null;
  let lastFileNames = "";
  let lastMachinesJson = "";
  let sending = false;

  function showScreen(name) {
    Object.values(screens).forEach((el) => el.classList.remove("active"));
    screens[name].classList.add("active");
  }

  function formatSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function machineParamsLabel(m) {
    const flow = m.flow_control === "xonxoff" ? "XON/XOFF" : "RTS/CTS";
    const term = m.line_terminator === "CRLF" ? "CR+LF" : m.line_terminator;
    return `${m.baudrate} baud · ${m.bytesize}${m.parity}${m.stopbits} · ${flow} · ${term}`;
  }

  function renderMachineGrid(machines) {
    const json = JSON.stringify(machines);
    if (json === lastMachinesJson) return;
    lastMachinesJson = json;

    machineGrid.innerHTML = "";
    machines.forEach((m) => {
      const btn = document.createElement("button");
      btn.className = "machine-btn";
      btn.innerHTML = `<span>${m.name}</span><span class="machine-btn-sub">${machineParamsLabel(m)}</span>`;
      btn.addEventListener("click", () => selectMachine(m.id));
      machineGrid.appendChild(btn);
    });
  }

  function renderFileList(files) {
    const names = files.map((f) => f.name).join("|");
    if (names === lastFileNames) return;
    lastFileNames = names;

    if (selectedFile && !files.some((f) => f.name === selectedFile)) {
      selectedFile = null;
    }

    fileList.innerHTML = "";
    if (files.length === 0) {
      const empty = document.createElement("div");
      empty.className = "empty-hint";
      empty.textContent = "No hay archivos en la carpeta compartida todavia.";
      fileList.appendChild(empty);
    } else {
      files.forEach((f) => {
        const row = document.createElement("div");
        row.className = "file-row" + (f.name === selectedFile ? " selected" : "");
        row.innerHTML = `<span class="file-name">${f.name}</span><span class="file-size">${formatSize(f.size)}</span>`;
        row.addEventListener("click", () => {
          selectedFile = f.name;
          updateSelectedFileUi();
          renderFileListSelection();
        });
        fileList.appendChild(row);
      });
    }
    updateSelectedFileUi();
  }

  function renderFileListSelection() {
    document.querySelectorAll(".file-row").forEach((row) => {
      const name = row.querySelector(".file-name").textContent;
      row.classList.toggle("selected", name === selectedFile);
    });
  }

  function updateSelectedFileUi() {
    selectedFileName.textContent = selectedFile || "Ninguno";
    btnSend.disabled = !selectedFile || sending;
  }

  function renderTransfer(t) {
    sending = t.status === "sending";
    updateSelectedFileUi();

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
      transferTitle.textContent = `Envio completado: ${t.filename}`;
      transferDetail.textContent = t.message || "Transferencia exitosa";
    } else if (t.status === "error") {
      transferBox.classList.add("error");
      transferTitle.textContent = `Error enviando ${t.filename || ""}`;
      transferDetail.textContent = t.message || "Ocurrio un error";
    }
  }

  function render(state) {
    renderTransfer(state.transfer);

    if (!state.usb_connected) {
      usbDot.classList.remove("connected");
      usbLabel.textContent = "Sin adaptador";
      showScreen("noUsb");
      return;
    }

    usbDot.classList.add("connected");

    if (state.awaiting_machine || !state.active_machine) {
      usbLabel.textContent = state.usb_device;
      usbDeviceLabel.textContent = `Adaptador detectado en ${state.usb_device}`;
      renderMachineGrid(state.machines);
      showScreen("selectMachine");
      return;
    }

    usbLabel.textContent = `${state.usb_device} · ${state.active_machine.name}`;
    activeMachineName.textContent = state.active_machine.name;
    activeMachineParams.textContent = machineParamsLabel(state.active_machine);
    renderFileList(state.files);
    showScreen("main");
  }

  async function poll() {
    try {
      const res = await fetch("/api/state");
      const data = await res.json();
      render(data);
    } catch (e) {
      usbLabel.textContent = "Sin conexion al backend";
    }
  }

  async function selectMachine(id) {
    await fetch("/api/machine/select", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    lastFileNames = "";
    poll();
  }

  btnChangeMachine.addEventListener("click", async () => {
    await fetch("/api/machine/clear", { method: "POST" });
    lastMachinesJson = "";
    poll();
  });

  btnSend.addEventListener("click", () => {
    if (!selectedFile) return;
    confirmText.textContent = `¿Enviar "${selectedFile}" a la maquina activa? Esto transmitira el programa por el puerto serial.`;
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
      body: JSON.stringify({ filename: selectedFile }),
    });
    const data = await res.json();
    if (!data.ok) {
      alert(data.error || "No se pudo iniciar el envio");
    }
    poll();
  });

  poll();
  setInterval(poll, POLL_MS);
})();
