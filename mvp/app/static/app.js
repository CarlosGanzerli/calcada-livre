"use strict";
// Tipos de barreira do MVP. O modelo de visão detecta buraco, obstáculo e piso quebrado;
// "piso quebrado" entra na API como "outro", com o nome no começo da descrição.
const ROTULO = {
  buraco: "Buraco", obstaculo: "Obstáculo", piso_quebrado: "Piso quebrado", degrau: "Degrau",
  sem_rampa: "Falta de rampa", calcada_estreita: "Calçada estreita", trecho_escuro: "Trecho escuro", outro: "Outro",
};
const COR = { buraco: "#b42318", obstaculo: "#b54708", piso_quebrado: "#6941c6" };
const COR_OUTROS = "#6a6e70";
const SITUACAO = {
  nova: "Aguardando triagem", validada: "Validada", quarentena: "Em quarentena",
  duplicada: "Duplicada", encaminhada: "Encaminhada", resolvida: "Resolvida",
};
const PRIORIDADE = { alta: "Alta", media: "Média", baixa: "Baixa" };
const ORIGEM = { app: "Cidadão", carrinho: "Carrinho", visao: "Visão computacional" };
const ORIGEM_CURTA = { ...ORIGEM, visao: "Visão" };
const FOTO_MAX = 10 * 1024 * 1024;
const VIDEO_MAX = 50 * 1024 * 1024;
// Limites aproximados do município de São Paulo, os mesmos da triagem.
const SP = { latMin: -24.01, latMax: -23.35, lonMin: -46.83, lonMax: -46.36 };

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (v) => `${Math.round(v * 100)}%`;
const tipoDe = (o) => (o.tipo === "outro" && /^Piso quebrado\b/.test(o.descricao || "") ? "piso_quebrado" : o.tipo);
const classeSelo = (tipo) => (COR[tipo] ? tipo : "neutro");
const selo = (tipo) => `<span class="selo ${classeSelo(tipo)}">${esc(ROTULO[tipo] || tipo)}</span>`;
const enderecoDe = (o) => (/Endereço: (.*?)\.(?= Comentário: |$)/s.exec(o.descricao || "") || [])[1] || "";

// O link da foto vem da API, que aceita relatos de qualquer origem: só http(s) vira link,
// e só as fotos guardadas por este site aparecem como imagem.
function linkDaFoto(url) {
  if (!url) return "";
  try {
    const u = new URL(url, location.origin);
    return u.protocol === "https:" || u.protocol === "http:" ? u.href : "";
  } catch { return ""; }
}
function fotoDoSite(url) {
  if (!url) return "";
  try {
    const u = new URL(url, location.origin);
    return u.origin === location.origin && u.pathname.startsWith("/visao/fotos/") ? u.pathname : "";
  } catch { return ""; }
}

let ocorrencias = [];
let filtroTipo = "";

// ---------- aviso flutuante ----------
let avisoTimer = null;
function avisar(msg) {
  const el = $("aviso");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(avisoTimer);
  avisoTimer = setTimeout(() => { el.hidden = true; }, 3500);
}

// ---------- mapa (centro inicial: Sé, São Paulo) ----------
// Se o mapa não carregar (conexão ruim), a página continua funcionando pela tabela.
let mapa = null, camada = null, marcadorUsuario = null;
if (window.L) {
  mapa = L.map("mapa", { keyboard: true, scrollWheelZoom: false }).setView([-23.5505, -46.6333], 12);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19, attribution: "&copy; colaboradores do OpenStreetMap",
  }).addTo(mapa);
  camada = L.layerGroup().addTo(mapa);
  mapa.on("focus", () => mapa.scrollWheelZoom.enable());
  mapa.on("click", (e) => {
    mapa.scrollWheelZoom.enable();
    $("mapa").classList.remove("marcando");
    definirLocal(e.latlng.lat, e.latlng.lng, "Local marcado no mapa", { origem: "mapa", buscarEndereco: true });
  });
} else {
  $("mapa").textContent = "Mapa indisponível no momento. A tabela abaixo mostra as ocorrências.";
}

// ---------- passo 1: foto ou vídeo, com prévia ----------
const EXT_VIDEO = /\.(mp4|webm|mov|avi|mkv|m4v|3gp)$/i;
const TEXTO_ARQUIVO = "<strong>Escolher foto ou vídeo</strong><span>Foto até 10 MB · vídeo MP4, WEBM ou MOV até 50 MB e 2 minutos</span>";
const ehVideo = (arq) => (arq.type || "").startsWith("video/") || EXT_VIDEO.test(arq.name || "");
const tamanho = (b) => (b > 1048576 ? `${(b / 1048576).toFixed(1).replace(".", ",")} MB` : `${Math.ceil(b / 1024)} KB`);

function textoDoBotao() {
  const arquivo = $("foto").files[0];
  if (arquivo) return ehVideo(arquivo) ? "Enviar e analisar vídeo" : "Enviar foto";
  return $("tipo-manual").value ? "Enviar relato" : "Enviar foto";
}
$("foto").addEventListener("change", () => {
  const arquivo = $("foto").files[0];
  if (!arquivo) { limparFoto(); return; }
  const video = ehVideo(arquivo);
  $("previa").hidden = video;
  if (!video) $("previa").src = URL.createObjectURL(arquivo);
  $("icone-video").hidden = !video;
  $("icone-arquivo").hidden = video;
  $("texto-foto").innerHTML = `<strong>${esc(arquivo.name)}</strong><span>${video ? "Vídeo" : "Foto"} · ${tamanho(arquivo.size)} · clique para trocar</span>`;
  $("btn-enviar").textContent = textoDoBotao();
});
$("tipo-manual").addEventListener("change", () => { $("btn-enviar").textContent = textoDoBotao(); });
function limparFoto() {
  $("previa").hidden = true;
  $("previa").removeAttribute("src");
  $("icone-video").hidden = true;
  $("icone-arquivo").hidden = false;
  $("texto-foto").innerHTML = TEXTO_ARQUIVO;
  $("btn-enviar").textContent = textoDoBotao();
}

// ---------- passo 2: local (endereço, mapa ou GPS) ----------
// Endereços pelo Nominatim do OpenStreetMap. Política de uso: no máximo uma consulta por
// segundo, só quando a pessoa pede (sem autocompletar) e sem nenhum dado pessoal na consulta.
const NOMINATIM = "https://nominatim.openstreetmap.org";
let ultimaConsulta = 0;
let origemDoLocal = "";
async function consultarNominatim(caminho) {
  const espera = 1100 - (Date.now() - ultimaConsulta);
  if (espera > 0) await new Promise((ok) => setTimeout(ok, espera));
  ultimaConsulta = Date.now();
  const r = await fetch(`${NOMINATIM}${caminho}`, { headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error("serviço de endereços indisponível");
  return r.json();
}
function statusLocal(msg, definido = false) {
  $("local-status").textContent = msg;
  $("local-status").classList.toggle("definido", definido);
}
function mostrarAba(modo) {
  document.querySelectorAll(".aba-painel").forEach((p) => { p.hidden = p.dataset.modo !== modo; });
}
document.querySelectorAll('input[name="modo"]').forEach((r) => r.addEventListener("change", () => mostrarAba(r.value)));

function limparLocal(msg = "Nenhum local escolhido.") {
  $("latitude").value = "";
  $("longitude").value = "";
  origemDoLocal = "";
  statusLocal(msg);
  if (marcadorUsuario) { marcadorUsuario.remove(); marcadorUsuario = null; }
}

function definirLocal(lat, lon, msg, { origem = "", buscarEndereco = false, centralizar = false } = {}) {
  $("latitude").value = lat.toFixed(6);
  $("longitude").value = lon.toFixed(6);
  origemDoLocal = origem;
  const fora = lat < SP.latMin || lat > SP.latMax || lon < SP.lonMin || lon > SP.lonMax;
  statusLocal(`${msg} (${lat.toFixed(5)}, ${lon.toFixed(5)})${fora ? ". Atenção: fica fora de São Paulo, onde o piloto funciona" : ""}`, !fora);
  if (mapa) {
    if (marcadorUsuario) marcadorUsuario.setLatLng([lat, lon]);
    else {
      marcadorUsuario = L.marker([lat, lon], { title: "Local da barreira (arraste para ajustar)", draggable: true }).addTo(mapa);
      marcadorUsuario.on("dragend", () => {
        const p = marcadorUsuario.getLatLng();
        definirLocal(p.lat, p.lng, "Local ajustado no mapa", { origem: "mapa", buscarEndereco: true });
      });
    }
    if (centralizar) mapa.setView([lat, lon], 17);
  }
  if (buscarEndereco) enderecoDoPonto(lat, lon);
}

// endereço digitado -> coordenadas
async function buscarEndereco() {
  const q = $("endereco").value.trim();
  if (q.length < 4) { statusLocal("Digite rua e número, bairro ou cidade."); $("endereco").focus(); return false; }
  statusLocal("Procurando o endereço…");
  try {
    const res = await consultarNominatim("/search?format=jsonv2&limit=1&countrycodes=br&accept-language=pt-BR"
      + `&viewbox=${SP.lonMin},${SP.latMax},${SP.lonMax},${SP.latMin}&q=${encodeURIComponent(q)}`);
    if (!res.length) { limparLocal("Endereço não encontrado. Confira o texto ou marque o ponto no mapa."); return false; }
    definirLocal(parseFloat(res[0].lat), parseFloat(res[0].lon), "Endereço encontrado", { origem: "endereco", centralizar: true });
    return true;
  } catch {
    statusLocal("Serviço de endereços indisponível. Marque o ponto no mapa.");
    return false;
  }
}

// coordenadas -> endereço legível (preenche o campo quando a pessoa usa o mapa ou o GPS)
async function enderecoDoPonto(lat, lon) {
  try {
    const r = await consultarNominatim(`/reverse?format=jsonv2&zoom=18&accept-language=pt-BR&lat=${lat}&lon=${lon}`);
    const a = r.address || {};
    const rua = [a.road, a.house_number].filter(Boolean).join(", ");
    const texto = [rua, a.suburb || a.neighbourhood, a.city || a.town].filter(Boolean).join(" - ");
    if (texto && $("latitude").value === lat.toFixed(6)) $("endereco").value = texto;
  } catch { /* sem o serviço de endereços, as coordenadas já bastam */ }
}

$("btn-buscar").addEventListener("click", buscarEndereco);
$("endereco").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); buscarEndereco(); } });
// o texto mudou depois da busca: o ponto antigo não vale mais
$("endereco").addEventListener("input", () => {
  if (origemDoLocal === "endereco") limparLocal("Endereço alterado. Clique em Buscar para localizar.");
});
$("btn-mapa").addEventListener("click", () => {
  if (!mapa) { statusLocal("Mapa indisponível agora. Use o endereço."); return; }
  $("mapa").classList.add("marcando");
  $("mapa").scrollIntoView({ behavior: "smooth", block: "center" });
  $("mapa").focus({ preventScroll: true });
  statusLocal("Clique no mapa no ponto da barreira.");
});
$("btn-local").addEventListener("click", () => {
  if (!navigator.geolocation) { statusLocal("Este navegador não informa a localização. Use o endereço ou o mapa."); return; }
  statusLocal("Buscando sua localização…");
  navigator.geolocation.getCurrentPosition(
    (p) => definirLocal(p.coords.latitude, p.coords.longitude, "Localização encontrada", { origem: "gps", buscarEndereco: true, centralizar: true }),
    () => statusLocal("Não foi possível obter a localização. Use o endereço ou o mapa."),
    { enableHighAccuracy: true, timeout: 10000 },
  );
});

// ---------- reduz a foto no aparelho (pouca conectividade; também descarta o EXIF) ----------
async function reduzirFoto(arquivo, ladoMax = 1280, qualidade = 0.82) {
  try {
    const bmp = await createImageBitmap(arquivo);
    const escala = Math.min(1, ladoMax / Math.max(bmp.width, bmp.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bmp.width * escala);
    canvas.height = Math.round(bmp.height * escala);
    canvas.getContext("2d").drawImage(bmp, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((ok) => canvas.toBlob(ok, "image/jpeg", qualidade));
    return blob && blob.size < arquivo.size ? blob : arquivo;
  } catch { return arquivo; }
}

// ---------- envio ----------
function mostrar(tipo, html) {
  const res = $("resultado");
  res.hidden = false;
  res.className = `resultado ${tipo}`;
  res.innerHTML = html;
  res.focus();
}
const alerta = (titulo, sub = "") => mostrar("alerta", `<div class="resultado-topo"><span class="resultado-icone" aria-hidden="true">!</span>
  <div><h3>${esc(titulo)}</h3>${sub ? `<p class="sub">${esc(sub)}</p>` : ""}</div></div>`);

async function lerResposta(r) {
  let corpo = {};
  try { corpo = await r.json(); } catch { /* resposta sem JSON, como a do proxy */ }
  if (r.ok) return corpo;
  const detalhe = corpo.detail?.[0]?.msg || (typeof corpo.detail === "string" ? corpo.detail : "");
  if (detalhe) throw new Error(detalhe);
  if (r.status === 413) throw new Error("Arquivo grande demais.");
  if (r.status >= 502) throw new Error("A detecção está indisponível agora. Você ainda pode relatar sem foto, escolhendo o tipo.");
  throw new Error(`Erro ${r.status}.`);
}

// o local é obrigatório: sem ele a ocorrência não entra no mapa nem passa pela triagem
async function localInformado() {
  if ($("endereco").value.trim() && !$("latitude").value) await buscarEndereco();
  if ($("latitude").value && $("longitude").value) return true;
  alerta("Informe onde fica a barreira.", "Digite o endereço e clique em Buscar, marque o ponto no mapa ou use a sua localização.");
  return false;
}

function limparFormulario() {
  $("form").reset();
  limparFoto();
  limparLocal();
  mostrarAba("endereco");
}

function resultadoDaOcorrencia(o, titulo, tipo, confianca) {
  const ok = confianca == null || confianca >= 0.5;
  const endereco = enderecoDe(o);
  const foto = fotoDoSite(o.foto_url);
  mostrar(ok ? "ok" : "alerta", `
    <div class="resultado-topo">
      <span class="resultado-icone" aria-hidden="true">${ok ? "✓" : "!"}</span>
      <div><h3>${esc(titulo)}</h3><p class="sub">A triagem automática roda a cada 15 minutos e define prioridade e protocolo.</p></div>
    </div>
    <dl>
      <dt>Tipo</dt><dd>${selo(tipo)}${confianca == null ? "" : ` ${pct(confianca)} de confiança`}</dd>
      <dt>Situação</dt><dd>${esc(SITUACAO[o.status] || o.status)}</dd>
      <dt>Origem</dt><dd>${esc(ORIGEM[o.origem] || o.origem)}</dd>
      ${endereco ? `<dt>Local</dt><dd>${esc(endereco)}</dd>` : ""}
    </dl>
    ${foto ? `<img src="${esc(foto)}" alt="Foto enviada com a barreira marcada: ${esc(ROTULO[tipo] || tipo)}">` : ""}`);
}

async function enviarFoto(arquivo, btn) {
  btn.disabled = true;
  btn.innerHTML = `<span class="giro" aria-hidden="true"></span>Analisando a foto…`;
  try {
    const foto = await reduzirFoto(arquivo);
    if (foto.size > FOTO_MAX) throw new Error("Foto maior que 10 MB.");
    const fd = new FormData();
    fd.append("foto", foto, "foto.jpg");
    for (const k of ["latitude", "longitude", "endereco", "descricao"]) if ($(k).value.trim()) fd.append(k, $(k).value.trim());
    const corpo = await lerResposta(await fetch("/visao/detectar", { method: "POST", body: fd }));
    if (!corpo.ocorrencia) { alerta("Nenhuma barreira identificada", corpo.mensagem); return; }
    const principal = corpo.deteccoes[0];
    resultadoDaOcorrencia(corpo.ocorrencia, corpo.mensagem, principal.classe, principal.confianca);
    limparFormulario();
    carregar();
  } catch (e) {
    alerta("Não foi possível enviar a foto", e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = textoDoBotao();
  }
}

// relato sem foto: o cidadão escolhe o tipo e a ocorrência entra com origem "app"
async function enviarRelato(tipo, btn) {
  btn.disabled = true;
  try {
    const endereco = $("endereco").value.trim().replace(/\.+$/, "");
    const comentario = $("descricao").value.trim();
    const descricao = endereco ? `Endereço: ${endereco}.${comentario ? ` Comentário: ${comentario}` : ""}` : comentario;
    const r = await fetch("/api/ocorrencias", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tipo, latitude: Number($("latitude").value), longitude: Number($("longitude").value),
        origem: "app", descricao: descricao || null,
      }),
    });
    const o = await lerResposta(r);
    resultadoDaOcorrencia(o, "Relato enviado.", tipo, null);
    limparFormulario();
    carregar();
  } catch (e) {
    alerta("Não foi possível enviar o relato", e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = textoDoBotao();
  }
}

$("form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const arquivo = $("foto").files[0];
  const tipoManual = $("tipo-manual").value;
  if (!arquivo && !tipoManual) {
    alerta("Escolha uma foto ou um vídeo antes de enviar.", "Sem foto, abra “Não tem foto?” e escolha o tipo da barreira.");
    $("foto").focus();
    return;
  }
  if (!(await localInformado())) return;
  const btn = $("btn-enviar");
  if (!arquivo) await enviarRelato(tipoManual, btn);
  else if (ehVideo(arquivo)) await enviarVideo(arquivo, btn);
  else await enviarFoto(arquivo, btn);
});

// ---------- vídeo: envio com progresso e análise ao vivo ----------
function subirVideo(fd, aoProgresso) {
  return new Promise((ok, falha) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/visao/videos");
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) aoProgresso(e.loaded / e.total); };
    xhr.onload = () => {
      let corpo = {};
      try { corpo = JSON.parse(xhr.responseText); } catch { /* resposta sem JSON */ }
      if (xhr.status >= 200 && xhr.status < 300) { ok(corpo); return; }
      const detalhe = corpo.detail?.[0]?.msg || (typeof corpo.detail === "string" ? corpo.detail : "");
      falha(new Error(detalhe || (xhr.status === 413 ? "Vídeo maior que 50 MB." : `Erro ${xhr.status}.`)));
    };
    xhr.onerror = () => falha(new Error("Falha de conexão."));
    xhr.send(fd);
  });
}

async function enviarVideo(arquivo, btn) {
  if (arquivo.size > VIDEO_MAX) { alerta("Vídeo maior que 50 MB.", "Envie um trecho mais curto, de até 2 minutos."); return; }
  btn.disabled = true;
  btn.innerHTML = `<span class="giro" aria-hidden="true"></span>Enviando vídeo… 0%`;
  try {
    const fd = new FormData();
    fd.append("video", arquivo, arquivo.name);
    for (const k of ["latitude", "longitude", "endereco"]) if ($(k).value.trim()) fd.append(k, $(k).value.trim());
    const r = await subirVideo(fd, (p) => { btn.innerHTML = `<span class="giro" aria-hidden="true"></span>Enviando vídeo… ${Math.round(p * 100)}%`; });
    $("resultado").hidden = true;
    abrirAnalise(r, arquivo.name);
    limparFormulario();
  } catch (e) {
    alerta("Não foi possível enviar o vídeo", e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = textoDoBotao();
  }
}

let analiseTimer = null;
function abrirAnalise(r, nome) {
  const dlg = $("dlg-video");
  $("dlg-arquivo").textContent = nome;
  $("dlg-estado").textContent = "Analisando…";
  $("dlg-estado").className = "dlg-estado";
  $("dlg-barra").style.width = "0";
  $("dlg-carregando").hidden = false;
  for (const t of ["buraco", "obstaculo", "piso_quebrado"]) $(`dlg-n-${t}`).textContent = "0";
  $("dlg-lista").innerHTML = `<li class="vazio">Nenhuma ainda.</li>`;
  const img = $("dlg-stream");
  img.onload = () => { $("dlg-carregando").hidden = true; };
  img.src = `${r.ao_vivo_url}?t=${Date.now()}`;
  dlg.showModal();

  let vistas = 0;
  clearInterval(analiseTimer);
  analiseTimer = setInterval(async () => {
    let s;
    try { s = await (await fetch(r.status_url)).json(); } catch { return; }
    if (!s.contagem) return;
    if (s.progresso != null) $("dlg-barra").style.width = `${Math.round(s.progresso * 100)}%`;
    for (const t of ["buraco", "obstaculo", "piso_quebrado"]) $(`dlg-n-${t}`).textContent = s.contagem[t];
    if (s.ocorrencias.length !== vistas) {
      vistas = s.ocorrencias.length;
      $("dlg-lista").innerHTML = s.ocorrencias.slice().reverse().map((o) => `
        <li>${selo(o.tipo)}<span>${pct(o.confianca)}</span><span>${esc(SITUACAO[o.status] || o.status)}</span></li>`).join("");
      carregar();
    }
    if (["concluida", "erro", "interrompida"].includes(s.status)) {
      clearInterval(analiseTimer);
      const n = s.ocorrencias.length;
      if (s.status === "concluida") {
        $("dlg-barra").style.width = "100%";
        $("dlg-estado").textContent = n
          ? `Análise concluída: ${n} ${n === 1 ? "barreira registrada" : "barreiras registradas"}.`
          : "Análise concluída: nenhuma barreira identificada com segurança.";
        $("dlg-estado").className = "dlg-estado fim";
      } else {
        $("dlg-estado").textContent = s.status === "erro" ? `Não foi possível analisar: ${s.erro}` : "Análise interrompida.";
        $("dlg-estado").className = "dlg-estado erro";
      }
      carregar();
    }
  }, 1000);
}

function fecharAnalise() {
  clearInterval(analiseTimer);
  $("dlg-stream").removeAttribute("src"); // encerra o fluxo (interrompe a análise se ainda estiver rodando)
  if ($("dlg-video").open) $("dlg-video").close();
  carregar();
}
$("dlg-fechar").addEventListener("click", fecharAnalise);
$("dlg-video").addEventListener("cancel", (e) => { e.preventDefault(); fecharAnalise(); });
$("dlg-mapa").addEventListener("click", () => {
  fecharAnalise();
  $("mapa-sec").scrollIntoView({ behavior: "smooth", block: "start" });
});

// ---------- filtros por tipo (mapa e tabela) ----------
document.querySelectorAll(".filtro").forEach((b) => b.addEventListener("click", () => {
  filtroTipo = b.dataset.tipo;
  document.querySelectorAll(".filtro").forEach((x) => {
    const ativo = x === b;
    x.classList.toggle("ativo", ativo);
    x.setAttribute("aria-pressed", String(ativo));
  });
  desenhar();
}));

// ---------- dados: resumo, tabela e mapa ----------
async function carregar() {
  try {
    const [lista, resumo] = await Promise.all([
      fetch("/api/ocorrencias?limite=500").then((r) => r.json()),
      fetch("/api/resumo").then((r) => r.json()),
    ]);
    ocorrencias = lista;
    $("n-total").textContent = resumo.total ?? lista.length;
    for (const t of ["buraco", "obstaculo", "piso_quebrado"]) $(`n-${t}`).textContent = lista.filter((o) => tipoDe(o) === t).length;
    $("n-nova").textContent = (resumo.por_status || {}).nova || 0;
    desenhar();
  } catch {
    $("lista").innerHTML = `<tr><td colspan="8" class="vazio">Sem conexão com o servidor. Nova tentativa em instantes.</td></tr>`;
  }
}

function filtrar(o) {
  const tipo = tipoDe(o);
  if (!filtroTipo) return true;
  return filtroTipo === "outros" ? !COR[tipo] : tipo === filtroTipo;
}

function desenhar() {
  const lista = ocorrencias.filter(filtrar);
  $("contagem-lista").textContent = `${lista.length} ${lista.length === 1 ? "ocorrência" : "ocorrências"}`;
  $("lista").innerHTML = lista.length ? lista.map(linha).join("")
    : `<tr><td colspan="8" class="vazio">${filtroTipo ? "Nenhuma ocorrência deste tipo." : "Nenhuma ocorrência registrada até agora."}</td></tr>`;

  if (!camada) return;
  camada.clearLayers();
  for (const o of lista) {
    if (o.status === "quarentena" || o.status === "duplicada") continue;
    const tipo = tipoDe(o);
    const endereco = enderecoDe(o);
    const foto = fotoDoSite(o.foto_url);
    L.circleMarker([o.latitude, o.longitude], { radius: 9, color: "#ffffff", weight: 2.5, fillColor: COR[tipo] || COR_OUTROS, fillOpacity: 1 })
      .bindPopup(`<div class="popup-titulo">${selo(tipo)}${o.confianca == null ? "" : ` ${pct(o.confianca)}`}</div>`
        + `${endereco ? esc(endereco) + "<br>" : ""}${esc(SITUACAO[o.status] || o.status)}`
        + `${o.protocolo ? " · " + esc(o.protocolo) : ""} · ${esc(ORIGEM[o.origem] || o.origem)}`
        + `${foto ? `<img src="${esc(foto)}" alt="Foto da ocorrência com a barreira marcada">` : ""}`)
      .on("click", (e) => {
        // marcando o local de um relato novo: o clique num ponto já existente também vale
        if (!$("mapa").classList.contains("marcando")) return;
        mapa.closePopup();
        $("mapa").classList.remove("marcando");
        definirLocal(e.latlng.lat, e.latlng.lng, "Local marcado no mapa", { origem: "mapa", buscarEndereco: true });
      })
      .addTo(camada);
  }
}

function linha(o) {
  const tipo = tipoDe(o);
  const local = enderecoDe(o) || `${o.latitude.toFixed(5)}, ${o.longitude.toFixed(5)}`;
  const confianca = o.confianca == null ? "—"
    : `<span class="barra"><span aria-hidden="true"><i style="width:${Math.round(o.confianca * 100)}%"></i></span>${pct(o.confianca)}</span>`;
  const link = linkDaFoto(o.foto_url);
  const foto = link ? `<a class="acao" href="${esc(link)}" target="_blank" rel="noopener noreferrer">Foto<span class="sr"> da ocorrência</span></a>` : "—";
  return `<tr>
    <td class="protocolo">${esc(o.protocolo || "—")}</td>
    <td>${selo(tipo)}</td>
    <td class="local">${esc(local)}${o.subprefeitura ? `<small>Subprefeitura ${esc(o.subprefeitura)}</small>` : ""}</td>
    <td>${confianca}</td>
    <td>${esc(PRIORIDADE[o.prioridade] || o.prioridade || "—")}</td>
    <td><span class="situacao ${esc(o.status)}">${esc(SITUACAO[o.status] || o.status)}</span></td>
    <td>${esc(ORIGEM_CURTA[o.origem] || o.origem)}</td>
    <td>${foto}</td>
  </tr>`;
}

carregar();
setInterval(carregar, 15000); // atualiza sozinho: novas ocorrências e o resultado da triagem
