# -*- coding: utf-8 -*-
"""
Diagnostico: mostra exatamente o que a API do GBIF devolve para alguns nomes,
para decidir qual chave leva a categoria da IUCN. Nao grava nada.

Uso: python diagnostico_gbif.py
"""
import os, json, sys
TRUST = "nao carregado"
try:
    import truststore; truststore.inject_into_ssl(); TRUST = "ativo"
except ImportError:
    TRUST = "nao instalado"
except Exception as e:
    TRUST = f"falhou: {e}"
for v in ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_FILE"):
    p = os.environ.get(v)
    if p and not os.path.exists(p):
        del os.environ[v]; print(f"(ignorando {v} orfa)")
import requests

G = "https://api.gbif.org/v1"
S = requests.Session(); S.headers["User-Agent"] = "RSAGeo-SALVE-diag/1.0"
NOMES = ["Pauxi mitu", "Amadonastur lacernulatus", "Crypturellus zabele"]
CONTROLE = "Panthera onca"


def j(url, **params):
    try:
        r = S.get(url, params=params or None, timeout=30)
        return r.status_code, (r.json() if r.status_code == 200 and r.content else None)
    except Exception as e:
        return f"EXC {type(e).__name__}: {e}", None


def iucn(key):
    sc, d = j(f"{G}/species/{key}/iucnRedListCategory")
    return f"HTTP {sc} -> {(d or {}).get('code', '(sem code)')}"


print(f"truststore: {TRUST}\n")

# controle: confirma que datasetKey funciona como filtro
sc, d = j(f"{G}/species/search", q=CONTROLE, rank="SPECIES", limit=3,
          datasetKey="d7dddbf4-2cf0-4f39-9b2a-bb099caae36c")
print(f"CONTROLE search+backbone '{CONTROLE}': HTTP {sc}, "
      f"{len((d or {}).get('results', []))} resultados "
      f"(se for 0, o filtro datasetKey e o problema)\n")

for nome in NOMES:
    print("=" * 70)
    print(nome)
    print("=" * 70)

    sc, m = j(f"{G}/species/match", name=nome, kingdom="Animalia", strict="false")
    print(f"  MATCH: HTTP {sc}")
    if m:
        print("   ", {k: m.get(k) for k in
              ("matchType", "rank", "confidence", "usageKey", "acceptedUsageKey",
               "canonicalName", "genus", "note") if m.get(k) is not None})

    sc, sr = j(f"{G}/species/search", q=nome, rank="SPECIES", limit=8)
    res = (sr or {}).get("results", [])
    print(f"\n  SEARCH sem filtro: HTTP {sc}, {len(res)} resultados")
    exatos = [r for r in res if (r.get("canonicalName") or "").lower() == nome.lower()]
    print(f"  {len(exatos)} com canonicalName exato\n")

    chaves = set()
    for i, r in enumerate(exatos[:4]):
        print(f"   [{i}] {r.get('canonicalName')} | rank={r.get('rank')} | "
              f"status={r.get('taxonomicStatus')}")
        print(f"       key={r.get('key')}  nubKey={r.get('nubKey')}  "
              f"acceptedKey={r.get('acceptedKey')}  accepted={r.get('accepted')}")
        print(f"       dataset={r.get('datasetKey')}")
        for campo in ("key", "nubKey", "acceptedKey"):
            k = r.get(campo)
            if k and k not in chaves:
                chaves.add(k)
                print(f"       IUCN via {campo}={k}: {iucn(k)}")
        print()

    # o que o backbone diz sobre cada chave
    for k in list(chaves)[:6]:
        sc, t = j(f"{G}/species/{k}")
        if t:
            print(f"   taxon {k}: {t.get('scientificName')} | rank={t.get('rank')} | "
                  f"status={t.get('taxonomicStatus')} | accepted={t.get('accepted')} | "
                  f"acceptedKey={t.get('acceptedKey')} | nubKey={t.get('nubKey')} | "
                  f"origem={'BACKBONE' if t.get('datasetKey')=='d7dddbf4-2cf0-4f39-9b2a-bb099caae36c' else 'checklist'}")
    print()
