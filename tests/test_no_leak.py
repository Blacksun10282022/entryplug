# No-leak (layer 1: the public generic rules, run locally and in CI; layer 2: if the owner's machine has
# ~/.kb/leak_terms.txt it is scanned too, and that word list is never committed).
# Zero private data in the machine repo: user absolute paths · records/ proposals/ materials/ corpus/ self/ or
# .sqlite outside the example · secret / cookie patterns · long Chinese text (>20 KB) outside the example and
# docs · BV ids outside the example · a sample plug.yaml may only reference the example equipment.
import re, subprocess
from pathlib import Path
import yaml
from conftest import ROOT

USER_PATH = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+(?!<)|/[cC]/Users/(?!<)|/home/[a-z]\w+/|/Users/[a-z]\w+/")
SECRETS = [re.compile(p) for p in (r"sk-[A-Za-z0-9]{20,}", r"AKIA[0-9A-Z]{16}", r"-----BEGIN [A-Z ]*PRIVATE KEY", r"ghp_[A-Za-z0-9]{30,}",
                                   r"(?i)\bcookie\s*[:=]\s*[A-Za-z0-9%=;_\-]{24,}", r"(?i)\bbearer\s+[A-Za-z0-9\-_\.]{24,}")]
BV = re.compile(r"BV1[0-9A-Za-z]{9}")
ALLOWED_BV = {"BV1EXAMPLE01"}
FORBIDDEN = re.compile(r"(^|/)(records|proposals|materials|corpus|self)/")
CJK = re.compile(r"[一-鿿]")
TEXT = {".py", ".md", ".yaml", ".yml", ".json", ".toml", ".txt", ".cfg", ".ini", ""}


def files():
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8").stdout
    return [f for f in out.split("\0") if f and (ROOT / f).is_file()]


def texts():
    for rel in files():
        p = ROOT / rel
        if p.suffix.lower() in TEXT:
            yield rel, p.read_text(encoding="utf-8", errors="replace")


def test_no_user_absolute_paths():
    bad = [(rel, USER_PATH.search(t).group(0)) for rel, t in texts() if USER_PATH.search(t)]
    assert not bad, bad


def test_no_private_dirs_or_sqlite_outside_example():
    bad = [rel for rel in files() if not rel.startswith("example-tool/") and (FORBIDDEN.search(rel) or rel.endswith(".sqlite"))]
    assert not bad, bad


def test_no_secret_patterns():
    bad = [(rel, s.pattern) for rel, t in texts() for s in SECRETS if s.search(t)]
    assert not bad, bad


def test_no_bv_ids_outside_example():
    bad = [(rel, sorted(set(BV.findall(t)) - ALLOWED_BV)) for rel, t in texts() if not rel.startswith("example-tool/") and set(BV.findall(t)) - ALLOWED_BV]
    assert not bad, bad


def test_no_long_chinese_text_outside_example_and_docs():
    bad = [(rel, len(CJK.findall(t))) for rel, t in texts() if not rel.startswith(("example-tool/", "docs/")) and len(CJK.findall(t)) > 20000]
    assert not bad, bad


def test_plug_yaml_samples_only_reference_example_tool():
    yamls = [rel for rel in files() if rel.endswith("plug.yaml")]
    assert yamls and all(rel.startswith("example-tool/") for rel in yamls), yamls
    for rel in yamls:
        cfg = yaml.safe_load((ROOT / rel).read_text(encoding="utf-8"))
        for t in cfg.get("tools") or []:
            path = t.get("path", "tools/%s" % t["name"])
            assert not Path(path).is_absolute() and ".." not in path and (ROOT / rel).parent.joinpath(path).is_dir(), (rel, path)
        for key in ("self", "proposals", "index"):
            assert not Path(str(cfg.get(key, ""))).is_absolute()


def test_private_term_list_if_present():
    """Layer 2: the owner's private word list (names, emails, real equipment names, drive paths…). Skipped when
    the list is absent; the list itself is never committed."""
    p = Path.home() / ".kb" / "leak_terms.txt"
    if not p.exists():
        return
    terms = [l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    bad = [(rel, term) for rel, t in texts() for term in terms if term in t]
    assert not bad, bad
