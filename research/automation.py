"""Configure the optional research loop once, preserving existing owner choices."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'research/experience'))
from experience import read, save, config
from learning_transport import BACKENDS


def runner_backend(root):
    """Follow the kit's CLI choice without launching a model or switching CLIs."""
    settings = {}
    runner = Path(root) / 'state/runner.env'
    if runner.is_file():
        for line in runner.read_text(encoding='utf-8').splitlines():
            key, sep, value = line.partition('=')
            if sep and key in ('AC_BACKEND', 'AC_BACKEND_CMD'):
                settings[key] = value
    value = lambda key: os.environ.get(key, settings.get(key, ''))
    if value('AC_BACKEND_CMD'):
        return 'custom'
    if value('AC_BACKEND'):
        return value('AC_BACKEND')
    search_path = os.pathsep.join((str(Path(root) / 'state/bin'),
                                  os.environ.get('PATH', ''), str(Path.home() / '.local/bin')))
    for cli in ('claude', 'codex', 'gemini', 'opencode', 'cursor-agent', 'copilot',
                'qwen', 'amp', 'droid', 'goose', 'crush', 'kimi'):
        if shutil.which(cli, path=search_path):
            return cli
    return 'unavailable'


def initialize(root=ROOT, checkout=None, model=None, backend=None):
    root = Path(root).resolve()
    custom = root / 'custom'
    made = []
    choices = {
        'research-auto.json': {'enabled': True, 'topic_hints': 'aihot'},
        'science-extensions.json': {'schema_version': 1, 'timeout_seconds': 180, 'extensions': {
            k: 100 for k in ('botorch','torchrl','lm_eval','inspect_ai','sam2','braindecode','deepxde','openmm')}},
        'experience.json': {'enabled': True, 'learning': 'skill_training', 'auto_discover': True,
            'auto_draft': True, 'auto_report': True,
            'skill_training': {'adapter': 'protocol', 'checkout': str(checkout or root/'vendor/skill-training'), 'allow_download': True,
                              'backend': backend or 'follow', 'model': model or '', 'epochs': 1, 'timeout_seconds': 2400}},
    }
    overrides = {'science-extensions.json': 'AC_SCIENCE_CONFIG', 'experience.json': 'AC_EXPERIENCE_CONFIG'}
    for name, value in choices.items():
        # A separately selected config remains authoritative, even when absent.
        if os.environ.get(overrides.get(name, '')):
            continue
        path = custom / name
        custom.mkdir(parents=True, exist_ok=True)
        try:
            # Never replace a setting created by the owner or another initializer.
            with path.open('x', encoding='utf-8') as stream:
                stream.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        except FileExistsError:
            continue
        made.append(name)
    return {'created': made, 'existing_settings': 'preserved', 'sharing': 'private drafts and feedback; owner decides public release'}


def configure_learning(root, mode, backend=None, model=None):
    """An explicit owner command; ordinary initialization never edits settings."""
    path = Path(os.environ.get('AC_EXPERIENCE_CONFIG') or Path(root)/'custom/experience.json')
    if not path.exists():
        if os.environ.get('AC_EXPERIENCE_CONFIG'):
            raise ValueError('Selected experience config is missing; create it before changing learning')
        initialize(root)
    choices = config(path)
    choices['learning'] = mode
    if mode != 'off':
        choices['enabled'] = True
    training = choices.setdefault('skill_training', {})
    if mode == 'skill_training':
        training.setdefault('adapter', 'protocol')
        training.setdefault('checkout', str(Path(root)/'vendor/skill-training'))
        training.setdefault('allow_download', True)
        training.setdefault('epochs', 1)
        training.setdefault('timeout_seconds', 2400)
    if backend is not None:
        if backend not in ('follow', *BACKENDS):
            raise ValueError('Unknown learning backend')
        training['backend'] = backend
        # A backend switch must not carry a model identifier across providers.
        training['model'] = model or ''
        training.pop('cli', None)
        if backend != 'custom':
            training.pop('command', None)
    elif model is not None:
        training['model'] = model
    save(path, choices)
    return {'learning': mode, 'backend': training.get('backend', 'follow'),
            'model': training.get('model') or 'current Agent/CLI default',
            'public_sharing': 'owner approval required'}


# KIT-083: its owner's three switches -- the website's Research Add-ons, or
# `automation.py choose` here: AIHot topic leads, the field tools, and how it
# learns from experience. On by default; each is written into the file its
# steps read as they run, so a change reaches the next step of a paper under
# way. A paper already planned with a tool keeps that plan.
EXPERIENCE_CHOICES = ('skill_training', 'direct', 'off')
TOOL_DEFAULT = 100  # what setup gives every tool


def _env(get):
    return get or (lambda key: os.environ.get(key, ''))


def _config_path(root, name, get=None):
    """Where a file is read from: one an environment variable selects, else
    custom/. The second value says whether it was selected that way."""
    key = {'science-extensions.json': 'AC_SCIENCE_CONFIG', 'experience.json': 'AC_EXPERIENCE_CONFIG'}.get(name)
    chosen = (_env(get)(key) or '').strip() if key else ''
    return (Path(chosen) if chosen else Path(root) / 'custom' / name), bool(chosen)


def state(root=ROOT, get=None):
    """What the add-ons run with now, for its owner's page: topic leads and
    tools on or off, and how it learns -- skill_training, direct, off, or
    custom (shared skills kept on by hand, learning off). A file not made yet
    reads as setup will make it; one that cannot be read is None."""
    get = _env(get)
    root = Path(root)
    out = {}
    hints = (get('AC_TOPIC_HINTS') or '').strip()
    try:
        if hints:
            out['topic_leads'] = hints == 'aihot'
        else:
            p = root / 'custom/research-auto.json'
            c = read(p) if p.exists() else {'enabled': True, 'topic_hints': 'aihot'}
            out['topic_leads'] = isinstance(c, dict) and c.get('enabled') is True and c.get('topic_hints') == 'aihot'
    except (OSError, ValueError):
        out['topic_leads'] = None
    try:
        p, selected = _config_path(root, 'science-extensions.json', get)
        if not p.exists():
            out['tools'] = not selected
        else:
            c = read(p)
            levels = c.get('extensions') if isinstance(c, dict) else None
            out['tools'] = isinstance(levels, dict) and c.get('enabled', True) is not False and any(levels.values())
    except (OSError, ValueError):
        out['tools'] = None
    try:
        p, selected = _config_path(root, 'experience.json', get)
        if not p.exists():
            out['experience'] = 'off' if selected else 'skill_training'
        else:
            c = config(p)
            learning = c.get('learning', 'off')
            out['experience'] = 'off' if not c.get('enabled', False) else learning if learning != 'off' else 'custom'
    except (OSError, ValueError, KeyError):
        out['experience'] = None
    return out


def choose(root=ROOT, topic_leads=None, tools=None, experience=None, get=None):
    """Its owner's choice (KIT-083). Each switch given is written into its
    file; every other setting there stays as it is. Missing files are made
    first, as at setup. A file that cannot be read (an owner's edit half
    done) is left alone and its switch not applied. Returns those applied."""
    root = Path(root)
    get = _env(get)
    initialize(root)
    done = []
    if topic_leads is not None:
        try:
            p = root / 'custom/research-auto.json'
            c = read(p)
            if isinstance(c, dict):
                c['enabled'] = True
                c['topic_hints'] = 'aihot' if topic_leads else 'off'
                save(p, c)
                done.append('topic_leads')
        except (OSError, ValueError):
            pass
    if tools is not None:
        try:
            p, _ = _config_path(root, 'science-extensions.json', get)
            c = read(p) if p.exists() else None
            if isinstance(c, dict) and isinstance(c.get('extensions'), dict):
                c['enabled'] = bool(tools)
                # On again with every tool at 0 (set so by hand): setup's levels,
                # or "on" would change nothing.
                if tools and not any(c['extensions'].values()):
                    c['extensions'] = {k: TOOL_DEFAULT for k in c['extensions']}
                save(p, c)
                done.append('tools')
        except (OSError, ValueError):
            pass
    if experience is not None:
        if experience not in EXPERIENCE_CHOICES:
            raise ValueError('experience must be skill_training, direct or off')
        try:
            p, _ = _config_path(root, 'experience.json', get)
            if p.exists():
                if experience == 'off':
                    c = config(p)
                    c['enabled'] = False
                    save(p, c)
                else:
                    configure_learning(root, experience)
                done.append('experience')
        except (OSError, ValueError, KeyError):
            pass
    return done


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=ROOT)
    s = p.add_subparsers(dest='action', required=True)
    a=s.add_parser('init'); a.add_argument('--checkout'); a.add_argument('--model'); a.add_argument('--backend')
    a=s.add_parser('learning', help='Choose off, direct summary or Skill Training for this Agent')
    a.add_argument('--mode', required=True, choices=['off','direct','skill_training'])
    a.add_argument('--backend', choices=['follow', *BACKENDS]); a.add_argument('--model')
    s.add_parser('topic-mode')
    a=s.add_parser('choose', help="Its owner's switches (KIT-083): topic leads, field tools, learning")
    a.add_argument('--topic-leads', choices=['on','off']); a.add_argument('--tools', choices=['on','off'])
    a.add_argument('--experience', choices=EXPERIENCE_CHOICES)
    s.add_parser('state', help='What the switches are now')
    a=p.parse_args()
    if a.action == 'init':
        print(json.dumps(initialize(a.root,a.checkout,a.model,a.backend),ensure_ascii=False)); return
    if a.action == 'learning':
        print(json.dumps(configure_learning(a.root,a.mode,a.backend,a.model),ensure_ascii=False)); return
    if a.action == 'choose':
        flag = lambda v: None if v is None else v == 'on'
        print(json.dumps({'applied': choose(a.root, flag(a.topic_leads), flag(a.tools), a.experience),
                          'now': state(a.root)}, ensure_ascii=False)); return
    if a.action == 'state':
        print(json.dumps(state(a.root), ensure_ascii=False)); return
    path = a.root/'custom/research-auto.json'
    c = read(path) if path.exists() else {}
    print(c.get('topic_hints','off') if c.get('enabled') else 'off')

if __name__=='__main__': main()
