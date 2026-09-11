# -*- coding: utf-8 -*-
"""
Busca no iNaturalist uma foto de licenca livre para cada especie, e grava
saida/fotos_inat.csv, consumido depois pelo gera_html.py.

So aceita foto com licenca Creative Commons. A foto padrao do iNaturalist
costuma ser "todos os direitos reservados" (license_code nulo), que nao pode
ser exibida em pagina institucional: nesses casos o script procura outra foto
do mesmo taxon que tenha licenca livre.

Respeita o limite pedido pelo iNaturalist: 60 requisicoes por minuto.

Uso:  python busca_fotos_inat.py [status_comparado.csv] [fotos_inat.csv]
      --todas    consulta as 15 mil especies em vez do subconjunto relevante
                 (estoura a cota diaria de 10 mil e leva umas 4 horas)

Por padrao consulta apenas as especies que importam: ameacadas no SALVE,
listadas nas portarias de 2026, ou ameacadas/extintas na IUCN.
"""
import sys, os, time, csv, threading, traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd

TRUSTSTORE = "nao carregado"
try:
    import truststore; truststore.inject_into_ssl(); TRUSTSTORE = "ativo"
except ImportError:
    TRUSTSTORE = "nao instalado (ok fora da rede corporativa)"
except Exception as e:
    TRUSTSTORE = f"FALHOU: {type(e).__name__}: {e}"

_ca_orfas = []
for _var in ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_FILE"):
    _p = os.environ.get(_var)
    if _p and not os.path.exists(_p):
        _ca_orfas.append((_var, _p)); del os.environ[_var]

import requests

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
TODAS = "--todas" in sys.argv
ENTRADA = ARGS[0] if ARGS else "saida/status_comparado.csv"
SAIDA = ARGS[1] if len(ARGS) > 1 else "saida/fotos_inat.csv"

INAT = "https://api.inaturalist.org/v1"
THREADS = 4
POR_MINUTO = 60          # limite pedido pelo iNaturalist

# Ordem de preferencia. Licenca nula (todos os direitos reservados) fica de fora:
# nao pode ser exibida. As NC (nao comercial) vem por ultimo de proposito, entao a
# foto registrada e sempre a melhor sob a politica mais restritiva quando existe uma.
# Elas sao registradas mesmo assim, para que mudar a politica depois nao exija
# reconsultar: quem decide se entram na pagina e a constante LICENCAS_ACEITAS do
# gera_html.py.
LICENCAS = ["cc0", "cc-by", "cc-by-sa", "cc-by-nd",
            "cc-by-nc", "cc-by-nc-sa", "cc-by-nc-nd"]
PESO = {l: i for i, l in enumerate(LICENCAS)}
COLUNAS = ["nome_cientifico", "taxon_id", "foto_id", "host", "licenca", "autor", "erro"]

AMEACADAS = {"CR", "EN", "VU"}
GLOBAIS = {"CR", "EN", "VU", "EX", "EW"}


class Limite:
    """espaca as chamadas para nao passar de POR_MINUTO, somando todas as threads"""
    def __init__(self, por_minuto):
        self.intervalo = 60.0 / por_minuto
        self.lock = threading.Lock()
        self.proximo = 0.0

    def espera(self):
        with self.lock:
            agora = time.monotonic()
            if self.proximo < agora:
                self.proximo = agora
            atraso = self.proximo - agora
            self.proximo += self.intervalo
        if atraso > 0:
            time.sleep(atraso)


limite = Limite(POR_MINUTO)
_local = threading.local()


def sessao():
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
        _local.s.headers["User-Agent"] = "RSAGeo-SALVE-fotos/1.0 (consulta de fauna ameacada)"
    return _local.s


def get(url, params=None, tentativas=3):
    ultimo = ""
    for i in range(tentativas):
        limite.espera()
        try:
            r = sessao().get(url, params=params, timeout=30)
            if r.status_code == 200:
                return r.json(), ""
            if r.status_code in (204, 404):
                return None, ""
            if r.status_code == 429:            # excedeu a cota: espera mais
                ultimo = "HTTP 429 (limite de requisicoes)"
                time.sleep(20 * (i + 1)); continue
            ultimo = f"HTTP {r.status_code}"
        except Exception as e:
            ultimo = f"{type(e).__name__}: {e}"
        time.sleep(2 * (i + 1))
    return None, ultimo


def host_de(url):
    """s3 = balde de dados abertos, static = servidor principal"""
    return "s3" if "inaturalist-open-data" in (url or "") else "static"


def escolher(fotos):
    """melhor foto com licenca livre, ou None"""
    livres = []
    for f in fotos:
        lic = (f.get("license_code") or "").lower()
        if lic in PESO and f.get("id"):
            livres.append((PESO[lic], f, lic))
    if not livres:
        return None
    livres.sort(key=lambda x: x[0])
    _, f, lic = livres[0]
    url = f.get("medium_url") or f.get("url") or ""
    return {"foto_id": f["id"], "host": host_de(url), "licenca": lic,
            "autor": (f.get("attribution_name") or "").strip()}


def consultar(nome):
    out = dict.fromkeys(COLUNAS, ""); out["nome_cientifico"] = nome
    d, err = get(f"{INAT}/taxa", {"q": nome, "rank": "species,subspecies", "per_page": 10})
    if err:
        out["erro"] = err; return out
    exatos = [r for r in (d or {}).get("results", [])
              if (r.get("name") or "").lower() == nome.lower() and r.get("is_active")]
    if not exatos:
        return out                        # sem taxon: sai com tudo vazio
    t = exatos[0]
    out["taxon_id"] = t["id"]

    # 1) a foto padrao ja serve?
    escolha = escolher([t["default_photo"]] if t.get("default_photo") else [])
    # 2) senao, procura entre as fotos do taxon uma com licenca livre
    if not escolha:
        det, err = get(f"{INAT}/taxa/{t['id']}")
        if err:
            out["erro"] = err; return out
        res = (det or {}).get("results") or [{}]
        escolha = escolher([tp.get("photo", {}) for tp in res[0].get("taxon_photos", [])])
    if escolha:
        out.update(escolha)
    return out


# ------------------------------------------------------------------ 1. lista
print(f"truststore: {TRUSTSTORE}")
for v, p in _ca_orfas:
    print(f"aviso: {v} apontava para arquivo inexistente e foi ignorada")

t = pd.read_csv(ENTRADA, dtype=str, keep_default_na=False)
t.columns = [c.lstrip("﻿") for c in t.columns]
if TODAS:
    alvo = t.nome_cientifico.tolist()
    print(f"\n--todas: {len(alvo)} especies. Isso passa da cota diaria de 10 mil do")
    print("iNaturalist e leva uma 4 horas. O script e retomavel, entao pode parar e voltar.")
else:
    m = (t.status_salve.isin(AMEACADAS) | (t.status_portaria_2026 != "não listada")
         | t.status_iucn_global.isin(GLOBAIS))
    alvo = t[m].nome_cientifico.tolist()
    print(f"\nsubconjunto relevante: {len(alvo)} especies")
    print("  (ameacadas no SALVE, listadas nas portarias, ou ameacadas/extintas na IUCN)")
    print("  use --todas para consultar as 15 mil")

feito = {}
if os.path.exists(SAIDA):
    c = pd.read_csv(SAIDA, dtype=str, keep_default_na=False)
    c.columns = [x.lstrip("﻿") for x in c.columns]
    feito = {r.nome_cientifico: r._asdict() for r in c.itertuples(index=False)}
    print(f"  cache: {len(feito)} ja consultadas")

pend = [n for n in alvo if n not in feito]
if not pend:
    print("\nNada pendente.")
    sys.exit(0)
print(f"  a consultar: {len(pend)}  (cerca de {len(pend)/POR_MINUTO:.0f} min no ritmo permitido)")

# ------------------------------------------------------------------ 2. conexao
print("\ntestando conexao com o iNaturalist...")
teste, err = get(f"{INAT}/taxa", {"q": "Panthera onca", "per_page": 1}, tentativas=2)
if err or not teste:
    print(f"\n  FALHOU: {err or 'resposta vazia'}")
    print("  Nada foi gravado.")
    try:
        r = sessao().get(f"{INAT}/taxa", params={"q": "Panthera onca"}, timeout=30)
        print(f"    HTTP {r.status_code}")
    except Exception:
        print("   " + traceback.format_exc().replace("\n", "\n    "))
    sys.exit(2)
print("  ok")

# ------------------------------------------------------------------ 3. busca
novos, t0 = [], time.time()
with ThreadPoolExecutor(THREADS) as ex:
    futs = {ex.submit(consultar, n): n for n in pend}
    for i, f in enumerate(as_completed(futs), 1):
        try:
            novos.append(f.result())
        except Exception as e:
            d = dict.fromkeys(COLUNAS, ""); d["nome_cientifico"] = futs[f]
            d["erro"] = f"{type(e).__name__}: {e}"
            novos.append(d)
        if i % 100 == 0 or i == len(pend):
            falta = (len(pend) - i) / POR_MINUTO
            print(f"  {i}/{len(pend)}  {time.time()-t0:.0f}s  (faltam ~{falta:.0f} min)")
            # grava parcial: a rodada e longa, nao pode perder o que ja veio
            pd.concat([pd.DataFrame(list(feito.values())) if feito else pd.DataFrame(columns=COLUNAS),
                       pd.DataFrame(novos, columns=COLUNAS)], ignore_index=True) \
              .drop_duplicates("nome_cientifico", keep="last") \
              .to_csv(SAIDA, index=False, encoding="utf-8-sig", lineterminator="\n")

# ------------------------------------------------------------------ 4. resumo
n = pd.DataFrame(novos, columns=COLUNAS).fillna("")
com = n[n.foto_id != ""]
print(f"\nCOM FOTO LIVRE: {len(com)} de {len(pend)}")
if len(com):
    print(f"  licencas: {com.licenca.value_counts().to_dict()}")
    print(f"  servidor: {com.host.value_counts().to_dict()}")
print(f"  sem taxon no iNaturalist ou so com foto restrita: {len(n) - len(com) - (n.erro != '').sum()}")
if (n.erro != "").sum():
    print(f"  com erro de rede: {(n.erro != '').sum()}")
print(f"\ngravado {SAIDA}")
print("Mande esse arquivo de volta no chat.")
