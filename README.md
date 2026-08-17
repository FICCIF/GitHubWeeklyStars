# 每周 GitHub 新发布 Star 榜单工具

![GitHubWeeklyStars](docs/banner.png)

抓取**近 7 天新建的 GitHub 仓库**，按 Star 数量从多到少排列（默认数据源：GitHub 搜索 API，
`created:>日期` 限定新建时间）。也支持抓取 GitHub Trending 热度榜（--source trending，按一周新增 star 的热度）。

支持四种输出方式：控制台表格、JSON、HTML 报告、Markdown 报告。

## 安装

需要 Python 3.9+：

```bash
pip install -r requirements.txt
```

## 用法

```bash
# 近 7 天新建仓库，按 Star 从多到少（默认前 30）
python github_trending.py

# 近 14 天新建仓库
python github_trending.py --days 14

# 只看前 10 名
python github_trending.py --top 10

# 换成 GitHub Trending 热度榜（按一周新增 star 的热度）
python github_trending.py --source trending

# 热度榜按本周新增 Star 排序
python github_trending.py --source trending --sort weekly

# 输出 JSON
python github_trending.py --json > new.json

# 生成 HTML 网页报告
python github_trending.py --html report.html

# 生成 Markdown 报告（适合放进 Issue / README）
python github_trending.py --markdown report.md
```

### 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| --source | new | 数据来源：new=近 N 天新建仓库（默认），trending=GitHub Trending 热度榜 |
| --days | 7 | --source new 时的新建时间窗口（天） |
| --since | weekly | --source trending 时的统计周期：daily / weekly / monthly |
| --sort | total | 排序：total 按总 Star 降序、weekly 按周期新增 Star 降序、name 按名字 |
| --top | 30 | 只显示前 N 条，0 显示全部 |
| --json | 关 | 输出 JSON 到 stdout |
| --html | 无 | 生成 HTML 报告文件 |
| --markdown | 无 | 生成 Markdown 报告文件 |

## 每周自动运行

### Windows

双击 run_weekly.bat 即可抓取近 7 天新建仓库榜单并自动打开 HTML 报告。
也可以注册任务计划程序实现每周定时：

```bat
schtasks /Create /SC WEEKLY /D MON /ST 09:00 /TN "GitHubNewRepos" /TR "<项目目录>\run_weekly.bat"
```

### GitHub Actions（推荐，云端定时，无需开电脑）

把本目录推送到 GitHub 仓库后，.github/workflows/weekly-trending.yml 会每周一
00:00 (UTC) 自动生成 report/weekly-trending.md 并提交。页面
Actions → 左侧 Workflows → Weekly GitHub Trending Report 也可手动触发。

## 说明与局限

- 新建仓库数据来自 GitHub 搜索 API（q=created:>日期），无需 Token；未登录限流 10 次/分钟，够用。
  若频繁使用，可设置 GITHUB_TOKEN 环境变量提升限额。
- 自动分页抓取所有符合条件的项目（每页 100 条，安全上限 2000）；未登录的搜索 API 限流 10 次/分钟，翻页时脚本会自动等待，首次加载可能稍慢。
- GitHub Trending 热度榜解析基于当前页面 DOM 结构（article.Box-row），GitHub 改版后若解析不到数据，需更新 parse_repos 中的选择器。
- Star 数中的 k / m（如 7.7k）会换算为整数参与排序，展示时保留原始文本。

## 开箱即用：EXE 桌面应用

不想用命令行的话，可以打包成一个 exe：打开后自动在浏览器中展示榜单
（近 7 天新建的 50 个项目，按 Star 从多到少，每项含中文简介、作用、
适用环境、GitHub 来源链接，页面有「刷新榜单」「退出程序」按钮）。

```bat
1. 双击 build.bat（首次会自动安装 PyInstaller）
2. 打包完成后，双击 dist\GitHubStarsApp.exe 即可
3. 也可以不打包直接运行：python github_stars_app.py
```

说明：

- 中文简介通过在线翻译接口生成，需要联网；若翻译失败会显示英文原文。
- 「作用」「适用环境」是根据项目名称和简介关键词自动判断的，仅供参考。
- 第一次双击 exe 如果提示「未知发布者」，点「更多信息 → 仍要运行」即可。

## v2 新增功能（桌面应用）

以 `github_stars_app.py` + `index.html` 为核心的本地网页应用，双击 exe 后自动打开浏览器：

- 搜索/筛选：按关键词、语言、最低 Star 过滤榜单
- 深色/浅色主题切换（记住偏好）
- 导出 CSV / Markdown 榜单文件
- 一键复制 git clone 命令 / 项目链接
- 收藏 / 屏蔽列表（存于 app_config.json，重启不丢）
- 项目详情：许可证、最近活跃时间、README 摘要（点每项「详情」按钮）
- AI 点评：点「AI 点评」配置 OpenAI 兼容接口（OpenAI/DeepSeek/Moonshot 等）；不配置时自动生成基于分类的点评
- 本周 Top 5 角标高亮

运行：先 `python github_stars_app.py` 试效果，满意后双击 `build.bat` 打包成 `dist\GitHubStarsApp.exe`。

## 每周自动推送（企业微信/钉钉）

```bash
python weekly_push.py --webhook https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的key --count 10
python weekly_push.py --webhook https://oapi.dingtalk.com/robot/send?access_token=你的token --type dingtalk
```

Windows 定时（每周一 9 点推送）：

```bat
schtasks /Create /SC WEEKLY /D MON /ST 09:00 /TN "GitHubPush" /TR "python <项目目录>\weekly_push.py --webhook 你的webhook --count 10"
```

GitHub Actions 已支持：仓库 Settings → Secrets 里添加 `WEBHOOK_URL` 后，每周一 00:00 UTC 自动推送前 10 名。

## 最新调整

- **只显示 100+ Star 的项目**：查询条件自动加上 `stars:>=100`，**取消数量上限**，自动分页抓取全部符合条件的项目（安全上限 2000 个）；CLI 可用 `--min-stars N` 调整阈值
- **自定义背景**：页面（或独立窗口）工具栏点「背景」，可设纯色 / 渐变预设 / 上传图片，保存在 app_config.json，重启保留
- **独立桌面窗口**：打包后 exe 用 pywebview 打开独立应用窗口，不再依赖浏览器标签页；若系统缺少 WebView2 运行库会自动回退为浏览器打开

## v3 优化

- **秒开**：抓取结果缓存到 cached_data.json，下次启动先显示缓存，后台自动刷新最新榜单
- **设置窗口**：最低 Star 数、GitHub Token（提升限额）、更新仓库；保存后自动重新抓取
- **单实例保护**：重复启动会弹提示，不会抢占端口冲突；运行日志写入 app.log
- **大数据量分页渲染**：每批渲染 40 条，滚动自动加载，几千条也不卡
- **历史周榜**：每次成功刷新自动存档当周榜单（保留 52 周），窗口里可回看任意周
- **正式化**：版本号 v3.0.0、应用图标、文件属性版本信息；设置里填 owner/repo 后可检查 GitHub Releases 新版本
