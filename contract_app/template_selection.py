"""Choose templates locally; document text/customer lists never go to chat AI."""
from dataclasses import dataclass
from pathlib import Path
import re

from .money import normalize
from .template_builder import template_metadata


@dataclass(frozen=True)
class TemplateMatch:
    path: Path
    title: str
    description: str
    score: int


def rank_templates(prompt: str, paths: list[Path]) -> list[TemplateMatch]:
    # The requested contract type precedes the work description. For example,
    # a purchase contract for containers serving a construction project is purchase.
    query = normalize(prompt)
    heading = re.split(r"\b(?:noi dung|cong viec|hang hoa)\s*:", query, maxsplit=1)[0]
    types = ["nguyen tac", "mua ban", "thi cong", "xay dung", "dich vu", "cho thue", "thue"]
    requested = [kind for kind in types if re.search(r"(?<!\w)" + kind + r"(?!\w)", heading)]
    stopwords = {"tao", "hop", "dong", "voi", "cong", "ty", "cho", "noi", "dung", "cua", "can", "mot", "mau", "test", "so", "anh", "chi"}
    tokens = {token for token in re.findall(r"[a-z0-9]+", heading) if len(token) >= 3 and token not in stopwords}
    matches = []
    for path in paths:
        metadata = template_metadata(path)
        title = metadata.get("title") or path.stem
        contract_type = metadata.get("contract_type") or ""
        text = normalize(title + " " + contract_type).replace("-", " ")
        score = sum(6 if kind != "nguyen tac" else 3 for kind in requested if kind in text)
        score += sum(2 for token in tokens if re.search(r"(?<!\w)" + re.escape(token) + r"(?!\w)", text))
        explicit_title = normalize(title)
        if len(explicit_title) > 8 and explicit_title in query:
            score += 30
        description = metadata.get("summary", "") or contract_type or path.name
        matches.append(TemplateMatch(path, title, description, score))
    return sorted(matches, key=lambda item: (-item.score, item.title))


def confident_template(matches: list[TemplateMatch]) -> Path | None:
    if len(matches) == 1:
        return matches[0].path
    if matches and matches[0].score >= 6 and matches[0].score - matches[1].score >= 4:
        return matches[0].path
    return None
