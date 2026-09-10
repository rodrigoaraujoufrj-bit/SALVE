# salve-fauna

Consolidação da exportação pública de fichas do SALVE (ICMBio) e cruzamento com a Lista Nacional
Oficial de Espécies da Fauna Ameaçadas de Extinção de 2026 e com a Lista Vermelha global da IUCN.

## Fontes

| fonte | conteúdo | arquivo |
|---|---|---|
| SALVE / ICMBio | exportação pública única das fichas, reino Animalia, 15.407 fichas, extraída em 10/09/2026 | `dados/salve_export/` (não versionado) |
| Portaria GM/MMA 1.667/2026 | peixes e invertebrados aquáticos, 490 táxons, DOU 28/04/2026 | `dados/portarias/portaria_1667_anexo1.txt` |
| Portaria MMA 1.704/2026 | anfíbios, aves, invertebrados terrestres, mamíferos, répteis; 790 ameaçadas + 9 extintas, DOU 17/06/2026 | `dados/portarias/portaria_1704_anexos.txt` |
| IUCN Red List | categoria global, via API do GBIF | gerado em `saida/iucn_global.csv` |

Até setembro de 2026 a fonte do SALVE era a exportação separada por bioma, sete CSVs. A exportação
única substituiu esse formato: ela inclui as espécies sem bioma atribuído, que o formato anterior
omitia, e por isso é o dado mais completo. O `consolida_salve.py` aceita qualquer quantidade de CSVs
na pasta e os dois formatos de subespécie, epíteto solto ou trinômio completo, então a troca de fonte
não exigiu mudança no restante do pipeline.

Os anexos das portarias foram transcritos dos PDFs do DOU. Formato: `n|novo|grupo|familia|especie|cat`,
onde `novo = *` marca espécie que não constava na lista anterior.

## Pipeline

```powershell
pip install -r requirements.txt   # na rede Petrobras: --index-url do Artifactory

# 1. consolida os CSVs da pasta em um só (dedup por espécie, campos multivalorados normalizados)
python scripts/consolida_salve.py dados/salve_export saida/salve_fauna_consolidado.csv

# 2. XLSX em modelo estrela (fichas + tabelas satélites)
python scripts/gera_xlsx_salve.py saida/salve_fauna_consolidado.csv saida/salve_fauna.xlsx

# 3. cruza com as portarias de 2026 e aplica realce
python scripts/cruza_portarias.py saida/salve_fauna_consolidado.csv saida/salve_fauna.xlsx

# 4. categoria global da IUCN (via GBIF, sem token; ~30 min, retomável pelo cache iucn_global.csv)
python scripts/iucn_global_gbif.py saida/salve_fauna_consolidado.csv saida/salve_fauna.xlsx

# 5. tabela final: uma linha por espécie com status SALVE, Portaria 2026 e IUCN global
python scripts/status_comparado.py saida/salve_fauna_consolidado.csv saida/salve_fauna.xlsx saida/iucn_global.csv

# 6. página de consulta autocontida publicada no GitHub Pages
python scripts/gera_html.py saida/status_comparado.csv docs/index.html
```

Rodar sempre a partir da raiz do repositório.

## Publicação

O site de consulta é servido pelo GitHub Pages a partir da pasta `docs/` da branch `main`,
no endereço `https://rodrigoaraujoufrj-bit.github.io/SALVE/`.

`docs/index.html` é um arquivo único e autocontido: HTML, CSS, JavaScript e os dados de
`saida/status_comparado.csv` embutidos como JSON no momento da geração. Não carrega nada de
CDN nem faz requisição de rede, então funciona também aberto direto do disco (`file://`),
o que atende quem está atrás do proxy corporativo.

Para atualizar o site depois de uma nova rodada do pipeline:

```powershell
python scripts/gera_html.py saida/status_comparado.csv docs/index.html
git add docs/index.html
git commit -m "Atualiza pagina de consulta"
git push
```

O Pages republica sozinho a cada push na `main`, em cerca de um minuto. A pasta `docs/` é
versionada de propósito e não entra no `.gitignore`.

O peso da página é dominado pelos dados embutidos. Para segurar o tamanho, o gerador
codifica as colunas repetitivas como dicionário com índice inteiro por linha e guarda
`iucn_global_nome_aceito` como `=` quando ele repete o nome científico. Com as 15.305
espécies o arquivo final fica em torno de 1,4 MB.

## Realce no XLSX

| cor | significado |
|---|---|
| amarelo | espécie nova na lista oficial (asterisco na portaria) |
| laranja | categoria da portaria diferente da categoria no SALVE |
| vermelho | ameaçada no SALVE (CR/EN/VU) mas ausente das duas portarias |
| azul | categoria nacional (SALVE) diferente da global (IUCN) |

## Observações

- Uma espécie pode aparecer mais de uma vez na exportação do SALVE; as cópias são idênticas e são deduplicadas por espécie e subespécie.
- A categoria do SALVE é a avaliação vigente do ICMBio; a data varia por grupo (2017 a 2026). A categoria global da IUCN é outra avaliação, com escopo mundial. As duas não precisam coincidir.
- Espécies sem bioma atribuído no SALVE (insulares, por exemplo) constam da exportação única e entram no cruzamento. Na fonte anterior, separada por bioma, elas ficavam de fora.
- Nomes que o GBIF trata como sinônimo são resolvidos para o táxon aceito antes de buscar a categoria IUCN.
- Quando o nome não existe na Taxonomia de Referência do GBIF, a categoria da IUCN é buscada pelo `nubKey` do táxon aceito, que é a única chave que o endpoint `iucnRedListCategory` reconhece. Usar a chave devolvida por `/species/search` faz a consulta responder `NE` para tudo, sem erro aparente.
- Espécie ausente da Taxonomia de Referência do GBIF fica sem categoria global. Não é falha da consulta: a IUCN avalia sobre esse mesmo backbone, então não há avaliação a recuperar.
