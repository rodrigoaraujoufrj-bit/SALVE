# -*- coding: utf-8 -*-
"""
Consolida as exportações por bioma do SALVE (ICMBio) em um único CSV limpo.

Uso local:  python consolida_salve.py <pasta_com_csvs> <saida.csv>
"""
import sys, glob, os, re
import pandas as pd

PASTA = sys.argv[1] if len(sys.argv) > 1 else "."
SAIDA = sys.argv[2] if len(sys.argv) > 2 else "salve_fauna_consolidado.csv"
SEP_MULTI = "; "   # separador único para todos os campos multivalorados

BIOMAS = {
    "Amazônia": "amazonia", "Caatinga": "caatinga", "Cerrado": "cerrado",
    "Mata Atlântica": "mata_atlantica", "Pampa": "pampa", "Pantanal": "pantanal",
    "Sistema Costeiro-Marinho": "marinho",
}
REGIOES = ["Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul"]
CATEGORIA_SIGLA = {
    "Extinta": "EX", "Extinta na Natureza": "EW", "Regionalmente Extinta": "RE",
    "Criticamente em Perigo": "CR", "Em Perigo": "EN", "Vulnerável": "VU",
    "Quase Ameaçada": "NT", "Menos Preocupante": "LC", "Dados Insuficientes": "DD",
    "Não Aplicável": "NA",
}
AMEACADAS = {"CR", "EN", "VU"}


def lista(valor, sep_regex):
    """quebra string multivalorada, remove vazios e duplicatas mantendo ordem"""
    if not valor:
        return []
    itens = [i.strip() for i in re.split(sep_regex, valor)]
    vistos, out = set(), []
    for i in itens:
        if i and i not in vistos:
            vistos.add(i); out.append(i)
    return out


def junta(itens):
    return SEP_MULTI.join(itens)


def corrige_caixa_uc(nome):
    """'ÁREA DE PROTEçãO' -> 'ÁREA DE PROTEÇÃO'; nomes em Title Case ficam como estão"""
    letras = [c for c in nome if c.isalpha()]
    if letras and sum(c.isupper() for c in letras) / len(letras) > 0.7:
        return nome.upper()
    return nome


def min_max(valor):
    if not valor:
        return (None, None)
    nums = re.findall(r"-?\d+(?:[.,]\d+)?", valor)
    nums = [float(n.replace(",", ".")) for n in nums]
    if not nums:
        return (None, None)
    return (min(nums), max(nums))


# ---------------------------------------------------------------- leitura
arquivos = sorted(glob.glob(os.path.join(PASTA, "*.csv")))
partes = []
for f in arquivos:
    d = pd.read_csv(f, dtype=str, keep_default_na=False, encoding="utf-8")
    d["arquivo_origem"] = os.path.basename(f)
    partes.append(d)
    print(f"lido {os.path.basename(f)}: {len(d)} linhas")
bruto = pd.concat(partes, ignore_index=True)
_ctrl = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
bruto = bruto.apply(lambda c: c.str.replace(_ctrl, "", regex=True))
print(f"total bruto: {len(bruto)}")

# ---------------------------------------------------------------- dedup
chave = ["especie", "subespecie"]
bruto["subespecie"] = bruto["subespecie"].str.strip()
cols_conteudo = [c for c in bruto.columns if c not in chave + ["arquivo_origem"]]
divergentes = bruto.groupby(chave)[cols_conteudo].nunique().gt(1).any(axis=1).sum()
print(f"espécies com ficha divergente entre biomas: {divergentes}")
df = bruto.drop_duplicates(subset=chave, keep="first").drop(columns="arquivo_origem").reset_index(drop=True)
print(f"após dedup: {len(df)} fichas únicas")

# ---------------------------------------------------------------- normalização
df.insert(0, "id_ficha", range(1, len(df) + 1))
# subespecie já traz o trinômio completo no SALVE
# subespecie pode vir só com o epíteto ("morio") ou com o trinômio inteiro ("Actinote morio morio"), conforme a exportação
def nome_completo(r):
    sub, esp = r["subespecie"].strip(), r["especie"].strip()
    if not sub: return esp
    return sub if sub.lower().startswith(esp.lower()) else f"{esp} {sub}"
df.insert(1, "nome_cientifico", df.apply(nome_completo, axis=1))
df["subespecie"] = df.apply(lambda r: r["nome_cientifico"][len(r["especie"].strip()):].strip() if r["subespecie"].strip() else "", axis=1)

# campos separados por vírgula
for c in ["estado", "bioma", "unidade_de_conservacao_federal", "rppn",
          "acao_conservacao", "plano_de_acao", "listas_e_convencoes"]:
    df[c] = df[c].apply(lambda v: junta(lista(v, r",\s*")))
df["unidade_de_conservacao_estadual"] = df["unidade_de_conservacao_estadual"].apply(
    lambda v: junta([corrige_caixa_uc(i) for i in lista(v, r",\s*")]))

# campos separados por quebra de linha
for c in ["bacia_hidrografica", "ameaca", "uso"]:
    df[c] = df[c].apply(lambda v: junta(lista(v, r"\r?\n")))
df["justificativa"] = df["justificativa"].str.replace(r"\s*\r?\n\s*", " ", regex=True).str.strip()

# região: '|Norte|Sul|' -> 'Norte; Sul' + flags
df["regiao"] = df["regiao"].apply(lambda v: junta(lista(v, r"\|")))
for r in REGIOES:
    df["reg_" + r.lower().replace("-", "_")] = df["regiao"].str.contains(r, regex=False).astype(int)

# bioma: flags e contagem
for nome, slug in BIOMAS.items():
    df["bioma_" + slug] = df["bioma"].str.contains(nome, regex=False).astype(int)
df["n_biomas"] = df[["bioma_" + s for s in BIOMAS.values()]].sum(axis=1)
df["n_estados"] = df["estado"].apply(lambda v: len(lista(v, r";\s*")))

# categoria IUCN
df["categoria_sigla"] = df["categoria"].map(CATEGORIA_SIGLA)
df["ameacada"] = df["categoria_sigla"].isin(AMEACADAS).astype(int)

# avaliação: mês/ano -> ano e data
dt = pd.to_datetime(df["mesano_avaliacao"], format="%m/%Y", errors="coerce")
df["ano_avaliacao"] = dt.dt.year.astype("Int64")
df["data_avaliacao"] = dt.dt.strftime("%Y-%m-01")

# altitude e batimetria -> numérico
for c, novo in [("altitudeminmax", "altitude"), ("barimetriaminmax", "batimetria")]:
    mm = df[c].apply(min_max)
    df[novo + "_min"] = [m[0] for m in mm]
    df[novo + "_max"] = [m[1] for m in mm]
df = df.drop(columns=["altitudeminmax", "barimetriaminmax"])

# reino é constante (Animalia): mantido apenas por completude taxonômica
# ordem final das colunas
ordem = (
    ["id_ficha", "nome_cientifico", "reino", "filo", "classe", "ordem", "familia", "genero",
     "especie", "subespecie", "nome_cientifico_anterior", "autor", "nome_comum", "grupo",
     "mesano_avaliacao", "ano_avaliacao", "data_avaliacao",
     "categoria", "categoria_sigla", "ameacada", "possivemente_extinta", "criterio",
     "endemica_brasil", "consta_em_lista_nacional_oficial", "migratoria", "tendencia_populacional",
     "regiao"] + ["reg_" + r.lower().replace("-", "_") for r in REGIOES] +
    ["estado", "n_estados", "bioma", "n_biomas"] + ["bioma_" + s for s in BIOMAS.values()] +
    ["bacia_hidrografica", "unidade_de_conservacao_federal", "unidade_de_conservacao_estadual", "rppn",
     "altitude_min", "altitude_max", "batimetria_min", "batimetria_max",
     "ameaca", "uso", "acao_conservacao", "plano_de_acao", "listas_e_convencoes", "justificativa"]
)
df = df[ordem]

# ---------------------------------------------------------------- checagens
assert df["nome_cientifico"].is_unique
assert not df.astype(str).apply(lambda s: s.str.contains("\n")).any().any(), "ainda há quebras de linha"
print("categorias sem sigla:", df["categoria_sigla"].isna().sum())
print(df["categoria_sigla"].value_counts().to_string())

# ---------------------------------------------------------------- saída
df.to_csv(SAIDA, index=False, encoding="utf-8-sig", sep=",", lineterminator="\n")
print(f"\ngravado {SAIDA}: {len(df)} linhas x {df.shape[1]} colunas")
