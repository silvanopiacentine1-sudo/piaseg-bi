"""BI Piaseg — consolida as fontes do Drive num único JSON por franqueado.

Fontes (pasta TI do Drive da franqueadora):
  - Arrancada de Vendas /Comparativo_Campanha_Jan25_vs_Jan26.xlsx  (campanha: meta x realizado, ranking)
  - Apólices não renovadas/*.XLS                                   (RptApolicesNaoRenovadas)
  - Apólices Canceladas/*.XLS                                      (RptDocsEmitidos)
  - Cotação x Conversão/<N> - <Mês>/                               (orçamento calculado + análise de produção)

Uso: python3 build_data.py   ->  gera data/bi_data.json
"""

import glob
import json
import os
import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

def _drive_local():
    """Pasta TI no Google Drive Desktop deste Mac (modo local). No servidor, BI_DRIVE_TI aponta para o espelho baixado."""
    achados = glob.glob(os.path.expanduser("~/Library/CloudStorage/GoogleDrive-*/Meu Drive/Piaseg Franchising/TI"))
    return achados[0] if achados else ""


DRIVE_TI = os.environ.get("BI_DRIVE_TI") or _drive_local()
PASTA_CAMPANHA = os.path.join(DRIVE_TI, "Arrancada de Vendas ")  # atenção: espaço no final do nome
PASTA_NAO_RENOVADAS = os.path.join(DRIVE_TI, "Apólices não renovadas")
PASTA_CANCELADAS = os.path.join(DRIVE_TI, "Apólices Canceladas")
PASTA_CONVERSAO = os.path.join(DRIVE_TI, "Cotação x Conversão")
# horário de MS em todas as datas (o servidor roda em UTC; sem isso a "posição" aparecia 4 h adiantada)
FUSO = ZoneInfo("America/Campo_Grande")


def _quando_arquivo(caminho):
    return datetime.fromtimestamp(os.path.getmtime(caminho), FUSO).isoformat(timespec="minutes")


SAIDA = os.environ.get("BI_SAIDA") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "bi_data.json")


def carregar_vinculos():
    """Login do portal -> franqueado(s) e gestores. No servidor vem da variável BI_VINCULOS_JSON
    (os e-mails dos franqueados não ficam no repositório); no Mac, do arquivo vinculos.json."""
    if os.environ.get("BI_VINCULOS_JSON"):
        return json.loads(os.environ["BI_VINCULOS_JSON"])
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "vinculos.json"), encoding="utf-8") as fh:
        return json.load(fh)

MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
         "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
META_MINIMA = 30000

# Unidades da própria Piaseg (matriz / contas internas) — fora do BI dos franqueados.
EXCLUIDAS = {"DOURADOS", "CAMPO GRANDE", "PIASEG CONSULTORIA", "PIASEG CORRETORA", "PIASEG",
             "STUDIO AGRONEGOCIOS", "STUDIO AGRONEGOCIOS LTDA", "CONSULTORIA"}

# Nomes de vendedor / grupo de produção que não aparecem no cruzamento automático.
ALIASES = {
    "THIAGO AGUILERA": "AGUILERA",
    "FABIANA TEIXEIRA REZENDE": "FABIANA TEIXEIRA",
    "LAISA CRISTINE PASQUALATO": "PASQUALATO",
    "ERNANI JOSE KRAICH": "ERNANI",
    "JOAO ANTONIO BOEIRA": "JOAO A P BOEIRA",
    "LUCAS JIKAL": "LJKL NEGOCIOS",
    "MIKAEL LEE/LJKL": "LJKL NEGOCIOS",
    "ROQUE HOSANO CRUZ": "ROQUE HOSANO DOS SANTOS CRUZ",
    "DIOGO FELIPE BONFIM": "VALE REPRESENTACOES",
    "NATALIA GIMENES": "VALE REPRESENTACOES",
    "ELIARA RODRIGUES": "ELIARA RODRIGUES FLORES DA COSTA",
    "GABRIEL CAIXETA": "GABRIEL CAIXETA TELES DOS SANTOS",
    "JULIO SARTORELLI": "JULIO CESAR SARTORELLI",
    "LINDOMAR PERUSSATTO": "LINDOMAR ANTONIO PERUSSATTO",
    "LEANDRO LIMA DE ALENCAR": "ALENCAR VEICULOS",
    "ROQUE/IVAN": "IVAN/ROQUE",
    "IVAN/ROQUE": "IVAN/ROQUE",
}

RAMOS_FORA_CONVERSAO = {"CONSORCIO", "FINANCIAMENTO"}


def normalizar(txt) -> str:
    txt = unicodedata.normalize("NFKD", str(txt or "")).encode("ascii", "ignore").decode()
    txt = re.sub(r"\s*/\s*", "/", txt)
    return re.sub(r"\s+", " ", txt).strip().upper()


def nome_curto(unidade) -> str:
    """'TERRA - PIASEG CONSULTORIA' -> 'TERRA'; 'MANO MOTORS - FR - SCHEILA' -> 'MANO MOTORS'."""
    return normalizar(str(unidade).split(" - ")[0])


def canonico(nome, crosswalk=None):
    """Nome de qualquer relatório -> nome do franqueado como está na campanha. None = excluído."""
    if nome is None or (isinstance(nome, float) and pd.isna(nome)):
        return None
    bruto = str(nome).strip()
    if crosswalk and bruto in crosswalk:
        bruto = crosswalk[bruto]
    n = nome_curto(bruto)
    if "/" in n:
        dono = n.split("/", 1)[1]
        if dono.startswith("TERRA"):
            return "TERRA"
        if n not in ALIASES:
            return None  # SILVANO/PIASEG, WILSON/CHL, CLESSIO/LP, STUDIO/UNIDADE… = matriz
    n = ALIASES.get(n, n)
    if n in EXCLUIDAS or n.startswith("STUDIO"):
        return None
    return n


def crosswalk_grupo_divisao():
    """Grupo de Produção (vendedor) -> Divisão (franqueado), a partir dos exports da campanha que têm as duas colunas."""
    cw = {}
    for f in glob.glob(os.path.join(PASTA_CAMPANHA, "2[56]", "*.[xX][lL][sS]*")):
        try:
            df = pd.read_excel(f)
        except Exception:
            continue
        cols = {normalizar(c): c for c in df.columns}
        if "DIVISAO" in cols and "GRUPO DE PRODUCAO" in cols:
            moda = df.groupby(cols["GRUPO DE PRODUCAO"])[cols["DIVISAO"]].agg(lambda s: s.mode()[0])
            for g, d in moda.items():
                cw.setdefault(str(g).strip(), str(d))
    return cw


def num(v):
    try:
        f = float(v)
        return None if pd.isna(f) else round(f, 2)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ campanha

def carregar_campanha():
    caminho = os.path.join(PASTA_CAMPANHA, "Comparativo_Campanha_Jan25_vs_Jan26.xlsx")
    xls = pd.ExcelFile(caminho)
    abas = [("Geral", "Comparativo Geral")] + [
        (s.replace("Comparativo ", ""), s) for s in xls.sheet_names
        if s.startswith("Comparativo ") and s != "Comparativo Geral"
    ]
    por_franq = {}
    for rotulo, aba in abas:
        df = xls.parse(aba)
        df = df[df["Unidade de Negócio"].notna() & (df["Unidade de Negócio"].astype(str).str.upper() != "TOTAL GERAL")]
        df = df[df["Posição"].notna()]
        participantes = len(df)
        for _, r in df.iterrows():
            f = canonico(r["Unidade de Negócio"])
            if not f:
                continue
            pos = int(re.sub(r"\D", "", str(r["Posição"])) or 0)
            por_franq.setdefault(f, {})[rotulo] = {
                "posicao": pos,
                "participantes": participantes,
                "base_2025": num(r["Total Vendido Ano 25"]),
                "realizado_2026": num(r["Total Vendido Ano 26"]),
                "negocios_2025": int(r["Qtd Negócios Ano 25"] or 0),
                "negocios_2026": int(r["Qtd Negócios Ano 26"] or 0),
                "variacao_pct": num(r["Variação (%)"]),
                "pontos": int(r["Pontos"] or 0),
            }
    meses = [m for m, _ in abas if m != "Geral"]
    return por_franq, meses, _quando_arquivo(caminho)


def ranking_periodo(campanha, meses):
    """Ranking de um conjunto de meses com a mesma regra do "Comparativo Geral" da campanha:
    soma totais e pontos dos meses; ordena por pontos e desempata pelo maior % de crescimento
    (franqueado sem base em 2025 conta como crescimento infinito no desempate)."""
    linhas = []
    for f, c in campanha.items():
        ms = [c[m] for m in meses if m in c]
        if not ms:
            continue
        s = lambda k: sum(x[k] or 0 for x in ms)
        b, r = s("base_2025"), s("realizado_2026")
        linhas.append((f, {
            "base_2025": round(b, 2), "realizado_2026": round(r, 2),
            "negocios_2025": s("negocios_2025"), "negocios_2026": s("negocios_2026"),
            "variacao_pct": (r - b) / b if b else None, "pontos": s("pontos"),
        }))
    linhas.sort(key=lambda x: (-x[1]["pontos"], -(x[1]["variacao_pct"] if x[1]["variacao_pct"] is not None else float("inf"))))
    for i, (f, d) in enumerate(linhas, 1):
        d.update(posicao=i, participantes=len(linhas))
    return dict(linhas)


TRIMESTRES = {1: ("Janeiro", "Fevereiro", "Março"), 2: ("Abril", "Maio", "Junho"),
              3: ("Julho", "Agosto", "Setembro"), 4: ("Outubro", "Novembro", "Dezembro")}


RAMOS_EXCLUIDOS_CAMPANHA = {  # mesma lista de montar_comparativo.py (pipeline da campanha)
    "CAPITALIZACAO", "CONSORCIO", "FINANCIAMENTO", "RURAL",
    "SEGURO AGRICOLA COM COBERTURA DO FESR", "SEGURO AGRICOLA SEM COBERTURA DO FESR",
    "SEGURO DE FLORESTAS COM FESR", "SEGURO DE FLORESTAS SEM FESR",
}


MES_ABREV = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]


def _ler_fontes(pasta):
    """Todos os exports de produção da pasta (25/ ou 26/) com colunas padronizadas."""
    fontes = []
    for f in glob.glob(os.path.join(pasta, "*.[xX][lL][sS]*")):
        if os.path.basename(f).startswith(("~", ".")):
            continue
        try:
            df = pd.read_excel(f)
        except Exception:
            continue
        cols = {normalizar(c): c for c in df.columns}
        if not {"PREMIO", "DIVISAO", "RAMO", "SEGURADORA", "INICIO DE VIGENCIA"} <= set(cols):
            continue
        df = df.rename(columns={cols["PREMIO"]: "PREMIO", cols["DIVISAO"]: "UNIDADE", cols["RAMO"]: "RAMO",
                                cols["SEGURADORA"]: "SEGURADORA", cols["INICIO DE VIGENCIA"]: "INICIO"})
        df = df[~df["RAMO"].apply(normalizar).isin(RAMOS_EXCLUIDOS_CAMPANHA)].copy()
        df["F"] = df["UNIDADE"].apply(canonico)
        df["PREMIO"] = pd.to_numeric(df["PREMIO"], errors="coerce").fillna(0)
        dt = pd.to_datetime(df["INICIO"], errors="coerce")
        fontes.append(df)
        for m in range(1, 13):  # export diário sem nome de mês: recorte por mês também é candidato
            sub = df[dt.dt.month == m]
            if 0 < len(sub) < len(df):
                fontes.append(sub)
    return fontes


def _totais(df):
    return {k: round(v, 0) for k, v in df[df["F"].notna()].groupby("F")["PREMIO"].sum().items() if round(v, 0)}


def _bate(totais, alvo):
    return all(abs(totais.get(k, 0) - v) <= 1 for k, v in alvo.items())


def carregar_campanha_detalhe(meses_campanha):
    """franq -> mes -> {por_ramo, por_seguradora} 2025 x 2026.
    Ramo vem das abas "Base" da própria planilha da campanha (bate centavo a centavo com o ranking).
    Seguradora vem do export de origem cujos totais por franqueado são iguais aos da planilha;
    se nenhum bater, o mês fica sem detalhe de seguradora (melhor faltar do que mostrar número diferente)."""
    xls = pd.ExcelFile(os.path.join(PASTA_CAMPANHA, "Comparativo_Campanha_Jan25_vs_Jan26.xlsx"))
    fontes = {ano: _ler_fontes(os.path.join(PASTA_CAMPANHA, ano)) for ano in ("25", "26")}
    out, sem_seg = {}, []
    for mes in meses_campanha:
        if mes not in MESES:
            continue
        bases = {}
        for ano in ("25", "26"):
            aba = f"Base {MES_ABREV[MESES.index(mes)]}{ano}"
            if aba not in xls.sheet_names:
                break
            b = xls.parse(aba).rename(columns={"Prêmio": "PREMIO", "Célula": "RAMO"})
            b["F"] = b["Unidade de Negócio"].apply(canonico)
            b["PREMIO"] = pd.to_numeric(b["PREMIO"], errors="coerce").fillna(0)
            alvo = _totais(b)
            seg = next((f for f in sorted(fontes[ano], key=len, reverse=True) if _bate(_totais(f), alvo)), None)
            if seg is not None:
                seg = seg[seg["F"].isin(set(alvo))]
            if seg is None:
                sem_seg.append(f"{mes}/{ano}")
            bases[ano] = (b[b["F"].notna()], seg)
        if len(bases) < 2:
            continue
        franqs = set(bases["25"][0]["F"]) | set(bases["26"][0]["F"])
        for franq in franqs:
            det = {}
            for col, chave, idx in (("RAMO", "por_ramo", 0), ("SEGURADORA", "por_seguradora", 1)):
                if bases["25"][idx] is None or bases["26"][idx] is None:
                    det[chave] = None
                    continue
                d25 = bases["25"][idx][bases["25"][idx]["F"] == franq]
                d26 = bases["26"][idx][bases["26"][idx]["F"] == franq]
                a25 = d25.groupby(d25[col].astype(str).str.strip())["PREMIO"].agg(["sum", "count"])
                a26 = d26.groupby(d26[col].astype(str).str.strip())["PREMIO"].agg(["sum", "count"])
                det[chave] = [{
                    "nome": k,
                    "v25": round(float(a25["sum"].get(k, 0)), 2), "q25": int(a25["count"].get(k, 0)),
                    "v26": round(float(a26["sum"].get(k, 0)), 2), "q26": int(a26["count"].get(k, 0)),
                } for k in sorted(set(a25.index) | set(a26.index))]
            out.setdefault(franq, {})[mes] = det
    if sem_seg:
        print(f"  AVISO: sem detalhe por seguradora (nenhum export bate com a planilha da campanha): {', '.join(sem_seg)}")
    return out


# ------------------------------------------------------------------ apólices

def _mais_recente(pasta):
    arqs = [f for f in glob.glob(os.path.join(pasta, "*.[xX][lL][sS]*")) if not os.path.basename(f).startswith("~")]
    return max(arqs, key=os.path.getmtime) if arqs else None


def _data(v):
    if isinstance(v, (datetime, pd.Timestamp)):
        return v.date()
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", str(v or ""))
    return datetime(int(m[3]), int(m[2]), int(m[1])).date() if m else None


def carregar_nao_renovadas():
    f = _mais_recente(PASTA_NAO_RENOVADAS)
    if not f:
        print(f"  AVISO: nenhum relatório encontrado em '{os.path.basename(PASTA_NAO_RENOVADAS)}' — tema fica vazio até a próxima atualização")
        return {}, None
    df = pd.read_excel(f)
    cols = {normalizar(c): c for c in df.columns}
    out = {}
    for _, r in df.iterrows():
        franq = canonico(r[cols["UNIDADE DE NEGOCIO"]])
        if not franq:
            continue
        termino = _data(r[cols["TERMINO DE VIGENCIA"]])
        out.setdefault(franq, []).append({
            "cliente": str(r[cols["CLIENTE"]]).strip(),
            "apolice": str(r[cols["APOLICE"]]).strip(),
            "seguradora": str(r[cols["SEGURADORA"]]).strip(),
            "produto": str(r[cols["PRODUTO"]]).strip(),
            "data": termino.isoformat() if termino else None,
            "premio": num(r[cols["PREMIO LIQUIDO"]]) or 0,
        })
    return out, _quando_arquivo(f)


def carregar_canceladas():
    f = _mais_recente(PASTA_CANCELADAS)
    if not f:
        print(f"  AVISO: nenhum relatório encontrado em '{os.path.basename(PASTA_CANCELADAS)}' — tema fica vazio até a próxima atualização")
        return {}, None
    df = pd.read_excel(f)
    cols = {normalizar(c): c for c in df.columns}
    out, vistos = {}, set()
    for _, r in df.iterrows():
        franq = canonico(r[cols["UNIDADE DE NEGOCIO"]])
        if not franq:
            continue
        canc = _data(r[cols["DATA CANCELAMENTO"]])
        chave = (r[cols["SEGURADORA"]], r[cols["APOLICE"]], canc, r[cols["VIGENCIA DO SEGURO"]])
        if chave in vistos:  # endossos repetem a mesma apólice
            continue
        vistos.add(chave)
        out.setdefault(franq, []).append({
            "cliente": str(r[cols["CLIENTE"]]).strip(),
            "apolice": str(r[cols["APOLICE"]]).strip(),
            "seguradora": str(r[cols["SEGURADORA"]]).strip(),
            "produto": str(r[cols["CELULA"]]).strip(),
            "data": canc.isoformat() if canc else None,
            "premio": num(r[cols["PREMIO LIQUIDO"]]) or 0,
        })
    return out, _quando_arquivo(f)


def resumo_apolices(lista):
    por_mes, por_produto = {}, {}
    for a in lista:
        if a["data"]:
            k = a["data"][:7]
            m = por_mes.setdefault(k, {"mes": k, "qtd": 0, "premio": 0.0})
            m["qtd"] += 1
            m["premio"] += a["premio"]
        p = por_produto.setdefault(a["produto"], {"produto": a["produto"], "qtd": 0, "premio": 0.0})
        p["qtd"] += 1
        p["premio"] += a["premio"]
    return {
        "qtd": len(lista),
        "premio": round(sum(a["premio"] for a in lista), 2),
        "por_mes": [dict(v, premio=round(v["premio"], 2)) for _, v in sorted(por_mes.items())],
        "por_produto": sorted([dict(v, premio=round(v["premio"], 2)) for v in por_produto.values()],
                              key=lambda x: -x["premio"]),
        "lista": sorted(lista, key=lambda a: a["data"] or "", reverse=True),
    }


# ------------------------------------------------------------------ cotação x conversão

def _arquivo(pasta, chave):
    for f in os.listdir(pasta):
        if f.startswith((".", "~")):
            continue
        if chave in normalizar(f):
            return os.path.join(pasta, f)
    return None


def carregar_conversao(cw):
    """Mesmos filtros do 'Indicador de Conversão' mensal:
    cotações sem 'Renovação Própria Corretora', sem matriz, cliente único, sem consórcio/financiamento;
    negócios efetivados sem prêmio negativo (cancelado/estorno), sem matriz, sem consórcio/financiamento."""
    out = {}       # franq -> mes -> {...}
    rede = {}      # mes -> {cotacoes, efetivados}
    for pasta in sorted(glob.glob(os.path.join(PASTA_CONVERSAO, "*")), key=lambda p: int(re.match(r"\d+", os.path.basename(p)).group() if re.match(r"\d+", os.path.basename(p)) else 99)):
        m = re.match(r"(\d+)\s*-", os.path.basename(pasta))
        if not m or not os.path.isdir(pasta):
            continue
        mes = int(m[1])
        f_orc, f_prod = _arquivo(pasta, "ORCAMENTO"), _arquivo(pasta, "PRODUCAO")
        if not f_orc or not f_prod:
            continue
        orc = pd.read_excel(f_orc)
        orc = orc[orc["TIPO DE ORÇAMENTO"].astype(str).str.strip() != "Renovação Própria Corretora"]
        orc = orc[~orc["RAMO"].apply(normalizar).isin(RAMOS_FORA_CONVERSAO)]
        orc = orc.assign(F=orc["GRUPO DE PRODUÇÃO"].apply(lambda g: canonico(g, cw)))
        orc = orc[orc["F"].notna()].drop_duplicates(subset="CLIENTE", keep="first")

        prod = pd.read_excel(f_prod)
        prod = prod[pd.to_numeric(prod["PRÊMIO"], errors="coerce") >= 0]
        prod = prod[~prod["RAMO"].apply(normalizar).isin(RAMOS_FORA_CONVERSAO)]
        prod = prod.assign(F=prod["GRUPO DE PRODUÇÃO"].apply(lambda g: canonico(g, cw)))
        prod = prod[prod["F"].notna()]

        rede[mes] = {"cotacoes": len(orc), "efetivados": len(prod)}
        for franq in set(orc["F"]) | set(prod["F"]):
            o, p = orc[orc["F"] == franq], prod[prod["F"] == franq]
            ramos = sorted(set(o["RAMO"].astype(str)) | set(p["RAMO"].astype(str)))
            vend = sorted(set(o["GRUPO DE PRODUÇÃO"].astype(str).str.strip()) | set(p["GRUPO DE PRODUÇÃO"].astype(str).str.strip()))
            out.setdefault(franq, {})[mes] = {
                "cotacoes": len(o),
                "efetivados": len(p),
                "premio_efetivado": round(float(pd.to_numeric(p["PRÊMIO"], errors="coerce").sum()), 2),
                "situacao": {str(k): int(v) for k, v in o["SITUAÇÃO"].value_counts().items()},
                "por_ramo": [{"ramo": r, "cotacoes": int((o["RAMO"].astype(str) == r).sum()),
                              "efetivados": int((p["RAMO"].astype(str) == r).sum())} for r in ramos],
                "por_vendedor": [{"vendedor": nome_curto(v).title(),
                                  "cotacoes": int((o["GRUPO DE PRODUÇÃO"].astype(str).str.strip() == v).sum()),
                                  "efetivados": int((p["GRUPO DE PRODUÇÃO"].astype(str).str.strip() == v).sum())} for v in vend],
            }
    return out, rede


# ------------------------------------------------------------------ comissões

# estrutura atual: Comissões/Recebidas/25 e /26 (desde 14/10/2026; "À Receber" e "Repasses Liberados" ainda não usados).
# Antes era "Comissões recebidas/25 e /26" — mantido como alternativa.
PASTA_COMISSOES = next((os.path.join(DRIVE_TI, *n) for n in (("Comissões", "Recebidas"), ("Comissões recebidas",))
                        if os.path.isdir(os.path.join(DRIVE_TI, *n))), os.path.join(DRIVE_TI, "Comissões", "Recebidas"))
PASTA_A_RECEBER = os.path.join(DRIVE_TI, "Comissões", "À Receber")
PASTA_LIBERADOS = os.path.join(DRIVE_TI, "Comissões", "Repasses Liberados")


def carregar_repasses(pasta, rotulo):
    """RptRepassesPendentes / RptRepassesLiberados: só VALOR e UNIDADE DE NEGÓCIO, sem data.
    É uma fotografia do momento: vale o relatório mais recente da pasta; a data do arquivo é a "posição".
    Retorna (franq -> valor, data_posicao)."""
    f = _mais_recente(pasta)
    if not f:
        print(f"  AVISO: nenhum relatório em '{rotulo}' — subtema fica vazio até a próxima atualização")
        return {}, None
    df = pd.read_excel(f)
    cols = {normalizar(c): c for c in df.columns}
    df["_F"] = df[cols["UNIDADE DE NEGOCIO"]].apply(canonico)
    df["_V"] = pd.to_numeric(df[cols["VALOR"]], errors="coerce").fillna(0)
    tot = df[df["_F"].notna()].groupby("_F")["_V"].sum()
    return {k: round(float(v), 2) for k, v in tot.items()}, _quando_arquivo(f)


TIPO_NEGOCIO = {  # coluna NEGÓCIO do RptRepassesPagos (Quiver)
    "N": "novo", "R": "renovacao", "EN": "endosso", "ER": "endosso", "CN": "cancelamento", "CR": "cancelamento",
}


def carregar_comissoes():
    """Repasses pagos (pastas 25/ e 26/). O relatório atual não tem data: o mês vem do nome do
    arquivo ("Março 26.XLS") ou de uma coluna de data, se o export passar a trazer; sem isso,
    o arquivo conta como o período inteiro do ano (mes = None).
    Retorna franq -> [{ano, mes, tipo, celula, valor, qtd}]."""
    out, arquivos = {}, {}
    for ano in ("25", "26"):
        for f in sorted(glob.glob(os.path.join(PASTA_COMISSOES, ano, "*.[xX][lL][sS]*"))):
            if os.path.basename(f).startswith(("~", ".")):
                continue
            df = pd.read_excel(f)
            cols = {normalizar(c): c for c in df.columns}
            mes_nome = next((i + 1 for i, m in enumerate(MESES) if normalizar(m) in normalizar(os.path.basename(f))), None)
            col_data = next((c for n, c in cols.items() if "DATA" in n or "PAGAMENTO" in n), None)
            df["_MES"] = pd.to_datetime(df[col_data], errors="coerce", dayfirst=True).dt.month if col_data else mes_nome
            df["_F"] = df[cols["UNIDADE DE NEGOCIO"]].apply(canonico)
            df["_T"] = df[cols["NEGOCIO"]].astype(str).str.strip().str.upper().map(TIPO_NEGOCIO).fillna("outros")
            df["_V"] = pd.to_numeric(df[cols["VALOR"]], errors="coerce").fillna(0)
            df["_C"] = df[cols["CELULA"]].astype(str).str.strip()
            df = df[df["_F"].notna()]
            arquivos.setdefault(ano, []).append(os.path.basename(f))
            g = df.groupby(["_F", "_MES", "_T", "_C"], dropna=False)["_V"].agg(["sum", "count"])
            for (franq, mes, tipo, cel), r in g.iterrows():
                out.setdefault(franq, []).append({
                    "ano": 2000 + int(ano), "mes": None if pd.isna(mes) else int(mes),
                    "tipo": tipo, "celula": cel, "valor": round(float(r["sum"]), 2), "qtd": int(r["count"]),
                })
    tem_mes = any(r["mes"] for lst in out.values() for r in lst)
    if not tem_mes:
        print("  AVISO: comissões sem informação de mês (relatório sem data e arquivos sem nome de mês) — filtro mensal indisponível")
    return out, arquivos


# ------------------------------------------------------------------ sinistros

PASTA_SINISTROS = os.path.join(DRIVE_TI, "Sinistros")


def _valor_br(v):
    """'4698,74' / '1.234,56' / 1670 -> float."""
    if isinstance(v, (int, float)):
        return 0.0 if pd.isna(v) else float(v)
    t = str(v or "").strip().replace("R$", "").replace(" ", "")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return 0.0


def carregar_sinistros():
    """RptSinistrosPagos (Quiver), um arquivo por mês: "Janeiro 26.XLS" (na pasta Sinistros ou em 25/ e 26/).
    O relatório não tem data, então o mês/ano vem do nome do arquivo. Retorna franq -> [pagamentos]."""
    out, sem_mes = {}, []
    for f in sorted(glob.glob(os.path.join(PASTA_SINISTROS, "**", "*.[xX][lL][sS]*"), recursive=True)):
        nome = os.path.basename(f)
        if nome.startswith(("~", ".")):
            continue
        mes = next((i + 1 for i, m in enumerate(MESES) if normalizar(m) in normalizar(nome)), None)
        # ano = ÚLTIMO número de 2 ou 4 dígitos do nome: "10.Outubro 26.XLS" -> 26 (o "10." é só a ordem do mês)
        numeros = re.findall(r"(?<!\d)(\d{4}|\d{2})(?!\d)", os.path.splitext(nome)[0])
        pasta_ano = os.path.basename(os.path.dirname(f))
        ano = int(numeros[-1]) if numeros else (int(pasta_ano) if pasta_ano.isdigit() else None)
        if ano and ano < 100:
            ano += 2000
        if not mes or not ano:
            sem_mes.append(nome)
            continue
        df = pd.read_excel(f)
        cols = {normalizar(c): c for c in df.columns}
        col = lambda *ns: next((cols[n] for n in ns if n in cols), None)
        for _, r in df.iterrows():
            franq = canonico(r[col("DIVISAO", "UNIDADE DE NEGOCIO")])
            if not franq:
                continue
            seg = re.sub(r"^\s*Seguradora:\s*", "", str(r[col("SEGURADORA")] or ""), flags=re.I).strip()
            out.setdefault(franq, []).append({
                "ano": ano, "mes": mes,
                "segurado": str(r[col("SEGURADO")]).strip(),
                "seguradora": seg,
                "sinistro": str(r[col("N SINISTRO", "NO SINISTRO", "Nº SINISTRO")]).strip(),
                "produto": str(r[col("PRODUTO")]).strip(),
                "celula": str(r[col("CELULA")]).strip(),
                "terceiro": "" if pd.isna(r[col("TERCEIRO - NOME")]) else str(r[col("TERCEIRO - NOME")]).strip(),
                "valor": round(_valor_br(r[col("VALOR PAGO")]), 2),
            })
    if sem_mes:
        print(f"  AVISO: sinistros sem mês no nome do arquivo (ignorados — renomeie p/ ex. 'Fevereiro 26.XLS'): {', '.join(sem_mes)}")
    return out


# ------------------------------------------------------------------ produção geral

def _padroniza_producao(df, cw):
    cols = {normalizar(c): c for c in df.columns}
    out = pd.DataFrame({
        "PREMIO": pd.to_numeric(df[cols["PREMIO"]], errors="coerce").fillna(0),
        "RAMO": df[cols["RAMO"]].astype(str).str.strip() if "RAMO" in cols else "",
        "SEGURADORA": df[cols["SEGURADORA"]].astype(str).str.strip() if "SEGURADORA" in cols else "",
        # entra só na chave da união sem duplicar (identifica o mesmo lançamento em downloads diferentes)
        "INICIO": pd.to_datetime(df[cols["INICIO DE VIGENCIA"]], errors="coerce").dt.strftime("%Y-%m-%d") if "INICIO DE VIGENCIA" in cols else "",
    })
    if "DIVISAO" in cols:
        out["F"] = df[cols["DIVISAO"]].apply(canonico)
    else:
        out["F"] = df[cols["GRUPO DE PRODUCAO"]].apply(lambda g: canonico(g, cw))
    return out


def _uniao_sem_duplicar(dfs):
    """Junta exports que se sobrepõem (downloads diários): cada linha distinta entra o máximo
    de vezes que aparece em um único arquivo, então nada é contado duas vezes."""
    cont, exemplo = {}, {}
    for df in dfs:
        d = df.fillna("").astype(str)
        for chave, n in d.value_counts().items():
            cont[chave] = max(cont.get(chave, 0), n)
    linhas = [list(k) for k, n in cont.items() for _ in range(n)]
    return pd.DataFrame(linhas, columns=dfs[0].columns) if linhas else dfs[0].iloc[0:0]


def carregar_producao_geral(cw):
    """Produção de TODOS os ramos e produtos (sem as exclusões da campanha), por franqueado.
    2025 e 2026: exports mensais da pasta da campanha ("Agosto 26.XLS"); os downloads diários sem
    nome de mês entram no mês em que foram baixados, unidos sem duplicar. Meses de 2026 que não
    estão lá vêm da "Análise de Produção" da pasta Cotação x Conversão (sem base 2025 para comparar).
    Retorna franq -> [{ano, mes, ramo, seguradora, valor, qtd}]."""
    brutos = {}  # (ano, mes) -> [df padronizado]
    for ano in ("25", "26"):
        por_mes = {}
        for f in glob.glob(os.path.join(PASTA_CAMPANHA, ano, "*.[xX][lL][sS]*")):
            nome = os.path.basename(f)
            if nome.startswith(("~", ".")):
                continue
            mes = next((i + 1 for i, m in enumerate(MESES) if normalizar(m) in normalizar(nome)), None)
            if mes is None:
                quando = datetime.fromtimestamp(os.path.getmtime(f), FUSO)
                if quando.year != 2000 + int(ano):
                    continue
                mes = quando.month
            try:
                cru = pd.read_excel(f)
            except Exception:
                continue
            por_mes.setdefault(mes, []).append(cru)
        for mes, dfs in por_mes.items():
            # padroniza as colunas de TODOS os arquivos antes de unir: o resultado não depende da ordem dos arquivos
            pads = [_padroniza_producao(d, cw) for d in dfs]
            for d in pads:
                d["PREMIO"] = d["PREMIO"].round(2)
            brutos[(2000 + int(ano), mes)] = pads[0] if len(pads) == 1 else _uniao_sem_duplicar(pads)
    for pasta in glob.glob(os.path.join(PASTA_CONVERSAO, "*")):
        m = re.match(r"(\d+)\s*-", os.path.basename(pasta))
        if not m or (2026, int(m[1])) in brutos or not os.path.isdir(pasta):
            continue
        f = _arquivo(pasta, "PRODUCAO")
        if f:
            brutos[(2026, int(m[1]))] = _padroniza_producao(pd.read_excel(f), cw)
    out = {}
    for (ano, mes), df in brutos.items():
        df = df[df["F"].notna()]
        df = df.assign(PREMIO=pd.to_numeric(df["PREMIO"], errors="coerce").fillna(0))
        for (franq, ramo, seg), g in df.groupby(["F", "RAMO", "SEGURADORA"]):
            out.setdefault(franq, []).append({"ano": ano, "mes": mes, "ramo": ramo, "seguradora": seg,
                                              "valor": round(float(g["PREMIO"].sum()), 2), "qtd": int(len(g))})
    return out


# ------------------------------------------------------------------ treinamento (100% fictício)

def gerar_treinamento(base):
    """Unidade-exemplo para ensinar os franqueados, com números INVENTADOS (semente fixa).
    Fica fora de "franqueados": nunca entra em ranking, média, rede ou visão TODOS."""
    import random
    rnd = random.Random(2026)
    ramos = ["AUTOMÓVEL - CASCO", "COMPREENSIVO RESIDENCIAL", "COMPREENSIVO EMPRESARIAL", "FIANÇA LOCATÍCIA",
             "VIDA INDIVIDUAL", "CAMINHÃO", "RISCOS DIVERSOS"]
    pesos = [0.38, 0.16, 0.14, 0.12, 0.08, 0.07, 0.05]
    segs = ["SEGURADORA ALFA", "SEGURADORA BETA", "SEGURADORA GAMA", "SEGURADORA DELTA", "SEGURADORA ÔMEGA"]
    vend = ["Vendedor Exemplo 1", "Vendedor Exemplo 2", "Vendedor Exemplo 3"]
    cli = lambda: f"CLIENTE EXEMPLO {rnd.randint(100, 999)}"
    v = lambda a, b: round(rnd.uniform(a, b), 2)

    # campanha: posição/pontos inventados, participantes = tamanho real do ranking (só um número de contexto)
    campanha = {}
    for mes in base["meses_campanha"]:
        b, r = v(45000, 90000), v(40000, 110000)
        part = max((d["campanha"].get(mes, {}).get("participantes", 0) for d in base["franqueados"].values()), default=30) or 30
        pts = 5 if r > b * 1.2 and r >= 30000 else 3 if r > b and r >= 30000 else 0
        det = lambda tot, nomes, w: [{"nome": n, "v25": round(tot[0] * x * rnd.uniform(.8, 1.2), 2), "q25": rnd.randint(1, 30),
                                       "v26": round(tot[1] * x * rnd.uniform(.8, 1.2), 2), "q26": rnd.randint(1, 30)} for n, x in zip(nomes, w)]
        campanha[mes] = {"posicao": rnd.randint(3, 12), "participantes": part, "base_2025": b, "realizado_2026": r,
                         "negocios_2025": rnd.randint(40, 90), "negocios_2026": rnd.randint(40, 95),
                         "variacao_pct": (r - b) / b, "pontos": pts,
                         "por_ramo": det((b, r), ramos, pesos), "por_seguradora": det((b, r), segs, [.3, .25, .2, .15, .1])}
    def periodo(ms, part):
        ms = [campanha[m] for m in ms if m in campanha]
        b, r = sum(x["base_2025"] for x in ms), sum(x["realizado_2026"] for x in ms)
        return {"posicao": rnd.randint(3, 10), "participantes": part, "base_2025": b, "realizado_2026": r,
                "negocios_2025": sum(x["negocios_2025"] for x in ms), "negocios_2026": sum(x["negocios_2026"] for x in ms),
                "variacao_pct": (r - b) / b if b else None, "pontos": sum(x["pontos"] for x in ms)}
    if campanha:
        part = max((d["campanha"].get("Geral", {}).get("participantes", 0) for d in base["franqueados"].values()), default=30)
        campanha["Geral"] = periodo(base["meses_campanha"], part)
        for t in base["trimestres_campanha"]:
            campanha[t] = periodo(TRIMESTRES[int(t[1])], part)

    # conversão + "média da rede" também inventada
    conversao, rede = [], []
    for r_ in base["rede_conversao"]:
        cot, ef = rnd.randint(40, 80), rnd.randint(30, 70)
        conversao.append({"mes": r_["mes"], "rotulo": r_["rotulo"], "cotacoes": cot, "efetivados": ef, "premio_efetivado": v(60000, 140000),
                          "situacao": {"Efetivado": ef // 2, "Negócios perdidos": cot // 4, "Transmitidos": cot // 3, "Calculado": cot // 8},
                          "por_ramo": [{"ramo": n, "cotacoes": max(0, round(cot * x)), "efetivados": max(0, round(ef * x))} for n, x in zip(ramos, pesos)],
                          "por_vendedor": [{"vendedor": n, "cotacoes": round(cot * x), "efetivados": round(ef * x)} for n, x in zip(vend, [.5, .3, .2])]})
        rede.append({"mes": r_["mes"], "rotulo": r_["rotulo"], "cotacoes": cot * 30, "efetivados": round(ef * 30 * rnd.uniform(.85, 1.1))})

    def apolices(qtd, campo_mes):
        lista = []
        for _ in range(qtd):
            mes = rnd.randint(1, 9)
            lista.append({"cliente": cli(), "apolice": str(rnd.randint(10**7, 10**8)), "seguradora": rnd.choice(segs),
                          "produto": rnd.choices(["AUTOMOVEL", "RESIDENCIA", "EMPRESA", "FIANCA LOCATICIA"], [5, 3, 1, 1])[0],
                          "data": f"2026-{mes:02d}-{rnd.randint(1, 28):02d}", "premio": v(300, 6000)})
        return resumo_apolices(lista)

    comissoes = []
    for ano in (2025, 2026):
        for mes in range(1, 13 if ano == 2025 else 10):
            for tipo, (a, b) in {"novo": (7000, 13000), "renovacao": (1500, 5000), "endosso": (0, 300), "cancelamento": (-600, -50)}.items():
                for ramo, x in zip(["AUTOMÓVEL", "PATRIMONIAL", "RISCOS FINANCEIROS", "PESSOAS INDIVIDUAL"], [.45, .3, .2, .05]):
                    comissoes.append({"ano": ano, "mes": mes, "tipo": tipo, "celula": ramo,
                                      "valor": round(v(a, b) * x * (1.15 if ano == 2026 else 1), 2), "qtd": rnd.randint(1, 25)})
    sinistros = [{"ano": 2026, "mes": m, "segurado": cli(), "seguradora": rnd.choice(segs), "sinistro": str(rnd.randint(10**6, 10**7)),
                  "produto": rnd.choice(["AUTO", "AUTO FROTA", "RESIDENCIAL"]), "celula": "AUTOMÓVEL", "terceiro": "",
                  "valor": v(1500, 25000)} for m in sorted({x["mes"] for d in base["franqueados"].values() for x in d["sinistros"]} or {1}) for _ in range(3)]
    producao = []
    for ano in (2025, 2026):
        for mes in range(1, 13 if ano == 2025 else 11):
            for ramo, x in zip(ramos, pesos):
                for sg, y in zip(segs, [.3, .25, .2, .15, .1]):
                    producao.append({"ano": ano, "mes": mes, "ramo": ramo, "seguradora": sg,
                                     "valor": round(v(70000, 120000) * x * y * (1.12 if ano == 2026 else 1), 2), "qtd": rnd.randint(1, 8)})
    return {"nome": "TREINAMENTO (exemplo fictício)", "ficticio": True, "campanha": campanha,
            "nao_renovadas": apolices(40, "termino"), "canceladas": apolices(12, "cancelamento"),
            "conversao": conversao, "rede_conversao": rede, "comissoes": comissoes, "sinistros": sinistros, "producao": producao,
            "comissoes_a_receber": v(18000, 32000), "comissoes_liberadas": v(4000, 9000)}


# ------------------------------------------------------------------ main

def main():
    cw = crosswalk_grupo_divisao()
    campanha, meses_campanha, at_camp = carregar_campanha()
    detalhe = carregar_campanha_detalhe(meses_campanha)
    for franq, por_mes in detalhe.items():
        for mes, det in por_mes.items():
            if mes in campanha.get(franq, {}):
                campanha[franq][mes].update(det)
    # trimestres ("T1".."T4"): ranking próprio, calculado como o Geral da campanha
    trimestres = []
    for q, ms in TRIMESTRES.items():
        ms = [m for m in ms if m in meses_campanha]
        if not ms:
            continue
        trimestres.append(f"T{q}")
        for f, d in ranking_periodo(campanha, ms).items():
            campanha[f][f"T{q}"] = d
    nao_ren, at_nr = carregar_nao_renovadas()
    canc, at_canc = carregar_canceladas()
    conv, rede = carregar_conversao(cw)
    comis, arq_comis = carregar_comissoes()
    sinis = carregar_sinistros()
    a_receber, pos_receber = carregar_repasses(PASTA_A_RECEBER, "Comissões/À Receber")
    liberados, pos_liberados = carregar_repasses(PASTA_LIBERADOS, "Comissões/Repasses Liberados")
    prod = carregar_producao_geral(cw)

    # Só entra quem é unidade franqueada (está na campanha ou nos relatórios de apólices) ou tem login vinculado;
    # vendedores soltos da cotação sem unidade identificada ficam de fora e são listados no aviso abaixo.
    vinculados = set(carregar_vinculos()["vinculos"])
    franqueados = sorted(set(campanha) | set(nao_ren) | set(canc) | set(comis) | set(sinis) | set(a_receber) | set(liberados) | (vinculados & set(conv)))
    sem_unidade = sorted(set(conv) - set(franqueados))
    dados = {}
    for f in franqueados:
        conv_f = conv.get(f, {})
        dados[f] = {
            "nome": f,
            "campanha": campanha.get(f, {}),
            "nao_renovadas": resumo_apolices(nao_ren.get(f, [])),
            "canceladas": resumo_apolices(canc.get(f, [])),
            "conversao": [dict(mes=m, rotulo=MESES[m - 1], **conv_f[m]) for m in sorted(conv_f)],
            "comissoes": comis.get(f, []),
            "sinistros": sinis.get(f, []),
            "comissoes_a_receber": a_receber.get(f),
            "comissoes_liberadas": liberados.get(f),
            "producao": prod.get(f, []),
        }

    saida = {
        "gerado_em": datetime.now(FUSO).isoformat(timespec="minutes"),
        "meta_minima_campanha": META_MINIMA,
        "meses_campanha": meses_campanha,
        "trimestres_campanha": trimestres,
        "fontes": {"campanha": at_camp, "nao_renovadas": at_nr, "canceladas": at_canc, "comissoes": arq_comis},
        # médias da rede (agregadas, sem expor nenhum outro franqueado)
        "rede_conversao": [{"mes": m, "rotulo": MESES[m - 1], **v} for m, v in sorted(rede.items())],
        "franqueados": dados,
        "posicao_repasses": {"a_receber": pos_receber, "liberados": pos_liberados},
        # média por franqueado (só entre quem tem valor) — número agregado, não expõe nenhuma unidade
        "media_rede_repasses": {"a_receber": round(sum(a_receber.values()) / len(a_receber), 2) if a_receber else None,
                                "liberados": round(sum(liberados.values()) / len(liberados), 2) if liberados else None},
    }
    saida["treinamento"] = gerar_treinamento(saida)
    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as fh:
        json.dump(saida, fh, ensure_ascii=False)

    print(f"OK: {len(dados)} franqueados -> {SAIDA}")
    for nome, chave in [("campanha", "campanha"), ("não renovadas", "nao_renovadas"), ("canceladas", "canceladas")]:
        print(f"  {nome}: {sum(1 for d in dados.values() if d[chave] and (d[chave] if chave == 'campanha' else d[chave]['qtd']))} franqueados com dados")
    if sem_unidade:
        print(f"  AVISO: vendedores da cotação sem unidade identificada (fora do BI): {', '.join(sem_unidade)}")
    print(f"  conversão: meses {[r['rotulo'] for r in saida['rede_conversao']]}")


if __name__ == "__main__":
    main()
