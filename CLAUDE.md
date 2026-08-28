# zotero-relevancia — notas para o Claude

## Contrato que não pode quebrar

O `zotero-tags` importa este módulo e depende de três coisas pelo nome:

- `limpar_doi(doi)`
- `normalizar_titulo(titulo)`
- `CORTE_FWCI_IMATURO_UTIL`

E lê o CSV pelas colunas `item_key`, `tier`, `flags`, `fwci`. Renomear qualquer
uma delas quebra o taguear silenciosamente — o teste
`TestContratoComZoteroTags` existe para pegar isso.

## Armadilhas já pagas

- **`title.search` não aceita pontuação.** Vai dentro de `filter`, onde `,`
  separa filtros e `:` separa chave de valor. Título com vírgula ou aspas devolve
  HTTP 400. Por isso a busca usa `normalizar_titulo()`, que só deixa `[a-z0-9 ]`.
- **`marcar_flags()` não pode depender de `pontuar()`.** Elas rodam em ordem no
  fluxo real, mas `fi_implausivel` é lido com `.get()` de propósito.
- **O banco é aberto com `immutable=1`.** É o que deixa rodar com o Zotero
  aberto; conexão normal dá `database is locked`.
- **Ausência confirmada também vai para o cache** (valor `{}`), para não
  reconsultar todo run um item que o OpenAlex não tem. Mas só quando não houve
  falha de rede — senão o cache guardaria um falso negativo.

## Ao mexer na régua

**Os pesos, tetos e cortes são os ORIGINAIS**, recuperados dos transcripts em
28/08/2026 — não são calibração nem chute. Não "arredonde" nenhum deles sem
motivo forte: cada um tem uma justificativa registrada no `configs.json` e no
`contexto.md`.

Se precisar recalibrar, o método é comparar contra as tags `r-*` do próprio
Zotero (elas são a saída da régua) e maximizar a concordância. Foi assim que se
mediu que os cortes originais dão 72% e que o teto possível é 96%.

**Nunca troque o FWCI por `cited_by_count`.** Foi medido: citação bruta reproduz
81% das tags originais, o FWCI como eixo principal chega a 96%. O FWCI é a única
métrica que compara agronomia tropical com machine learning de forma justa.

## Sobre a divergência de 72%

Com os cortes originais, ~10 itens que estão tagueados `r-a` no Zotero saem como
`r-b`: são papers de FWCI alto (3 a 17) que ficam entre 46 e 59 pontos, logo
abaixo do corte A=62. Provavelmente falta algo da fórmula original que não foi
recuperado, ou as métricas mudaram desde 19/08 (as tags são daquela data).

Isso é **conhecido e aceito** — decisão do Matheus em 28/08. Não "conserte"
mexendo nos cortes sem falar com ele. O `tier_fwci` existe justamente para
mostrar esses casos.
