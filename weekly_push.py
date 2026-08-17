#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每周榜单推送：把 GitHub 每周新发布 Top 榜单推送到企业微信/钉钉机器人。

用法：
    python weekly_push.py --webhook https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx --count 10
    python weekly_push.py --webhook https://oapi.dingtalk.com/robot/send?access_token=xxx --type dingtalk --count 10
"""

import argparse
import json
import sys
import urllib.request

from github_stars_app import DAYS, enrich, fetch_new_repos


def build_text(repos, count):
    n = min(count, len(repos))
    lines = ["GitHub 每周新发布项目 Top " + str(n), ""]
    for i, r in enumerate(repos[:n], 1):
        lines.append(str(i) + ". " + r["name"] + "  ★" + str(r["stars"]))
        lines.append("    语言: " + (r["language"] or "-")
                     + "  | 作用: " + r["purpose"]
                     + "  | 适用: " + r["env"])
        lines.append("    " + r["url"])
        lines.append("")
    return "\n".join(lines)


def send(webhook, text, msgtype):
    if msgtype == "dingtalk":
        payload = {"msgtype": "markdown",
                   "markdown": {"title": "GitHub 每周新发布榜单", "text": text}}
    else:
        payload = {"msgtype": "markdown",
                   "markdown": {"content": text}}
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(webhook, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", "replace")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="推送 GitHub 每周新发布榜单到机器人")
    parser.add_argument("--webhook", required=True, help="企业微信/钉钉机器人 webhook 地址")
    parser.add_argument("--type", choices=["wecom", "dingtalk"], default="wecom",
                        help="机器人类型")
    parser.add_argument("--count", type=int, default=10, help="推送前 N 名")
    args = parser.parse_args()

    print("正在抓取数据...", file=sys.stderr)
    repos = fetch_new_repos(DAYS)
    repos = enrich(repos)
    repos.sort(key=lambda r: r["stars"], reverse=True)
    text = build_text(repos, args.count)
    result = send(args.webhook, text, args.type)
    print("推送结果:", result[:200])


if __name__ == "__main__":
    sys.exit(main())
