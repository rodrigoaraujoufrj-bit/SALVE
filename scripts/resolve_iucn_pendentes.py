# -*- coding: utf-8 -*-
"""
Resolve apenas as especies pendentes do cache da IUCN, sem precisar do resto do pipeline.

Reconsulta no GBIF so quem ficou como HIGHERRANK ou sem match, usando a busca textual
que enxerga sinonimo sob outro genero (ex.: Pauxi mitu -> Mitu mitu), e regrava o cache.
Nao precisa do consolidado nem do XLSX: le e escreve so o iucn_global.csv.

Uso:  python resolve_iucn_pendentes.py [caminho\\do\\iucn_global.csv]
Sem argumento, procura iucn_global.csv na pasta atual.

Nao grava nada se a conexao com o GBIF falhar: faz um teste antes de comecar e
aborta mostrando o erro real, em vez de sobrescrever o cache com linhas vazias.
"""
import sys, os, time, re, shutil, threading, traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd

# REQUESTS_CA_BUNDLE apontando para arquivo que nao existe derruba o requests antes
# de qualquer conexao, com "Could not find a suitable TLS CA certificate bundle".
# Acontece quando o instalador do proxy corporativo grava o certificado numa pasta
# temporaria que o Windows depois limpa, deixando a variavel orfa. Nesse caso a
# variavel e ignorada e a validacao passa a ser feita pelo truststore, que usa o
# repositorio de certificados do Windows. A verificacao TLS continua ativa.
_ca_orfas = []
for _var in ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_FILE"):
    _p = os.environ.get(_var)
    if _p and not os.path.exists(_p):
        _ca_orfas.append((_var, _p))
        del os.environ[_var]

TRUSTSTORE = "nao carregado"
try:                       # rede corporativa com proxy (Netskope)
    import truststore
    truststore.inject_into_ssl()
    TRUSTSTORE = "ativo"
except ImportError:
    TRUSTSTORE = "nao instalado (ok fora da rede corporativa)"
except Exception as e:     # incompatibilidade de versao nao pode derrubar o script
    TRUSTSTORE = f"FALHOU: {type(e).__name__}: {e}"

import requests

CACHE = sys.argv[1] if len(sys.argv) > 1 else "iucn_global.csv"
GBIF = "https://api.gbif.org/v1"
THREADS = 8
PENDENTES = ["HIGHERRANK", "sem match", "sem match (só gênero)", "erro", ""]
COLUNAS = ["nome_cientifico", "gbif_key", "gbif_nome_aceito", "gbif_match",
           "gbif_confianca", "categoria_iucn_global", "iucn_codigo", "erro"]

IUCN_PT = {"EX": "Extinta", "EW": "Extinta na Natureza", "CR": "Criticamente em Perigo", "EN": "Em Perigo",
           "VU": "Vulnerável", "NT": "Quase Ameaçada", "LC": "Menos Preocupante", "DD": "Dados Insuficientes",
           "NE": "Não Avaliada", "NA": "Não Aplicável"}

# uma Session por thread: requests.Session nao e thread-safe
_local = threading.local()
def sessao():
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
        _local.s.headers["User-Agent"] = "RSAGeo-SALVE-IUCN/1.0"
    return _local.s


def get(url, params=None, tentativas=4):
    """devolve (json, erro). erro vazio quando deu certo ou quando foi 404 legitimo."""
    ultimo = ""
    for i in range(tentativas):
        try:
            r = sessao().get(url, params=params, timeout=30)
            if r.status_code == 200:
                return r.json(), ""
            if r.status_code == 404:
                return None, ""
            ultimo = f"HTTP {r.status_code}"
        except Exception as e:                 # qualquer erro, nao so RequestException
            ultimo = f"{type(e).__name__}: {e}"
        if i < tentativas - 1:
            time.sleep(1.5 * (i + 1))
    return None, ultimo


def consultar(nome):
    out = dict.fromkeys(COLUNAS, "")
    out["nome_cientifico"] = nome
    if re.search(r"\bsp\.|\bcf\.|\baff\.|'", nome):
        out["gbif_match"] = "nome provisório"; return out
    m, err = get(f"{GBIF}/species/match", {"name": nome, "kingdom": "Animalia", "strict": "false"})
    if err:
        out["gbif_match"] = "erro"; out["erro"] = err; return out
    if not m or m.get("matchType") in (None, "NONE"):
        out["gbif_match"] = "sem match"; return out
    if m.get("matchType") == "HIGHERRANK":
        # so achou o genero: a busca textual enxerga sinonimo sob outro genero
        sr, err = get(f"{GBIF}/species/search", {"q": nome, "rank": "SPECIES", "limit": 20})
        if err:
            out["gbif_match"] = "erro"; out["erro"] = err; return out
        cand = [r for r in (sr or {}).get("results", []) if r.get("canonicalName", "").lower() == nome.lower()]
        if not cand:
            out["gbif_match"] = "sem match (só gênero)"; return out
        c = cand[0]
        m = {"matchType": "SEARCH", "confidence": 90, "usageKey": c.get("key"),
             "acceptedUsageKey": c.get("acceptedKey"), "canonicalName": c.get("canonicalName", "")}
    out["gbif_match"] = m.get("matchType", "")
    out["gbif_confianca"] = m.get("confidence", "")
    if m.get("matchType") == "FUZZY" and m.get("confidence", 0) < 90:
        out["gbif_match"] = "fuzzy fraco"; return out
    key = m.get("acceptedUsageKey") or m.get("usageKey")
    out["gbif_key"] = key
    out["gbif_nome_aceito"] = m.get("canonicalName", "")
    if m.get("acceptedUsageKey"):
        acc, _ = get(f"{GBIF}/species/{key}")
        if acc: out["gbif_nome_aceito"] = acc.get("canonicalName", out["gbif_nome_aceito"])
    r, err = get(f"{GBIF}/species/{key}/iucnRedListCategory")
    if err:
        out["gbif_match"] = "erro"; out["erro"] = err; return out
    if r and r.get("code"):
        out["iucn_codigo"] = r["code"]
        out["categoria_iucn_global"] = IUCN_PT.get(r["code"], r.get("category", r["code"]))
    else:
        out["iucn_codigo"] = "NE"
        out["categoria_iucn_global"] = "Não Avaliada"
    return out


# ------------------------------------------------------------------ 1. carrega
print(f"truststore: {TRUSTSTORE}")
for _var, _p in _ca_orfas:
    print(f"aviso: {_var} apontava para arquivo inexistente e foi ignorada")
    print(f"       {_p}")
    print("       a validacao TLS passa a usar o repositorio de certificados do Windows")
if not os.path.exists(CACHE):
    print(f"\nERRO: nao encontrei {CACHE}")
    sys.exit(1)

c = pd.read_csv(CACHE, dtype=str, keep_default_na=False)
c.columns = [x.lstrip("﻿") for x in c.columns]
for col in COLUNAS:
    if col not in c.columns:
        c[col] = ""
print(f"cache: {CACHE}")
print(f"  {len(c)} especies")
print(f"  situacao atual: {c.gbif_match.value_counts().to_dict()}")

pend = c[c.gbif_match.isin(PENDENTES)].nome_cientifico.tolist()
if not pend:
    print("\nNada pendente. Cache ja esta completo.")
    sys.exit(0)

# ------------------------------------------------------------------ 2. teste de conexao
print(f"\ntestando conexao com o GBIF...")
teste, err = get(f"{GBIF}/species/match", {"name": "Panthera onca", "kingdom": "Animalia"}, tentativas=2)
if err or not teste:
    print(f"\n  FALHOU: {err or 'resposta vazia'}")
    print("\n  Nada foi gravado, seu cache esta intacto.")
    print("  Diagnostico detalhado:")
    try:
        r = sessao().get(f"{GBIF}/species/match", params={"name": "Panthera onca"}, timeout=30)
        print(f"    HTTP {r.status_code}, {len(r.content)} bytes")
    except Exception:
        print("   " + traceback.format_exc().replace("\n", "\n    "))
    print("\n  Causas comuns: proxy corporativo bloqueando api.gbif.org, ou")
    print("  variaveis HTTP_PROXY/HTTPS_PROXY nao configuradas nesta sessao.")
    sys.exit(2)
print(f"  ok ({teste.get('canonicalName','?')} respondeu)")

# ------------------------------------------------------------------ 3. consulta
print(f"\n{len(pend)} especies a reconsultar...")
novos, t0 = [], time.time()
with ThreadPoolExecutor(THREADS) as ex:
    futs = {ex.submit(consultar, n): n for n in pend}
    for i, f in enumerate(as_completed(futs), 1):
        try:
            novos.append(f.result())
        except Exception as e:
            d = dict.fromkeys(COLUNAS, ""); d["nome_cientifico"] = futs[f]
            d["gbif_match"] = "erro"; d["erro"] = f"{type(e).__name__}: {e}"
            novos.append(d)
        if i % 50 == 0 or i == len(pend):
            print(f"  {i}/{len(pend)}  ({time.time()-t0:.0f}s)")

n = pd.DataFrame(novos, columns=COLUNAS).fillna("")

# ------------------------------------------------------------------ 4. resumo antes de gravar
erros = n[n.gbif_match == "erro"]
resolvidas = int(((~n.gbif_match.isin(PENDENTES)) & (n.iucn_codigo != "")).sum())
print(f"\nRESOLVIDAS: {resolvidas} de {len(pend)}")
print(f"  matches   : {n.gbif_match.value_counts().to_dict()}")
if resolvidas:
    print(f"  categorias: {n[n.iucn_codigo != ''].iucn_codigo.value_counts().to_dict()}")
if len(erros):
    print(f"\n  {len(erros)} com erro de rede. Primeiros:")
    for _, r in erros.head(3).iterrows():
        print(f"    {r.nome_cientifico}: {r.erro}")

if resolvidas == 0:
    print("\nNada resolvido. Cache NAO foi alterado.")
    sys.exit(3)

# ------------------------------------------------------------------ 5. grava
shutil.copy(CACHE, CACHE + ".bak")
c = pd.concat([c[~c.nome_cientifico.isin(pend)], n], ignore_index=True)
c = c.drop_duplicates("nome_cientifico", keep="last").sort_values("nome_cientifico")
c[COLUNAS].to_csv(CACHE, index=False, encoding="utf-8-sig", lineterminator="\n")
print(f"\ngravado {CACHE} (backup em {CACHE}.bak)")
print("Agora mande esse arquivo de volta no chat.")
