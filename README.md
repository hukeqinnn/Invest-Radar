# Invest Radar

本地 RSS/播客抓取、转写和摘要程序。默认每天 10:30 和 18:00 自动扫描配置里的 RSS 源，只处理上次成功扫描到本次扫描开始之间发布、且还没生成 LLM 摘要的新内容，把正文、逐字稿和系统摘要保存到本地。

当前默认配置已经加入多个播客/RSS 源，例如：

```text
小Lin说: https://feed.xyzfm.space/mkkxu98dm89e
摸鱼早报: https://feed.xyzfm.space/p3uyn6vmyxn3
起朱楼宴宾客: https://feed.xyzfm.space/ahng8d9qlywl
```

## 运行一次

```bash
cd /Users/hb34649/Documents/Codex/2026-07-06/wo-d/outputs/invest-radar
python3 -m invest_radar run --config config/sources.toml
```

输出位置：

```text
data/radar.db          # SQLite 数据库，本地生成，不提交 Git
data/texts/            # 每篇/每期正文 Markdown，本地生成
data/audio/            # 临时音频，转写后可自动删除
data/transcripts/      # Whisper 逐字稿，本地生成
data/summaries/        # LLM 系统摘要，本地生成
reports/               # 每日抓取报告，本地生成
logs/                  # 定时任务日志，本地生成
```

报告文件名会包含生成时间和内容主题，例如单篇节目会带上“来源-标题”，一天生成多份报告时更容易区分。
正文、音频、逐字稿和摘要的文件名前缀会按 `local_timezone` 配置生成，默认当前配置为北京时间 `Asia/Shanghai`。

## 本地转写模型

把 Whisper 模型放到：

```text
models/ggml-small.bin
```

如果你从浏览器下载到了 `Downloads`，可以执行：

```bash
cp ~/Downloads/ggml-small.bin models/ggml-small.bin
ls -lh models/ggml-small.bin
```

## LLM 系统摘要

程序不会把 API key 写进配置文件，也不会提交到 Git。推荐存到 macOS Keychain：

```bash
python3 scripts/save_openai_key.py
```

也可以临时通过 `OPENAI_API_KEY` 环境变量提供，但不要把 key 写进仓库文件。

日常定时运行只处理扫描窗口内的新内容：

```text
无新增内容 -> 不下载音频、不转写、不调用 LLM
有新增内容 -> 只处理上次成功扫描到本次扫描开始之间发布的内容
```

这样不会为了历史旧稿反复消耗 API。
如果某次抓取、转写或 LLM 摘要报错，程序不会推进“上次成功扫描时间”，下一次会继续覆盖这个窗口，避免漏掉失败内容。

手动试跑 1 篇历史逐字稿的 LLM 摘要：

```bash
python3 -m invest_radar llm-backfill --limit 1 --config config/sources.toml
```

手动处理某一条已经入库的节目：

```bash
python3 -m invest_radar process-item --id 11 --config config/sources.toml
```

## 添加新的 RSS 源

编辑 `config/sources.toml`，追加：

```toml
[[sources]]
name = "新的博客或播客名"
type = "rss"
url = "https://example.com/feed.xml"
enabled = true
fetch_full_pages = false
```

如果某个 RSS 源不允许下载或再处理音频，可以只抓取 RSS 文本：

```toml
download_audio = false
transcribe_audio = false
```

## 安装每天 10:30 和 18:00 定时任务

```bash
cd /Users/hb34649/Documents/Codex/2026-07-06/wo-d/outputs/invest-radar
python3 scripts/install_launchd.py
```

卸载：

```bash
python3 scripts/uninstall_launchd.py
```

## 重要说明

- 这个版本抓取 RSS 里的文本内容和文章正文。
- 对小宇宙 RSS，`description` 通常只是简介/章节，不是完整讲话稿。
- 如果 `models/ggml-small.bin` 存在，程序会下载音频并调用 `whisper-cli` 生成逐字稿。
- 如果模型不存在，报告会提示缺少模型，不会转写。
- 如果配置 `summary_mode = "llm"`，程序会使用 OpenAI API 对逐字稿生成系统摘要。
- `.gitignore` 已排除 API key 文件、数据库、音频、逐字稿、报告、日志和本地 Whisper 模型。
- 报告只是信息整理，不构成投资建议。
