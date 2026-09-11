# -*- coding: utf-8 -*-
"""
Gera docs/index.html: pagina de consulta autocontida (HTML + CSS + JS num arquivo so),
sem CDN e sem dependencia externa, a partir de saida/status_comparado.csv.

Funciona servida pelo GitHub Pages e tambem aberta direto do disco (file://).
Os dados vao embutidos como JSON no momento da geracao.

Uso: python scripts/gera_html.py saida/status_comparado.csv docs/index.html
"""
import sys, os, json, datetime
import pandas as pd

ENTRADA = sys.argv[1] if len(sys.argv) > 1 else "saida/status_comparado.csv"
SAIDA = sys.argv[2] if len(sys.argv) > 2 else "docs/index.html"
LIMITE_MB = 15.0
# exportacao do SALVE que originou os dados, mostrada no cabecalho da pagina
EXPORT_SALVE = "10/09/2026"
# campo de texto da secao Metodologia, editado a mao a cada publicacao.
# Nao e gerado automaticamente: o "Pagina gerada em" do cabecalho ja cobre isso.
DATA_ATUALIZACAO = "11/09/2026"
URL_README = "https://github.com/rodrigoaraujoufrj-bit/SALVE/blob/main/README.md"

# colunas que se repetem muito: viram dicionario (indice inteiro por linha)
CATEGORICAS = ["grupo", "classe", "ordem", "familia", "endemica_brasil", "status_salve",
               "ano_avaliacao_salve", "status_portaria_2026", "portaria_2026",
               "status_iucn_global", "iucn_global_match", "nacional_x_global"]
FLAGS = ["nova_na_lista_2026", "mudou_salve_x_portaria",
         "ameacada_salve_fora_portarias", "mudou_nacional_x_global"]

# ------------------------------------------------------------------ leitura
df = pd.read_csv(ENTRADA, dtype=str, keep_default_na=False)
df.columns = [c.lstrip("﻿") for c in df.columns]

# o round-trip pelo Excel deixa inteiros como '1667.0' / '2017.0': normaliza
def inteiro(v):
    v = (v or "").strip()
    if v in ("", "nan", "None"):
        return ""
    try:
        return str(int(float(v)))
    except ValueError:
        return v

for c in ["id_ficha", "portaria_2026", "ano_avaliacao_salve"] + FLAGS:
    if c in df.columns:
        df[c] = df[c].map(inteiro)
for c in FLAGS:
    df[c] = df[c].replace("", "0")

COLS = list(df.columns)
print(f"lido {ENTRADA}: {len(df)} linhas x {len(COLS)} colunas")

# ------------------------------------------------------------------ payload compacto
# iucn_global_nome_aceito repete o nome_cientifico na grande maioria das linhas:
# guarda '=' nesses casos e reconstroi no navegador (mantendo vazio quando e vazio de fato)
iguais = int((df.iucn_global_nome_aceito == df.nome_cientifico).sum())
df["iucn_global_nome_aceito"] = df.iucn_global_nome_aceito.where(
    df.iucn_global_nome_aceito != df.nome_cientifico, "=")
print(f"iucn_global_nome_aceito identico ao nome cientifico em {iguais} linhas (guardado como '=')")

cats, codigos = {}, {}
for c in CATEGORICAS:
    valores = sorted(df[c].unique())
    cats[c] = valores
    codigos[c] = {v: i for i, v in enumerate(valores)}

linhas = []
for t in df.itertuples(index=False):
    linha = []
    for c in COLS:
        v = getattr(t, c)
        if c in codigos:
            linha.append(codigos[c][v])
        elif c in FLAGS:
            linha.append(int(v))
        elif c == "id_ficha":
            linha.append(int(v))
        else:
            linha.append(v)
    linhas.append(linha)

payload = {"cols": COLS, "cats": cats, "rows": linhas}
dados_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
print(f"payload JSON: {len(dados_json.encode('utf8'))/1e6:.2f} MB")

hoje = datetime.date.today().strftime("%d/%m/%Y")

# ------------------------------------------------------------------ template
TEMPLATE = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SALVE Fauna: consulta comparada</title>
<style>
*{box-sizing:border-box}
:root{
  --tinta:#1b2430; --tinta2:#5a6577; --linha:#d8dee8; --fundo:#f4f6f9; --papel:#fff;
  --acento:#1f4e78; --acento-claro:#e8eef5;
  --amarelo:#fff2a8; --laranja:#f8cbad; --vermelho:#f4b6b6; --azul:#cfe2f3; --cinza:#ededed;
}
html,body{margin:0;padding:0}
body{background:var(--fundo);color:var(--tinta);
  font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
  -webkit-text-size-adjust:100%}
.env{max-width:1500px;margin:0 auto;padding:16px}
h1{font-size:19px;margin:0 0 2px;font-weight:650;letter-spacing:-.2px}
.sub{color:var(--tinta2);font-size:12.5px;margin:0}

header.topo{background:var(--papel);border:1px solid var(--linha);border-radius:8px;
  padding:14px 16px;margin-bottom:12px}
.fontes{margin-top:9px;font-size:12px;color:var(--tinta2);
  display:flex;flex-wrap:wrap;gap:5px 14px}
.fontes b{color:var(--tinta);font-weight:600}
.aviso{margin-top:10px;padding:8px 11px;background:#fbf7e8;border-left:3px solid #d9b441;
  border-radius:3px;font-size:12.2px;color:#5c4a1a}

.painel{background:var(--papel);border:1px solid var(--linha);border-radius:8px;
  padding:12px 14px;margin-bottom:12px}
.busca{width:100%;padding:9px 11px;font-size:15px;border:1px solid var(--linha);
  border-radius:6px;font-family:inherit;color:var(--tinta);background:var(--papel)}
.busca:focus{outline:2px solid var(--acento);outline-offset:-1px;border-color:var(--acento)}

.filtros{display:grid;grid-template-columns:repeat(auto-fit,minmax(158px,1fr));gap:9px;margin-top:11px}
.campo{display:flex;flex-direction:column;gap:3px;min-width:0}
.campo label{font-size:11px;font-weight:600;color:var(--tinta2);text-transform:uppercase;letter-spacing:.4px}
.campo select{padding:6px 7px;border:1px solid var(--linha);border-radius:5px;background:var(--papel);
  font-size:13px;font-family:inherit;color:var(--tinta);width:100%}

.marcas{display:flex;flex-wrap:wrap;gap:7px;margin-top:11px;padding-top:11px;border-top:1px solid var(--linha)}
.marca{display:inline-flex;align-items:center;gap:6px;padding:5px 10px;border:1px solid var(--linha);
  border-radius:14px;font-size:12.5px;cursor:pointer;background:var(--papel);user-select:none}
.marca:hover{border-color:var(--acento)}
.marca input{margin:0;cursor:pointer}
.marca.on{background:var(--acento-claro);border-color:var(--acento);color:var(--acento);font-weight:600}
.marca .n{color:var(--tinta2);font-variant-numeric:tabular-nums}
.marca.on .n{color:var(--acento)}

.barra{display:flex;flex-wrap:wrap;align-items:center;gap:9px;margin-top:11px;
  padding-top:11px;border-top:1px solid var(--linha)}
.contador{font-size:13.5px}
.contador b{font-size:16px;font-variant-numeric:tabular-nums}
.espaco{flex:1}
button.acao{padding:7px 13px;border:1px solid var(--linha);background:var(--papel);color:var(--tinta);
  border-radius:5px;font-size:13px;cursor:pointer;font-family:inherit}
button.acao:hover{border-color:var(--acento);color:var(--acento)}
button.acao.destaque{background:var(--acento);color:#fff;border-color:var(--acento);font-weight:600}
button.acao.destaque:hover{background:#163a5a;color:#fff}

.legenda{display:flex;flex-wrap:wrap;gap:6px 15px;margin-top:11px;padding-top:11px;
  border-top:1px solid var(--linha);font-size:12px;color:var(--tinta2)}
.legenda span{display:inline-flex;align-items:center;gap:6px}
.amostra{width:13px;height:13px;border-radius:3px;border:1px solid rgba(0,0,0,.16);flex:none}

.rolagem{background:var(--papel);border:1px solid var(--linha);border-radius:8px;overflow:auto;max-height:66vh}
table{border-collapse:collapse;width:100%;font-size:13px}
thead th{position:sticky;top:0;z-index:2;background:var(--acento);color:#fff;text-align:left;
  padding:9px 10px;font-weight:600;font-size:12px;cursor:pointer;white-space:nowrap;user-select:none}
thead th:hover{background:#163a5a}
thead th .seta{opacity:.45;font-size:10px;margin-left:3px}
thead th.ativo .seta{opacity:1}
tbody td{padding:7px 10px;border-bottom:1px solid #eef1f5;vertical-align:top}
tbody tr{cursor:pointer}
tbody tr:hover td{background:#f0f4fa}
tbody tr.sel td{background:var(--acento-claro)}
.cien{font-style:italic;white-space:nowrap}
.st{text-align:center;font-weight:600;white-space:nowrap;font-variant-numeric:tabular-nums}
.st.amarelo{background:var(--amarelo)}
.st.laranja{background:var(--laranja)}
.st.vermelho{background:var(--vermelho)}
.st.azul{background:var(--azul)}
.st.cinza{background:var(--cinza);color:var(--tinta2)}
.vazio{padding:40px 16px;text-align:center;color:var(--tinta2)}

.paginas{display:flex;flex-wrap:wrap;align-items:center;gap:9px;justify-content:center;
  padding:11px 0 4px;font-size:13px;color:var(--tinta2)}
.paginas button{padding:5px 11px;border:1px solid var(--linha);background:var(--papel);color:var(--tinta);
  border-radius:5px;cursor:pointer;font-size:13px;font-family:inherit}
.paginas button:hover:not(:disabled){border-color:var(--acento);color:var(--acento)}
.paginas button:disabled{opacity:.4;cursor:default}

.veu{position:fixed;inset:0;background:rgba(20,28,38,.42);z-index:9;display:none}
.veu.on{display:block}
.gaveta{position:fixed;top:0;right:0;bottom:0;width:min(460px,100%);background:var(--papel);
  z-index:10;box-shadow:-3px 0 22px rgba(0,0,0,.17);transform:translateX(100%);
  transition:transform .17s ease;display:flex;flex-direction:column}
.gaveta.on{transform:translateX(0)}
.gaveta .cabeca{padding:15px 17px;border-bottom:1px solid var(--linha);display:flex;
  align-items:flex-start;gap:11px}
.gaveta .cabeca h2{margin:0;font-size:17px;font-style:italic;font-weight:600;line-height:1.3}
.gaveta .cabeca .pop{margin:3px 0 0;font-size:12.5px;color:var(--tinta2);font-style:normal}
.fechar{margin-left:auto;border:none;background:none;font-size:26px;line-height:1;cursor:pointer;
  color:var(--tinta2);padding:0 2px}
.fechar:hover{color:var(--tinta)}
.gaveta .corpo{overflow:auto;padding:5px 17px 22px}
.gaveta dl{margin:0}
.gaveta dt{font-size:10.5px;font-weight:700;color:var(--tinta2);text-transform:uppercase;
  letter-spacing:.5px;margin-top:13px}
.gaveta dd{margin:2px 0 0;font-size:13.5px;word-break:break-word}
.gaveta .grupo{margin-top:17px;padding-top:5px;border-top:2px solid var(--linha);
  font-size:11.5px;font-weight:700;color:var(--acento);text-transform:uppercase;letter-spacing:.6px}
.selo{display:inline-block;padding:2px 9px;border-radius:11px;font-weight:700;font-size:13px}

.metodo{background:var(--papel);border:1px solid var(--linha);border-radius:8px;margin-top:12px}
.metodo>summary{padding:12px 16px;cursor:pointer;font-weight:600;font-size:14px;
  list-style:none;display:flex;align-items:center;gap:9px;user-select:none}
.metodo>summary::-webkit-details-marker{display:none}
.metodo>summary::before{content:"\25B8";color:var(--acento);font-size:13px;
  display:inline-block;transition:transform .15s}
.metodo[open]>summary::before{transform:rotate(90deg)}
.metodo>summary:hover{color:var(--acento)}
.metodo>summary:focus-visible{outline:2px solid var(--acento);outline-offset:-2px;border-radius:8px}
.metodo .texto{padding:2px 16px 16px;max-width:76ch;font-size:13.5px;line-height:1.65}
.metodo h3{font-size:12px;text-transform:uppercase;letter-spacing:.5px;color:var(--acento);
  margin:18px 0 6px;font-weight:700}
.metodo p{margin:0 0 10px}
.metodo ol{margin:0 0 10px;padding-left:20px}
.metodo li{margin-bottom:7px;padding-left:3px}
.metodo .cien{font-style:italic;white-space:normal}
.metodo .fonte-met{margin:16px 0 0;padding-top:12px;border-top:1px solid var(--linha);
  font-size:12.5px;color:var(--tinta2)}
.metodo a{color:var(--acento)}
footer{margin:14px 0 6px;font-size:11.5px;color:var(--tinta2);text-align:center;line-height:1.7}

@media (max-width:820px){
  .env{padding:11px}
  .esconde{display:none}
  .rolagem{max-height:none}
  thead th,tbody td{padding:7px 8px;font-size:12.5px}
}
</style>
</head>
<body>
<div class="env">

<header class="topo">
  <h1>SALVE Fauna: consulta comparada</h1>
  <p class="sub">__N_ESPECIES__ espécies avaliadas, com o status no SALVE, nas Portarias de 2026 e na Lista Vermelha global da IUCN.</p>
  <div class="fontes">
    <span><b>SALVE / ICMBio</b> exportação de __EXPORT_SALVE__</span>
    <span><b>Portaria GM/MMA 1.667/2026</b> DOU 28/04/2026</span>
    <span><b>Portaria MMA 1.704/2026</b> DOU 17/06/2026</span>
    <span><b>IUCN Red List</b> via API do GBIF</span>
    <span><b>Página gerada em</b> __DATA_GERACAO__</span>
  </div>
  <p class="aviso">A categoria do SALVE é a avaliação vigente do ICMBio para o território brasileiro. A categoria da IUCN é uma avaliação global, de outro escopo e outra data. As duas não precisam coincidir, e divergência entre elas não indica erro.</p>
</header>

<div class="painel">
  <input class="busca" id="busca" type="search" autocomplete="off" spellcheck="false"
         placeholder="Buscar por nome científico, nome comum ou nome aceito na IUCN">

  <div class="filtros" id="filtros"></div>

  <div class="marcas" id="marcas"></div>

  <div class="barra">
    <span class="contador"><b id="quantos">0</b> <span id="rotulo">espécies</span></span>
    <span class="espaco"></span>
    <button class="acao" id="limpar" type="button">Limpar filtros</button>
    <button class="acao destaque" id="exportar" type="button">Exportar CSV</button>
  </div>

  <div class="legenda">
    <span><i class="amostra" style="background:var(--amarelo)"></i> nova na lista oficial de 2026</span>
    <span><i class="amostra" style="background:var(--laranja)"></i> categoria da portaria diferente do SALVE</span>
    <span><i class="amostra" style="background:var(--vermelho)"></i> ameaçada no SALVE e fora das portarias</span>
    <span><i class="amostra" style="background:var(--azul)"></i> categoria nacional diferente da global</span>
    <span><i class="amostra" style="background:var(--cinza)"></i> sem categoria global na IUCN</span>
  </div>
</div>

<div class="rolagem">
  <table>
    <thead><tr id="cabecalho"></tr></thead>
    <tbody id="corpo"></tbody>
  </table>
  <div class="vazio" id="vazio" style="display:none">Nenhuma espécie corresponde aos filtros aplicados.</div>
</div>

<div class="paginas" id="paginas"></div>

<details class="metodo">
  <summary>Metodologia: como os dados foram cruzados</summary>
  <div class="texto">
    <p>Esta consulta reúne três fontes: as fichas do SALVE (avaliação nacional do ICMBio), as Portarias MMA 1.667/2026 e 1.704/2026 (lista oficial de espécies ameaçadas) e a Lista Vermelha da IUCN (avaliação global). Cobre apenas o reino Animalia; a flora ameaçada segue outra lista, mantida pelo CNCFlora/JBRJ.</p>

    <h3>O problema de juntar as três fontes</h3>
    <p>O SALVE e a IUCN às vezes usam nomes científicos diferentes para a mesma espécie, porque a taxonomia é revisada com frequência e as duas bases nem sempre atualizam no mesmo ritmo: uma pode já ter adotado um gênero novo enquanto a outra ainda usa o antigo, ou uma trata como espécie o que a outra ainda trata como subespécie.</p>

    <h3>O caminho usado</h3>
    <p>Para resolver isso, o cruzamento passa pelo GBIF (Global Biodiversity Information Facility), uma referência internacional que mantém o histórico de sinônimos e integra dados de várias bases, incluindo a própria IUCN. O processo segue quatro etapas, em ordem:</p>
    <ol>
      <li>Tenta bater o nome científico exato entre SALVE e GBIF.</li>
      <li>Se o nome do SALVE é reconhecido como um sinônimo antigo, o sistema segue automaticamente para o nome atualizado e busca a categoria da IUCN nesse nome, registrando qual foi o nome usado, para permitir conferência depois.</li>
      <li>Se apenas o gênero é reconhecido, o sistema faz uma segunda busca para tentar localizar o nome sob um gênero diferente, situação comum quando um grupo inteiro passou por revisão taxonômica recente. Foi assim, por exemplo, que se recuperou a categoria do mutum-de-alagoas, que no SALVE está registrado como <span class="cien">Pauxi mitu</span> e na base internacional aparece sob o nome <span class="cien">Mitu mitu</span>.</li>
      <li>Correspondências aproximadas só são aceitas quando a similaridade do nome é muito alta, para evitar juntar espécies parecidas mas diferentes.</li>
    </ol>

    <h3>O que fica sem correspondência, de propósito</h3>
    <p>Quando uma espécie avaliada pelo SALVE ainda é tratada pela IUCN como parte de outra espécie (ou o contrário), não existe uma categoria global equivalente de fato. Nesses casos o sistema não aproxima, o campo fica indicado como "sem categoria global". A alternativa seria herdar a categoria da espécie mais próxima, mas isso atribuiria a um animal uma avaliação que ninguém fez para ele especificamente, então essa aproximação foi descartada por princípio.</p>

    <p class="fonte-met">Dados atualizados em __DATA_ATUALIZACAO__. Detalhamento técnico, código e fontes no <a href="__URL_README__" target="_blank" rel="noopener">README do repositório</a>.</p>
  </div>
</details>

<footer>
  Consolidado a partir da exportação pública única das fichas do SALVE / ICMBio, reino Animalia.<br>
  Inclui as espécies sem bioma atribuído, que ficavam de fora quando a fonte era a exportação separada por bioma.
</footer>

</div>

<div class="veu" id="veu"></div>
<aside class="gaveta" id="gaveta" aria-hidden="true">
  <div class="cabeca">
    <div>
      <h2 id="g-nome"></h2>
      <p class="pop" id="g-pop"></p>
    </div>
    <button class="fechar" id="g-fechar" type="button" aria-label="Fechar">&times;</button>
  </div>
  <div class="corpo"><dl id="g-corpo"></dl></div>
</aside>

<script>
(function(){
"use strict";

var P = __PAYLOAD__;
var COLS = P.cols, CATS = P.cats;

// ---------------------------------------------------------------- decodifica
var ROWS = P.rows.map(function(r){
  var o = {}, i, c;
  for (i = 0; i < COLS.length; i++){
    c = COLS[i];
    o[c] = CATS[c] ? CATS[c][r[i]] : r[i];
  }
  if (o.iucn_global_nome_aceito === "=") o.iucn_global_nome_aceito = o.nome_cientifico;
  return o;
});

function semAcento(s){
  return (s == null ? "" : String(s)).toLowerCase()
    .normalize("NFD").replace(/[\u0300-\u036f]/g, "");
}
ROWS.forEach(function(o){
  o._b = semAcento(o.nome_cientifico + " " + o.nome_comum + " " + o.iucn_global_nome_aceito);
});

// ---------------------------------------------------------------- rotulos
var ROTULO = {
  id_ficha:"ID da ficha", nome_cientifico:"Nome científico", nome_comum:"Nome comum",
  grupo:"Grupo", classe:"Classe", ordem:"Ordem", familia:"Família",
  endemica_brasil:"Endêmica do Brasil", status_salve:"Status SALVE",
  ano_avaliacao_salve:"Ano da avaliação SALVE", status_portaria_2026:"Status Portaria 2026",
  portaria_2026:"Portaria", nova_na_lista_2026:"Nova na lista de 2026",
  status_iucn_global:"Status IUCN global", iucn_global_nome_aceito:"Nome aceito na IUCN",
  iucn_global_match:"Tipo de correspondência no GBIF",
  mudou_salve_x_portaria:"Categoria mudou (SALVE x Portaria)",
  ameacada_salve_fora_portarias:"Ameaçada no SALVE e fora das portarias",
  nacional_x_global:"Nacional x global", mudou_nacional_x_global:"Nacional difere da global"
};
var CATEGORIA = {
  EX:"Extinta", EW:"Extinta na Natureza", RE:"Regionalmente Extinta",
  CR:"Criticamente em Perigo", EN:"Em Perigo", VU:"Vulnerável", NT:"Quase Ameaçada",
  LC:"Menos Preocupante", DD:"Dados Insuficientes", NA:"Não Aplicável", NE:"Não Avaliada"
};

// ---------------------------------------------------------------- cores
// mesma precedencia aplicada no XLSX pelo status_comparado.py
function corPortaria(o){
  var c = "";
  if (o.ameacada_salve_fora_portarias === 1) c = "vermelho";
  if (o.mudou_salve_x_portaria === 1) c = "laranja";
  if (o.nova_na_lista_2026 === 1 && o.mudou_salve_x_portaria === 0) c = "amarelo";
  return c;
}
function corIucn(o){
  if (o.mudou_nacional_x_global === 1) return "azul";
  if (o.status_iucn_global === "NE" || o.status_iucn_global === "") return "cinza";
  return "";
}
function corSalve(o){
  return o.ameacada_salve_fora_portarias === 1 ? "vermelho" : "";
}

// ---------------------------------------------------------------- filtros
var SELETORES = [
  ["grupo","Grupo"], ["status_salve","Status SALVE"], ["status_portaria_2026","Status Portaria 2026"],
  ["status_iucn_global","Status IUCN global"], ["portaria_2026","Portaria"],
  ["endemica_brasil","Endêmica do Brasil"], ["nacional_x_global","Nacional x global"]
];
var MARCAS = [
  ["nova_na_lista_2026","Nova na lista 2026"],
  ["mudou_salve_x_portaria","Categoria mudou"],
  ["ameacada_salve_fora_portarias","Ameaçada fora das portarias"],
  ["mudou_nacional_x_global","Nacional difere da global"]
];

function textoValor(campo, v){
  if (v === "" || v == null) return campo === "portaria_2026" ? "não listada" : "(sem informação)";
  if (campo === "status_salve" || campo === "status_iucn_global"){
    return v + (CATEGORIA[v] ? " (" + CATEGORIA[v] + ")" : "");
  }
  return v;
}

var caixa = document.getElementById("filtros");
SELETORES.forEach(function(par){
  var campo = par[0];
  var d = document.createElement("div");
  d.className = "campo";
  var valores = CATS[campo].slice().sort(function(a,b){
    if (a === "") return -1;
    if (b === "") return 1;
    return a.localeCompare(b, "pt-BR");
  });
  var opcoes = ['<option value="">Todos</option>'];
  valores.forEach(function(v){
    opcoes.push('<option value="' + esc(v) + '">' + esc(textoValor(campo, v)) + "</option>");
  });
  d.innerHTML = '<label for="f-' + campo + '">' + par[1] + "</label>" +
                '<select id="f-' + campo + '" data-campo="' + campo + '">' + opcoes.join("") + "</select>";
  caixa.appendChild(d);
});

var caixaMarcas = document.getElementById("marcas");
MARCAS.forEach(function(par){
  var campo = par[0];
  var n = 0;
  ROWS.forEach(function(o){ if (o[campo] === 1) n++; });
  var l = document.createElement("label");
  l.className = "marca";
  l.innerHTML = '<input type="checkbox" data-marca="' + campo + '"> ' + par[1] +
                ' <span class="n">' + n.toLocaleString("pt-BR") + "</span>";
  caixaMarcas.appendChild(l);
});

// ---------------------------------------------------------------- tabela
var COLUNAS = [
  {campo:"nome_cientifico", titulo:"Nome científico", cls:"cien"},
  {campo:"nome_comum", titulo:"Nome comum", esconde:true},
  {campo:"grupo", titulo:"Grupo"},
  {campo:"familia", titulo:"Família", esconde:true},
  {campo:"status_salve", titulo:"SALVE", st:corSalve},
  {campo:"status_portaria_2026", titulo:"Portaria 2026", st:corPortaria},
  {campo:"status_iucn_global", titulo:"IUCN global", st:corIucn}
];
var POR_PAGINA = 100;
var ordemCampo = "nome_cientifico", ordemAsc = true, pagina = 1;
var visiveis = ROWS;

function esc(s){
  return String(s == null ? "" : s)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

var cabecalho = document.getElementById("cabecalho");
cabecalho.innerHTML = COLUNAS.map(function(c){
  return '<th data-campo="' + c.campo + '"' + (c.esconde ? ' class="esconde"' : "") + ">" +
         esc(c.titulo) + '<span class="seta"></span></th>';
}).join("");

function aplicar(){
  var termo = semAcento(document.getElementById("busca").value.trim());
  var sel = {}, marc = [];
  Array.prototype.forEach.call(document.querySelectorAll("#filtros select"), function(s){
    if (s.value !== "" || s.selectedIndex > 0) sel[s.dataset.campo] = s.value;
  });
  Array.prototype.forEach.call(document.querySelectorAll("#marcas input"), function(i){
    i.parentNode.classList.toggle("on", i.checked);
    if (i.checked) marc.push(i.dataset.marca);
  });

  visiveis = ROWS.filter(function(o){
    if (termo && o._b.indexOf(termo) === -1) return false;
    for (var c in sel){ if (o[c] !== sel[c]) return false; }
    for (var i = 0; i < marc.length; i++){ if (o[marc[i]] !== 1) return false; }
    return true;
  });
  ordenar();
  pagina = 1;
  desenhar();
}

function ordenar(){
  var f = ordemCampo, s = ordemAsc ? 1 : -1;
  visiveis = visiveis.slice().sort(function(a,b){
    var x = a[f], y = b[f];
    if (x === y) return a.nome_cientifico.localeCompare(b.nome_cientifico, "pt-BR");
    if (x === "" || x == null) return 1;
    if (y === "" || y == null) return -1;
    if (typeof x === "number" && typeof y === "number") return (x - y) * s;
    return String(x).localeCompare(String(y), "pt-BR") * s;
  });
}

function desenhar(){
  var total = visiveis.length;
  document.getElementById("quantos").textContent = total.toLocaleString("pt-BR");
  document.getElementById("rotulo").textContent =
    (total === 1 ? "espécie" : "espécies") +
    (total === ROWS.length ? "" : " de " + ROWS.length.toLocaleString("pt-BR"));

  var paginas = Math.max(1, Math.ceil(total / POR_PAGINA));
  if (pagina > paginas) pagina = paginas;
  var ini = (pagina - 1) * POR_PAGINA;
  var fatia = visiveis.slice(ini, ini + POR_PAGINA);

  document.getElementById("vazio").style.display = total ? "none" : "block";

  var html = fatia.map(function(o){
    var tds = COLUNAS.map(function(c){
      var v = o[c.campo];
      var classe = c.cls || "";
      if (c.st){ classe = "st " + c.st(o); }
      if (c.esconde) classe += " esconde";
      var texto = (v === "" || v == null) ? "" : v;
      return '<td class="' + classe.trim() + '">' + esc(texto) + "</td>";
    }).join("");
    return '<tr data-id="' + o.id_ficha + '">' + tds + "</tr>";
  }).join("");
  document.getElementById("corpo").innerHTML = html;

  var p = document.getElementById("paginas");
  if (total <= POR_PAGINA){ p.innerHTML = ""; }
  else {
    p.innerHTML =
      '<button type="button" id="p-ant"' + (pagina === 1 ? " disabled" : "") + ">Anterior</button>" +
      "<span>Página " + pagina.toLocaleString("pt-BR") + " de " + paginas.toLocaleString("pt-BR") +
      " (" + (ini + 1).toLocaleString("pt-BR") + " a " +
      Math.min(ini + POR_PAGINA, total).toLocaleString("pt-BR") + ")</span>" +
      '<button type="button" id="p-prox"' + (pagina === paginas ? " disabled" : "") + ">Próxima</button>";
    document.getElementById("p-ant").onclick = function(){ if (pagina > 1){ pagina--; desenhar(); sobe(); } };
    document.getElementById("p-prox").onclick = function(){ if (pagina < paginas){ pagina++; desenhar(); sobe(); } };
  }

  Array.prototype.forEach.call(cabecalho.children, function(th){
    var ativo = th.dataset.campo === ordemCampo;
    th.classList.toggle("ativo", ativo);
    th.querySelector(".seta").textContent = ativo ? (ordemAsc ? "▲" : "▼") : "◆";
  });
}

function sobe(){
  var r = document.querySelector(".rolagem");
  if (r.scrollTop > 0) r.scrollTop = 0;
  else r.scrollIntoView({block:"start"});
}

// ---------------------------------------------------------------- gaveta de detalhe
var BLOCOS = [
  ["Taxonomia", ["nome_cientifico","nome_comum","grupo","classe","ordem","familia","endemica_brasil"]],
  ["Avaliação no SALVE", ["status_salve","ano_avaliacao_salve"]],
  ["Lista Nacional Oficial de 2026", ["status_portaria_2026","portaria_2026","nova_na_lista_2026",
                                      "mudou_salve_x_portaria","ameacada_salve_fora_portarias"]],
  ["Lista Vermelha global da IUCN", ["status_iucn_global","iucn_global_nome_aceito","iucn_global_match",
                                     "nacional_x_global","mudou_nacional_x_global"]],
  ["Referência", ["id_ficha"]]
];

function abrir(id){
  var o = null;
  for (var i = 0; i < ROWS.length; i++){ if (ROWS[i].id_ficha === id){ o = ROWS[i]; break; } }
  if (!o) return;
  document.getElementById("g-nome").textContent = o.nome_cientifico;
  document.getElementById("g-pop").textContent = o.nome_comum || "sem nome comum registrado";

  var h = [];
  BLOCOS.forEach(function(b){
    h.push('<div class="grupo">' + esc(b[0]) + "</div>");
    b[1].forEach(function(campo){
      var v = o[campo], texto;
      if (campo === "nova_na_lista_2026" || campo === "mudou_salve_x_portaria" ||
          campo === "ameacada_salve_fora_portarias" || campo === "mudou_nacional_x_global"){
        texto = v === 1 ? "Sim" : "Não";
      } else if (campo === "status_salve" || campo === "status_iucn_global"){
        var cor = campo === "status_salve" ? corSalve(o) : corIucn(o);
        texto = v === "" ? "sem categoria" : v + (CATEGORIA[v] ? " (" + CATEGORIA[v] + ")" : "");
        h.push("<dt>" + esc(ROTULO[campo]) + "</dt><dd><span class='selo " +
               (cor ? "st " + cor : "") + "'>" + esc(texto) + "</span></dd>");
        return;
      } else if (campo === "status_portaria_2026"){
        var c2 = corPortaria(o);
        h.push("<dt>" + esc(ROTULO[campo]) + "</dt><dd><span class='selo " +
               (c2 ? "st " + c2 : "") + "'>" + esc(v) + "</span></dd>");
        return;
      } else {
        texto = (v === "" || v == null) ? "sem informação" : v;
        if (campo === "portaria_2026" && texto !== "sem informação") texto = "Portaria " + texto + "/2026";
      }
      h.push("<dt>" + esc(ROTULO[campo]) + "</dt><dd>" + esc(texto) + "</dd>");
    });
  });
  document.getElementById("g-corpo").innerHTML = h.join("");
  document.getElementById("gaveta").classList.add("on");
  document.getElementById("gaveta").setAttribute("aria-hidden","false");
  document.getElementById("veu").classList.add("on");
}
function fechar(){
  document.getElementById("gaveta").classList.remove("on");
  document.getElementById("gaveta").setAttribute("aria-hidden","true");
  document.getElementById("veu").classList.remove("on");
  var s = document.querySelector("tbody tr.sel");
  if (s) s.classList.remove("sel");
}

// ---------------------------------------------------------------- exportar
function exportar(){
  var campos = COLS;
  var linhas = [campos.map(function(c){ return ROTULO[c] || c; }).join(",")];
  visiveis.forEach(function(o){
    linhas.push(campos.map(function(c){
      var v = o[c];
      v = (v == null) ? "" : String(v);
      return /[",\n;]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
    }).join(","));
  });
  var texto = "﻿" + linhas.join("\r\n");
  var blob = new Blob([texto], {type:"text/csv;charset=utf-8"});
  var a = document.createElement("a");
  var url = URL.createObjectURL(blob);
  a.href = url;
  a.download = "salve_fauna_filtrado_" + new Date().toISOString().slice(0,10) + ".csv";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(function(){ URL.revokeObjectURL(url); }, 1500);
}

// ---------------------------------------------------------------- eventos
var espera = null;
document.getElementById("busca").addEventListener("input", function(){
  clearTimeout(espera);
  espera = setTimeout(aplicar, 90);
});
document.getElementById("filtros").addEventListener("change", aplicar);
document.getElementById("marcas").addEventListener("change", aplicar);
document.getElementById("limpar").addEventListener("click", function(){
  document.getElementById("busca").value = "";
  Array.prototype.forEach.call(document.querySelectorAll("#filtros select"), function(s){ s.selectedIndex = 0; });
  Array.prototype.forEach.call(document.querySelectorAll("#marcas input"), function(i){ i.checked = false; });
  aplicar();
});
document.getElementById("exportar").addEventListener("click", exportar);
cabecalho.addEventListener("click", function(e){
  var th = e.target.closest("th");
  if (!th) return;
  var campo = th.dataset.campo;
  if (campo === ordemCampo) ordemAsc = !ordemAsc;
  else { ordemCampo = campo; ordemAsc = true; }
  ordenar();
  pagina = 1;
  desenhar();
});
document.getElementById("corpo").addEventListener("click", function(e){
  var tr = e.target.closest("tr");
  if (!tr) return;
  var s = document.querySelector("tbody tr.sel");
  if (s) s.classList.remove("sel");
  tr.classList.add("sel");
  abrir(parseInt(tr.dataset.id, 10));
});
document.getElementById("g-fechar").addEventListener("click", fechar);
document.getElementById("veu").addEventListener("click", fechar);
document.addEventListener("keydown", function(e){ if (e.key === "Escape") fechar(); });

aplicar();
})();
</script>
</body>
</html>
"""

html = (TEMPLATE
        .replace("__PAYLOAD__", dados_json)
        .replace("__DATA_GERACAO__", hoje)
        .replace("__EXPORT_SALVE__", EXPORT_SALVE)
        .replace("__DATA_ATUALIZACAO__", DATA_ATUALIZACAO)
        .replace("__URL_README__", URL_README)
        .replace("__N_ESPECIES__", f"{len(df):,}".replace(",", ".")))

os.makedirs(os.path.dirname(SAIDA) or ".", exist_ok=True)
with open(SAIDA, "w", encoding="utf-8") as f:
    f.write(html)

mb = os.path.getsize(SAIDA) / 1e6
print(f"gravado {SAIDA}: {mb:.2f} MB")
if mb > LIMITE_MB:
    print(f"ATENCAO: passou de {LIMITE_MB:.0f} MB")
