# -*- coding: utf-8 -*-
"""
Resolve apenas as especies pendentes do cache da IUCN, sem precisar do resto do pipeline.

Reconsulta no GBIF so quem ficou como HIGHERRANK ou sem match, usando a busca textual
que enxerga sinonimo sob outro genero (ex.: Pauxi mitu -> Mitu mitu), e regrava o cache.
Nao precisa do consolidado nem do XLSX: le e escreve so o iucn_global.csv.

Uso:  python resolve_iucn_pendentes.py [caminho\\do\\iucn_global.csv]
Sem argumento, procura iucn_global.csv na pasta atual.
"""
import sys, os, time, re, shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
try:                       # rede corporativa com proxy (Netskope)
    import truststore; truststore.inject_into_ssl()
except ImportError:
    pass
import requests

CACHE = sys.argv[1] if len(sys.argv) > 1 else "iucn_global.csv"
GBIF = "https://api.gbif.org/v1"
THREADS = 8
PENDENTES = ["HIGHERRANK", "sem match", "sem match (só gênero)", ""]

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "RSAGeo-SALVE-IUCN/1.0"
IUCN_PT = {"EX": "Extinta", "EW": "Extinta na Natureza", "CR": "Criticamente em Perigo", "EN": "Em Perigo",
           "VU": "Vulnerável", "NT": "Quase Ameaçada", "LC": "Menos Preocupante", "DD": "Dados Insuficientes",
           "NE": "Não Avaliada", "NA": "Não Aplicável"}


def get(url, params=None, tentativas=4):
    for i in range(tentativas):
        try:
            r = SESSION.get(url, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
        except requests.RequestException:
            pass
        time.sleep(1.5 * (i + 1))
    return None


def consultar(nome):
    out = {"nome_cientifico": nome, "gbif_key": "", "gbif_nome_aceito": "", "gbif_match": "",
           "gbif_confianca": "", "categoria_iucn_global": "", "iucn_codigo": "", "erro": ""}
    if re.search(r"\bsp\.|\bcf\.|\baff\.|'", nome):
        out["gbif_match"] = "nome provisório"; return out
    m = get(f"{GBIF}/species/match", {"name": nome, "kingdom": "Animalia", "strict": "false"})
    if not m or m.get("matchType") in (None, "NONE"):
        out["gbif_match"] = "sem match"; return out
    if m.get("matchType") == "HIGHERRANK":
        # so achou o genero: a busca textual enxerga sinonimo sob outro genero
        sr = get(f"{GBIF}/species/search", {"q": nome, "rank": "SPECIES", "limit": 20})
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
        acc = get(f"{GBIF}/species/{key}")
        if acc: out["gbif_nome_aceito"] = acc.get("canonicalName", out["gbif_nome_aceito"])
    r = get(f"{GBIF}/species/{key}/iucnRedListCategory")
    if r and r.get("code"):
        out["iucn_codigo"] = r["code"]
        out["categoria_iucn_global"] = IUCN_PT.get(r["code"], r.get("category", r["code"]))
    else:
        out["iucn_codigo"] = "NE"
        out["categoria_iucn_global"] = "Não Avaliada"
    return out


# ------------------------------------------------------------------ 1. carrega
if not os.path.exists(CACHE):
    print(f"ERRO: nao encontrei {CACHE}")
    print("Passe o caminho como argumento, por exemplo:")
    print(r'  python resolve_iucn_pendentes.py "C:\Users\AOGK\Downloads\iucn_global.csv"')
    sys.exit(1)

c = pd.read_csv(CACHE, dtype=str, keep_default_na=False)
c.columns = [x.lstrip("\ufeff") for x in c.columns]
print(f"cache: {CACHE}")
print(f"  {len(c)} especies")
print(f"  situacao atual: {c.gbif_match.value_counts().to_dict()}")

pend = c[c.gbif_match.isin(PENDENTES)].nome_cientifico.tolist()
if not pend:
    print("\nNada pendente. Cache ja esta completo.")
    sys.exit(0)
print(f"\n{len(pend)} especies a reconsultar no GBIF...")

# ------------------------------------------------------------------ 2. consulta
novos, t0 = [], time.time()
with ThreadPoolExecutor(THREADS) as ex:
    futs = {ex.submit(consultar, n): n for n in pend}
    for i, f in enumerate(as_completed(futs), 1):
        try:
            novos.append(f.result())
        except Exception as e:
            novos.append({"nome_cientifico": futs[f], "gbif_match": "erro", "erro": str(e)})
        if i % 50 == 0 or i == len(pend):
            print(f"  {i}/{len(pend)}  ({time.time()-t0:.0f}s)")

# ------------------------------------------------------------------ 3. regrava
shutil.copy(CACHE, CACHE + ".bak")
n = pd.DataFrame(novos)
c = pd.concat([c[~c.nome_cientifico.isin(pend)], n], ignore_index=True)
c = c.drop_duplicates("nome_cientifico", keep="last").sort_values("nome_cientifico")
c.to_csv(CACHE, index=False, encoding="utf-8-sig", lineterminator="\n")

resolvidas = int((~n.gbif_match.isin(PENDENTES) & (n.iucn_codigo != "")).sum())
print(f"\nRESOLVIDAS: {resolvidas} de {len(pend)}")
print(f"  novos matches : {n.gbif_match.value_counts().to_dict()}")
print(f"  categorias    : {n[n.iucn_codigo != ''].iucn_codigo.value_counts().to_dict()}")
print(f"\ngravado {CACHE} (backup em {CACHE}.bak)")
print("Agora mande esse arquivo de volta no chat.")
