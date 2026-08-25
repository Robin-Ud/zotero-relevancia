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

Os pesos e tetos são reconstrução, não os originais (ver README). Se for
recalibrar, o método que funcionou foi comparar contra as tags `r-*` do próprio
Zotero e maximizar a concordância. Não invente cortes "redondos": eles já foram
chutados uma vez e erraram 41 itens.
