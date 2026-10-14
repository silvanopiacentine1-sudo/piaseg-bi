"""BI Piaseg — servidor (local e web).

Login com o mesmo usuário/senha do Portal do Franqueado (piaseg_usuarios em get_data.php, senha em sha256).
Cada login só recebe os dados do(s) próprio(s) franqueado(s); gestores (admins) escolhem qualquer um.
Na campanha, o franqueado vê só a própria posição no ranking — nenhum número de outro franqueado sai do servidor.

Local:  python3 server.py            -> http://localhost:8020
Web:    PORT, DATA_DIR, SECRET_KEY, BI_VINCULOS_JSON, GOOGLE_SERVICE_ACCOUNT_JSON (Render)
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import urllib.request
from collections import defaultdict, deque

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import atualizador
from build_data import carregar_vinculos

BASE = os.path.dirname(os.path.abspath(__file__))
PORTAL_DATA_URL = os.environ.get("PORTAL_DATA_URL", "https://www.piaseg.com.br/get_data.php")
PORTA = int(os.environ.get("PORT") or os.environ.get("BI_PORTA") or "8020")
NA_WEB = bool(os.environ.get("PORT"))
SECRET_KEY = (os.environ.get("SECRET_KEY") or secrets.token_hex(32)).encode()
SESSAO_HORAS = 12
TODOS = "__TODOS__"
TREINAMENTO = "__TREINAMENTO__"  # unidade fictícia p/ ensinar; liberada a qualquer login, nunca somada às reais
COMUM = ("gerado_em", "atualizado", "fontes", "meta_minima_campanha", "meses_campanha", "trimestres_campanha",
         "posicao_repasses", "media_rede_repasses")

app = FastAPI(title="BI Piaseg", docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def cabecalhos_seguranca(request: Request, call_next):
    r = await call_next(request)
    r.headers["X-Frame-Options"] = "DENY"
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["Referrer-Policy"] = "same-origin"
    if NA_WEB:
        r.headers["Strict-Transport-Security"] = "max-age=31536000"
    if request.url.path.startswith("/api/"):
        r.headers["Cache-Control"] = "no-store"
    return r


# ------------------------------------------------------------------ dados (com cache pela data do arquivo)

_cache = {"mtime": None, "dados": None}


def dados():
    try:
        mt = os.path.getmtime(atualizador.ARQ_DADOS)
    except OSError:
        raise HTTPException(503, "Os dados do BI estão sendo carregados pela primeira vez. Tente novamente em alguns minutos.")
    if _cache["mtime"] != mt:
        with open(atualizador.ARQ_DADOS, encoding="utf-8") as fh:
            _cache.update(dados=json.load(fh), mtime=mt)
    return _cache["dados"]


# ------------------------------------------------------------------ login

def usuarios_portal():
    req = urllib.request.Request(PORTAL_DATA_URL, headers={"User-Agent": "piaseg-bi"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r).get("piaseg_usuarios") or []
    except Exception:
        raise HTTPException(503, "Não foi possível consultar os usuários do Portal do Franqueado. Tente novamente.")


def perfil(usuario, nome):
    cfg = carregar_vinculos()
    admin = usuario in [a.lower() for a in cfg["admins"]]
    meus = sorted(f for f, logins in cfg["vinculos"].items() if usuario in [l.lower() for l in logins])
    return {"usuario": usuario, "nome": nome, "admin": admin, "franqueados": meus}


def _b64(b):
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def criar_token(usuario, nome):
    corpo = _b64(json.dumps({"u": usuario, "n": nome, "exp": int(time.time()) + SESSAO_HORAS * 3600}).encode())
    return corpo + "." + _b64(hmac.new(SECRET_KEY, corpo.encode(), hashlib.sha256).digest())


def sessao(authorization: str):
    token = authorization.removeprefix("Bearer ").strip()
    try:
        corpo, assinatura = token.split(".")
        ok = hmac.compare_digest(assinatura, _b64(hmac.new(SECRET_KEY, corpo.encode(), hashlib.sha256).digest()))
        d = json.loads(base64.urlsafe_b64decode(corpo + "=" * (-len(corpo) % 4)))
        if not ok or d["exp"] < time.time():
            raise ValueError
    except Exception:
        raise HTTPException(401, "Sessão expirada. Faça login novamente.")
    return perfil(d["u"], d["n"])


# limite de tentativas de senha: 8 erros em 15 min por IP (e por usuário) bloqueiam por 15 min
_erros = defaultdict(deque)
_erros_trava = threading.Lock()


def _bloqueado(chave):
    with _erros_trava:
        fila = _erros[chave]
        while fila and fila[0] < time.time() - 900:
            fila.popleft()
        return len(fila) >= 8


def _registrar_erro(*chaves):
    with _erros_trava:
        for c in chaves:
            _erros[c].append(time.time())


class LoginIn(BaseModel):
    usuario: str
    senha: str


@app.post("/api/login")
def login(d: LoginIn, request: Request):
    usuario = d.usuario.strip().lower()[:200]
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "")).split(",")[0].strip()
    if _bloqueado("ip:" + ip) or _bloqueado("u:" + usuario):
        raise HTTPException(429, "Muitas tentativas. Aguarde 15 minutos e tente novamente.")
    h = hashlib.sha256(d.senha.encode("utf-8")).hexdigest()
    u = next((u for u in usuarios_portal() if str(u.get("u", "")).strip().lower() == usuario and hmac.compare_digest(str(u.get("h", "")), h)), None)
    if not u:
        _registrar_erro("ip:" + ip, "u:" + usuario)
        raise HTTPException(401, "Usuário ou senha incorretos. Use o mesmo acesso do Portal do Franqueado.")
    p = perfil(usuario, u.get("nome") or usuario)
    if not p["admin"] and not p["franqueados"]:
        raise HTTPException(403, "Seu login ainda não está vinculado a nenhuma unidade. Fale com a franqueadora.")
    return {"token": criar_token(usuario, p["nome"]), **p}


@app.get("/api/me")
def me(authorization: str = Header(default="")):
    p = sessao(authorization)
    p["opcao_treinamento"] = TREINAMENTO
    if p["admin"]:
        p["todos"] = sorted(dados()["franqueados"])
        p["opcao_todos"] = TODOS
    return p


@app.get("/api/painel")
def painel(franqueado: str, authorization: str = Header(default="")):
    p = sessao(authorization)
    base = dados()
    if franqueado == TREINAMENTO:
        return {**{k: base.get(k) for k in COMUM}, **base["treinamento"]}  # inclui a própria "média da rede" fictícia
    if franqueado == TODOS:
        if not p["admin"]:
            raise HTTPException(403, "A visão de todos os franqueados é exclusiva do gestor.")
        return {**{k: base.get(k) for k in COMUM}, "rede_conversao": base["rede_conversao"], "todos": True, "membros": base["franqueados"]}
    if not p["admin"] and franqueado not in p["franqueados"]:
        raise HTTPException(403, "Você não tem acesso a esta unidade.")
    f = base["franqueados"].get(franqueado)
    if not f:
        raise HTTPException(404, "Ainda não há dados para esta unidade.")
    return {**{k: base.get(k) for k in COMUM}, "rede_conversao": base["rede_conversao"], **f}


# ------------------------------------------------------------------ gestor: status e atualização manual

class AtualizarIn(BaseModel):
    modo: str = "mensal"


@app.get("/api/admin/status")
def status(authorization: str = Header(default="")):
    if not sessao(authorization)["admin"]:
        raise HTTPException(403, "Exclusivo do gestor.")
    return atualizador.ler_status()


@app.post("/api/admin/atualizar")
def atualizar_agora(d: AtualizarIn, authorization: str = Header(default="")):
    if not sessao(authorization)["admin"]:
        raise HTTPException(403, "Exclusivo do gestor.")
    if not os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"):
        raise HTTPException(400, "Atualização automática só funciona no servidor (no Mac, use o Abrir BI.command).")
    modo = "diario" if d.modo == "diario" else "mensal"
    threading.Thread(target=atualizador.atualizar, args=(modo,), daemon=True).start()
    return {"ok": True, "mensagem": "Atualização iniciada. Leva alguns minutos."}


@app.get("/saude")
def saude():
    return {"ok": True, "dados": os.path.exists(atualizador.ARQ_DADOS)}


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")


@app.on_event("startup")
def _inicio():
    atualizador.iniciar_agenda()


if __name__ == "__main__":
    print(f"BI Piaseg rodando em http://localhost:{PORTA}")
    uvicorn.run(app, host="0.0.0.0" if NA_WEB else "127.0.0.1", port=PORTA, log_level="warning")
