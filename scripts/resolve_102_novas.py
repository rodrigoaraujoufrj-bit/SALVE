# -*- coding: utf-8 -*-
"""
Consulta as 102 especies novas da exportacao unica do SALVE, sem precisar do resto do pipeline.

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

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
TESTE = "--teste" in sys.argv
CACHE = ARGS[0] if ARGS else "iucn_global.csv"
GBIF = "https://api.gbif.org/v1"
THREADS = 8
PENDENTES = ["HIGHERRANK", "sem match", "erro"]   # "sem match (só gênero)" ja confirmado sem caminho no GBIF
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
            if r.status_code in (204, 404):
                return None, ""      # sem conteudo: o taxon nao tem categoria
            ultimo = f"HTTP {r.status_code}"
        except Exception as e:                 # qualquer erro, nao so RequestException
            ultimo = f"{type(e).__name__}: {e}"
        if i < tentativas - 1:
            time.sleep(1.5 * (i + 1))
    return None, ultimo


def resolver_backbone(chave):
    """
    Leva uma chave de catalogo ate a chave do backbone (nubKey), que e a unica que
    o endpoint iucnRedListCategory entende. Devolve (chave_backbone, nome_aceito).

    O nubKey nao vem no resultado de /species/search: so aparece no detalhe do taxon.
    E quando o registro e sinonimo, quem carrega o nubKey e o taxon aceito, nao ele.
    Ex.: Pauxi mitu (sinonimo, sem nub) -> Mitu mitu -> nubKey 2482280.
    """
    t, _ = get(f"{GBIF}/species/{chave}")
    if not t:
        return None, ""
    if t.get("nubKey"):
        return t["nubKey"], t.get("canonicalName", "")
    ak = t.get("acceptedKey")
    if not ak:
        return None, ""
    a, _ = get(f"{GBIF}/species/{ak}")
    if not a:
        return None, ""
    if a.get("nubKey"):
        return a["nubKey"], a.get("canonicalName", "")
    # o aceito tambem nao tem nub: tenta casar o nome dele direto no backbone
    nome_ac = a.get("canonicalName") or ""
    if nome_ac:
        mm, _ = get(f"{GBIF}/species/match", {"name": nome_ac, "kingdom": "Animalia"})
        if mm and mm.get("matchType") not in (None, "NONE", "HIGHERRANK"):
            return (mm.get("acceptedUsageKey") or mm.get("usageKey")), mm.get("canonicalName", nome_ac)
    return None, ""


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
        # o nome nao esta no backbone (foi isso que fez o match parar no genero).
        # A busca sem filtro alcanca os demais catalogos; de la, resolver_backbone
        # segue ate o nubKey, que e a chave aceita pelo endpoint da IUCN.
        sr, err = get(f"{GBIF}/species/search", {"q": nome, "rank": "SPECIES", "limit": 20})
        if err:
            out["gbif_match"] = "erro"; out["erro"] = err; return out
        cand = [r for r in (sr or {}).get("results", [])
                if (r.get("canonicalName") or "").lower() == nome.lower() and r.get("key")]
        # sinonimos primeiro: sao os que apontam para o nome aceito atual
        cand.sort(key=lambda r: 0 if r.get("acceptedKey") else 1)
        chave, aceito = None, ""
        for r in cand[:4]:
            chave, aceito = resolver_backbone(r["key"])
            if chave:
                break
        if not chave:
            out["gbif_match"] = "sem match (só gênero)"; return out
        m = {"matchType": "SEARCH", "confidence": 90, "usageKey": chave,
             "acceptedUsageKey": None, "canonicalName": aceito}
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

# as 102 especies que so existem na exportacao unica do SALVE e nunca foram
# consultadas. Lista fixa para dispensar o consolidado, que e um arquivo de 24 MB.
NOVAS = [
"Abiliodesmus cataractae",
"Amnesteophis melanauchen",
"Asthenopodes picteti",
"Axelsonia littoralis",
"Balaenoptera omurai",
"Bothrops alcatraz",
"Bothrops germanoi",
"Bothrops insularis",
"Bothrops otavioi",
"Brachystomella aspera",
"Caecilia armata",
"Cavia intermedia",
"Cephalorhynchus commersonii",
"Ceratoscopelus maderensis",
"Chthonerpeton exile",
"Clavisotoma filifera",
"Cornalatus tabulus",
"Cryptopygus pentatomus",
"Cycloramphus faustoi",
"Diaphus holti",
"Dipturus teevani",
"Echinorhinus brucus",
"Eresia erysice",
"Etmopterus gracilispinis",
"Etmopterus granulosus",
"Etmopterus lucifer",
"Eukerria garmani",
"Facciolella oxyrhyncha",
"Falco tinnunculus",
"Fregata aquila",
"Glossoscolex giganteus",
"Glossoscolex grandis",
"Glossoscolex klossae",
"Gurgesiella dorsalifera",
"Gymnoscopelus braueri",
"Heraclides torquatus",
"Hydrolagus affinis",
"Hydrolagus matallanasi",
"Hypanus say",
"Hypostomus meleagris",
"Hypselotropis limodes",
"Ischnotelson guanambiensis",
"Ischnura hastata",
"Isistius brasiliensis",
"Isistius plutodus",
"Johngarthia lagostoma",
"Lampadena anomala",
"Lampadena chavesi",
"Leptohyphes mollipes",
"Leptonychotes weddellii",
"Leucophaeus modestus",
"Malacoraja obscura",
"Megachasma pelagios",
"Meridiorhantus orbignyi",
"Microcaecilia supernumeraria",
"Micropholcus brazlandia",
"Mimosiphonops reinhardti",
"Morus bassanus",
"Mustelus schmitti",
"Myliobatis ridens",
"Neacomys marajoara",
"Nemamyxine kreffti",
"Neoplecostomus botucatu",
"Norops williamsii",
"Oxyrhopus occipitalis",
"Parastacus laevigatus",
"Paraxenylla zelliae",
"Phocoena dioptrica",
"Picumnus castelnau",
"Principestreptus sulcanus",
"Proisotoma subminuta",
"Psammobatis bergi",
"Psammobatis lentiginosa",
"Psammobatis rutrum",
"Psenes maculatus",
"Pseudocarcharias kamoharai",
"Rajella bigelowi",
"Rajella purpuriventralis",
"Rajella sadowskii",
"Rhinocricus insularis",
"Rineloricaria konopickyi",
"Rineloricaria lima",
"Schroederichthys bivius",
"Schroederichthys saurisqualus",
"Scinax alcatraz",
"Scinax peixotoi",
"Scyliorhinus boa",
"Scyliorhinus cabofriensis",
"Somniosus antarcticus",
"Squaliolus laticaudus",
"Squalus acanthias",
"Squalus bahiensis",
"Squalus lobularis",
"Squalus quasimodo",
"Squatina argentina",
"Stenocercus tricristatus",
"Tatochila mercedis",
"Tessarithys machaerophorus",
"Tetronarce nobiliana",
"Trichomycterus punctatissimus",
"Xenylla subcavernarum",
"Zearaja brevicaudata"
]

pend = [n for n in NOVAS if n not in set(c.nome_cientifico)]
pend += c[c.gbif_match.isin(PENDENTES)].nome_cientifico.tolist()
pend = list(dict.fromkeys(pend))
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

# ------------------------------------------------------------------ 2b. modo teste
if TESTE:
    CONTROLE = [
        ("Pauxi mitu", "deve resolver para Mitu mitu (nubKey 2482280) com categoria real"),
        ("Amadonastur lacernulatus", "deve resolver para Buteogallus lacernulatus (nubKey 7537530)"),
        ("Dendrocincla taunayi", "arapacu, EN no SALVE"),
        ("Crypturellus zabele", "sem caminho para o backbone: deve seguir sem categoria"),
    ]
    print("\n" + "=" * 62)
    print("MODO TESTE: nada sera gravado")
    print("=" * 62)
    for nome, nota in CONTROLE:
        r = consultar(nome)
        print(f"\n{nome}")
        print(f"  esperado : {nota}")
        print(f"  match    : {r['gbif_match']}  (chave GBIF {r['gbif_key'] or 'nenhuma'})")
        print(f"  aceito   : {r['gbif_nome_aceito'] or 'nao resolvido'}")
        print(f"  IUCN     : {r['iucn_codigo'] or 'vazio'}  {r['categoria_iucn_global']}")
        if r["erro"]:
            print(f"  erro     : {r['erro']}")
    print("\n" + "=" * 62)
    print("Se 'Pauxi mitu' resolver para Mitu mitu com categoria diferente de NE, funcionou.")
    print("Rode entao sem --teste para processar as 568.")
    sys.exit(0)

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
