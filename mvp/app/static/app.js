const NOMES = {
  buraco: "Buraco", obstaculo: "Obstáculo", degrau: "Degrau", sem_rampa: "Falta de rampa",
  calcada_estreita: "Calçada estreita", trecho_escuro: "Trecho escuro", outro: "Outro",
};
const PRIORIDADES = { alta: "alta", media: "média", baixa: "baixa" };
const CORES = { alta: "#a10000", media: "#c27c00", baixa: "#22662b" };

// Se o mapa não carregar (conexão ruim), a página continua funcionando pela tabela.
let mapa = null;
let camada = null;
if (window.L) {
  mapa = L.map("mapa").setView([-23.5505, -46.6333], 12);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap",
  }).addTo(mapa);
  camada = L.layerGroup().addTo(mapa);
  mapa.on("click", e => {
    document.getElementById("lat").value = e.latlng.lat.toFixed(6);
    document.getElementById("lon").value = e.latlng.lng.toFixed(6);
  });
} else {
  document.getElementById("mapa").textContent = "Mapa indisponível no momento. Use a tabela abaixo.";
}

function texto(v) { return v == null ? "—" : String(v); }

function celula(tr, valor, classe) {
  const td = document.createElement("td");
  td.textContent = texto(valor);
  if (classe) td.className = classe;
  tr.appendChild(td);
}

async function carregar() {
  const [lista, resumo] = await Promise.all([
    fetch("/api/ocorrencias?limite=300").then(r => r.json()),
    fetch("/api/resumo").then(r => r.json()),
  ]);
  const s = resumo.por_status || {};
  document.getElementById("resumo").textContent =
    `${resumo.total} ocorrências: ${s.encaminhada || 0} encaminhadas, ${s.nova || 0} aguardando triagem, ` +
    `${s.quarentena || 0} em quarentena, ${s.duplicada || 0} duplicadas. ` +
    `${(resumo.por_prioridade || {}).alta || 0} de prioridade alta.`;

  camada?.clearLayers();
  const corpo = document.getElementById("linhas");
  corpo.replaceChildren();
  for (const o of lista) {
    if (camada && o.status !== "quarentena" && o.status !== "duplicada") {
      L.circleMarker([o.latitude, o.longitude], {
        radius: 8, weight: 2, color: CORES[o.prioridade] || "#555", fillOpacity: .6,
      }).bindPopup(`${NOMES[o.tipo] || o.tipo} · ${o.status}${o.protocolo ? " · " + o.protocolo : ""}`).addTo(camada);
    }
    const tr = document.createElement("tr");
    celula(tr, NOMES[o.tipo] || o.tipo);
    celula(tr, o.origem);
    celula(tr, o.status);
    celula(tr, PRIORIDADES[o.prioridade] ?? o.prioridade, o.prioridade ? "p-" + o.prioridade : "");
    celula(tr, o.protocolo);
    celula(tr, o.subprefeitura);
    corpo.appendChild(tr);
  }
}

document.getElementById("gps").addEventListener("click", () => {
  navigator.geolocation?.getCurrentPosition(p => {
    document.getElementById("lat").value = p.coords.latitude.toFixed(6);
    document.getElementById("lon").value = p.coords.longitude.toFixed(6);
  });
});

document.getElementById("form").addEventListener("submit", async ev => {
  ev.preventDefault();
  const f = new FormData(ev.target);
  const msg = document.getElementById("msg");
  const corpo = {
    tipo: f.get("tipo"),
    latitude: Number(String(f.get("latitude")).replace(",", ".")),
    longitude: Number(String(f.get("longitude")).replace(",", ".")),
    origem: "app",
    descricao: f.get("descricao") || null,
  };
  const r = await fetch("/api/ocorrencias", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corpo),
  });
  msg.textContent = r.ok ? "Relato enviado. Ele passa pela triagem automática em até 15 minutos." : "Não foi possível enviar. Confira os campos.";
  if (r.ok) { ev.target.reset(); carregar(); }
});

carregar();
setInterval(carregar, 60000);
