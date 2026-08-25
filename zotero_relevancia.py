#!/usr/bin/env python3
"""zotero_relevancia — regua de relevancia bibliometrica da biblioteca do Zotero.

Le os itens de topo do zotero.sqlite, busca metrica no OpenAlex (com cache de TTL
por idade da publicacao) e escreve um CSV com um tier A/B/C/D por item.

O consumidor e o zotero_tags.py, que importa este modulo por tres coisas
(limpar_doi, normalizar_titulo, CORTE_FWCI_IMATURO_UTIL) e le o CSV pela chave
item_key. Mudar nome de coluna aqui quebra o taguear.

    python3 zotero_relevancia.py              # roda e escreve o CSV do dia
    python3 zotero_relevancia.py --offline    # so o cache, sem rede
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

AQUI = os.path.dirname(os.path.abspath(__file__))
ANO_ATUAL = datetime.date.today().year
API = "https://api.openalex.org"
PAUSA_ENTRE_REQUESTS = 0.12          # OpenAlex pede no maximo ~10/s


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

def carregar_config(caminho=None):
    with open(caminho or os.path.join(AQUI, "configs.json"), encoding="utf-8") as arq:
        cfg = json.load(arq)
    for chave in ("banco", "dir_csv", "cache"):
        cfg[chave] = os.path.expanduser(cfg[chave])
    return cfg


CFG = carregar_config()

PESO_CITACOES = CFG["peso_citacoes"]
PESO_REVISTA = CFG["peso_revista"]
PESO_AUTOR = CFG["peso_autor"]

TETO_CIT_ANO = CFG["teto_cit_ano"]
TETO_FI = CFG["teto_fi"]
TETO_H_REVISTA = CFG["teto_h_revista"]
TETO_H_AUTOR = CFG["teto_h_autor"]
TETO_FI_PLAUSIVEL = CFG["teto_fi_plausivel"]

CORTE_A = CFG["corte_a"]
CORTE_B = CFG["corte_b"]
CORTE_C = CFG["corte_c"]

FWCI_ANOS_MINIMOS = CFG["fwci_anos_minimos"]
CORTE_FWCI_IMATURO_UTIL = CFG["corte_fwci_imaturo_util"]


# --------------------------------------------------------------------------
# Normalizacao — usadas tambem pelo zotero_tags
# --------------------------------------------------------------------------

def sem_acento(texto):
    texto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in texto if not unicodedata.combining(c)).lower()


def limpar_doi(doi):
    """'https://doi.org/10.1/X', 'doi:10.1/X' e '10.1/x' viram '10.1/x'."""
    doi = (doi or "").strip().lower()
    doi = re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", doi)
    doi = re.sub(r"^doi:\s*", "", doi)
    return doi.strip()


def normalizar_titulo(titulo):
    """Chave de comparacao: sem acento, sem pontuacao, sem espaco duplo."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", sem_acento(titulo))).strip()


def saturar(valor, teto):
    """Satura em 1.0. Evita que um outlier de citacao domine a nota."""
    if teto <= 0:
        return 0.0
    return min(1.0, max(0.0, valor / float(teto)))


# --------------------------------------------------------------------------
# Cache com TTL por idade da publicacao
# --------------------------------------------------------------------------

class Cache:
    def __init__(self, caminho, cfg):
        self.caminho = caminho
        self.ttl = cfg["ttl_meses"]
        self.dados = {}
        if os.path.exists(caminho):
            try:
                with open(caminho, encoding="utf-8") as arq:
                    self.dados = json.load(arq)
            except (ValueError, OSError):
                self.dados = {}          # cache corrompido nao pode derrubar o run

    def ttl_segundos(self, ano):
        idade = ANO_ATUAL - ano if ano else 0
        for limite, meses in self.ttl:
            if idade <= limite:
                return meses * 30 * 86400
        return 30 * 86400

    def pegar(self, chave, ano):
        entrada = self.dados.get(chave)
        if not entrada:
            return None
        if time.time() - entrada.get("t", 0) > self.ttl_segundos(ano):
            return None
        return entrada.get("v")

    def guardar(self, chave, valor):
        self.dados[chave] = {"t": time.time(), "v": valor}

    def salvar(self):
        os.makedirs(os.path.dirname(self.caminho), exist_ok=True)
        tmp = self.caminho + ".tmp"
        with open(tmp, "w", encoding="utf-8") as arq:
            json.dump(self.dados, arq)
        os.replace(tmp, self.caminho)     # troca atomica: nunca deixa cache pela metade


# --------------------------------------------------------------------------
# OpenAlex
# --------------------------------------------------------------------------

class OpenAlex:
    def __init__(self, cache, cfg, offline=False):
        self.cache = cache
        self.mailto = cfg.get("mailto") or ""
        self.offline = offline
        self.falhas = []          # (url, motivo) — saber QUAL falhou e por que

    def _get(self, caminho, params=None):
        if self.offline:
            return None
        params = dict(params or {})
        if self.mailto:
            params["mailto"] = self.mailto
        url = "%s/%s" % (API, caminho.lstrip("/"))
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": "zotero-relevancia"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                dados = json.load(resp)
            time.sleep(PAUSA_ENTRE_REQUESTS)
            return dados
        except urllib.error.HTTPError as erro:
            if erro.code == 404:
                return None               # item mesmo nao existe la; nao e falha
            self.falhas.append((url, "HTTP %s" % erro.code))
        except (urllib.error.URLError, ValueError, OSError) as erro:
            self.falhas.append((url, type(erro).__name__ + ": " + str(erro)[:80]))
        return None

    def obra(self, doi, titulo, ano):
        """Work por DOI; sem DOI, tenta casar por titulo exato normalizado."""
        chave = "work:doi:" + doi if doi else "work:tit:" + normalizar_titulo(titulo)
        em_cache = self.cache.pegar(chave, ano)
        if em_cache is not None:
            return em_cache or None

        if doi:
            dados = self._get("works/doi:" + doi)
        else:
            if not titulo:
                return None
            # title.search vai dentro de `filter`, onde ',' separa filtros e ':'
            # separa chave de valor — titulo com pontuacao devolve HTTP 400.
            # O normalizado so tem [a-z0-9 ], e o casamento exato vem depois.
            termo = normalizar_titulo(titulo)[:250]
            if not termo:
                return None
            busca = self._get("works", {"filter": "title.search:" + termo,
                                        "per-page": 5})
            dados = None
            alvo = normalizar_titulo(titulo)
            for candidato in (busca or {}).get("results", []):
                if normalizar_titulo(candidato.get("title") or "") == alvo:
                    dados = candidato
                    break

        if dados is not None:
            self.cache.guardar(chave, self._enxugar_obra(dados))
            return self.cache.dados[chave]["v"]
        if not self.offline and not self.falhas:
            self.cache.guardar(chave, {})     # ausencia confirmada tambem vale cache
        return None

    @staticmethod
    def _enxugar_obra(dados):
        """Guarda so o que a nota usa — o work cru do OpenAlex passa de 100 KB."""
        local = (dados.get("primary_location") or {}).get("source") or {}
        return {
            "cited_by_count": dados.get("cited_by_count") or 0,
            "fwci": dados.get("fwci"),
            "type": dados.get("type") or "",
            "publication_year": dados.get("publication_year"),
            "source_id": local.get("id") or "",
            "source_name": local.get("display_name") or "",
            "author_ids": [
                (a.get("author") or {}).get("id") or ""
                for a in (dados.get("authorships") or [])[:10]
            ],
        }

    def fonte(self, source_id, ano):
        if not source_id:
            return {}
        chave = "src:" + source_id
        em_cache = self.cache.pegar(chave, ano)
        if em_cache is not None:
            return em_cache
        dados = self._get("sources/" + source_id.rsplit("/", 1)[-1])
        enxuto = {"summary_stats": (dados or {}).get("summary_stats") or {},
                  "display_name": (dados or {}).get("display_name") or ""}
        if dados is not None:
            self.cache.guardar(chave, enxuto)
        return enxuto

    def h_autor_max(self, author_ids, ano):
        """Maior h-index entre os autores. Um nome forte ja indica o peso do grupo."""
        melhor = 0
        for autor_id in author_ids:
            if not autor_id:
                continue
            chave = "aut:" + autor_id
            em_cache = self.cache.pegar(chave, ano)
            if em_cache is None:
                dados = self._get("authors/" + autor_id.rsplit("/", 1)[-1])
                if dados is None:
                    continue
                em_cache = (dados.get("summary_stats") or {}).get("h_index") or 0
                self.cache.guardar(chave, em_cache)
            melhor = max(melhor, em_cache or 0)
        return melhor


# --------------------------------------------------------------------------
# Leitura do banco
# --------------------------------------------------------------------------

def campo(con, item_id, nome):
    linha = con.execute(
        """SELECT v.value FROM itemData d JOIN itemDataValues v ON v.valueID = d.valueID
           WHERE d.itemID = ? AND d.fieldID = (SELECT fieldID FROM fields WHERE fieldName = ?)""",
        (item_id, nome),
    ).fetchone()
    return linha[0] if linha else ""


def colecoes_do_item(con, item_id):
    return {
        nome for (nome,) in con.execute(
            """SELECT c.collectionName FROM collectionItems ci
               JOIN collections c ON c.collectionID = ci.collectionID
               WHERE ci.itemID = ?""",
            (item_id,),
        )
    }


def ano_de(texto):
    achado = re.search(r"(1[6-9]\d\d|20\d\d)", texto or "")
    return int(achado.group(1)) if achado else None


def coletar_itens(con):
    """Itens de topo vivos. Anexo, nota e lixeira ficam de fora."""
    linhas = con.execute(
        """SELECT i.itemID, i.key, t.typeName FROM items i
           JOIN itemTypes t ON t.itemTypeID = i.itemTypeID
           WHERE t.typeName NOT IN ('attachment', 'note', 'annotation')
             AND i.itemID NOT IN (SELECT itemID FROM deletedItems)
           ORDER BY i.itemID""",
    ).fetchall()

    itens = []
    for item_id, chave, tipo in linhas:
        titulo = campo(con, item_id, "title")
        itens.append({
            "id": item_id,
            "key": chave,
            "tipo": tipo,
            "titulo": titulo,
            "doi": limpar_doi(campo(con, item_id, "DOI")),
            "ano": ano_de(campo(con, item_id, "date")),
            "revista": campo(con, item_id, "publicationTitle"),
            "colecoes": colecoes_do_item(con, item_id),
            "obra": None,
            "fonte": None,
            "h_autor_max": 0,
            "fwci": None,
            "flags": [],
        })
    return itens


# --------------------------------------------------------------------------
# Nota
# --------------------------------------------------------------------------

def citacoes_por_ano(citacoes, ano):
    idade = max(1, ANO_ATUAL - ano + 1) if ano else 1
    return citacoes / float(idade)


def pontuar(item):
    obra = item["obra"] or {}
    fonte = item["fonte"] or {}
    metricas = fonte.get("summary_stats", {})

    item["citacoes"] = obra.get("cited_by_count") or 0
    item["cit_ano"] = citacoes_por_ano(item["citacoes"], item["ano"])
    item["fi_2y"] = round(metricas.get("2yr_mean_citedness") or 0.0, 2)
    item["h_revista"] = metricas.get("h_index") or 0
    item["fi_implausivel"] = item["fi_2y"] > TETO_FI_PLAUSIVEL
    if item["fi_implausivel"]:
        item["fi_2y"] = 0.0

    eixo_cit = PESO_CITACOES * saturar(item["cit_ano"], TETO_CIT_ANO)
    eixo_rev = PESO_REVISTA * (
        0.6 * saturar(item["fi_2y"], TETO_FI)
        + 0.4 * min(1.0, item["h_revista"] / TETO_H_REVISTA)
    )
    eixo_aut = PESO_AUTOR * min(1.0, item["h_autor_max"] / TETO_H_AUTOR)

    item["score"] = round(eixo_cit + eixo_rev + eixo_aut, 1)
    return item["score"]


def score_fwci_puro(item):
    """Nota alternativa so com FWCI, para comparar com o composto.

    FWCI 1.0 = media mundial da area e do ano. Mapeado na mesma escala de 0 a 10.
    """
    if item["fwci"] is None:
        return None
    return round(min(10.0, item["fwci"] * 2.5), 1)


def marcar_flags(itens, cfg):
    por_doi, por_titulo = {}, {}
    for item in itens:
        if item["doi"]:
            por_doi.setdefault(item["doi"], []).append(item)
        chave = normalizar_titulo(item["titulo"])
        if chave:
            por_titulo.setdefault(chave, []).append(item)

    for item in itens:
        flags = []
        obra = item["obra"]

        if obra is None:
            flags.append("sem_registro_openalex")
        else:
            if obra.get("type") and obra["type"] not in cfg["tipos_de_paper"]:
                flags.append("nao_e_paper")
            if item["fwci"] is not None:
                idade = ANO_ATUAL - (item["ano"] or ANO_ATUAL)
                if idade < FWCI_ANOS_MINIMOS:
                    flags.append("fwci_imaturo")

        if not item["doi"]:
            flags.append("sem_doi")
        if item.get("fi_implausivel"):     # so existe depois de pontuar()
            flags.append("fi_implausivel")

        revista = sem_acento(item["revista"] or (obra or {}).get("source_name") or "")
        if revista and any(m in revista for m in cfg["marcas_de_congresso"]):
            flags.append("resumo_de_congresso")

        if item["doi"] and len(por_doi.get(item["doi"], [])) > 1:
            flags.append("doi_duplicado")
        chave = normalizar_titulo(item["titulo"])
        if chave and len(por_titulo.get(chave, [])) > 1:
            flags.append("titulo_duplicado")

        item["flags"] = sorted(set(flags))


def classificar(item):
    if "nao_e_paper" in item["flags"] or "sem_registro_openalex" in item["flags"]:
        return "D"
    if "resumo_de_congresso" in item["flags"]:
        return "D"
    if item["score"] >= CORTE_A:
        return "A"
    if item["score"] >= CORTE_B:
        return "B"
    if item["score"] >= CORTE_C:
        return "C"
    return "D"


# --------------------------------------------------------------------------
# Saida
# --------------------------------------------------------------------------

COLUNAS = [
    "tier", "score", "fwci", "score_fwci", "citacoes", "citacoes_por_ano",
    "revista", "fi_2y", "h_revista", "h_autor_max", "ano", "tipo", "colecoes",
    "flags", "titulo", "doi", "item_key",
]


def escrever_csv(itens, caminho):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "w", newline="", encoding="utf-8") as arq:
        escritor = csv.writer(arq)
        escritor.writerow(COLUNAS)
        for item in itens:
            escritor.writerow([
                item["tier"], item["score"],
                "" if item["fwci"] is None else round(item["fwci"], 2),
                "" if item["score_fwci"] is None else item["score_fwci"],
                item["citacoes"], round(item["cit_ano"], 1), item["revista"],
                item["fi_2y"], item["h_revista"], item["h_autor_max"],
                item["ano"] or "", item["tipo"], "; ".join(sorted(item["colecoes"])),
                " ".join(item["flags"]), item["titulo"], item["doi"], item["key"],
            ])


def resumir(itens, caminho):
    contagem = {}
    for item in itens:
        contagem[item["tier"]] = contagem.get(item["tier"], 0) + 1
    print("%d itens classificados -> %s\n" % (len(itens), caminho))
    print("tiers: " + "  ".join(
        "%s=%d" % (t, contagem.get(t, 0)) for t in "ABCD"))


def divergencia_fwci(itens, quantos=10):
    """Onde o prestigio da revista puxa a nota para longe do impacto real.

    Score composto alto e FWCI baixo = o paper esta pegando carona no periodico.
    """
    candidatos = [i for i in itens if i["score_fwci"] is not None]
    candidatos.sort(key=lambda i: abs(i["score"] - i["score_fwci"]), reverse=True)
    if not candidatos:
        return
    print("\nCOMPOSTO x FWCI PURO — maiores divergencias")
    print("%-6s %-6s %-6s  %s" % ("comp", "fwci", "delta", "titulo"))
    for item in candidatos[:quantos]:
        delta = item["score"] - item["score_fwci"]
        print("%-6.1f %-6.1f %+-6.1f %s" % (
            item["score"], item["score_fwci"], delta, item["titulo"][:70]))


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def processar(itens, api):
    for numero, item in enumerate(itens, 1):
        obra = api.obra(item["doi"], item["titulo"], item["ano"])
        item["obra"] = obra
        if obra:
            item["fwci"] = obra.get("fwci")
            if not item["ano"]:
                item["ano"] = obra.get("publication_year")
            if not item["revista"]:
                item["revista"] = obra.get("source_name") or ""
            item["fonte"] = api.fonte(obra.get("source_id"), item["ano"])
            item["h_autor_max"] = api.h_autor_max(obra.get("author_ids") or [],
                                                  item["ano"])
        pontuar(item)
        item["score_fwci"] = score_fwci_puro(item)
        if numero % 25 == 0:
            sys.stderr.write("  %d/%d\n" % (numero, len(itens)))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--offline", action="store_true",
                   help="usa so o cache; nao toca a rede")
    p.add_argument("--config", default=None, help="outro configs.json")
    p.add_argument("--saida", default=None, help="sobrepoe o caminho do CSV")
    args = p.parse_args(argv)

    cfg = carregar_config(args.config) if args.config else CFG
    if not os.path.exists(cfg["banco"]):
        sys.exit("nao achei o banco do Zotero em %s" % cfg["banco"])

    con = sqlite3.connect("file:%s?immutable=1" % cfg["banco"], uri=True)
    try:
        itens = coletar_itens(con)
    finally:
        con.close()
    if not itens:
        sys.exit("nenhum item de topo no banco — o Zotero ja sincronizou?")

    cache = Cache(cfg["cache"], cfg)
    api = OpenAlex(cache, cfg, offline=args.offline)
    print("%d itens; consultando OpenAlex%s" % (
        len(itens), " (offline)" if args.offline else ""))
    try:
        processar(itens, api)
    finally:
        cache.salvar()

    marcar_flags(itens, cfg)
    for item in itens:
        item["tier"] = classificar(item)
    itens.sort(key=lambda i: (-i["score"], i["titulo"]))

    caminho = args.saida or os.path.join(
        cfg["dir_csv"],
        "zotero_relevancia_%s.csv" % datetime.date.today().isoformat())
    escrever_csv(itens, caminho)
    resumir(itens, caminho)
    divergencia_fwci(itens)

    if api.falhas:
        print("\n%d requests falharam — rode de novo antes de taguear, "
              "CSV incompleto vira tag errada" % len(api.falhas))
        for url, motivo in api.falhas[:10]:
            print("  %s\n    %s" % (url, motivo))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
