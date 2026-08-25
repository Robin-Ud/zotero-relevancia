#!/usr/bin/env python3
"""Testes do zotero_relevancia. Rode: python3 zotero_relevancia_test.py"""

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zotero_relevancia as z


CFG = z.CFG


def item(**kw):
    base = {
        "key": "AAAA1111", "titulo": "Um titulo", "doi": "10.1/x", "ano": 2020,
        "revista": "Journal of Testing", "tipo": "journalArticle",
        "colecoes": set(), "obra": {}, "fonte": {}, "h_autor_max": 0,
        "fwci": None, "flags": [],
    }
    base.update(kw)
    return base


class TestNormalizacao(unittest.TestCase):
    def test_limpar_doi_tira_prefixos(self):
        for cru in ("https://doi.org/10.1/X", "http://dx.doi.org/10.1/X",
                    "doi:10.1/X", "  10.1/x  "):
            self.assertEqual(z.limpar_doi(cru), "10.1/x")

    def test_limpar_doi_vazio(self):
        self.assertEqual(z.limpar_doi(None), "")
        self.assertEqual(z.limpar_doi(""), "")

    def test_normalizar_titulo_ignora_acento_e_pontuacao(self):
        self.assertEqual(
            z.normalizar_titulo("Produção de Mudas: uma revisão!"),
            z.normalizar_titulo("producao de mudas uma revisao"))

    def test_saturar_limita_em_um(self):
        self.assertEqual(z.saturar(100.0, 10.0), 1.0)
        self.assertEqual(z.saturar(5.0, 10.0), 0.5)
        self.assertEqual(z.saturar(-3.0, 10.0), 0.0)
        self.assertEqual(z.saturar(5.0, 0.0), 0.0)

    def test_ano_de_pega_o_ano(self):
        self.assertEqual(z.ano_de("2019-03-14"), 2019)
        self.assertEqual(z.ano_de("14/03/2019"), 2019)
        self.assertIsNone(z.ano_de("sem data"))


class TestNota(unittest.TestCase):
    def test_citacoes_por_ano_conta_o_ano_corrente(self):
        # publicado neste ano com 10 citacoes: idade 1, nao divide por zero
        self.assertEqual(z.citacoes_por_ano(10, z.ANO_ATUAL), 10.0)

    def test_citacoes_por_ano_sem_ano_nao_explode(self):
        self.assertEqual(z.citacoes_por_ano(4, None), 4.0)

    def test_fi_implausivel_e_zerado(self):
        # revista com FI absurdo (erro de dado) nao pode inflar a nota
        it = item(fonte={"summary_stats": {"2yr_mean_citedness": 999.0}})
        z.pontuar(it)
        self.assertTrue(it["fi_implausivel"])
        self.assertEqual(it["fi_2y"], 0.0)

    def test_score_nunca_passa_da_soma_dos_pesos(self):
        it = item(
            obra={"cited_by_count": 100000},
            fonte={"summary_stats": {"2yr_mean_citedness": z.TETO_FI,
                                     "h_index": z.TETO_H_REVISTA}},
            h_autor_max=z.TETO_H_AUTOR * 10)
        z.pontuar(it)
        teto = z.PESO_CITACOES + z.PESO_REVISTA + z.PESO_AUTOR
        self.assertLessEqual(it["score"], teto)

    def test_item_sem_nada_pontua_zero(self):
        it = item(obra=None, fonte=None)
        self.assertEqual(z.pontuar(it), 0.0)

    def test_fwci_manda_no_eixo_principal(self):
        """FWCI normaliza por area: e ele que pontua, nao a citacao bruta."""
        nicho = item(fwci=4.0, obra={"cited_by_count": 3})      # pouco citado, alto FWCI
        popular = item(fwci=0.2, obra={"cited_by_count": 5000})  # muito citado, baixo FWCI
        z.pontuar(nicho)
        z.pontuar(popular)
        self.assertGreater(nicho["score"], popular["score"])

    def test_sem_fwci_cai_para_citacao_por_ano(self):
        sem = item(fwci=None, ano=z.ANO_ATUAL - 1,
                   obra={"cited_by_count": int(z.TETO_CIT_ANO * 2)})
        z.pontuar(sem)
        self.assertAlmostEqual(sem["score"], z.PESO_CITACOES, places=1)

    def test_score_fwci_puro_escala(self):
        self.assertIsNone(z.score_fwci_puro(item(fwci=None)))
        self.assertEqual(z.score_fwci_puro(item(fwci=1.0)), 2.5)
        self.assertEqual(z.score_fwci_puro(item(fwci=100.0)), 10.0)


class TestFlags(unittest.TestCase):
    def test_sem_registro_openalex(self):
        itens = [item(obra=None)]
        z.marcar_flags(itens, CFG)
        self.assertIn("sem_registro_openalex", itens[0]["flags"])

    def test_tipo_fora_da_lista_vira_nao_e_paper(self):
        itens = [item(obra={"type": "dataset"})]
        z.marcar_flags(itens, CFG)
        self.assertIn("nao_e_paper", itens[0]["flags"])

    def test_artigo_nao_recebe_nao_e_paper(self):
        itens = [item(obra={"type": "article"})]
        z.marcar_flags(itens, CFG)
        self.assertNotIn("nao_e_paper", itens[0]["flags"])

    def test_fwci_de_paper_novo_e_imaturo(self):
        itens = [item(obra={"type": "article"}, fwci=3.0, ano=z.ANO_ATUAL)]
        z.marcar_flags(itens, CFG)
        self.assertIn("fwci_imaturo", itens[0]["flags"])

    def test_fwci_de_paper_velho_nao_e_imaturo(self):
        itens = [item(obra={"type": "article"}, fwci=3.0, ano=z.ANO_ATUAL - 8)]
        z.marcar_flags(itens, CFG)
        self.assertNotIn("fwci_imaturo", itens[0]["flags"])

    def test_doi_repetido_marca_os_dois(self):
        itens = [item(key="A", doi="10.1/z"), item(key="B", doi="10.1/z")]
        z.marcar_flags(itens, CFG)
        self.assertTrue(all("doi_duplicado" in i["flags"] for i in itens))

    def test_doi_diferente_nao_marca(self):
        itens = [item(key="A", doi="10.1/z"), item(key="B", doi="10.1/w",
                                                   titulo="Outro")]
        z.marcar_flags(itens, CFG)
        self.assertFalse(any("doi_duplicado" in i["flags"] for i in itens))

    def test_titulo_igual_com_doi_diferente_ainda_marca(self):
        itens = [item(key="A", doi="10.1/z", titulo="Mesmo Titulo"),
                 item(key="B", doi="10.1/w", titulo="mesmo titulo!")]
        z.marcar_flags(itens, CFG)
        self.assertTrue(all("titulo_duplicado" in i["flags"] for i in itens))

    def test_caderno_de_resumos(self):
        itens = [item(obra={"type": "article"},
                      revista="Journal of Animal Science, Supplement 3")]
        z.marcar_flags(itens, CFG)
        self.assertIn("resumo_de_congresso", itens[0]["flags"])

    def test_sem_doi(self):
        itens = [item(doi="")]
        z.marcar_flags(itens, CFG)
        self.assertIn("sem_doi", itens[0]["flags"])


class TestClassificar(unittest.TestCase):
    def test_cortes(self):
        for score, tier in ((10.0, "A"), (z.CORTE_A, "A"), (z.CORTE_B, "B"),
                            (z.CORTE_C, "C"), (0.0, "D")):
            self.assertEqual(z.classificar(item(flags=[], score=score)), tier)

    def test_nao_e_paper_cai_para_d_mesmo_com_nota_alta(self):
        self.assertEqual(
            z.classificar(item(flags=["nao_e_paper"], score=10.0)), "D")

    def test_sem_openalex_cai_para_d(self):
        self.assertEqual(
            z.classificar(item(flags=["sem_registro_openalex"], score=10.0)), "D")

    def test_resumo_de_congresso_cai_para_d(self):
        self.assertEqual(
            z.classificar(item(flags=["resumo_de_congresso"], score=9.0)), "D")


class TestCache(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.caminho = os.path.join(self.dir, "c.json")

    def test_grava_e_le(self):
        c = z.Cache(self.caminho, CFG)
        c.guardar("k", {"a": 1})
        c.salvar()
        self.assertEqual(z.Cache(self.caminho, CFG).pegar("k", 2020), {"a": 1})

    def test_entrada_vencida_volta_none(self):
        c = z.Cache(self.caminho, CFG)
        c.dados["k"] = {"t": time.time() - 10 * 365 * 86400, "v": {"a": 1}}
        self.assertIsNone(c.pegar("k", z.ANO_ATUAL))

    def test_paper_novo_vence_antes_que_paper_velho(self):
        c = z.Cache(self.caminho, CFG)
        self.assertLess(c.ttl_segundos(z.ANO_ATUAL), c.ttl_segundos(1990))

    def test_cache_corrompido_nao_derruba(self):
        with open(self.caminho, "w") as arq:
            arq.write("{lixo")
        self.assertEqual(z.Cache(self.caminho, CFG).dados, {})


class TestBuscaPorTitulo(unittest.TestCase):
    """Titulo com ',' ou ':' quebrava o filter do OpenAlex com HTTP 400."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.api = z.OpenAlex(z.Cache(os.path.join(self.dir, "c.json"), CFG), CFG)
        self.vistos = []
        self.api._get = lambda caminho, params=None: (
            self.vistos.append((caminho, params)) or {"results": []})

    def test_pontuacao_nao_vaza_para_o_filtro(self):
        cru = ('Efeitos da isca granulada "EAV-041-A" no controle das formigas '
               'cortadeiras Atta sexdens rubropilosa Forel, 1908 e Acromyrmex '
               'spp. (Hymenoptera, Formicidae)')
        self.api.obra("", cru, 2020)
        _caminho, params = self.vistos[0]
        termo = params["filter"].split("title.search:", 1)[1]
        for proibido in (",", ":", '"', "(", ")"):
            self.assertNotIn(proibido, termo)

    def test_titulo_vazio_nao_bate_na_rede(self):
        self.assertIsNone(self.api.obra("", "   ", 2020))
        self.assertEqual(self.vistos, [])


class TestContratoComZoteroTags(unittest.TestCase):
    """O zotero_tags importa este modulo. Quebrar isso quebra o taguear."""

    def test_expoe_o_que_o_tags_importa(self):
        self.assertTrue(callable(z.limpar_doi))
        self.assertTrue(callable(z.normalizar_titulo))
        self.assertIsInstance(z.CORTE_FWCI_IMATURO_UTIL, float)

    def test_csv_tem_as_colunas_que_o_tags_le(self):
        for coluna in ("item_key", "tier", "flags", "fwci"):
            self.assertIn(coluna, z.COLUNAS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
