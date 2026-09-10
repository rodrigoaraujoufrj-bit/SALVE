# salve-fauna

Consolidação das exportações por bioma do SALVE (ICMBio) e cruzamento com a Lista Nacional
Oficial de Espécies da Fauna Ameaçadas de Extinção de 2026 e com a Lista Vermelha global da IUCN.

## Fontes

| fonte | conteúdo | arquivo |
|---|---|---|
| SALVE / ICMBio | exportação pública das fichas, uma por bioma (7 CSVs) | `dados/salve_export/` (não versionado) |
| Portaria GM/MMA 1.667/2026 | peixes e invertebrados aquáticos, 490 táxons, DOU 28/04/2026 | `dados/portarias/portaria_1667_anexo1.txt` |
| Portaria MMA 1.704/2026 | anfíbios, aves, invertebrados terrestres, mamíferos, répteis; 790 ameaçadas + 9 extintas, DOU 17/06/2026 | `dados/portarias/portaria_1704_anexos.txt` |
| IUCN Red List | categoria global, via API do GBIF | gerado em `iucn_global.csv` |

Os anexos das portarias foram transcritos dos PDFs do DOU. Formato: `n|novo|grupo|familia|especie|cat`,
onde `novo = *` marca espécie que não constava na lista anterior.

## Pipeline

```powershell
pip install -r requirements.txt   # na rede Petrobras: --index-url do Artifactory

# 1. consolida os 7 CSVs em um só (dedup por espécie, campos multivalorados normalizados)
python scripts/consolida_salve.py dados/salve_export saida/salve_fauna_consolidado.csv

# 2. XLSX em modelo estrela (fichas + tabelas satélites)
python scripts/gera_xlsx_salve.py saida/salve_fauna_consolidado.csv saida/salve_fauna.xlsx

# 3. cruza com as portarias de 2026 e aplica realce
python scripts/cruza_portarias.py saida/salve_fauna_consolidado.csv saida/salve_fauna.xlsx

# 4. categoria global da IUCN (via GBIF, sem token; ~30 min, retomável pelo cache iucn_global.csv)
python scripts/iucn_global_gbif.py saida/salve_fauna_consolidado.csv saida/salve_fauna.xlsx

# 5. tabela final: uma linha por espécie com status SALVE, Portaria 2026 e IUCN global
python scripts/status_comparado.py saida/salve_fauna_consolidado.csv saida/salve_fauna.xlsx saida/iucn_global.csv
```

Rodar sempre a partir da raiz do repositório.

## Realce no XLSX

| cor | significado |
|---|---|
| amarelo | espécie nova na lista oficial (asterisco na portaria) |
| laranja | categoria da portaria diferente da categoria no SALVE |
| vermelho | ameaçada no SALVE (CR/EN/VU) mas ausente das duas portarias |
| azul | categoria nacional (SALVE) diferente da global (IUCN) |

## Observações

- Uma espécie que ocorre em N biomas aparece N vezes nas exportações do SALVE; as cópias são idênticas e são deduplicadas.
- A categoria do SALVE é a avaliação vigente do ICMBio; a data varia por grupo (2017 a 2026). A categoria global da IUCN é outra avaliação, com escopo mundial. As duas não precisam coincidir.
- Espécies sem bioma atribuído no SALVE (insulares, por exemplo) não saem nas exportações por bioma e ficam sem ficha no cruzamento.
- Nomes que o GBIF trata como sinônimo são resolvidos para o táxon aceito antes de buscar a categoria IUCN.
