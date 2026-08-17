#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub 每周新发布项目榜单 - 桌面应用 v2（本地网页版）

双击 exe（或 python github_stars_app.py）后自动打开浏览器：
展示近 7 天新建的 50 个项目，按 Star 从多到少排列。
v2 新增：搜索/筛选、深色主题、导出 CSV/Markdown、一键复制、
收藏/屏蔽（本地持久化）、项目详情（许可证/活跃度/README 摘要）、
AI 点评与本周 Top5 推荐。

页面文件：index.html（需与脚本/exe 放在一起）
打包成 exe：双击 build.bat（PyInstaller --onefile --noconsole --add-data "index.html;."）
"""

import json
import logging
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SEARCH_URL = "https://api.github.com/search/repositories"
TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 github-stars-app/2.0")
DAYS = 7
LIMIT = 100
APP_VERSION = "3.0.0"

CACHE = {"data": None, "detail": {}, "ai_comments": {}, "page": None,
        "fetching": False, "error": "", "progress": ""}
LOCK = threading.Lock()
STOP = threading.Event()
WEBVIEW_MODE = False
LOCK_SOCK = None

DEFAULT_CONFIG = {
    "theme": "light",
    "layout": "grid",
    "favorites": [],
    "ignored": [],
    "bg": {"type": "default", "value": ""},
    "ai": {"base_url": "", "api_key": "", "model": ""},
    "min_stars": 100,
    "token": "",
    "repo": "",
    "translate": True,
}


def resource_path(name):
    """打包后从 PyInstaller 临时目录取文件，开发时从脚本目录取。"""
    if getattr(sys, "_MEIPASS", None):
        return os.path.join(sys._MEIPASS, name)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), name)


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def config_path():
    return os.path.join(app_dir(), "app_config.json")


def cache_path():
    return os.path.join(app_dir(), "cached_data.json")


def history_path():
    return os.path.join(app_dir(), "history.json")


def log_path():
    return os.path.join(app_dir(), "app.log")


logger = logging.getLogger("github_stars_app")
if not logger.handlers:
    try:
        _h = logging.FileHandler(log_path(), encoding="utf-8")
        _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(_h)
        logger.setLevel(logging.INFO)
    except Exception:
        pass


def fetch_url(url, headers=None, timeout=25, label=""):
    """带硬超时的请求：DNS/连接卡死时也会在 timeout 内返回错误，绝不无限等待。"""
    headers = headers or {"User-Agent": UA}
    result = {}

    def worker():
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result["data"] = resp.read()
        except Exception as exc:
            result["error"] = exc

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout + 5)
    if "data" in result:
        return result["data"]
    if "error" in result:
        raise result["error"]
    raise RuntimeError("网络请求超时（" + (label or url) + "）。可能被防火墙/运营商阻断，请检查网络或配置代理。")


def get_page():
    if CACHE["page"] is None:
        path = resource_path("index.html")
        try:
            with open(path, "r", encoding="utf-8") as f:
                CACHE["page"] = f.read()
        except Exception:
            CACHE["page"] = "<html><body><h1>缺少 index.html</h1><p>请把 index.html 与本程序放在同一目录。</p></body></html>"
    return CACHE["page"]


# ---------------------------------------------------------------- 配置持久化
def load_config():
    try:
        with open(config_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        cfg = dict(DEFAULT_CONFIG)
        cfg.update(data)
        ai = dict(DEFAULT_CONFIG["ai"])
        ai.update(data.get("ai") or {})
        cfg["ai"] = ai
        return cfg
    except Exception:
        return dict(DEFAULT_CONFIG)


def save_config(cfg):
    try:
        with open(config_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ---------------------------------------------------------------- 数据抓取
def fetch_new_repos(days=DAYS, min_stars=100):
    """GitHub 搜索 API：近 days 天新建、star>=min_stars 的全部仓库（分页抓取，按 star 降序）。"""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    headers = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN") or (load_config().get("token") or "").strip() or None
    if token:
        headers["Authorization"] = "token " + token
    repos = []
    page = 1
    per_page = 100
    max_pages = 20  # 安全上限：最多抓 2000 个，防无界请求
    logger.info("开始抓取：min_stars=%s since=%s", min_stars, since)
    while page <= max_pages:
        CACHE["progress"] = "正在抓取第 " + str(page) + " 页..."
        params = {
            "q": "created:>" + since + " stars:>=" + str(min_stars),
            "sort": "stars",
            "order": "desc",
            "per_page": str(per_page),
            "page": str(page),
        }
        url = SEARCH_URL + "?" + urllib.parse.urlencode(params)
        try:
            raw = fetch_url(url, headers=headers, timeout=25, label="GitHub API 第 %s 页" % page)
            data = json.loads(raw.decode("utf-8", "replace"))
        except urllib.error.URLError as exc:
            raise RuntimeError("无法连接 GitHub API（%s）。请检查网络，或配置系统代理后重试。" % exc)
        except urllib.error.HTTPError as exc:
            if exc.code == 403:
                logger.warning("GitHub API 限流（第 %s 页）", page)
                raise RuntimeError(
                    "GitHub API 限流（未登录 10 次/分钟）。请等 1 分钟再刷新，"
                    "或到「设置」填入 GitHub Token 提升限额。")
            if exc.code in (401, 422):
                raise RuntimeError("GitHub 请求被拒绝（HTTP %s），请检查设置的 Token 是否正确。" % exc.code)
            raise
        items = data.get("items", [])
        logger.info("第 %s 页返回 %s 项（累计 %s）", page, len(items), len(repos))
        CACHE["progress"] = "第 " + str(page) + " 页完成，已找到 " + str(len(repos)) + " 个项目，正在翻译简介..."
        for it in items:
            lic = it.get("license") or {}
            repos.append({
                "name": it.get("full_name", ""),
                "url": it.get("html_url", ""),
                "stars": int(it.get("stargazers_count") or 0),
                "forks": int(it.get("forks_count") or 0),
                "language": it.get("language") or "",
                "description": it.get("description") or "",
                "created": (it.get("created_at") or "")[:10],
                "pushed": (it.get("pushed_at") or "")[:10],
                "license": lic.get("spdx_id") or lic.get("name") or "",
                "homepage": it.get("homepage") or "",
                "issues": int(it.get("open_issues_count") or 0),
            })
        if len(items) < per_page:
            break
        page += 1
        if token:
            time.sleep(1.5)
        else:
            time.sleep(6)  # 未登录限流 10 次/分钟，翻页需等待
    logger.info("抓取完成：共 %s 项", len(repos))
    return repos
def translate(text):
    if not text:
        return ""
    text = text[:1500]
    params = {"client": "gtx", "sl": "en", "tl": "zh-CN", "dt": "t", "q": text}
    url = TRANSLATE_URL + "?" + urllib.parse.urlencode(params)
    try:
        raw = fetch_url(url, headers={"User-Agent": UA}, timeout=4, label="翻译接口")
        data = json.loads(raw.decode("utf-8", "replace"))
        parts = []
        for seg in data[0]:
            if seg and seg[0]:
                parts.append(seg[0])
        return "".join(parts)
    except Exception:
        return text


# ---------------------------------------------------------------- 作用 / 适用环境
def classify(repo):
    text = (repo["name"] + " " + repo["description"]).lower()
    if any(k in text for k in ("llm", "gpt", "ai agent", "agent", "machine learning",
                               "deep learning", "neural", "model", "rag", "diffusion",
                               "inference", "train", "openai", "claude")):
        purpose = "AI / 大模型"
    elif any(k in text for k in ("android", "ios", "flutter", "react native",
                                 "mobile", "swiftui", "iphone")):
        purpose = "移动应用"
    elif any(k in text for k in ("web", "website", "browser", "frontend", "dashboard",
                                 "chrome extension", "next.js", "nextjs", "vue",
                                 "react", "html", "css", "ui")):
        purpose = "Web 应用 / 前端"
    elif any(k in text for k in ("cli", "command line", "terminal", "script")):
        purpose = "命令行 / 脚本工具"
    elif any(k in text for k in ("library", "sdk", "framework", "api", "tool",
                                 "plugin", "extension", "server")):
        purpose = "开发工具 / 框架"
    elif any(k in text for k in ("game", "3d", "render", "graphics", "image")):
        purpose = "图形 / 多媒体"
    else:
        purpose = "通用工具"
    if any(k in text for k in ("android", "ios", "ios ", "flutter", "react native",
                               "mobile", "swiftui", "iphone", "watchos")):
        env = "手机"
    elif any(k in text for k in ("web", "website", "browser", "frontend", "dashboard",
                                 "chrome extension", "next.js", "nextjs", "vue",
                                 "react", "html", "css")):
        env = "电脑 / 手机（浏览器）"
    elif any(k in text for k in ("desktop", "windows", "macos", "linux", "cli",
                                 "terminal", "server", "sdk", "library", "framework")):
        env = "电脑"
    else:
        env = "电脑"
    return purpose, env


def translate_many(texts):
    """并发翻译；连续 8 次失败立即熔断，剩余条目保留英文原文。"""
    results = {}
    fails = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(translate, t): i for i, t in enumerate(texts)}
        for fut in as_completed(futs):
            i = futs[fut]
            try:
                res = fut.result()
            except Exception:
                res = ""
            results[i] = res
            if not res or res.strip() == texts[i].strip():
                fails += 1
            else:
                fails = 0
            if fails >= 8:
                for f2 in futs:
                    f2.cancel()
                break
    return [results.get(i, texts[i]) for i in range(len(texts))]


def enrich(repos):
    descs = [r["description"] for r in repos]
    cfg = load_config()
    translate_enabled = bool(cfg.get("translate", True))
    zh_list = []
    if translate_enabled and descs:
        logger.info("开始翻译/丰富 %s 条简介", len(repos))
        zh_list = translate_many(descs)
        logger.info("翻译/丰富完成")
    for i, r in enumerate(repos):
        zh = zh_list[i] if i < len(zh_list) else r["description"]
        r["zh_desc"] = zh if zh else "（无简介）"
        purpose, env = classify(r)
        r["purpose"] = purpose
        r["env"] = env
    return repos


def load_projects():
    cfg = load_config()
    min_stars = int(cfg.get("min_stars") or 100)
    repos = fetch_new_repos(DAYS, min_stars=min_stars)
    repos = enrich(repos)
    repos.sort(key=lambda r: r["stars"], reverse=True)
    return repos


def save_cache(projects, updated):
    try:
        with open(cache_path(), "w", encoding="utf-8") as f:
            json.dump({"updated": updated, "projects": projects}, f, ensure_ascii=False)
    except Exception as exc:
        logger.warning("保存缓存失败: %s", exc)


def load_cache():
    try:
        with open(cache_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_history(projects):
    try:
        now = datetime.now(timezone.utc)
        week = (now - timedelta(days=now.weekday())).date().isoformat()
        entry = {
            "week": week,
            "saved_at": now.strftime("%Y-%m-%d %H:%M UTC"),
            "projects": [
                {k: p.get(k) for k in ("name", "url", "stars", "forks", "language", "created", "zh_desc", "purpose", "env")}
                for p in projects
            ],
        }
        try:
            with open(history_path(), "r", encoding="utf-8") as f:
                hist = json.load(f)
            if not isinstance(hist, list):
                hist = []
        except Exception:
            hist = []
        hist = [h for h in hist if h.get("week") != week]
        hist.insert(0, entry)
        hist = hist[:52]
        with open(history_path(), "w", encoding="utf-8") as f:
            json.dump(hist, f, ensure_ascii=False, indent=1)
    except Exception as exc:
        logger.warning("保存历史失败: %s", exc)


def fetch_fresh():
    projects = load_projects()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if projects:  # 空结果不覆盖缓存/历史，保留上次可用数据
        save_cache(projects, now)
        save_history(projects)
    return projects, now


def start_background_fetch():
    """后台抓取最新榜单，不阻塞页面。"""
    if CACHE.get("fetching"):
        return
    CACHE["fetching"] = True
    CACHE["error"] = ""
    threading.Thread(target=_background_fetch, daemon=True).start()


def _background_fetch():
    logger.info("后台抓取开始")
    try:
        projects, now = fetch_fresh()
        CACHE["data"] = (projects, now)
        CACHE["error"] = ""
        CACHE["progress"] = "抓取完成，共 " + str(len(projects)) + " 个项目"
    except Exception as exc:
        logger.error("后台抓取失败: %s", exc)
        CACHE["error"] = str(exc)
        CACHE["progress"] = "抓取失败"
    finally:
        CACHE["fetching"] = False
        logger.info("后台抓取结束")


def get_projects(refresh=False):
    """返回 dict: projects / updated / loading / from_cache / error / progress。
    永不阻塞：慢活由后台线程执行，页面轮询即可。失败时透传 error，前端停止轮询。"""
    if refresh:
        start_background_fetch()
    data = CACHE.get("data")
    fetching = CACHE.get("fetching", False)
    error = CACHE.get("error", "") if not fetching else ""
    progress = CACHE.get("progress", "")
    if data:
        return {"projects": data[0], "updated": data[1], "loading": fetching,
                "from_cache": False, "error": error, "progress": progress}
    cached = load_cache()
    if cached and cached.get("projects"):
        return {"projects": cached["projects"], "updated": cached.get("updated", ""),
                "loading": fetching, "from_cache": True, "error": error, "progress": progress}
    if fetching:
        return {"projects": [], "updated": "", "loading": True, "from_cache": False,
                "error": "", "progress": progress}
    if error:
        return {"projects": [], "updated": "", "loading": False, "from_cache": False,
                "error": error, "progress": ""}
    start_background_fetch()
    return {"projects": [], "updated": "", "loading": True, "from_cache": False,
            "error": "", "progress": ""}
def fetch_detail(name):
    if name in CACHE["detail"]:
        return CACHE["detail"][name]
    with LOCK:
        if name in CACHE["detail"]:
            return CACHE["detail"][name]
        info = {"readme": ""}
        url = "https://api.github.com/repos/" + name + "/readme"
        headers = {"User-Agent": UA, "Accept": "application/vnd.github.raw"}
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = "token " + token
        try:
            raw = fetch_url(url, headers=headers, timeout=10, label="README")
            info["readme"] = raw.decode("utf-8", "replace")[:400].strip()
        except Exception:
            info["readme"] = ""
        CACHE["detail"][name] = info
        return info


# ---------------------------------------------------------------- AI 点评（OpenAI 兼容接口）
def ai_comments(names):
    cfg = load_config()
    ai = cfg.get("ai") or {}
    key = (ai.get("api_key") or "").strip()
    if not key:
        return {}
    base = (ai.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    model = (ai.get("model") or "").strip() or "gpt-4o-mini"
    url = base + "/chat/completions"
    prompt = (
        "你是 GitHub 项目点评助手。下面列出了本周新发布的 GitHub 项目"
        "（名称：描述）。请为每个项目写一句 30 字以内的中文点评，"
        "只输出 JSON 对象，键为项目全名，值为点评，示例："
        '{"owner/repo":"一句话点评"}。不要输出其他内容。\n项目列表：\n'
        + "\n".join("- " + n for n in names[:15])
    )
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 2000,
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + key, "User-Agent": UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        content = data["choices"][0]["message"]["content"]
        content = content.strip()
        if content.startswith(chr(96) * 3):
            content = content.split("\n", 1)[-1]
            if content.endswith(chr(96) * 3):
                content = content[:-3]
        return json.loads(content)
    except Exception:
        return {}


def check_update():
    repo = (load_config().get("repo") or "").strip()
    if not repo:
        return {"error": "未设置更新仓库（设置窗口中填写，如 owner/repo）"}
    url = "https://api.github.com/repos/" + repo + "/releases/latest"
    try:
        raw = fetch_url(url, headers={"User-Agent": UA}, timeout=10, label="更新检查")
        data = json.loads(raw.decode("utf-8", "replace"))
        latest = (data.get("tag_name") or "").lstrip("v")
        current = APP_VERSION
        has_update = False
        try:
            cv = [int(x) for x in current.split(".")]
            lv = [int(x) for x in latest.split(".")]
            has_update = lv > cv
        except Exception:
            has_update = latest != current
        return {"latest": latest, "current": current, "has_update": has_update,
                "url": data.get("html_url", ""), "note": data.get("name", "")}
    except Exception as exc:
        return {"error": "检查更新失败：" + str(exc)}


def diag():
    """快速诊断：GitHub API 是否可达、搜索剩余配额。"""
    result = {"github": {"ok": False, "error": ""},
              "token": bool(os.environ.get("GITHUB_TOKEN") or (load_config().get("token") or "").strip())}
    try:
        raw = fetch_url("https://api.github.com/rate_limit",
                          headers={"User-Agent": UA}, timeout=6, label="GitHub API 诊断")
        data = json.loads(raw.decode("utf-8", "replace"))
        core = data.get("resources", {}).get("search", {})
        result["github"]["ok"] = True
        result["github"]["remaining"] = core.get("remaining")
        result["github"]["limit"] = core.get("limit")
        result["github"]["reset"] = core.get("reset")
    except Exception as exc:
        result["github"]["error"] = str(exc)
    try:
        turl = (TRANSLATE_URL + "?client=gtx&sl=en&tl=zh-CN&dt=t&q=test")
        fetch_url(turl, headers={"User-Agent": UA}, timeout=3, label="翻译接口诊断")
        result["translate"] = {"ok": True, "error": ""}
    except Exception as exc:
        result["translate"] = {"ok": False, "error": str(exc)}
    return result


# ---------------------------------------------------------------- 本地 Web 服务
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            if path == "/":
                self._html(get_page())
            elif path in ("/api/data", "/refresh"):
                self._json(get_projects(refresh=(path == "/refresh")))
            elif path == "/api/config":
                self._json(load_config())
            elif path == "/api/ai_comments":
                self._json({"comments": CACHE["ai_comments"]})
            elif path == "/api/appinfo":
                self._json({"version": APP_VERSION, "repo": load_config().get("repo", "")})
            elif path == "/api/history":
                try:
                    with open(history_path(), "r", encoding="utf-8") as f:
                        hist = json.load(f)
                    self._json({"weeks": [{"week": h.get("week"), "saved_at": h.get("saved_at"),
                                           "count": len(h.get("projects") or [])} for h in hist]})
                except Exception:
                    self._json({"weeks": []})
            elif path.startswith("/api/history/"):
                week_key = urllib.parse.unquote(path[len("/api/history/"):])
                try:
                    with open(history_path(), "r", encoding="utf-8") as f:
                        hist = json.load(f)
                    entry = next((h for h in hist if h.get("week") == week_key), None)
                    if entry:
                        self._json({"week": week_key, "projects": entry.get("projects", []),
                                    "saved_at": entry.get("saved_at", "")})
                    else:
                        self._json({"error": "该周暂无数据"})
                except Exception as exc:
                    self._json({"error": str(exc)})
            elif path == "/api/check_update":
                self._json(check_update())
            elif path == "/api/diag":
                self._json(diag())
            elif path.startswith("/api/repo/"):
                name = urllib.parse.unquote(path[len("/api/repo/"):])
                info = {"license": "", "pushed": "", "homepage": "", "issues": 0}
                for r in get_projects()[0][0]:
                    if r["name"] == name:
                        info = {k: r.get(k, "") for k in ("license", "pushed", "homepage", "issues")}
                        break
                info["readme"] = fetch_detail(name)["readme"]
                self._json(info)
            elif path == "/shutdown":
                self._html("Bye")
                threading.Thread(target=STOP.set, daemon=True).start()
                if WEBVIEW_MODE:
                    threading.Timer(0.5, lambda: os._exit(0)).start()
            else:
                self.send_error(404)
        except Exception as exc:
            logger.warning("接口异常: %s", exc)
            try:
                self._json({"error": str(exc)})
            except Exception:
                pass

    def do_POST(self):
        try:
            path = urllib.parse.urlparse(self.path).path
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw.decode("utf-8", "replace")) if raw else {}
            if path == "/api/config":
                cfg = dict(load_config())
                for k in ("theme", "layout", "favorites", "ignored", "ai", "bg", "min_stars", "token", "repo", "translate"):
                    if k in payload:
                        cfg[k] = payload[k]
                save_config(cfg)
                if any(k in payload for k in ("min_stars", "token", "repo")):
                    CACHE["data"] = None
                self._json({"ok": True})
            elif path == "/api/ai_comment":
                names = payload.get("names") or []
                comments = ai_comments(names)
                with LOCK:
                    for k, v in comments.items():
                        CACHE["ai_comments"][k] = v
                self._json({"ok": True, "comments": comments})
            else:
                self.send_error(404)
        except Exception as exc:
            try:
                self._json({"error": str(exc)})
            except Exception:
                pass

    def _html(self, text):
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def single_instance():
    """占用 8865 端口防止重复启动，占用失败说明已有实例在运行。"""
    global LOCK_SOCK
    LOCK_SOCK = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        LOCK_SOCK.bind(("127.0.0.1", 8865))
        LOCK_SOCK.listen(1)
        return True
    except OSError:
        return False


def _main():
    logger.info("程序启动 v%s", APP_VERSION)
    if not single_instance():
        logger.info("检测到已有实例在运行，本次退出")
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0, "GitHubStarsApp 已在运行，请先关闭现有窗口。", "提示", 0x40)
        except Exception:
            pass
        return 2
    server = None
    port = 0
    for p in range(8866, 8899):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", p), Handler)
            port = p
            break
        except OSError:
            continue
    if server is None:
        return 1
    threading.Thread(target=server.serve_forever, daemon=True).start()
    get_projects()  # 启动后台抓取，不阻塞首屏
    global WEBVIEW_MODE
    url = "http://127.0.0.1:%d/" % port
    try:
        import webview  # 独立窗口模式（推荐）
        WEBVIEW_MODE = True
        webview.create_window("GitHub 每周新发布项目榜单", url)
        webview.start()
        server.shutdown()
        return 0
    except Exception:
        # 回退：用默认浏览器打开
        WEBVIEW_MODE = False
        try:
            webbrowser.open(url)
        except Exception:
            pass
        STOP.wait()
        server.shutdown()
        return 0


def main():
    try:
        return _main()
    except Exception:
        logger.exception("程序异常，详见日志 app.log")
        return 1


if __name__ == "__main__":
    sys.exit(main())
