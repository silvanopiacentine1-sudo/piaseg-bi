"""Atualização automática do BI no servidor (Render).

- Espelha as pastas do Drive (Piaseg Franchising/TI) num disco local, com a mesma estrutura e as datas
  de modificação do Drive (algumas regras usam a data do arquivo, ex.: downloads diários de produção).
- Diário (10h, horário de MS): pasta da campanha -> temas Campanha e Produção geral.
- Mensal (dia 05): também Cotação x Conversão, Não renovadas, Canceladas, Comissões e Sinistros.
- Roda o build_data.py num processo separado e só troca os dados no ar se o resultado for válido:
  em caso de erro, o portal continua com a última versão boa (nada se perde).
"""

import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR") or os.path.join(BASE, "data")
ESPELHO = os.path.join(DATA_DIR, "drive", "TI")
ARQ_DADOS = os.path.join(DATA_DIR, "bi_data.json")
ARQ_STATUS = os.path.join(DATA_DIR, "status.json")
FUSO = ZoneInfo("America/Campo_Grande")
HORA_DIARIA = 10
DIA_MENSAL = 5

PASTAS_DIARIAS = ["Arrancada de Vendas "]  # atenção: o nome real tem espaço no final
PASTAS_MENSAIS = ["Cotação x Conversão", "Apólices não renovadas", "Apólices Canceladas", "Comissões recebidas", "Sinistros"]
IGNORAR_SUBPASTAS = {"backups"}            # backups do Excel da campanha: não são usados pelo BI
EXTENSOES = (".xls", ".xlsx")
FOLDER_MIME = "application/vnd.google-apps.folder"

_trava = threading.Lock()


def agora():
    return datetime.now(FUSO)


# ------------------------------------------------------------------ status

def ler_status():
    try:
        with open(ARQ_STATUS, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _gravar_json(caminho, dados):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(dados, fh, ensure_ascii=False)
    os.replace(tmp, caminho)  # troca atômica: quem lê nunca pega arquivo pela metade


def _status(**mudancas):
    st = ler_status()
    st.update(mudancas)
    _gravar_json(ARQ_STATUS, st)
    return st


# ------------------------------------------------------------------ Drive

def _servico():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = service_account.Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive.readonly"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _listar(svc, q, campos="files(id, name, mimeType, modifiedTime, size)"):
    itens, token = [], None
    while True:
        r = svc.files().list(q=q, fields=f"nextPageToken, {campos}", pageSize=500, pageToken=token,
                             supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        itens += r.get("files", [])
        token = r.get("nextPageToken")
        if not token:
            return itens


def _achar_pasta(svc, nome):
    seguro = nome.strip().replace("'", "\\'")
    achados = _listar(svc, f"name contains '{seguro}' and mimeType = '{FOLDER_MIME}' and trashed = false", "files(id, name)")
    exatos = [f for f in achados if f["name"].strip() == nome.strip()]
    if not exatos:
        raise RuntimeError(f"Pasta '{nome.strip()}' não encontrada no Drive — confirme que foi compartilhada com a conta de serviço.")
    return exatos[0]["id"]


def _ts(rfc3339):
    return datetime.fromisoformat(rfc3339.replace("Z", "+00:00")).timestamp()


def _espelhar(svc, pasta_id, destino, manifesto, mantidos):
    """Baixa só o que mudou (por id + data de modificação) e reproduz a data do Drive no arquivo local."""
    from googleapiclient.http import MediaIoBaseDownload
    os.makedirs(destino, exist_ok=True)
    for item in _listar(svc, f"'{pasta_id}' in parents and trashed = false"):
        caminho = os.path.join(destino, item["name"])
        if item["mimeType"] == FOLDER_MIME:
            if item["name"].strip().lower() not in IGNORAR_SUBPASTAS:
                _espelhar(svc, item["id"], caminho, manifesto, mantidos)
            continue
        if not item["name"].lower().endswith(EXTENSOES) or item["name"].startswith("~$"):
            continue
        mantidos.add(caminho)
        if manifesto.get(caminho) == [item["id"], item["modifiedTime"]] and os.path.exists(caminho):
            continue
        req = svc.files().get_media(fileId=item["id"], supportsAllDrives=True)
        buf = io.BytesIO()
        baixador = MediaIoBaseDownload(buf, req)
        feito = False
        while not feito:
            _, feito = baixador.next_chunk()
        with open(caminho + ".parcial", "wb") as fh:
            fh.write(buf.getvalue())
        os.replace(caminho + ".parcial", caminho)
        os.utime(caminho, (_ts(item["modifiedTime"]),) * 2)
        manifesto[caminho] = [item["id"], item["modifiedTime"]]


def sincronizar(pastas):
    """Espelha as pastas pedidas. Arquivos apagados/renomeados no Drive somem do espelho também."""
    svc = _servico()
    arq_manif = os.path.join(DATA_DIR, "drive", "manifesto.json")
    try:
        with open(arq_manif, encoding="utf-8") as fh:
            manifesto = json.load(fh)
    except Exception:
        manifesto = {}
    avisos = []
    for nome in pastas:
        destino = os.path.join(ESPELHO, nome)
        mantidos = set()
        try:
            pasta_id = _achar_pasta(svc, nome)
        except RuntimeError as e:
            if nome in PASTAS_DIARIAS:
                raise                      # sem a pasta da campanha não há o que atualizar
            avisos.append(f"{e} Usando a última cópia baixada.")
            continue
        _espelhar(svc, pasta_id, destino, manifesto, mantidos)
        for raiz, _, arquivos in os.walk(destino):
            for a in arquivos:
                c = os.path.join(raiz, a)
                if c not in mantidos:
                    os.remove(c)
                    manifesto.pop(c, None)
    _gravar_json(arq_manif, manifesto)
    return svc, avisos


def campanha_atualizada_hoje(svc):
    """A planilha da campanha é regerada pela automação da campanha por volta das 10h; confere se já é a de hoje."""
    pasta = _achar_pasta(svc, PASTAS_DIARIAS[0])
    r = _listar(svc, f"'{pasta}' in parents and name = 'Comparativo_Campanha_Jan25_vs_Jan26.xlsx' and trashed = false")
    return bool(r) and datetime.fromtimestamp(_ts(r[0]["modifiedTime"]), FUSO).date() == agora().date()


# ------------------------------------------------------------------ build

def gerar_dados(mensal_ok):
    """Roda o build em processo separado e só publica se o resultado for coerente com o anterior."""
    novo = os.path.join(DATA_DIR, "bi_data.novo.json")
    env = dict(os.environ, BI_DRIVE_TI=ESPELHO, BI_SAIDA=novo)
    proc = subprocess.run([sys.executable, os.path.join(BASE, "build_data.py")], env=env, cwd=BASE,
                          capture_output=True, text=True, timeout=1800)
    saida = (proc.stdout or "") + (proc.stderr or "")
    avisos = [l.strip().replace("AVISO: ", "") for l in saida.splitlines() if "AVISO" in l]
    if proc.returncode != 0 or not os.path.exists(novo):
        raise RuntimeError("Falha ao montar os dados: " + saida.strip().splitlines()[-1] if saida.strip() else "erro desconhecido")
    with open(novo, encoding="utf-8") as fh:
        dados = json.load(fh)
    try:
        with open(ARQ_DADOS, encoding="utf-8") as fh:
            antes = len(json.load(fh)["franqueados"])
    except Exception:
        antes = 0
    if antes and len(dados["franqueados"]) < antes * 0.6:
        raise RuntimeError(f"Resultado suspeito ({len(dados['franqueados'])} franqueados contra {antes} antes) — mantida a versão anterior.")
    st = ler_status()
    marca = agora().isoformat(timespec="minutes")
    dados["atualizado"] = {"diario": marca, "mensal": marca if mensal_ok else st.get("mensal_em") or marca}
    if os.path.exists(ARQ_DADOS):
        shutil.copy2(ARQ_DADOS, os.path.join(DATA_DIR, "bi_data.anterior.json"))  # cópia da última versão boa
    _gravar_json(ARQ_DADOS, dados)
    os.remove(novo)
    return avisos


def atualizar(modo):
    """modo 'diario' = só a pasta da campanha; 'mensal' = todas as pastas."""
    if not _trava.acquire(blocking=False):
        return {"ok": False, "erro": "Já existe uma atualização em andamento."}
    try:
        _status(rodando=modo, inicio=agora().isoformat(timespec="minutes"))
        pastas = PASTAS_DIARIAS + (PASTAS_MENSAIS if modo == "mensal" else [])
        svc, avisos_drive = sincronizar(pastas)
        fresca = campanha_atualizada_hoje(svc)
        # o mensal só conta como feito se TODAS as pastas foram lidas; senão a agenda tenta de novo
        mensal_ok = modo == "mensal" and not avisos_drive
        avisos = avisos_drive + gerar_dados(mensal_ok)
        if not fresca:
            avisos.append("A planilha da campanha ainda não foi regerada hoje (a automação da campanha roda por volta das 10h).")
        marca = agora().isoformat(timespec="minutes")
        mud = dict(rodando=None, diario_em=marca, avisos=avisos, erro=None, campanha_do_dia=fresca)
        if mensal_ok:
            mud["mensal_em"] = marca
        _status(**mud)
        return {"ok": True, "avisos": avisos}
    except Exception as e:
        _status(rodando=None, erro=f"{agora():%d/%m %H:%M} — {e}")
        return {"ok": False, "erro": str(e)}
    finally:
        _trava.release()


# ------------------------------------------------------------------ agenda

def _laco():
    """Confere a cada minuto. Diário às 10h; se a planilha da campanha ainda não for a do dia,
    tenta de novo a cada 15 min até as 12h. Dia 05: atualização mensal (todas as pastas)."""
    while True:
        try:
            st, t = ler_status(), agora()
            hoje = t.date().isoformat()
            ultima = st.get("ultima_tentativa")
            pode_tentar = not ultima or datetime.fromisoformat(ultima) <= t - timedelta(minutes=15)
            if not os.path.exists(ARQ_DADOS):
                if pode_tentar:                           # primeira subida: carrega tudo
                    _status(ultima_tentativa=t.isoformat(timespec="minutes"))
                    atualizar("mensal")
            elif t.hour >= HORA_DIARIA:
                # mensal: a partir do dia 05 (se o servidor estiver fora no dia 05, roda no primeiro dia em que voltar)
                mensal_pendente = t.day >= DIA_MENSAL and (st.get("mensal_em") or "")[:7] != t.strftime("%Y-%m")
                feito_hoje = (st.get("diario_em") or "")[:10] == hoje
                if mensal_pendente and pode_tentar:
                    _status(ultima_tentativa=t.isoformat(timespec="minutes"))
                    atualizar("mensal")
                elif pode_tentar and (not feito_hoje or (not st.get("campanha_do_dia") and t.hour < 12)):
                    _status(ultima_tentativa=t.isoformat(timespec="minutes"))
                    atualizar("diario")
        except Exception as e:
            _status(erro=f"agenda: {e}")
        time.sleep(60)


def iniciar_agenda():
    if os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"):
        threading.Thread(target=_laco, daemon=True, name="agenda-bi").start()
