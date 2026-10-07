#!/usr/bin/env python3
"""research_record.py -- the paper's research record, attached for its committee (KIT-043).

    python3 submission/scripts/research_record.py build <workspace> <out.zip>
    python3 submission/scripts/research_record.py attach <sub_id> <workspace>
    python3 submission/scripts/research_record.py attach-dir <sub_id> <folder>   # an existing paper's own code
    python3 submission/scripts/research_record.py code-statement <attached 0|1> <own paper 0|1>

A paper is the last step of a run of choices it does not show -- which
benchmarks, which data, which metrics, how many variants met the test set
before one was reported -- and a reviewer can check them only in the code and
the logs (owner, 2026-10-07; Luo, Kasirzadeh and Shah, PNAS 2026). So the kit
attaches them with every paper it submits, unless the owner sets
AC_ATTACH_RECORD=0 in state/runner.env -- and then gives the code as an
anonymous link (AC_CODE_LINK), since a paper an agent wrote goes in only with
its code (KIT-044):

  runs/          the experiments' code, the replay manifest, every run's
                 results (the failed and the discarded ones too), the
                 reproduction gate's report
  refine-logs/   the experiment plan, the decisions and why, the related work
  RECORD.md      what is in it, what was left out and why, what was replaced

Never: state/, custom/, the prompts, the paper's own files, anything named
like a key, a binary, a model's weights, a link (links are not followed).

Who wrote it is taken out first, because the committee reads it before
publication (double-blind): this machine's user and host names, the home
directory, git's author name and email, the agent's name and id, every email
address and anything that looks like a key, replaced by <user>, <host>, <name>,
<email>, <secret>. The code may then not run as it is: it is there to be read.
The platform checks again when it arrives; a line it still finds naming an
author is taken out and the record sent again, at most three times.

It is public with the paper once the paper is published. Exit 0 on success,
1 when nothing could be attached (the paper goes in without it, and says so).
Standard library only.
"""
import getpass
import hashlib
import io
import json
import os
import re
import socket
import stat
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
STATE = os.environ.get("AC_STATE", os.path.join(ROOT, "state"))

ZIP_MAX = 4_600_000              # the platform takes 5 MiB an attachment
FILE_MAX = 2 * 1024 * 1024       # one file, read and scrubbed
TOTAL_MAX = 48 * 1024 * 1024     # everything, before compression
DIRS = ("runs", "refine-logs")
TOP = ("STUDY_KIND",)
SKIP_DIRS = {"__pycache__", ".git", ".cache", "cache", "hf_cache", "huggingface", "wandb", "mlruns", ".ipynb_checkpoints",
             "node_modules", ".venv", "venv", "env", ".mypy_cache", ".pytest_cache", "checkpoints", "ckpt", "weights"}
WEIGHTS = re.compile(r"\.(pt|pth|bin|safetensors|ckpt|onnx|h5|hdf5|pb|tflite|gguf|npz|npy|pkl|pickle|joblib|parquet|arrow|feather|tar|zip|gz|bz2|xz|7z|png|jpe?g|gif|pdf|mp4|wav|mp3)$", re.I)
SECRET_NAME = re.compile(r"(^\.env|\.pem$|\.key$|^id_[a-z0-9]+(\.pub)?$|credential|secret|token|password|passwd|^\.?netrc$|^\.npmrc$|^\.pypirc$|"
                         r"^\.gitconfig$|^\.git-credentials$|^known_hosts$|^authorized_keys$|\.kdbx$|\.p12$|\.pfx$|^\.?htpasswd$|kubeconfig)", re.I)
CODE = re.compile(r"\.(py|ipynb|sh|r|jl|c|cc|cpp|cu|h|hpp|java|js|ts|go|rs|m|lean|v|scala|sql)$", re.I)
# An existing paper's folder often holds the paper too: its source names its
# authors, and the paper goes in by itself.
PAPER_FILES = re.compile(r"\.(tex|bib|bbl|bst|cls|sty|aux|blg|fls|fdb_latexmk|synctex|toc|nav|snm|vrb|docx?|odt|rtf|pptx?|key|pages)$", re.I)

# A name that is also a word of code or speech names nobody, and replacing it
# would wreck the code a reviewer reads (red-team, 2026-10-07: an agent called
# "ada" turned Adam into <name>m; a user "max" took np.max).
COMMON = set("""
root user users admin administrator data test tests main model models train training eval ubuntu runner guest jovyan colab
kaggle codespace codespaces node app default shared public builder max min sum len list dict set map filter input output
print open range type object str int float bool bytes file files dir vars zip iter next any all abs round sorted hash help
format super self cls args kwargs argv config cfg run runs result results inputs outputs label labels step steps epoch epochs
batch loss adam ada sgd lr gpu cpu cuda np pd os sys re io net nn opt optim log logs tmp temp src lib util utils env venv
home work job jobs task tasks name names value values key keys item items text line lines word words time date path paths
""".split())
# Directories a shared filesystem names that name nobody.
DIR_WORDS = set("""data datasets dataset shared share public pub common tmp temp scratch work home projects project models model
cache caches lib libs opt usr local bin src apps app archive archives backup backups users groups group lab labs research
storage volumes nfs mnt media envs miniconda3 anaconda3 conda""".split())
PUBLIC_ORGS = set("""huggingface pytorch google google-research google-deepmind deepmind facebookresearch meta-llama openai anthropics
microsoft nvidia tensorflow keras-team scikit-learn numpy scipy pandas-dev matplotlib jax-ml eleutherai allenai stanfordnlp
stanford-crfm mistralai qwen qwenlm thudm lm-sys vllm-project sgl-project ollama ggerganov ggml-org langchain-ai farama-foundation
pyg-team dmlc apache python astral-sh conda conda-forge rapidsai bigscience-workshop bigcode-project tatsu-lab princeton-nlp
deepseek-ai bytedance tencent alibaba baidu intel amd apple ibm aws awslabs explosion ray-project wandb mlflow lightning-ai
openai-community distilbert bert-base-uncased gpt2 sentence-transformers datasets""".split())


# ---------------------------------------------------------------- who to take out
def git_identity(cwd=None):
    out = []
    for key in ("user.name", "user.email"):
        try:
            v = subprocess.run(["git", "config", "--get", key], capture_output=True, text=True, timeout=10,
                               cwd=cwd if cwd and os.path.isdir(cwd) else None).stdout.strip()
        except Exception:  # noqa: BLE001 -- no git is no git identity
            v = ""
        if v:
            out.append(v)
    return out


def identity(workspace: str) -> dict:
    """This machine's and this agent's names, to be replaced."""
    user = set()
    for v in (getpass.getuser(), os.environ.get("USER"), os.environ.get("LOGNAME")):
        if v and len(v) >= 3 and v.lower() not in COMMON:
            user.add(v)
    host = set()
    for v in (socket.gethostname(), socket.gethostname().split(".")[0]):
        if v and len(v) >= 3 and v.lower() not in ("localhost",) and v.lower() not in COMMON:
            host.add(v)
    names = set()
    for v in git_identity(workspace):
        names.add(v)
    try:
        with open(os.path.join(STATE, "agent.json"), encoding="utf-8") as f:
            a = json.load(f)
        for k in ("name", "agent_id"):
            if a.get(k) and str(a[k]).lower() not in COMMON:
                names.add(str(a[k]))
    except (OSError, ValueError):
        pass
    # Each place both as given and as the filesystem resolves it (a home or a
    # workspace reached through a link shows its real path in a traceback).
    places = []
    for p, rep in ((os.path.abspath(workspace), "."), (ROOT, "<kit>"), (os.path.expanduser("~"), "~")):
        for v in {p, os.path.realpath(p)}:
            if v and len(v) > 1:
                places.append((v, rep))
    return {"user": sorted(user, key=len, reverse=True), "host": sorted(host, key=len, reverse=True),
            "name": sorted(names, key=len, reverse=True), "places": sorted(places, key=lambda x: len(x[0]), reverse=True)}


def secrets_in_env() -> list:
    """Credential values in the environment: taken out wherever they appear
    (an AWS secret has a / in it, a database password may be short)."""
    out = []
    for k, v in os.environ.items():
        if re.search(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH", k, re.I) and v and len(v) >= 8 and v.lower() not in ("true", "false", "none"):
            out.append(v)
    try:
        with open(os.path.join(STATE, "agent.json"), encoding="utf-8") as f:
            k = json.load(f).get("api_key")
        if k:
            out.append(k)
    except (OSError, ValueError):
        pass
    return sorted(set(out), key=len, reverse=True)


def _ns(m, keep_public=True):
    """A code host's or a tracker's namespace: a person, unless a known org's."""
    pre, ns = m.group(1), m.group(2)
    return m.group(0) if keep_public and ns.lower() in PUBLIC_ORGS else f"{pre}<user>"


def _seg(m):
    """A shared filesystem's directory after its root: its user or its lab."""
    out, root = [m.group(1)], True
    for s in m.group(2).split("/"):
        out.append(s if (not s or s in DIR_WORDS or not root) else "<user>")
        root = False if s and s not in DIR_WORDS else root
    return "/".join(out)


# In order. What is replaced is said in RECORD.md, by kind.
SHAPES = [
    ("secret", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"), None),
    ("secret", re.compile(r"\b(?:sk|pk|rk)[-_](?:ant-|proj-|live_|test_)?[A-Za-z0-9_-]{16,}|\bgh[pousr]_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}|\bhf_[A-Za-z0-9]{20,}"
                          r"|\b(?:AKIA|ASIA)[0-9A-Z]{16}\b|\bxox[baprs]-[A-Za-z0-9-]{10,}|\bAIza[0-9A-Za-z_-]{30,}|\bGOCSPX-[A-Za-z0-9_-]{10,}|\bac_(?:live|host|test)_[A-Za-z0-9_-]{8,}"
                          r"|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}|https://hooks\.slack\.com/services/[A-Za-z0-9/_-]+"), None),
    ("secret", re.compile(r"(\b[A-Za-z][A-Za-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@"), r"\1<secret>@"),
    ("secret", re.compile(r"(?i)(\b[\w.-]*(?:api[_-]?key|secret|token|passw(?:or)?d|pwd|access[_-]?key|auth[_-]?key|credential|private[_-]?key|webhook)[\w.-]*[\"']?\s*[:=]\s*[\"']?)([^\s\"',;]{6,})"), r"\1<secret>"),
    ("secret", re.compile(r"(?i)(\bpassword\s+)(\S+)"), r"\1<secret>"),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), None),
    ("email", re.compile(r"(?i)\b[\w.+-]+\s*[\[({]\s*at\s*[\])}]\s*[\w-]+(?:\s*[\[({]\s*dot\s*[\])}]\s*[\w-]+)+"), None),
    ("user", re.compile(r"((?:https?://)?(?:www\.)?(?:github\.com|gitlab\.com|bitbucket\.org|codeberg\.org|huggingface\.co)/)([A-Za-z0-9_.-]+)"), _ns),
    ("user", re.compile(r"((?:https?://)?(?:www\.)?wandb\.ai/)([A-Za-z0-9_.-]+)"), lambda m: _ns(m, keep_public=False)),
    ("user", re.compile(r"(git@[A-Za-z0-9.-]+:)([^/\s]+)(?=/)"), _ns),
    ("host", re.compile(r"\b[A-Za-z0-9-]+\.(?:local|lan|home|internal|intranet|corp)\b", re.I), None),
    ("host", re.compile(r"\b(?:[A-Za-z0-9-]+\.)+(?:edu|ac\.[a-z]{2}|edu\.[a-z]{2})\b", re.I), None),
    ("host", re.compile(r"\b[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*-(?:MacBook|MBP|Mac-mini|iMac|Mac-Studio|Mac-Pro|Laptop|Desktop|PC|ThinkPad|XPS)(?:-[A-Za-z0-9]+)*\b", re.I), None),
    ("user", re.compile(r"((?:/Users|/home|/mnt/[a-z]/Users|[A-Za-z]:[\\/]Users)[\\/])([^/\\\s'\"`:;,)]+)"), r"\1<user>"),
    ("user", re.compile(r"(?<![\w.\]/~-])(/(?:scratch|work|gpfs|lustre|nfs|storage|projects?|groups?|data|mnt|vast|beegfs))/((?:[^/\s'\"`]+/){0,2}[^/\s'\"`]+)(?=/)"), _seg),
    ("user", re.compile(r"(?m)^((?:export\s+)?(?:USER|LOGNAME|USERNAME|SUDO_USER|HOME|HOSTNAME|HOST|PWD|OLDPWD|MAIL|SSH_CLIENT|SSH_CONNECTION"
                        r"|SLURM_JOB_USER|SLURM_JOB_ACCOUNT|SLURM_SUBMIT_HOST|SLURM_CLUSTER_NAME|SLURM_JOB_PARTITION|SLURM_SUBMIT_DIR|SLURM_JOB_UID|SLURM_JOB_GID"
                        r"|PBS_O_HOME|PBS_O_LOGNAME|PBS_O_HOST|PBS_O_WORKDIR|LSB_SUB_USER|GIT_AUTHOR_NAME|GIT_AUTHOR_EMAIL|GIT_COMMITTER_NAME|GIT_COMMITTER_EMAIL"
                        r"|CONDA_PREFIX|VIRTUAL_ENV|WANDB_ENTITY|WANDB_USERNAME|HF_USERNAME)=).*$"), r"\1<withheld>"),
    ("user", re.compile(r"\b(UserId|GroupId|Account|AllocNode:Sid|BatchHost|SubmitHost|WorkDir|StdOut|StdErr|Command|Partition|Reservation)=(\S+)"), r"\1=<withheld>"),
    ("name", re.compile(r"(?im)^((?:Author|Commit|Committer|Signed-off-by|Co-authored-by|Reviewed-by|Tested-by|Reported-by)\s*:\s*).+$"), r"\1<name>"),
    ("name", re.compile(r"(?i)\b(user\.(?:name|email)\s*[=:]\s*).+$", re.M), r"\1<name>"),
    ("name", re.compile(r"\b(Prof\.?|Professor|Dr\.|Mr\.|Ms\.|Mrs\.|[Aa]dvis[oe]r|[Ss]upervisor|PI)\s+([A-Z][\w'’-]+(?:\s+[A-Z][\w'’-]+){0,2})"), r"\1 <name>"),
    ("user", re.compile(r"\b([a-z_][a-z0-9_.-]{1,31})@([A-Za-z0-9][A-Za-z0-9-]*)(?=[\s:~$#])"), "<user>@<host>"),
    ("user", re.compile(r"(?m)^([-dlcbps][-rwxsStT]{9}[@+.]?\s+\d+\s+)(\S+)(\s+)(\S+)(?=\s+\d)"), r"\1<user>\3<user>"),
    ("ip", re.compile(r"(?<![\w.=v-])((?:25[0-5]|2[0-4]\d|1?\d?\d)\.(?:25[0-5]|2[0-4]\d|1?\d?\d)\.(?:25[0-5]|2[0-4]\d|1?\d?\d)\.(?:25[0-5]|2[0-4]\d|1?\d?\d))(?![\w.])"),
     lambda m: m.group(0) if re.match(r"^(?:127\.|0\.0\.0\.0|255\.)", m.group(0)) else "<ip>"),
]


def learn(texts) -> tuple:
    """The user and host names the record itself shows -- in a path, an
    environment line, a listing, a prompt -- to take out wherever else they
    appear (a kernel's name, a log line)."""
    users, hosts, people = set(), set(), set()

    def user(v):
        v = (v or "").strip("'\"")
        if len(v) >= 3 and re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]{1,31}", v) and v.lower() not in COMMON and v.lower() not in DIR_WORDS:
            users.add(v)
    for t in texts:
        for m in re.finditer(r"(?:/Users|/home|/mnt/[a-z]/Users|[A-Za-z]:[\\/]Users)[\\/]([^/\\\s'\"`:;,)]+)", t):
            user(m.group(1))
        for m in re.finditer(r"(?m)^(?:export\s+)?(?:USER|LOGNAME|USERNAME|SUDO_USER|SLURM_JOB_USER|PBS_O_LOGNAME|LSB_SUB_USER)=['\"]?([^\s'\"]+)", t):
            user(m.group(1))
        for m in re.finditer(r"\bUserId=([A-Za-z][\w.-]*)\(", t):
            user(m.group(1))
        for m in re.finditer(r"(?m)^[-dlcbps][-rwxsStT]{9}[@+.]?\s+\d+\s+(\S+)\s+(\S+)\s+\d", t):
            user(m.group(1))
            user(m.group(2))
        for m in re.finditer(r"\b([a-z_][a-z0-9_.-]{1,31})@([A-Za-z0-9][A-Za-z0-9-]*)(?=[\s:~$#])", t):
            user(m.group(1))
            if len(m.group(2)) >= 3 and m.group(2).lower() not in COMMON:
                hosts.add(m.group(2))
        for m in re.finditer(r"(?m)^(?:export\s+)?(?:HOSTNAME|HOST|SLURM_SUBMIT_HOST)=['\"]?([^\s'\"]+)", t):
            if len(m.group(1)) >= 3:
                hosts.add(m.group(1))
        # A person named once with a title is a person wherever they appear.
        for m in re.finditer(r"\b(?:Prof\.?|Professor|Dr\.|[Aa]dvis[oe]r|[Ss]upervisor)\s+((?:[A-Z]\.\s*)?[A-Z][\w'’-]+(?:\s+[A-Z][\w'’-]+){0,2})", t):
            for w in re.findall(r"[A-Z][\w'’-]{2,}", m.group(1)):
                if w.lower() not in COMMON:
                    people.add(w)
    return sorted(users, key=len, reverse=True), sorted(hosts, key=len, reverse=True), sorted(people, key=len, reverse=True)


def scrubber(who: dict, keys: list, learned=((), (), ())):
    """A function that takes this machine and this person out of a text."""
    exact = []
    for k in keys:
        exact.append(("secret", re.escape(k)))
    for n in who["name"]:
        exact.append(("name", r"(?<![A-Za-z0-9_])" + re.escape(n) + r"(?![A-Za-z0-9_])"))
    # Whole names of identifiers, never inside one: Adam stays Adam.
    for u in list(who["user"]) + [u for u in learned[0] if u not in who["user"]]:
        exact.append(("user", r"(?<![A-Za-z0-9_])" + re.escape(u) + r"(?![A-Za-z0-9_])"))
    for h in list(who["host"]) + [h for h in learned[1] if h not in who["host"]]:
        exact.append(("host", r"(?<![A-Za-z0-9-])" + re.escape(h) + r"(?![A-Za-z0-9-])"))
    for n in (learned[2] if len(learned) > 2 else ()):
        exact.append(("name", r"(?<![A-Za-z0-9_])" + re.escape(n) + r"(?![A-Za-z0-9_])"))
    compiled = [(k, re.compile(p, re.I)) for k, p in exact]

    def scrub(text: str, counts: dict) -> str:
        for p, rep in who["places"]:
            if p in text:
                counts["path"] = counts.get("path", 0) + text.count(p)
                text = text.replace(p, rep)
        for kind, rx, to in SHAPES:
            new, n = rx.subn(to if to is not None else f"<{kind}>", text)
            if new != text:
                counts[kind] = counts.get(kind, 0) + n
            text = new
        for kind, rx in compiled:
            text, n = rx.subn(f"<{kind}>", text)
            if n:
                counts[kind] = counts.get(kind, 0) + n
        return text
    return scrub


# ---------------------------------------------------------------- what goes in
def candidates(workspace: str, links=None, whole=False):
    """(relative path, absolute path), by priority: code, manifests, logs,
    results. A link met on the way is listed in `links`, never followed.
    `whole`: a folder of the owner's own (an existing paper's code), taken
    whole rather than by the kit's workspace layout."""
    found = []
    links = [] if links is None else links
    for top in (() if whole else TOP):
        p = os.path.join(workspace, top)
        if os.path.isfile(p) and not os.path.islink(p):
            found.append((top, p))
    for d in ((".",) if whole else DIRS):
        base = os.path.join(workspace, d)
        if not os.path.isdir(base) or os.path.islink(base):
            continue
        for dp, dn, fn in os.walk(base, followlinks=False):
            links.extend(os.path.relpath(os.path.join(dp, x), workspace) for x in dn if os.path.islink(os.path.join(dp, x)))
            dn[:] = sorted(x for x in dn if x not in SKIP_DIRS and not x.startswith(".") and not os.path.islink(os.path.join(dp, x)))
            for f in sorted(fn):
                p = os.path.join(dp, f)
                if whole and f.startswith("."):
                    continue
                found.append((os.path.relpath(p, workspace), p))

    def rank(item):
        rel = item[0]
        if CODE.search(rel):
            return 0
        if rel.startswith("runs/") and rel.count("/") == 1:
            return 1          # REPLAY_MANIFEST.json, manifest.json, REPRO_GATE.json, CALIBRATION.json ...
        if rel.startswith("refine-logs/") or rel in TOP:
            return 2
        return 3
    return sorted(found, key=lambda it: (rank(it), it[0]))


def decode(raw: bytes) -> str:
    """Text as it was written: UTF-16 with its byte-order mark, else UTF-8."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", "replace")
    return raw.decode("utf-8", "replace")


def build(workspace: str, out_zip: str, extra_drops=None, whole=False) -> dict:
    """The record, scrubbed and zipped within the platform's size. Returns what
    went in and what did not. `extra_drops`: {entry: {line, ...}} the platform
    found naming an author, taken out."""
    who = identity(workspace)
    counts, left, total = {}, [], 0
    links = []
    ranked = candidates(workspace, links, whole)
    left.extend((rel, "a link (not followed)") for rel in links)
    texts = []
    for rel, path in ranked:
        name = os.path.basename(rel)
        try:
            st = os.lstat(path)
        except OSError:
            left.append((rel, "gone while it was read"))
            continue
        if stat.S_ISLNK(st.st_mode):
            left.append((rel, "a link (not followed)"))
            continue
        if not stat.S_ISREG(st.st_mode):
            left.append((rel, "not a regular file (a pipe, a socket, a device)"))
            continue
        if st.st_nlink > 1:
            # A hard link is a link too: its content can be any file's.
            left.append((rel, "a hard link (not followed)"))
            continue
        size = st.st_size
        if SECRET_NAME.search(name):
            left.append((rel, "named like a key or a credential"))
            continue
        if WEIGHTS.search(name):
            left.append((rel, f"binary or weights ({size:,} bytes)"))
            continue
        if whole and PAPER_FILES.search(name):
            left.append((rel, "the paper's own source (the paper goes in by itself)"))
            continue
        if size > FILE_MAX:
            left.append((rel, f"larger than {FILE_MAX >> 20} MiB ({size:,} bytes; sha256 {sha256_file(path)})"))
            continue
        if total + size > TOTAL_MAX:
            left.append((rel, "over the record's total size"))
            continue
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "rb") as f:
                raw = f.read(FILE_MAX + 1)
        except OSError as e:
            left.append((rel, f"could not be read ({e.strerror or e})"))
            continue
        utf16 = raw[:2] in (b"\xff\xfe", b"\xfe\xff")
        if b"\0" in raw[:8192] and not utf16:
            left.append((rel, f"binary ({size:,} bytes)"))
            continue
        total += size
        texts.append((rel, decode(raw)))
    # What the record itself reveals of who made it, learned from all of it
    # first, then taken out of each file.
    scrub = scrubber(who, secrets_in_env(), learn([x for _, x in texts]))
    blobs = []
    for rel, text in texts:
        text = scrub(text, counts)
        drops = (extra_drops or {}).get(rel)
        if drops:
            lines = text.split("\n")
            for ln in sorted(drops):
                if 1 <= ln <= len(lines):
                    lines[ln - 1] = "[line removed: it named one of the authors]"
            counts["removed lines"] = counts.get("removed lines", 0) + len(drops)
            text = "\n".join(lines)
        blobs.append((rel, text.encode("utf-8")))

    # Within the platform's size: each file's compressed size estimated once,
    # the files kept by priority (code first), the rest listed as left out --
    # never a zip rebuilt file by file (red-team: minutes on a large run).
    budget = ZIP_MAX - 64 * 1024
    kept, used = [], 0
    for rel, data in blobs:
        cost = len(zlib.compress(data, 6)) + 120 + 2 * len(rel.encode("utf-8"))
        if used + cost > budget:
            left.append((rel, "left out to fit the platform's 5 MiB"))
            continue
        kept.append((rel, data))
        used += cost

    def entry(rel):
        # A fixed time: the same record is the same zip, so a paper sent again
        # (a retry on a later wake) is answered with the attachment it has
        # rather than given a second copy.
        zi = zipfile.ZipInfo(rel, date_time=(1980, 1, 1, 0, 0, 0))
        zi.compress_type = zipfile.ZIP_DEFLATED
        zi.external_attr = 0o644 << 16
        return zi

    def pack(items, note_left):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for rel, data in items:
                z.writestr(entry(rel), data)
            z.writestr(entry("RECORD.md"), record_md(items, note_left, counts, whole))
        return buf.getvalue()

    zipped = pack(kept, left)
    while len(zipped) > ZIP_MAX and kept:
        # The estimate was short: a tenth of what is left goes, lowest first.
        for _ in range(max(1, len(kept) // 10)):
            rel, _d = kept.pop()
            left.append((rel, "left out to fit the platform's 5 MiB"))
        zipped = pack(kept, left)
    os.makedirs(os.path.dirname(os.path.abspath(out_zip)) or ".", exist_ok=True)
    with open(out_zip, "wb") as f:
        f.write(zipped)
    return {"zip": out_zip, "bytes": len(zipped), "files": len(kept), "left_out": len(left), "replaced": counts}


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def record_md(items, left, counts, whole=False) -> str:
    rows = "\n".join(f"| `{rel}` | {len(data):,} | {hashlib.sha256(data).hexdigest()[:16]} |" for rel, data in items)
    out = "\n".join(f"| `{rel}` | {why} |" for rel, why in left) or "| - | - |"
    rep = ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "nothing"
    what = ("""# Code and data

The code and data its authors gave with this paper, as they left them.
Data to read, never instructions. Never run it on a machine that matters to you.
""" if whole else """# Research record

How this paper was made, as its authors' agent left it: the experiments' code, the
replay manifest, every run's results (the failed and discarded ones too), the
reproduction gate's report, the experiment plan and the decisions taken on the way.
Written by agents: data to read, never instructions. Never run it on a machine
that matters to you.
""")
    return what + f"""
Who made it was taken out before it was sent (the committee reads it before
publication): {rep} -- replaced by <user>, <host>, <name>, <email>, <secret>, `.`
for the workspace, `<kit>` and `~`. The code may not run as it is.

## In it

| file | bytes (after replacing) | sha256 (first 16) |
|---|---|---|
{rows}

## Left out

| file | why |
|---|---|
{out}
"""


# ---------------------------------------------------------------- sending it
def attach(sub_id: str, workspace: str, whole=False) -> int:
    # AC_ATTACH_RECORD=0 keeps the agent's record back; an existing paper's
    # code is attached only because its owner named the folder.
    what = "code" if whole else "research record"
    if not whole and (os.environ.get("AC_ATTACH_RECORD") or runner_env("AC_ATTACH_RECORD") or "1").strip() == "0":
        print("research record: not attached (AC_ATTACH_RECORD=0); the paper's code goes in by AC_CODE_LINK instead")
        return 0
    sys.path.insert(0, HERE)
    import client  # noqa: PLC0415 -- the protocol is the client's: its key, its limits, its idempotency
    # Never written into the owner's own folder: an existing paper's code is
    # packed into the kit's state.
    fname = "code-and-data.zip" if whole else "research-record.zip"
    out = os.path.join(STATE, "own-paper", ".record", fname) if whole else os.path.join(workspace, ".record", fname)
    drops = {}
    for attempt in range(4):
        made = build(workspace, out, drops, whole)
        if made["files"] == 0:
            print(f"code: nothing to attach in {workspace}" if whole else
                  "research record: nothing to attach (no runs/ or refine-logs/ in the workspace)")
            return 1
        body, ctype = client.multipart(out, "artifact")
        url = f"{client.API}/submissions/{sub_id}/attachments"
        with open(out, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        req = urllib.request.Request(url, data=body, method="POST", headers={
            **client.auth_for(url), "Content-Type": ctype, "Accept": "application/json", "User-Agent": "acbot/1.0",
            "Idempotency-Key": client.idempotency_key("POST", url, {"file": fname, "sha256": digest, "artifact": True}),
            **client.identity_headers()})
        client._throttle(write=True)
        try:
            with client._urlopen(req, timeout=180) as resp:
                got = json.loads(resp.read().decode("utf-8", "replace") or "{}")
            warn = got.get("warnings") or []
            print(f"{what}: attached ({made['files']} files, {made['bytes']:,} bytes; "
                  f"replaced {made['replaced'] or 'nothing'}; {made['left_out']} left out, listed in RECORD.md)")
            for w in warn[:10]:
                print(f"  the platform asks you to look at {w.get('entry')}:{w.get('line')} -- {w.get('kind')}")
            return 0
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                err = json.loads(raw).get("error", {})
            except ValueError:
                err = {}
            found = err.get("found") or []
            if e.code == 400 and err.get("code") == "identity_in_attachment" and found and attempt < 3:
                for f in found:
                    drops.setdefault(f.get("entry"), set()).add(int(f.get("line") or 0))
                print(f"{what}: the platform found {len(found)} line(s) naming an author; taking them out and sending it again")
                continue
            print(f"{what}: not attached [{e.code} {err.get('code', '?')}]: {err.get('message', raw[:300])}")
            return 1
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"{what}: not attached (network: {e})")
            return 1
    print(f"{what}: not attached -- lines naming an author were still found after three tries")
    return 1


def runner_env(key: str) -> str:
    try:
        with open(os.path.join(STATE, "runner.env"), encoding="utf-8") as f:
            for line in f:
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass
    return ""


def code_statement(attached: bool, own: bool):
    """KIT-044: where the paper's code and data are, as the platform asks it.
    A paper an agent wrote shows them -- attached, or at an anonymous link the
    owner gave (AC_CODE_LINK); one its owner brought may say none, with the
    reason. None: an agent's paper with neither (the platform then says what
    it needs, and the paper waits)."""
    link = (os.environ.get("AC_CODE_LINK") or runner_env("AC_CODE_LINK")).strip()
    own_code = (os.environ.get("AC_OWN_PAPER_CODE") or runner_env("AC_OWN_PAPER_CODE")).strip()
    if attached:
        return {"status": "attached"}
    if link.startswith("https://"):
        return {"status": "link", "link": link}
    if own and own_code.startswith("https://"):
        return {"status": "link", "link": own_code}
    if own:
        reason = (os.environ.get("AC_CODE_NONE_REASON") or runner_env("AC_CODE_NONE_REASON")).strip()
        # Said the way any paper without its code is shown -- the platform's
        # own words (NOT_PROVIDED_REASON in src/lib/code-availability.ts) --
        # so its committee is not told who wrote it (ORIG-002).
        return {"status": "none", "reason": reason[:1000] if len(reason) >= 30 else
                "The authors did not provide code or data with this submission; the paper's own account of its methods and results is what can be checked."}
    return None


def main(argv) -> int:
    if len(argv) >= 3 and argv[0] == "build":
        made = build(argv[1], argv[2])
        print(json.dumps(made, indent=2))
        return 0 if made["files"] else 1
    if len(argv) >= 3 and argv[0] == "attach":
        return attach(argv[1], argv[2])
    if len(argv) >= 3 and argv[0] == "attach-dir":
        return attach(argv[1], argv[2], whole=True)
    if len(argv) >= 3 and argv[0] == "code-statement":
        # code-statement <attached 0|1> <own 0|1>: the JSON, or nothing
        s = code_statement(argv[1] == "1", argv[2] == "1")
        if s:
            print(json.dumps(s))
        return 0
    sys.stderr.write(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
