#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub 每周新发布 Star 榜单抓取工具

默认抓取「近 7 天新建的仓库」（GitHub 搜索 API：created:>日期，按 star 从多到少），
也支持抓取 GitHub Trending 热度榜（--source trending）。

用法示例:
    python github_trending.py                                   # 近 7 天新建仓库，按总 Star 降序（默认）
    python github_trending.py --days 14                         # 近 14 天新建仓库
    python github_trending.py --source trending                 # GitHub Trending 本周热度榜
    python github_trending.py --source trending --sort weekly   # 热度榜按本周新增 star 降序
    python github_trending.py --top 10                          # 只显示前 10
    python github_trending.py --json > new.json                 # 输出 JSON
    python github_trending.py --html report.html                # 生成 HTML 报告
    python github_trending.py --markdown report.md              # 生成 Markdown 报告
"""

import argparse
import html as html_lib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from html import unescape

try:
    from bs4 import BeautifulSoup
except ImportError:  # 依赖缺失提示
    print(
        "缺少依赖 beautifulsoup4，请先执行: pip install -r requirements.txt",
        file=sys.stderr,
    )
    sys.exit(1)

TRENDING_URL = "https://github.com/trending?since={since}"
SEARCH_URL = "https://api.github.com/search/repositories"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 "
        "weekly-star-ranking-tool/1.0"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

PERIOD_LABEL = {
    "daily": "today",
    "weekly": "this week",
    "monthly": "this month",
}
PERIOD_CN = {
    "daily": "今日",
    "weekly": "本周",
    "monthly": "本月",
}

_UNIT_MULT = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}


def parse_number(text):
    """把 '7.7k' / '1,234' / '+12.3k' 这类文本解析为整数。"""
    if not text:
        return 0
    text = text.strip().replace(",", "")
    m = re.match(r"[+]?([\d.]+)\s*([kmb]?)$", text, re.IGNORECASE)
    if not m:
        return 0
    value = float(m.group(1))
    mult = _UNIT_MULT.get(m.group(2).lower(), 1)
    return int(value * mult)


def fetch_html(since):
    url = TRENDING_URL.format(since=since)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace")


def fetch_new_repos(days, min_stars=100):
    """通过 GitHub 搜索 API 抓取近 days 天新建、star>=min_stars 的全部仓库（分页）。"""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    headers = dict(HEADERS, Accept="application/vnd.github+json")
    repos = []
    page = 1
    per_page = 100
    max_pages = 20  # 安全上限：最多 2000 个
    while page <= max_pages:
        params = {
            "q": "created:>" + since + " stars:>=" + str(min_stars),
            "sort": "stars",
            "order": "desc",
            "per_page": str(per_page),
            "page": str(page),
        }
        url = SEARCH_URL + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            if exc.code == 403:
                raise RuntimeError("GitHub API 限流（未登录 10 次/分钟），请稍后再试，或设置 GITHUB_TOKEN 环境变量。")
            if exc.code in (401, 422):
                raise RuntimeError("GitHub 请求被拒绝（HTTP %s），请检查 Token 是否正确。" % exc.code)
            raise
        items = data.get("items", [])
        for item in items:
            repos.append(
                {
                    "name": item.get("full_name", ""),
                    "url": item.get("html_url", ""),
                    "description": item.get("description") or "",
                    "language": item.get("language") or "",
                    "total_stars": int(item.get("stargazers_count") or 0),
                    "total_stars_raw": "",
                    "forks": int(item.get("forks_count") or 0),
                    "forks_raw": "",
                    "stars_period": int(item.get("stargazers_count") or 0),
                    "stars_period_raw": "",
                    "period": "weekly",
                    "created_at": item.get("created_at") or "",
                }
            )
        if len(items) < per_page:
            break
        page += 1
        time.sleep(6)  # 未登录限流 10 次/分钟
    return repos
def parse_repos(html, since):
    soup = BeautifulSoup(html, "html.parser")
    repos = []
    for article in soup.select("article.Box-row"):
        name_link = article.select_one("h2 a")
        if not name_link:
            continue
        href = name_link.get("href", "")
        full_name = unescape(name_link.get_text("", strip=True)).strip("/")

        desc_el = article.select_one("p")
        description = unescape(desc_el.get_text(" ", strip=True)).strip() if desc_el else ""

        lang_el = article.select_one('[itemprop="programmingLanguage"]')
        language = lang_el.get_text(strip=True) if lang_el else ""

        total_stars = forks = 0
        total_stars_raw = forks_raw = ""
        for a in article.select("a[href$='/stargazers'], a[href$='/forks']"):
            text = a.get_text("", strip=True)
            if a.get("href", "").endswith("/stargazers"):
                total_stars_raw = text
                total_stars = parse_number(text)
            elif a.get("href", "").endswith("/forks"):
                forks_raw = text
                forks = parse_number(text)

        # 新增 star：优先取专门的周期徽标（如 "+1,234 stars this week"）
        stars_period = 0
        stars_period_raw = ""
        for el in article.select(
            "span.d-inline-block.float-sm-right, span.color-fg-muted.ml-3, div.f6 span"
        ):
            text = el.get_text(" ", strip=True)
            m = re.search(r"([\d.,]+\s*[kmb]?)\s+stars?\s", text, re.IGNORECASE)
            if m:
                stars_period_raw = m.group(1)
                stars_period = parse_number(stars_period_raw)
                break
        # 兜底：从整块文本里找
        if stars_period == 0:
            full_text = article.get_text(" ", strip=True)
            m = re.search(
                r"([\d.,]+\s*[kmb]?)\s+stars?\s+" + PERIOD_LABEL[since],
                full_text,
                re.IGNORECASE,
            )
            if m:
                stars_period_raw = m.group(1)
                stars_period = parse_number(stars_period_raw)

        repos.append(
            {
                "name": full_name,
                "url": "https://github.com" + href,
                "description": description,
                "language": language,
                "total_stars": total_stars,
                "total_stars_raw": total_stars_raw,
                "forks": forks,
                "forks_raw": forks_raw,
                "stars_period": stars_period,
                "stars_period_raw": stars_period_raw,
                "period": since,
                "created_at": "",
            }
        )
    return repos


def sort_repos(repos, sort):
    if sort == "name":
        repos.sort(key=lambda r: r["name"].lower())
    elif sort == "weekly":
        repos.sort(key=lambda r: (r["stars_period"], r["total_stars"]), reverse=True)
    else:  # total（默认）：按总 star 从多到少
        repos.sort(key=lambda r: (r["total_stars"], r["stars_period"]), reverse=True)
    return repos


def fmt_num(n, raw):
    if raw:
        return raw
    return f"{n:,}"


def source_meta(source, since, days):
    if source == "new":
        return {
            "title": f"GitHub 新建仓库 Star 榜单（近 {days} 天）",
            "headers": ("#", "项目", "Star", "创建时间", "Forks", "语言", "简介"),
            "md_headers": "| # | 项目 | Star | 创建时间 | Forks | 语言 | 简介 |",
        }
    period_cn = PERIOD_CN[since]
    return {
        "title": f"GitHub {period_cn} Star 榜单",
        "headers": ("#", "项目", "总 Star", period_cn + "新增", "Forks", "语言", "简介"),
        "md_headers": "| # | 项目 | 总 Star | 周期新增 | Forks | 语言 | 简介 |",
    }


def build_rows(repos, source):
    rows = []
    for i, r in enumerate(repos, 1):
        total = fmt_num(r["total_stars"], r["total_stars_raw"])
        forks = fmt_num(r["forks"], r["forks_raw"])
        lang = r["language"] or "-"
        desc = r["description"][:56] + "..." if len(r["description"]) > 57 else r["description"]
        cells = [str(i), r["name"], total]
        if source == "new":
            created = (r.get("created_at") or "")[:10] or "-"
            cells.append(created)
        else:
            cells.append(fmt_num(r["stars_period"], r["stars_period_raw"]))
        cells.append(forks)
        cells.append(lang)
        cells.append(desc)
        rows.append(cells)
    return rows


def print_table(repos, source, since, days):
    meta = source_meta(source, since, days)
    headers = meta["headers"]
    rows = build_rows(repos, source)
    widths = [max(len(str(h)), max(len(row[j]) for row in rows)) for j, h in enumerate(headers)]
    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    print(sep)
    print("|" + "|".join(f" {h:<{widths[j]}} " for j, h in enumerate(headers)) + "|")
    print(sep)
    for row in rows:
        print("|" + "|".join(f" {c:<{widths[j]}} " for j, c in enumerate(row)) + "|")
    print(sep)


def write_html(repos, path, source, since, days):
    meta = source_meta(source, since, days)
    period_cn = PERIOD_CN.get(since, "本周")
    rows_html = []
    for i, r in enumerate(repos, 1):
        name_html = html_lib.escape(r["name"])
        url_html = html_lib.escape(r["url"])
        lang = html_lib.escape(r["language"] or "-")
        desc = html_lib.escape(r["description"] or "")
        cells = (
            f"<td class='rank'>{i}</td>"
            f"<td><a href='{url_html}' target='_blank' rel='noopener'>{name_html}</a></td>"
            f"<td class='num'>{fmt_num(r['total_stars'], r['total_stars_raw'])}</td>"
        )
        if source == "new":
            created = html_lib.escape((r.get("created_at") or "")[:10] or "-")
            cells += f"<td class='num'>{created}</td>"
        else:
            cells += f"<td class='num'>{fmt_num(r['stars_period'], r['stars_period_raw'])}</td>"
        cells += (
            f"<td class='num'>{fmt_num(r['forks'], r['forks_raw'])}</td>"
            f"<td>{lang}</td>"
            f"<td class='desc'>{desc}</td>"
        )
        rows_html.append("<tr>" + cells + "</tr>")
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    page = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{ font-family: -apple-system, 'Segoe UI', 'Microsoft YaHei', sans-serif; margin: 24px; color: #1f2328; }}
  h1 {{ font-size: 22px; }}
  .meta {{ color: #656d76; font-size: 13px; margin-bottom: 16px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
  th, td {{ border-bottom: 1px solid #d8dee4; padding: 8px 10px; text-align: left; }}
  th {{ background: #f6f8fa; position: sticky; top: 0; }}
  .rank {{ color: #656d76; width: 40px; }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
  a {{ color: #0969da; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .desc {{ max-width: 420px; color: #57606a; }}
</style>
</head>
<body>
<h1>{title}</h1>
<p class="meta">共 {count} 个项目 · 按 Star 从多到少排列 · 生成时间 {generated}</p>
<table>
<thead><tr><th>#</th><th>项目</th><th>{star_col}</th>{extra_col}<th>Forks</th><th>语言</th><th>简介</th></tr></thead>
<tbody>
{body}
</tbody>
</table>
</body>
</html>
""".format(
        title=html_lib.escape(meta["title"]),
        count=len(repos),
        generated=generated,
        star_col="总 Star" if source != "new" else "Star",
        extra_col="<th>创建时间</th>" if source == "new" else f"<th>{period_cn} 新增</th>",
        body="\n".join(rows_html),
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)


def write_markdown(repos, path, source, since, days):
    meta = source_meta(source, since, days)
    lines = [
        "# " + meta["title"],
        "",
        "> 共 " + str(len(repos)) + " 个项目 · 按 Star 从多到少排列",
        "> 生成时间：" + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "",
        meta["md_headers"],
        "|---|------|--------|----------|-------|------|------|"
        if source != "new"
        else "|---|------|------|----------|-------|------|------|",
    ]
    for i, r in enumerate(repos, 1):
        desc = (r["description"] or "").replace("|", "\\|").replace("\n", " ")
        lang = (r["language"] or "-").replace("|", "\\|")
        name = r["name"].replace("|", "\\|")
        row = (
            "| " + str(i) + " | [" + name + "](" + r["url"] + ") | "
            + fmt_num(r["total_stars"], r["total_stars_raw"]) + " | "
        )
        if source == "new":
            created = (r.get("created_at") or "")[:10] or "-"
            row += created + " | "
        else:
            row += fmt_num(r["stars_period"], r["stars_period_raw"]) + " | "
        row += (
            fmt_num(r["forks"], r["forks_raw"]) + " | " + lang + " | " + desc + " |"
        )
        lines.append(row)
    lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        description="抓取每周 GitHub 新发布/热门项目，按 Star 数量从多到少排列",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--source", choices=["new", "trending"], default="new",
                        help="数据来源：new=近 N 天新建仓库（默认），trending=GitHub Trending 热度榜")
    parser.add_argument("--days", type=int, default=7,
                        help="--source new 时的新建时间窗口（天）")
    parser.add_argument("--min-stars", type=int, default=100,
                        help="只显示 star 数不低于该值的项目（默认 100）")
    parser.add_argument("--since", choices=["daily", "weekly", "monthly"], default="weekly",
                        help="--source trending 时的统计周期")
    parser.add_argument("--sort", choices=["total", "weekly", "name"], default="total",
                        help="排序方式：total=按总 Star 降序（默认），weekly=按周期新增 Star 降序，name=按名称")
    parser.add_argument("--top", type=int, default=30,
                        help="只显示前 N 条，0 表示全部")
    parser.add_argument("--json", action="store_true", help="输出 JSON 到 stdout")
    parser.add_argument("--html", metavar="PATH", default=None, help="生成 HTML 报告文件")
    parser.add_argument("--markdown", metavar="PATH", default=None, help="生成 Markdown 报告文件")
    args = parser.parse_args()

    try:
        if args.source == "new":
            repos = fetch_new_repos(args.days)
        else:
            repos = parse_repos(fetch_html(args.since), args.since)
    except Exception as exc:
        print("抓取失败：" + str(exc), file=sys.stderr)
        return 1

    if not repos:
        print("未获取到任何项目。", file=sys.stderr)
        return 1

    repos = sort_repos(repos, args.sort)
    if args.top and args.top > 0:
        repos = repos[: args.top]

    if args.json:
        print(json.dumps(repos, ensure_ascii=False, indent=2))
    else:
        print_table(repos, args.source, args.since, args.days)

    if args.html:
        write_html(repos, args.html, args.source, args.since, args.days)
        print("\nHTML 报告已生成：" + args.html)
    if args.markdown:
        write_markdown(repos, args.markdown, args.source, args.since, args.days)
        print("Markdown 报告已生成：" + args.markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
