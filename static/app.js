"use strict";
const $ = (selector) => document.querySelector(selector);
const state = {
  mode: "hybrid",
  document: null,
  page: 1,
  boxes: [],
  selectedResult: null,
  uploadBusy: false,
  searchBusy: false,
  searchVersion: 0,
  searchController: null,
  previewVersion: 0,
};
const searchModes = {
  hybrid: {
    label: "Híbrida",
    hint: "Combina significado e palavras para encontrar trechos relevantes.",
  },
  semantic: {
    label: "Por significado",
    hint: "Encontra ideias próximas, além de palavras iguais.",
  },
  tfidf: {
    label: "Por palavras",
    hint: "Compara palavras e verifica a relação com a consulta completa.",
  },
};
const icon = (name, extra = "") => {
  const element = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  element.setAttribute("class", `icon ${extra}`);
  element.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(element.namespaceURI, "use");
  use.setAttribute("href", `#i-${name}`);
  element.append(use);
  return element;
};
const el = (tag, className, text) => {
  const element = document.createElement(tag);
  element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
};
function notice(message, type = "") {
  const node = $("#notice");
  node.textContent = message;
  node.className = `notice ${type}`;
  node.hidden = !message;
  node.setAttribute("role", type === "error" ? "alert" : "status");
}
async function request(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let body;
    try {
      body = await response.json();
    } catch {
      body = {};
    }
    const message =
      typeof body.detail === "string"
        ? body.detail
        : response.status === 422
          ? "Confira a consulta e os limites do arquivo."
          : "Não foi possível concluir a operação.";
    throw new Error(message);
  }
  return response;
}
async function loadLibrary() {
  const documents = await (await request("/documents")).json();
  $("#nav-count").textContent = $("#library-count").textContent =
    documents.length;
  if (!documents.length) return;
  const list = $("#document-list");
  list.replaceChildren();
  for (const doc of documents) {
    const row = el("button", "document-row");
    row.type = "button";
    row.dataset.id = doc.id;
    row.classList.toggle("selected", state.document?.id === doc.id);
    const image = el("span", "document-icon");
    image.append(icon("file"));
    const info = el("span", "document-info");
    const title = el("span", "document-title", doc.filename);
    title.title = doc.filename;
    info.append(
      title,
      el(
        "span",
        "document-meta",
        `${doc.page_count} ${doc.page_count === 1 ? "página" : "páginas"} · ${new Date(doc.created_at).toLocaleDateString("pt-BR")}`,
      ),
    );
    const ready = el("span", "document-ready");
    ready.append(icon("check"), document.createTextNode("Texto indexado"));
    info.append(ready);
    row.append(image, info);
    row.addEventListener("click", () => openDocument(doc.id));
    list.append(row);
  }
}
async function upload(file) {
  if (!file || state.uploadBusy) return;
  if (!/\.(png|jpe?g|pdf)$/i.test(file.name))
    return notice("Escolha um arquivo PNG, JPEG ou PDF.", "error");
  if (file.size > 10 * 1024 * 1024)
    return notice("O arquivo excede o limite de 10 MB.", "error");
  state.uploadBusy = true;
  $("#upload-button").disabled = $("#demo-button").disabled = true;
  $("#dropzone").setAttribute("aria-busy", "true");
  notice(
    `Processando ${file.name}. O OCR em CPU pode levar alguns minutos.`,
    "busy",
  );
  try {
    const body = new FormData();
    body.append("file", file);
    const doc = await (
      await request("/documents", { method: "POST", body })
    ).json();
    await loadLibrary();
    await openDocument(doc.id);
    notice(
      `${doc.filename} está pronto para busca. Processado em ${doc.duration_seconds.toFixed(1).replace(".", ",")} s.`,
    );
    if ($("#query").value.trim()) await search();
  } catch (error) {
    notice(
      error.message || "Verifique a conexão com a aplicação local.",
      "error",
    );
  } finally {
    state.uploadBusy = false;
    $("#upload-button").disabled = $("#demo-button").disabled = false;
    $("#dropzone").setAttribute("aria-busy", "false");
    $("#file-input").value = "";
  }
}
async function openDocument(id, page = 1, boxes = [], resultId = null) {
  const version = ++state.previewVersion;
  try {
    const doc = await (await request(`/documents/${id}`)).json();
    if (version !== state.previewVersion) return;
    state.document = doc;
    state.page = page;
    state.boxes = boxes;
    state.selectedResult = resultId;
    $("#preview-empty").hidden = true;
    $("#preview-content").hidden = false;
    $("#preview-subtitle").textContent = doc.filename;
    $("#processing-time").textContent =
      `${doc.duration_seconds.toFixed(1).replace(".", ",")} s · ${doc.preprocess ? "Imagem tratada" : "Imagem original"}`;
    const select = $("#page-select");
    select.replaceChildren();
    for (const p of doc.pages) {
      const option = el("option", "", `${p.number} de ${doc.page_count}`);
      option.value = p.number;
      select.append(option);
    }
    select.value = page;
    for (const row of document.querySelectorAll(".document-row"))
      row.classList.toggle("selected", row.dataset.id === id);
    for (const card of document.querySelectorAll(".result-card"))
      card.classList.toggle("selected", card.dataset.id === resultId);
    renderPage();
  } catch (error) {
    if (version === state.previewVersion) notice(error.message, "error");
  }
}
function renderPage() {
  const page = state.document.pages.find((p) => p.number === state.page);
  const image = $("#page-image");
  image.width = page.width;
  image.height = page.height;
  image.src = page.image_url;
  image.alt = `${state.document.filename}, página ${page.number}`;
  $("#extracted-text").textContent =
    page.text || "Nenhum texto reconhecido nesta página.";
  const overlay = $("#highlights");
  overlay.replaceChildren();
  overlay.setAttribute("viewBox", `0 0 ${page.width} ${page.height}`);
  for (const box of state.boxes) {
    const polygon = document.createElementNS(overlay.namespaceURI, "polygon");
    polygon.setAttribute(
      "points",
      box.map((point) => point.join(",")).join(" "),
    );
    overlay.append(polygon);
  }
  $(".page-scroll").scrollTop = 0;
}
function clearHighlights() {
  state.boxes = [];
  state.selectedResult = null;
  for (const card of document.querySelectorAll(".result-card"))
    card.classList.remove("selected");
  if (state.document) renderPage();
}
function setSearchBusy(busy) {
  state.searchBusy = busy;
  $("#search-button").disabled = busy;
  $("#results").setAttribute("aria-busy", String(busy));
  for (const button of document.querySelectorAll(".mode"))
    button.disabled = busy;
}
function cancelSearch() {
  ++state.searchVersion;
  ++state.previewVersion;
  state.searchController?.abort();
  state.searchController = null;
  clearHighlights();
  setSearchBusy(false);
}
function renderSearchSummary(data, query, method) {
  $("#result-count").textContent =
    `${data.results.length} ${data.results.length === 1 ? "trecho" : "trechos"}`;
  $("#results-subtitle").textContent =
    `“${query}” · ${searchModes[method].label}`;
  if (data.interpreted_query && data.interpreted_query !== query) {
    const note = el("span", "query-adjustment", `Busca ajustada: “${data.interpreted_query}”.`);
    if (data.excluded_terms?.length)
      note.append(document.createTextNode(` Tema excluído: ${data.excluded_terms.join(", ")}.`));
    $("#results-subtitle").append(note);
  }
}

function createEmptyResults(method) {
  const empty = el("div", "empty result-empty");
  const image = el("div", "empty-icon");
  image.append(icon("search"));
  empty.append(
    image,
    el("strong", "", "Nenhum trecho encontrado"),
    el(
      "p",
      "",
      method === "tfidf"
        ? "Não encontramos palavras relacionadas à consulta em um trecho relevante. Experimente termos do documento ou use a busca híbrida."
        : "Não encontramos um trecho com relação suficiente à consulta. Tente detalhar o assunto ou adicionar o documento correspondente.",
    ),
  );
  return empty;
}

function createResultCard(hit, method) {
  const card = el("button", "result-card");
  card.type = "button";
  card.dataset.id = hit.id;
  const top = el("div", "result-top");
  const filename = el("span", "result-filename", hit.filename);
  filename.title = hit.filename;
  top.append(
    icon("file"),
    filename,
    el(
      "span",
      "result-score",
      method === "hybrid"
        ? `Pontuação ${hit.score.toFixed(4).replace(".", ",")}`
        : `Similaridade ${hit.score.toFixed(2).replace(".", ",")}`,
    ),
  );
  top.lastElementChild.title =
    method === "hybrid"
      ? "Pontuação de combinação das duas buscas, com ajuste de relevância. Não representa probabilidade de acerto."
      : "Similaridade do trecho com a consulta. Não representa probabilidade de acerto.";
  const bottom = el("div", "result-bottom");
  bottom.append(
    el("span", "", `Página ${hit.page} · Ver na fonte`),
    icon("arrow"),
  );
  card.append(top, el("p", "result-snippet", hit.text), bottom);
  card.addEventListener("click", () =>
    openDocument(hit.document_id, hit.page, hit.boxes, hit.id),
  );
  return card;
}

async function search() {
  const query = $("#query").value.trim();
  if (!query) {
    cancelSearch();
    notice("Digite o assunto que deseja encontrar.", "error");
    $("#query").focus();
    return;
  }
  const version = ++state.searchVersion;
  state.searchController?.abort();
  const controller = new AbortController();
  state.searchController = controller;
  const previewVersion = ++state.previewVersion;
  clearHighlights();
  if ($("#notice").classList.contains("error")) notice("");
  const method = state.mode;
  setSearchBusy(true);
  try {
    const data = await (
      await request("/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, method, top_k: 5 }),
        signal: controller.signal,
      })
    ).json();
    if (version !== state.searchVersion) return;
    const results = $("#results");
    results.replaceChildren();
    renderSearchSummary(data, query, method);
    if (!data.results.length) {
      // Uma busca sem resposta também precisa remover o destaque da busca anterior.
      if (previewVersion === state.previewVersion) clearHighlights();
      results.append(createEmptyResults(method));
      return;
    }
    for (const hit of data.results) {
      results.append(createResultCard(hit, method));
    }
    const first = data.results[0];
    if (previewVersion === state.previewVersion)
      await openDocument(first.document_id, first.page, first.boxes, first.id);
  } catch (error) {
    if (version !== state.searchVersion || error.name === "AbortError") return;
    notice(
      error.message || "Verifique a conexão com a aplicação local.",
      "error",
    );
  } finally {
    if (version === state.searchVersion) {
      state.searchController = null;
      setSearchBusy(false);
    }
  }
}
$("#upload-button").addEventListener("click", () => $("#file-input").click());
$("#file-input").addEventListener("change", (event) =>
  upload(event.target.files[0]),
);
$("#demo-button").addEventListener("click", async () => {
  try {
    const response = await request("/example");
    await upload(
      new File([await response.blob()], "manutencao_01.png", {
        type: "image/png",
      }),
    );
  } catch (error) {
    notice(error.message, "error");
  }
});
$("#search-form").addEventListener("submit", (event) => {
  event.preventDefault();
  search();
});
$("#query").addEventListener("input", () => {
  if (state.searchBusy) cancelSearch();
});
for (const button of document.querySelectorAll(".mode"))
  button.addEventListener("click", () => {
    state.mode = button.dataset.mode;
    for (const item of document.querySelectorAll(".mode")) {
      item.classList.toggle("active", item === button);
      item.setAttribute("aria-pressed", item === button ? "true" : "false");
    }
    $("#method-hint").textContent = searchModes[state.mode].hint;
    if ($("#query").value.trim()) search();
  });
for (const button of document.querySelectorAll("[data-query]"))
  button.addEventListener("click", () => {
    $("#query").value = button.dataset.query;
    search();
  });
$("#page-select").addEventListener("change", (event) => {
  ++state.previewVersion;
  state.page = Number(event.target.value);
  state.boxes = [];
  renderPage();
});
const dropzone = $("#dropzone");
dropzone.addEventListener("dragover", (event) => {
  event.preventDefault();
  dropzone.classList.add("dragging");
});
dropzone.addEventListener("dragleave", (event) => {
  if (!dropzone.contains(event.relatedTarget))
    dropzone.classList.remove("dragging");
});
dropzone.addEventListener("drop", (event) => {
  event.preventDefault();
  dropzone.classList.remove("dragging");
  if (event.dataTransfer.files.length > 1)
    return notice("Adicione um documento por vez.", "error");
  upload(event.dataTransfer.files[0]);
});
loadLibrary().catch(() =>
  notice(
    "Não foi possível acessar a aplicação local. Verifique o terminal.",
    "error",
  ),
);
