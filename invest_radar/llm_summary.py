from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import subprocess
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .files import date_prefix, slugify
from .html_text import clean_text


SYSTEM_PROMPT = """你是一个面向股票、基金、宏观和产业跟踪的中文信息分析助手。
你的任务是把播客逐字稿整理成可复盘的信息笔记，而不是写营销文案。

硬性规则：
1. 只基于用户提供的逐字稿，不补充外部事实，不编造公司、数据、政策或结论。
2. 不给买入、卖出、持有、仓位、价格目标等投资建议。
3. 必须区分：事实/数据、主播或嘉宾观点、你的归纳推断、仍需验证的信息。
4. 对 Whisper 转写中疑似错别字、错名、错数字的地方，标注“可能误识别”，不要强行解释。
5. 数字、金额、比例、公司名、政策名、时间点要尽量保留；不确定时写“不确定”。
6. 输出要结构化、可扫描、少废话；优先服务后续跟踪和复盘。"""


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    model: str
    api_key_env: str
    keychain_service: str
    keychain_account: str
    reasoning_effort: str
    verbosity: str
    timeout_seconds: int
    max_chars_per_chunk: int


def get_api_key(config: LLMConfig) -> str:
    env_key = os.environ.get(config.api_key_env, "").strip()
    if env_key:
        return env_key

    if config.keychain_service and config.keychain_account:
        try:
            result = subprocess.run(
                [
                    "security",
                    "find-generic-password",
                    "-a",
                    config.keychain_account,
                    "-s",
                    config.keychain_service,
                    "-w",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            key = result.stdout.strip()
            if key:
                return key
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass

    raise RuntimeError(
        f"OpenAI API key not found. Set {config.api_key_env} or save it in macOS Keychain "
        f"service={config.keychain_service!r}, account={config.keychain_account!r}."
    )


def split_text(text: str, max_chars: int) -> list[str]:
    text = clean_text(text)
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for paragraph in text.splitlines():
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if current and current_len + len(paragraph) + 1 > max_chars:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(paragraph)
        current_len += len(paragraph) + 1

    if current:
        chunks.append("\n".join(current))
    return chunks


def _extract_text(response: dict) -> str:
    output_text = response.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    parts: list[str] = []
    for item in response.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if isinstance(text, str):
                parts.append(text)
    if parts:
        return "\n".join(parts).strip()
    raise RuntimeError("OpenAI response did not contain output text")


def call_openai_responses(prompt: str, config: LLMConfig) -> str:
    api_key = get_api_key(config)
    url = config.base_url.rstrip("/") + "/responses"
    payload = {
        "model": config.model,
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": SYSTEM_PROMPT}],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            },
        ],
    }
    if config.model.startswith(("gpt-5", "o3", "o4")):
        payload["reasoning"] = {"effort": config.reasoning_effort}
    if config.model.startswith("gpt-5"):
        payload["text"] = {"verbosity": config.verbosity}
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=config.timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API HTTP {exc.code}: {error_body[:800]}") from exc
    except URLError as exc:
        raise RuntimeError(f"OpenAI API network error: {exc.reason}") from exc

    return _extract_text(json.loads(body))


def list_openai_models(config: LLMConfig) -> list[str]:
    api_key = get_api_key(config)
    url = config.base_url.rstrip("/") + "/models"
    request = Request(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=config.timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API HTTP {exc.code}: {error_body[:800]}") from exc
    except URLError as exc:
        raise RuntimeError(f"OpenAI API network error: {exc.reason}") from exc

    data = json.loads(body)
    return sorted(item["id"] for item in data.get("data", []) if "id" in item)


def chunk_prompt(title: str, source: str, chunk: str, index: int, total: int) -> str:
    return f"""请整理以下播客逐字稿分块，供后续汇总使用。

节目：{source}
标题：{title}
分块：{index}/{total}

输出结构：
## 本块主题
用 1-2 句话说明本块主要讲什么。

## 事实与数据
- 提取明确事实、时间、金额、比例、公司、政策、市场数据。

## 观点与判断
- 只写逐字稿中明确表达的观点；不要补充外部观点。

## 涉及标的与行业
- 公司/机构：
- 行业/主题：
- 资产/市场：

## 风险与不确定性
- 包括逐字稿中提到的风险，以及转写可能误识别处。

## 可跟踪线索
- 后续值得关注的事件、指标、公司动作或政策变化。

逐字稿：
{chunk}
"""


def final_prompt(title: str, source: str, content: str, *, content_label: str) -> str:
    return f"""请把以下{content_label}整合成一份系统化中文投资信息笔记。

节目：{source}
标题：{title}

输出结构：
# {title}

## 一句话结论
用一句话说明本期最值得关注的信息，不要写成投资建议。

## 结构化要点
按主题分组，每组包含“发生了什么 / 为什么重要 / 后续看什么”。不要只是罗列原句。

## 公司、行业与资产
用表格输出，列为：类型、名称、上下文、可能影响、确定性。
类型只能从“公司/机构、行业/主题、资产/市场、政策/宏观”中选择。
确定性只能写“明确提及、推断、可能误识别”。

## 关键事实与数字
列出重要数字、时间、金额、比例、政策或事件。没有就写“无明确数字”。

## 观点归因
区分“主播/嘉宾观点”和“事实信息”。如果无法判断来源，写“逐字稿未明确归因”。

## 风险与不确定性
列出市场风险、产业风险、政策风险、信息质量风险，以及转写可能误识别处。

## 后续跟踪
给出 3-8 个后续跟踪问题或指标，要求可观察、可验证。

## 非投资但值得知道
只保留和商业、消费、科技、产业相关的信息；娱乐闲谈可忽略。

## 不构成投资建议
用一句话提醒这只是信息整理。

{content_label}：
{content}
"""


def reduce_prompt(title: str, source: str, chunk_summaries: list[str]) -> str:
    joined = "\n\n---\n\n".join(chunk_summaries)
    return final_prompt(title, source, joined, content_label="分块摘要")


def summarize_with_llm(title: str, source: str, transcript: str, config: LLMConfig) -> str:
    chunks = split_text(transcript, config.max_chars_per_chunk)
    if len(chunks) == 1:
        return call_openai_responses(final_prompt(title, source, chunks[0], content_label="完整逐字稿"), config)

    chunk_summaries = [
        call_openai_responses(chunk_prompt(title, source, chunk, index, len(chunks)), config)
        for index, chunk in enumerate(chunks, start=1)
    ]
    return call_openai_responses(reduce_prompt(title, source, chunk_summaries), config)


def summary_path_for_item(
    summaries_dir: Path,
    source_name: str,
    title: str,
    published_at: str,
    local_timezone: str = "",
) -> Path:
    source_dir = summaries_dir / slugify(source_name, "source")
    source_dir.mkdir(parents=True, exist_ok=True)
    return source_dir / f"{date_prefix(published_at, local_timezone)}-{slugify(title)}.summary.md"


def write_summary_markdown(
    path: Path,
    *,
    title: str,
    source_name: str,
    published_at: str,
    link: str,
    model: str,
    summary: str,
) -> Path:
    lines = [
        f"# {title}",
        "",
        f"- 来源: {source_name}",
        f"- 发布时间: {published_at or '未知'}",
        f"- 原始链接: {link or '无'}",
        f"- 摘要模型: {model}",
        "",
        summary,
    ]
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return path
