from __future__ import annotations

from collections import Counter
import re

from .html_text import clean_text


DEFAULT_KEYWORDS = (
    "AI",
    "ETF",
    "IPO",
    "A股",
    "港股",
    "美股",
    "股票",
    "基金",
    "债券",
    "黄金",
    "白银",
    "原油",
    "汇率",
    "美元",
    "美债",
    "利率",
    "降息",
    "通胀",
    "估值",
    "财报",
    "利润",
    "现金流",
    "半导体",
    "芯片",
    "新能源",
    "消费",
    "医药",
    "银行",
    "地产",
    "红利",
    "风险",
)


def split_sentences(text: str) -> list[str]:
    text = clean_text(text)
    if not text:
        return []
    parts = re.split(r"(?<=[。！？!?；;])\s*|\n+", text)
    sentences = [part.strip(" -•\t") for part in parts if len(part.strip()) >= 8]
    return sentences


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9.+-]{1,}|[\u4e00-\u9fff]{2,}", text)
    return [word.lower() for word in words]


def extract_tags(text: str, keywords: tuple[str, ...] = ()) -> list[str]:
    candidates = keywords or DEFAULT_KEYWORDS
    tags: list[str] = []
    lower = text.lower()
    for keyword in candidates:
        if keyword.lower() in lower:
            tags.append(keyword)
    return tags[:20]


def summarize_text(text: str, sentence_count: int = 8, keywords: tuple[str, ...] = ()) -> str:
    sentences = split_sentences(text)
    if not sentences:
        return "没有可总结的正文。"

    if len(sentences) <= sentence_count:
        selected = sentences
    else:
        token_counts = Counter(_tokens(text))
        keyword_set = {keyword.lower() for keyword in (keywords or DEFAULT_KEYWORDS)}
        scored: list[tuple[float, int, str]] = []
        for index, sentence in enumerate(sentences):
            sentence_tokens = _tokens(sentence)
            score = 0.0
            score += sum(token_counts[token] for token in sentence_tokens[:40]) / 10
            score += sum(3 for keyword in keyword_set if keyword and keyword in sentence.lower())
            score += 1.5 if re.search(r"\d|%|％|万|亿|美元|人民币|港元", sentence) else 0
            score += max(0, 2 - index * 0.05)
            if 20 <= len(sentence) <= 160:
                score += 1
            scored.append((score, index, sentence))
        top = sorted(scored, key=lambda item: item[0], reverse=True)[:sentence_count]
        selected = [sentence for _, _, sentence in sorted(top, key=lambda item: item[1])]

    tags = extract_tags(text, keywords)
    lines = ["## 本地摘要"]
    lines.extend(f"- {sentence}" for sentence in selected)
    if tags:
        lines.append("")
        lines.append("## 命中关键词")
        lines.append("、".join(tags))
    return "\n".join(lines)
