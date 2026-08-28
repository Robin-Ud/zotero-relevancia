# zotero-relevancia

Régua de relevância bibliométrica da biblioteca do Zotero. Lê o `zotero.sqlite`,
busca métrica no OpenAlex e escreve um CSV com um tier **A/B/C/D** por item.

Quem consome é o [`zotero-tags`](../zotero-tags), que transforma o tier na tag
`r-*`. Os dois juntos são o motor da skill `zotero-tags`.

```bash
python3 zotero_relevancia.py            # roda e escreve o CSV do dia
python3 zotero_relevancia.py --offline  # só o cache, sem tocar a rede
python3 zotero_relevancia_test.py       # 42 testes, sem rede
```

## Como a nota é feita

Quatro eixos, escala **0–100**, todos saturados para que um outlier não domine:

| eixo | peso | vem de |
|---|---|---|
| **FWCI** | 35 | impacto do artigo na própria área (1,0 = média mundial) |
| revista | 25 | 60% fator de impacto 2 anos + 40% h-index do periódico |
| citações | 20 | `cited_by_count` ÷ idade |
| autor | 20 | maior h-index entre os 10 primeiros autores |

O FWCI leva o maior peso porque é a única métrica aqui que compara agronomia
tropical com machine learning de forma justa. A revista pesa menos que ele de
propósito: fator de impacto não mede o paper — é a crítica da DORA.

**Quando o FWCI não entra, os 35 pontos são redistribuídos** entre os outros
três, em vez de contarem zero. Senão tese e livro, que nunca têm FWCI, seriam
punidos duas vezes pela mesma ausência.

O FWCI de paper muito novo é ruído — mas a imaturidade **só desqualifica o FWCI
quando ele é baixo**. Paper de 2025 com FWCI 63 já provou; paper de 2026 com
FWCI 0 só não teve tempo.

Tiers pelos cortes 62 / 40 / 20. Algumas flags derrubam para D independente da
nota: `nao_e_paper`, `sem_registro_openalex`, `resumo_de_congresso`.

### Segunda opinião: `tier_fwci`

O CSV traz uma segunda classificação, só pelo FWCI (cortes 3,0 / 1,5 / 0,8), sem
mistura com revista nem autor. O relatório `COMPOSTO x FWCI PURO` lista onde as
duas discordam: `tier B` com `tier_fwci A` é paper forte na área que o prestígio
da revista não acompanha; o contrário é carona no periódico.

Também vai a coluna `percentil` (o `citation_normalized_percentile` do
OpenAlex), mais legível que o FWCI cru para conversar sobre um artigo.

### Armadilhas do OpenAlex já tratadas

- **Agregador vindo como fonte.** O DOAJ aparece como `source` com h-index 215.
  Só `type='journal'` conta como revista (flag `fonte_nao_e_revista`).
- **Fator de impacto absurdo.** A *Pakistan J. of Agric. Sciences* vem com 823:
  acima de `teto_fi_plausivel` (50) é erro de dados, não revista boa, e zera.
- **Literatura cinzenta não é demérito.** Boletim da Embrapa vem como `other`;
  vira `r-sem-metrica` ("não consigo avaliar"), nunca `r-d` ("avaliei e é fraco").

## Cache

`~/.cache/zotero-relevancia/openalex.json`. A revalidação é uma escada por
idade da publicação — paper novo muda de citação rápido, paper velho não muda
mais:

| idade | revalida |
|---|---|
| menos de 1 ano | a cada 3 meses |
| 1 a 2 anos | a cada 6 meses |
| 2 a 5 anos | todo ano |
| 5 a 15 anos | a cada 2 anos |
| mais de 15 anos | **só na entrada** — nunca mais consulta |

O custo de rede de uma rodada é só o que venceu mais os itens novos. Item sem
ano é tratado como recém-publicado: revalidar demais é barato, confiar em
métrica velha de um paper que talvez seja novo não é.

Se algum request falhar, o script **avisa e sai com código 1** — CSV incompleto
vira tag errada. Rode de novo antes de taguear.

## Aviso: esta régua é uma reconstrução

O arquivo original foi perdido no `rm -rf *` de 2026-08-25 e só voltou pela
metade dos transcripts do Claude (o miolo do cálculo, sem os valores das
constantes). **Os pesos e tetos são escolha nova.** Os cortes A/B/C foram
calibrados contra as tags `r-*` que já estavam no Zotero — a saída da régua
original — e reproduzem 43 de 47 itens, **91%**.




