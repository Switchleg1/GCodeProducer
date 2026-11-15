"""Keep the offline manual navigable and schema-derived references current."""
from pathlib import Path
import importlib
import inspect
import pkgutil
import re
from urllib.parse import unquote, urlsplit

from gcodeproducer.core.cam import KINDS
from tools.generate_reference import STAGES, render_documents

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def prose(text):
    # Examples may contain arbitrary Markdown-like syntax; check document links.
    return re.sub(r"^```[^\n]*\n.*?^```\s*$", "", text, flags=re.M | re.S)


def links(path):
    return re.findall(r"!?\[[^\]]*\]\(([^\s)]+)\)", prose(path.read_text(encoding="utf-8")))


def anchors(path):
    result = set()
    counts = {}
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*$", prose(path.read_text(encoding="utf-8")), re.M):
        slug = re.sub(r"[^\w\-\s]", "", heading.lower()).replace(" ", "-")
        n = counts.get(slug, 0)
        counts[slug] = n + 1
        result.add(slug if n == 0 else f"{slug}-{n}")
    return result


def test_generated_documentation_matches_code():
    for name, expected in render_documents().items():
        assert (DOCS / "reference" / name).read_text(encoding="utf-8") == expected, (
            f"Run python tools/generate_reference.py: {name} is stale")


def test_local_documentation_links_and_anchors():
    failures = []
    for path in [ROOT / "README.md", *sorted(DOCS.rglob("*.md"))]:
        for link in links(path):
            url = urlsplit(link)
            if url.scheme or url.netloc:
                continue
            target = (path.parent / unquote(url.path)).resolve() if url.path else path
            # The root README deliberately links to the sibling GCodeTools repo.
            if not target.is_relative_to(ROOT):
                continue
            if not target.exists():
                failures.append(f"{path.relative_to(ROOT)} -> {link}: missing target")
            elif url.fragment and target.suffix == ".md" and unquote(url.fragment) not in anchors(target):
                failures.append(f"{path.relative_to(ROOT)} -> {link}: missing heading")
    assert not failures, "\n".join(failures)


def test_all_manual_pages_reachable_from_index():
    seen, pending = set(), [DOCS / "README.md"]
    while pending:
        path = pending.pop().resolve()
        if path in seen:
            continue
        seen.add(path)
        for link in links(path):
            url = urlsplit(link)
            if url.scheme or url.netloc or not url.path:
                continue
            target = (path.parent / unquote(url.path)).resolve()
            if target.is_relative_to(DOCS) and target.suffix == ".md" and target.exists():
                pending.append(target)
    assert set(DOCS.rglob("*.md")) <= seen


def test_documentation_images_are_centralized_and_indexed():
    pictures = DOCS / "pictures"
    inventory = (pictures / "README.md").read_text(encoding="utf-8")
    for path in DOCS.rglob("*"):
        if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"):
            assert path.is_relative_to(pictures), f"Move {path} into docs/pictures"
            assert f"]({path.name})" in inventory, f"Index {path.name} in pictures/README.md"


def test_feature_reference_coverage_and_lightweight_readme():
    from gcodeproducer import stages as builtins
    from gcodeproducer.stages.base import SliceStage
    discovered = set()
    for info in pkgutil.iter_modules(builtins.__path__):
        module = importlib.import_module(f"gcodeproducer.stages.{info.name}")
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ == module.__name__ and issubclass(cls, SliceStage) and cls.id:
                discovered.add(cls.id)
    assert discovered == {cls.id for cls in STAGES}, "Add new built-ins to the reference generator"
    stages = (DOCS / "reference" / "stage-settings.md").read_text(encoding="utf-8")
    for cls in STAGES:
        assert f"## {cls.id}\n" in stages
        for param in cls.parameters():
            assert f"`{param.name}`" in stages
    operations = (DOCS / "cam" / "operations.md").read_text(encoding="utf-8")
    for kind in KINDS:
        assert f"## {kind.title()}\n" in operations
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert len(readme.splitlines()) <= 100, "Keep detailed instructions in docs/"
    assert "docs/README.md" in readme
