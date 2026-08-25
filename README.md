# zotero-relevancia

Régua de relevância bibliométrica da biblioteca do Zotero. Lê o `zotero.sqlite`,
busca métrica no OpenAlex e escreve um CSV com um tier **A/B/C/D** por item.

Quem consome é o [`zotero-tags`](../zotero-tags), que transforma o tier na tag
`r-*`. Os dois juntos são o motor da skill `zotero-tags`.

```bash
python3 zotero_relevancia.py            # roda e escreve o CSV do dia
python3 zotero_relevancia.py --offline  # só o cache, sem tocar a rede
python3 zotero_relevancia_test.py       # 33 testes, sem rede
```

## Como a nota é feita

Três eixos, somando 10 pontos, todos saturados para que um outlier não domine:

| eixo | peso | vem de |
|---|---|---|
| **impacto por área** | 5 | **FWCI** do OpenAlex (fallback: citações ÷ idade) |
| revista | 3 | 60% fator de impacto 2 anos + 40% h-index do periódico |
| autor | 2 | maior h-index entre os 10 primeiros autores |

O tier sai do corte (`corte_a/b/c` no `configs.json`). Algumas flags derrubam
para D direto, independente da nota: `nao_e_paper`, `sem_registro_openalex`,
`resumo_de_congresso`.

O eixo principal é o **FWCI** (1.0 = média mundial da área e do ano). Usar FWCI
em vez de citação bruta é o que impede a régua de punir literatura de nicho: um
paper de micotoxina em pastagem cita pouco em números absolutos e ainda assim
pode estar muito acima da média da própria área. Item sem FWCI cai para citações
por ano, que é o que existe.

O CSV também traz o FWCI cru. O relatório `COMPOSTO x FWCI PURO` mostra onde os dois
mais divergem — é ali que o prestígio do periódico está puxando a nota para longe
do impacto real do artigo.

## Cache

`~/.cache/zotero-relevancia/openalex.json`, com TTL por idade da publicação:
3 meses até 2 anos, 6 até 10, 12 acima. Paper novo muda de citação rápido; paper
velho não. O custo de rede de uma rodada é só o que venceu mais os itens novos.

Se algum request falhar, o script **avisa e sai com código 1** — CSV incompleto
vira tag errada. Rode de novo antes de taguear.

## Aviso: esta régua é uma reconstrução

O arquivo original foi perdido no `rm -rf *` de 2026-08-25 e só voltou pela
metade dos transcripts do Claude (o miolo do cálculo, sem os valores das
constantes). **Os pesos e tetos são escolha nova.** Os cortes A/B/C foram
calibrados contra as tags `r-*` que já estavam no Zotero — a saída da régua
original — e reproduzem 42 de 47 itens, **89%**.

O FWCI como eixo principal não foi chute: o Matheus lembrou que a régua original
classificava por área, e medir confirmou (81% com citação bruta, 89% com FWCI).

Ou seja: a ordenação é fiel, os números absolutos não são os de antes. Se a
classificação de algum item parecer errada, o problema provavelmente está nos
pesos/tetos do `configs.json`, não no item.
