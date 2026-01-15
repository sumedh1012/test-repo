(function () {
  const jobId = window.PDFKIT_JOB_ID;

  const pageSelect = document.getElementById("pageSelect");
  const pageImgs = [...document.querySelectorAll(".pageImg")];

  const overlayBox = document.getElementById("overlayBox");

  const modeTextBtn = document.getElementById("modeText");
  const modeImageBtn = document.getElementById("modeImage");
  const modeRedactBtn = document.getElementById("modeRedact");

  const textValue = document.getElementById("textValue");
  const textSize = document.getElementById("textSize");
  const textColor = document.getElementById("textColor");

  const imgFile = document.getElementById("imgFile");
  const imgW = document.getElementById("imgW");
  const imgH = document.getElementById("imgH");

  const opsCount = document.getElementById("opsCount");
  const clearOpsBtn = document.getElementById("clearOpsBtn");
  const saveBtn = document.getElementById("saveBtn");
  const downloadLink = document.getElementById("downloadLink");

  let mode = "text"; // text | image | redact
  let ops = [];

  function setMode(m) {
    mode = m;
    modeTextBtn.classList.toggle("secondary", mode !== "text");
    modeImageBtn.classList.toggle("secondary", mode !== "image");
    modeRedactBtn.classList.toggle("secondary", mode !== "redact");
  }

  modeTextBtn.addEventListener("click", () => setMode("text"));
  modeImageBtn.addEventListener("click", () => setMode("image"));
  modeRedactBtn.addEventListener("click", () => setMode("redact"));
  setMode("text");

  function getActiveImg() {
    const idx = String(pageSelect.value);
    return document.getElementById(`pageImg-${idx}`);
  }

  function showActivePage() {
    const idx = String(pageSelect.value);
    pageImgs.forEach(img => {
      img.style.display = (img.dataset.pageIndex === idx) ? "block" : "none";
    });
  }

  pageSelect.addEventListener("change", showActivePage);
  showActivePage();

  function updateOpsCount() {
    opsCount.textContent = `Pending ops: ${ops.length}`;
  }
  updateOpsCount();

  clearOpsBtn.addEventListener("click", () => {
    ops = [];
    updateOpsCount();
    downloadLink.style.display = "none";
  });

  // CSRF helper (Django docs pattern)
  function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== "") {
      const cookies = document.cookie.split(";");
      for (let i = 0; i < cookies.length; i++) {
        const cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === (name + "=")) {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
    }
    return cookieValue;
  }

  function clickToPdfCoords(img, clientX, clientY) {
    const rect = img.getBoundingClientRect();
    const xOnImg = clientX - rect.left;
    const yOnImg = clientY - rect.top;

    const pageW = parseFloat(img.dataset.pageWidth);
    const pageH = parseFloat(img.dataset.pageHeight);

    const x = (xOnImg / rect.width) * pageW;
    const y = (yOnImg / rect.height) * pageH;

    return { x, y, rect };
  }

  // Add text / image on click
  pageImgs.forEach(img => {
    img.addEventListener("click", async (e) => {
      if (mode === "redact") return;

      const { x, y } = clickToPdfCoords(img, e.clientX, e.clientY);
      const page = parseInt(img.dataset.pageIndex, 10);

      if (mode === "text") {
        const t = (textValue.value || "").trim();
        if (!t) return;
        ops.push({
          type: "add_text",
          page,
          x, y,
          text: t,
          size: parseFloat(textSize.value || "18"),
          color: textColor.value || "#000000",
        });
        updateOpsCount();
        downloadLink.style.display = "none";
      }

      if (mode === "image") {
        const file = imgFile.files && imgFile.files[0];
        if (!file) return;

        const dataUrl = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result));
          reader.onerror = reject;
          reader.readAsDataURL(file);
        });

        ops.push({
          type: "add_image",
          page,
          x, y,
          w: parseFloat(imgW.value || "220"),
          h: parseFloat(imgH.value || "160"),
          dataUrl
        });
        updateOpsCount();
        downloadLink.style.display = "none";
      }
    });
  });

  // Redaction by drag rectangle
  let drag = null;

  function showOverlay(img, x0, y0, x1, y1) {
    const container = img.parentElement; // canvasWrap padding affects overlay positioning; use bounding client rects
    const imgRect = img.getBoundingClientRect();
    const cRect = container.getBoundingClientRect();

    const left = Math.min(x0, x1);
    const top = Math.min(y0, y1);
    const width = Math.abs(x1 - x0);
    const height = Math.abs(y1 - y0);

    overlayBox.style.display = "block";
    overlayBox.style.left = (left - cRect.left) + "px";
    overlayBox.style.top = (top - cRect.top) + "px";
    overlayBox.style.width = width + "px";
    overlayBox.style.height = height + "px";
  }

  function hideOverlay() {
    overlayBox.style.display = "none";
  }

  pageImgs.forEach(img => {
    img.addEventListener("mousedown", (e) => {
      if (mode !== "redact") return;
      e.preventDefault();

      drag = {
        img,
        startX: e.clientX,
        startY: e.clientY,
      };
      showOverlay(img, drag.startX, drag.startY, e.clientX, e.clientY);
    });

    img.addEventListener("mousemove", (e) => {
      if (!drag || mode !== "redact") return;
      showOverlay(drag.img, drag.startX, drag.startY, e.clientX, e.clientY);
    });

    window.addEventListener("mouseup", (e) => {
      if (!drag || mode !== "redact") return;

      const img = drag.img;
      const page = parseInt(img.dataset.pageIndex, 10);

      const a = clickToPdfCoords(img, drag.startX, drag.startY);
      const b = clickToPdfCoords(img, e.clientX, e.clientY);

      const x = a.x;
      const y = a.y;
      const w = b.x - a.x;
      const h = b.y - a.y;

      hideOverlay();
      drag = null;

      // Ignore tiny drags
      if (Math.abs(w) < 2 || Math.abs(h) < 2) return;

      ops.push({ type: "redact", page, x, y, w, h });
      updateOpsCount();
      downloadLink.style.display = "none";
    });
  });

  saveBtn.addEventListener("click", async () => {
    if (ops.length === 0) return;

    saveBtn.disabled = true;
    saveBtn.textContent = "Saving...";

    try {
      const res = await fetch(`/edit/${jobId}/apply/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCookie("csrftoken"),
        },
        body: JSON.stringify({ ops }),
      });

      const data = await res.json();
      if (!data.ok) {
        alert(data.error || "Failed");
        return;
      }

      downloadLink.href = data.download_url;
      downloadLink.style.display = "inline-block";
      ops = [];
      updateOpsCount();
    } catch (err) {
      alert("Error saving edits.");
    } finally {
      saveBtn.disabled = false;
      saveBtn.textContent = "Save PDF";
    }
  });
})();