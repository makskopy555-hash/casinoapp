import os, hmac, hashlib, json, time, math, random, sqlite3, asyncio
from urllib.parse import parse_qsl
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton

TOKEN = os.environ["9080526597:AAH2aC4LlsnAuddRavaFKFw5VpvMPRVRLn8"]
URL = os.environ["casinoapp-production.up.railway.app"]  # https://твой-домен (Railway)
ADMIN = "rockvillager"

db = sqlite3.connect(os.getenv("DB", "casino.db"), check_same_thread=False)
db.execute("create table if not exists u(id integer primary key, name text, rub real default 0, stars real default 0)")
G = {}  # активные раунды "Рейс"
M = [13, 3, 1.3, .7, .4, .7, 1.3, 3, 13]  # плинко, RTP ~99%


def user(req):
    d = dict(parse_qsl(req.headers.get("X-Init", ""), keep_blank_values=True))
    h = d.pop("hash", "")
    s = "\n".join(f"{k}={v}" for k, v in sorted(d.items()))
    k = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(hmac.new(k, s.encode(), hashlib.sha256).hexdigest(), h):
        raise web.HTTPUnauthorized()
    u = json.loads(d["user"])
    db.execute("insert into u(id,name) values(?,?) on conflict(id) do update set name=excluded.name",
               (u["id"], (u.get("username") or "").lower()))
    db.commit()
    return u["id"], (u.get("username") or "").lower()


def row(uid): return db.execute("select rub,stars from u where id=?", (uid,)).fetchone()
def bal(uid, c): return row(uid)[0 if c == "rub" else 1]
def add(uid, c, d):
    db.execute(f"update u set {c}=round({c}+?,2) where id=?", (d, uid)); db.commit()


def take(uid, b, c):
    a = round(float(b.get("bet", 0)), 2)
    if a <= 0 or a > bal(uid, c): raise ValueError("Недостаточно средств")
    add(uid, c, -a)
    return a


R = web.RouteTableDef()


def api(path):
    def w(f):
        async def h(r):
            uid, name = user(r)
            b = await r.json() if r.can_read_body else {}
            c = b.get("cur", "rub")
            if c not in ("rub", "stars"): c = "rub"
            try: res = f(uid, name, b, c)
            except (ValueError, TypeError) as e: res = {"err": str(e)}
            res["rub"], res["stars"] = row(uid)
            res["admin"] = name == ADMIN
            return web.json_response(res)
        R.post(path)(h)
        return f
    return w


@api("/api/me")
def me(u, n, b, c): return {}


@api("/api/plinko")
def plinko(u, n, b, c):
    a = take(u, b, c)
    p = [random.randint(0, 1) for _ in range(8)]
    m = M[sum(p)]
    add(u, c, round(a * m, 2))
    return {"path": p, "mult": m, "win": round(a * m, 2)}


def mult(g): return math.floor(math.exp(.15 * (time.time() - g["t"])) * 100) / 100


@api("/api/race/start")
def rstart(u, n, b, c):
    if u in G: raise ValueError("Раунд уже идёт")
    a = take(u, b, c)
    G[u] = dict(a=a, c=c, t=time.time(), cr=max(1.0, min(100.0, 0.96 / (1 - random.random()))))
    return {}


@api("/api/race/tick")
def rtick(u, n, b, c):
    g = G.get(u)
    if not g: return {"state": "idle", "m": 1}
    m = mult(g)
    if m >= g["cr"]:
        del G[u]; return {"state": "crash", "m": round(g["cr"], 2)}
    return {"state": "fly", "m": m}


@api("/api/race/land")
def rland(u, n, b, c):
    g = G.get(u)
    if not g: raise ValueError("Раунд уже закончен")
    m = mult(g)
    del G[u]
    if m >= g["cr"]: return {"state": "crash", "m": round(g["cr"], 2)}
    w = round(g["a"] * m, 2)
    add(u, g["c"], w)
    return {"state": "land", "m": m, "win": w}


@api("/api/upgrade")
def upgrade(u, n, b, c):
    t = round(float(b.get("to", 0)), 2)
    a = round(float(b.get("bet", 0)), 2)
    if not (a < t <= a * 50): raise ValueError("Цель должна быть больше ставки (макс. x50)")
    take(u, b, c)
    ok = random.random() < a / t
    if ok: add(u, c, t)
    return {"ok": ok, "chance": a / t * 100}


@api("/api/give")
def give(u, n, b, c):
    if n != ADMIN: raise ValueError("Нет доступа")
    r = db.execute("select id from u where name=?", (str(b.get("user", "")).lstrip("@").lower(),)).fetchone()
    if not r: raise ValueError("Пользователь ещё не открывал приложение")
    add(r[0], c, round(float(b.get("amount", 0)), 2))
    return {}


async def main():
    bot, dp = Bot(TOKEN), Dispatcher()

    @dp.message(CommandStart())
    async def start(m):
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎮 Играть", web_app=WebAppInfo(url=URL))]])
        await m.answer("🎰 Плинко, Рейс и Апгрейдер — жми «Играть»", reply_markup=kb)

    app = web.Application()
    app.add_routes(R)
    app.router.add_get("/", lambda r: web.FileResponse("index.html"))
    run = web.AppRunner(app)
    await run.setup()
    await web.TCPSite(run, "0.0.0.0", int(os.getenv("PORT", 8080))).start()
    await dp.start_polling(bot)


asyncio.run(main())
