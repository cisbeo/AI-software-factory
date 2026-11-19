#!/usr/bin/env python3
"""PreToolUse hook: blocks destructive commands and secret files (spec §8).

Claude Code runs it before Bash and the file tools, with the call as JSON on
stdin (`tool_name`, `tool_input`, `cwd`, ...). Exit 2 blocks the call and
shows stderr to the model; exit 0 lets it through. Claude Code treats any
other exit code as a hook error and runs the call anyway, so every failure
here, including input it doesn't understand, ends in exit 2: fail closed.

Always blocked:
- history rewrite: rebase, commit --amend, reset to another commit, branch -f/-D,
  checkout -B, filter-branch, filter-repo, replace, update-ref, reflog expire;
- force push (-f, --force*, +refspec, --delete, :refspec, --mirror, --prune);
- push to the base branch (factory/config.json `base_branch`), or of every branch;
- from a job worktree (.worktrees/<job-id>, or a factory/* branch), push of
  anything but factory/<job-id>;
- recursive delete (rm -r, find -delete, find -exec rm) outside the git
  worktree it runs in, of the worktree itself or of its .git, or in a
  directory the hook can't tell;
- secret files (.env*, keys, certificates) named in a shell command or
  targeted by Read, Edit, Write, MultiEdit, NotebookEdit or Grep.

In a reviewer-<lens> subagent (the `agent_type` Claude Code adds to the
input; or with `--reviewer <lens>`), the agent is read-only: Write only to factory/jobs/<job>/round-<n>/review-<lens>.md, no
Edit, and Bash limited to commands that read; the ui and ux lenses may also
start the dev server and drive agent-browser. Hooks set in an agent's
frontmatter don't run in Claude Code 2.1.285, so this project-wide hook
reads `agent_type` instead; an unknown reviewer-* agent is blocked.

This is a barrier on what the agent asks for, not a sandbox: a script the
agent writes and runs can still do what it likes. The P2 sandbox covers that.
"""

import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

SECRET_PATTERNS = (".env*", "*.pem", "*.key", "*.p8", "*.p12", "*.pfx", "*.jks", "*.keystore",
                   "*.crt", "*.cer", "*.der", "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*")
PATH_KEYS = {"Read": "file_path", "Edit": "file_path", "Write": "file_path",
             "MultiEdit": "file_path", "NotebookEdit": "notebook_path"}
EDIT_TOOLS = {"Edit", "MultiEdit", "NotebookEdit"}
LENSES = {"code", "security", "spec", "standards", "ui", "ux"}
INTERFACE_LENSES = {"ui", "ux"}

SEPARATORS = {";", ";;", "&", "&&", "|", "||", "|&", "(", ")"}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
HEREDOC = re.compile(r"(?<!<)<<-?(?!<)\s*(['\"]?)([\w.-]+)\1")
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
WRAPPERS = {"command", "builtin", "exec", "nohup", "time", "caffeinate", "env", "nice", "timeout", "sudo"}
WRAPPER_VALUE_OPTS = {"-u", "-n", "-s", "-k", "-g", "-C", "-S"}

REWRITE_SUBCOMMANDS = {"filter-branch", "filter-repo", "replace", "update-ref"}
RESET_MODES = {"--hard", "--soft", "--mixed", "--keep", "--merge"}
FORCE_PUSH = {"--force", "--force-with-lease", "--force-if-includes", "--mirror", "--delete", "--prune"}
PUSH_VALUE_OPTS = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}

READ_PROGRAMS = {"cd", "pushd", "popd", "pwd", "ls", "cat", "head", "tail", "wc", "grep", "egrep", "fgrep",
                 "rg", "find", "diff", "cmp", "cut", "tr", "jq", "file", "stat", "echo", "printf", "test", "[",
                 "true", "false", "which", "type", "basename", "dirname", "realpath", "readlink", "nl",
                 "tree", "du", "sleep", "date", "uname", "git"}
READ_GIT = {"log", "diff", "show", "status", "rev-parse", "ls-files", "ls-tree", "blame", "grep",
            "merge-base", "cat-file", "shortlog", "describe", "rev-list", "name-rev", "branch", "help", "version"}
READ_BRANCH_ARGS = {"--show-current", "--list", "-l", "-a", "--all", "-r", "--remotes", "-v", "-vv"}
INTERFACE_PROGRAMS = {"agent-browser", "lsof", "kill", "curl", "npm", "pnpm", "yarn", "bun"}
DEV_SCRIPTS = {"dev", "start", "preview"}
CURL_WRITES = {"-o", "--output", "-O", "--remote-name", "-D", "--dump-header", "-c", "--cookie-jar",
               "-T", "--upload-file", "-K", "--config"}
FIND_ACTIONS = ("-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fls")


class Block(Exception):
    pass


def require(cond, message):
    if not cond:
        raise Block(message)


# ---- Secrets --------------------------------------------------------------------

def is_secret(text):
    parts = [p for p in re.split(r"[/\\]", text) if p]
    return any(fnmatch.fnmatchcase(p.lower(), pat) for p in parts for pat in SECRET_PATTERNS)


def secret_in_word(word):
    return any(is_secret(piece) for piece in re.split(r"[^\w./~${}@+%*-]", word) if piece)


# ---- Paths and git -----------------------------------------------------------------

def resolve(base, target):
    if base is None or any(c in target for c in "$`"):
        return None
    path = Path(os.path.expanduser(target))
    return path if path.is_absolute() else base / path


def git(cwd, *args):
    if cwd is None or not cwd.is_dir():
        return None
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=10)
    return res.stdout.strip() if res.returncode == 0 else None


def project_dir(payload_cwd):
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(env) if env else payload_cwd


def inside(path, root, allow_equal=False):
    path, root = os.path.realpath(path), os.path.realpath(root)
    return (allow_equal and path == root) or path.startswith(root + os.sep)


def check_deletion(targets, cwd, ctx, allow_root=False):
    require(cwd is not None, "recursive delete in a directory the hook can't tell (unknown cd); blocked")
    top = git(cwd, "rev-parse", "--show-toplevel")
    require(top, f"recursive delete outside a git worktree ({cwd}); blocked")
    project = ctx["project"]
    require(project is not None and inside(top, project, allow_equal=True),
            f"recursive delete in {top}, outside this project's worktrees; blocked")
    for target in targets:
        parts = Path(target).parts
        glob_at = next((i for i, p in enumerate(parts) if any(c in p for c in "*?[")), None)
        literal = str(Path(*parts[:glob_at])) if glob_at else target
        path = resolve(cwd, literal if glob_at != 0 else ".")
        require(path is not None, f"recursive delete of {target}: the hook can't tell which path that is; blocked")
        ok = inside(path, top, allow_equal=allow_root or glob_at is not None)
        dotgit = os.path.join(os.path.realpath(top), ".git")
        real = os.path.realpath(path)
        require(ok and real != dotgit and not real.startswith(dotgit + os.sep),
                f"recursive delete outside the worktree {top}: {target}")


# ---- Git rules -------------------------------------------------------------------------

def split_git(words, cwd):
    i, opts = 1, []
    while i < len(words) and words[i].startswith("-"):
        opt = words[i]
        if opt == "-C" and i + 1 < len(words):
            cwd = resolve(cwd, words[i + 1])
            i += 2
            continue
        if opt in ("-c", "--git-dir", "--work-tree", "--namespace") and i + 1 < len(words):
            opts.append(opt)
            i += 2
            continue
        opts.append(opt.split("=", 1)[0])
        i += 1
    sub = words[i] if i < len(words) else None
    return cwd, opts, sub, words[i + 1:]


def short_flags(args):
    return "".join(a[1:] for a in args if a.startswith("-") and not a.startswith("--"))


def check_history(sub, args):
    msg = f"git {sub} rewrites history; blocked (spec §8)"
    if sub == "rebase":
        require(args and all(a in ("--abort", "--quit", "--show-current-patch") for a in args), msg)
    require(sub not in REWRITE_SUBCOMMANDS, msg)
    if sub == "commit":
        require(not any(a.startswith("--amend") for a in args), "git commit --amend rewrites history; blocked")
    if sub == "reset":
        require(not RESET_MODES & set(args), msg)
        before = args[:args.index("--")] if "--" in args else args
        positional = [a for a in before if not a.startswith("-")]
        require(not positional or positional[0] in ("HEAD", "@"),
                f"git reset {positional[0] if positional else ''} moves the branch and rewrites history; blocked")
    if sub == "reflog":
        require(args[:1] not in (["expire"], ["delete"]), msg)
    if sub == "branch":
        require(not ({"--force"} & set(args)) and not set("fD") & set(short_flags(args)),
                "git branch -f/-D rewrites or drops history; blocked")
    if sub in ("checkout", "switch"):
        require(not {"-B", "-C", "--force-create"} & set(args), f"git {sub} -B/-C resets a branch and rewrites history; blocked")


def check_push(cwd, opts, args, ctx):
    require(cwd is not None and cwd.is_dir(), "git push from a directory the hook can't tell; blocked")
    require(not {"--git-dir", "--work-tree"} & set(opts), "git push with --git-dir/--work-tree: the hook can't tell the branch; blocked")
    positional, tags, i = [], False, 0
    while i < len(args):
        a = args[i]
        if a == "--":
            positional += args[i + 1:]
            break
        if a in PUSH_VALUE_OPTS:
            i += 2
            continue
        name = a.split("=", 1)[0]
        if a.startswith("--"):
            require(name not in FORCE_PUSH, f"git push {name} is a force push; blocked (spec §8)")
            require(name not in ("--all", "--branches"), f"git push {name} pushes every branch, the base one too; blocked")
            tags = tags or name == "--tags"
        elif a.startswith("-") and len(a) > 1:
            require(not set("fd") & set(a[1:]), f"git push {a} is a force push; blocked (spec §8)")
        else:
            positional.append(a)
        i += 1

    top = git(cwd, "rev-parse", "--show-toplevel")
    require(top, f"git push outside a git repository ({cwd}); blocked")
    current = git(cwd, "symbolic-ref", "--short", "-q", "HEAD")
    base = ctx["base"]()

    dsts = []
    for spec in positional[1:]:
        require(not spec.startswith("+"), f"git push {spec} is a force push; blocked (spec §8)")
        require(not spec.startswith(":"), f"git push {spec} deletes a remote branch; blocked")
        require("*" not in spec, f"git push {spec}: wildcard refspecs are blocked")
        src, _, dst = spec.partition(":")
        dst = dst or src
        if dst in ("HEAD", "@"):
            require(current, "git push HEAD on a detached HEAD: the hook can't tell the branch; blocked")
            dst = current
        dsts.append(dst[len("refs/heads/"):] if dst.startswith("refs/heads/") else dst)
    if not positional[1:] and not tags:
        upstream = git(cwd, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{push}")
        if upstream and "/" in upstream:
            dsts.append(upstream.split("/", 1)[1])
        else:
            require(current, "git push on a detached HEAD: the hook can't tell the branch; blocked")
            dsts.append(current)
    if tags:
        dsts.append("--tags")

    require(base not in dsts, f"git push to the base branch {base}; blocked: merges go through the forge (spec §8)")
    job = f"factory/{Path(top).name}" if Path(top).parent.name == ".worktrees" else (
        current if current and current.startswith("factory/") else None)
    if job:
        other = [d for d in dsts if d != job]
        require(not other, f"from this job worktree only {job} may be pushed, not {', '.join(other)}; blocked")


# ---- Reviewers: read-only -------------------------------------------------------------

def check_reviewer_command(words, redirects, lens):
    no = f"read-only reviewer ({lens}) may not run: {' '.join(words)}"
    for op, target in redirects:
        if ">" in op:
            require(target == "/dev/null" or (op.endswith("&") and (target.isdigit() or target == "-")),
                    f"read-only reviewer ({lens}) may not write to {target}")
    if not words:
        return
    prog, args = os.path.basename(words[0]), words[1:]
    interface = lens in INTERFACE_LENSES
    require(prog in READ_PROGRAMS or (interface and prog in INTERFACE_PROGRAMS), no)
    if prog == "git":
        _, opts, sub, rest = split_git(words, Path("."))
        require(not {"-c", "--git-dir", "--work-tree", "--exec-path"} & set(opts), no)
        require(sub in READ_GIT, no)
        require(not any(a.startswith(("--output", "--open-files-in-pager")) or a == "-O" for a in rest), no)
        if sub == "branch":
            require(all(a in READ_BRANCH_ARGS for a in rest), no)
    elif prog == "find":
        require(not any(a.startswith(FIND_ACTIONS) for a in args), no)
    elif prog == "rg":
        require(not any(a.startswith("--pre") for a in args), no)
    elif prog == "curl":
        require(not any(a.split("=", 1)[0] in CURL_WRITES for a in args), no)
    elif prog in ("npm", "pnpm", "yarn", "bun"):
        script = args[1:2] if args[:1] in (["run"], ["run-script"]) else args[:1]
        require(script and script[0] in DEV_SCRIPTS, no)


def check_reviewer_write(path_text, lens, ctx):
    require(".." not in Path(path_text).parts, f"read-only reviewer ({lens}) may write only its review file")
    project = ctx["project"]
    require(project is not None, f"read-only reviewer ({lens}): unknown project directory; blocked")
    try:
        rel = Path(os.path.realpath(path_text)).relative_to(os.path.realpath(project))
    except ValueError:
        raise Block(f"read-only reviewer ({lens}) may write only its review file, not {path_text}")
    p = rel.parts
    require(len(p) == 5 and p[:2] == ("factory", "jobs") and re.fullmatch(r"round-\d+", p[3])
            and p[4] == f"review-{lens}.md",
            f"read-only reviewer ({lens}) may write only factory/jobs/<job>/round-<n>/review-{lens}.md, not {path_text}")


# ---- Shell parsing -------------------------------------------------------------------

def strip_heredocs(command):
    out, pending = [], []
    for line in command.split("\n"):
        if pending:
            if line.strip() == pending[0]:
                pending.pop(0)
            continue
        out.append(line)
        pending += [m.group(2) for m in HEREDOC.finditer(line)]
    return "\n".join(out)


def tokenize(command):
    lex = shlex.shlex(command.replace("\n", " ; "), posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = ""
    try:
        return list(lex)
    except ValueError as e:
        raise Block(f"couldn't understand the command ({e}); blocked")


def segments(tokens):
    words, redirects, i = [], [], 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in SEPARATORS:
            yield words, redirects
            words, redirects = [], []
        elif tok and set(tok) <= set("<>&|"):
            redirects.append((tok, tokens[i + 1] if i + 1 < len(tokens) else ""))
            i += 1
        else:
            words.append(tok)
        i += 1
    yield words, redirects


def unwrap(words):
    i, sudo = 0, False
    while i < len(words):
        name = os.path.basename(words[i])
        if ASSIGNMENT.match(words[i]):
            i += 1
        elif name in WRAPPERS:
            sudo = sudo or name == "sudo"
            i += 1
            while i < len(words) and (words[i].startswith("-") or ASSIGNMENT.match(words[i])):
                i += 2 if words[i] in WRAPPER_VALUE_OPTS else 1
            if name == "timeout" and i < len(words):
                i += 1  # the duration
        else:
            break
    return words[i:], sudo


def message_args(prog, sub, args):
    """Indexes of commit/tag messages: quoted data, not paths."""
    if prog != "git" or sub not in ("commit", "tag"):
        return set()
    return {i + 1 for i, a in enumerate(args) if a in ("-m", "--message")}


def check_command(command, cwd, ctx, depth=0):
    require(depth < 5, "command nested too deep to check; blocked")
    command = strip_heredocs(command)
    for inner in re.findall(r"`([^`]*)`", command):
        check_command(inner, cwd, ctx, depth + 1)
    for words, redirects in segments(tokenize(command)):
        for w in words:
            if "$(" in w:
                check_command(w.split("$(", 1)[1].rstrip(")"), cwd, ctx, depth + 1)
        words, sudo = unwrap(words)
        if not words:
            for _, target in redirects:
                require(not secret_in_word(target), f"secret file in the command: {target}; blocked (spec §8)")
            if ctx["lens"]:
                check_reviewer_command(words, redirects, ctx["lens"])
            continue
        prog, args = os.path.basename(words[0]), words[1:]
        git_cwd, opts, sub, sub_args = split_git(words, cwd) if prog == "git" else (cwd, [], None, [])

        skip = message_args(prog, sub, sub_args)
        for i, w in enumerate(sub_args if prog == "git" else args):
            if i not in skip:
                require(not secret_in_word(w), f"secret file in the command: {w}; blocked (spec §8)")
        for _, target in redirects:
            require(not secret_in_word(target), f"secret file in the command: {target}; blocked (spec §8)")

        if prog in ("cd", "pushd"):
            dest = [a for a in args if not a.startswith("-")]
            cwd = resolve(cwd, dest[0]) if dest else Path.home()
        elif prog in SHELLS:
            flags = [a for a in args if a.startswith("-") and "c" in a[1:] and not a.startswith("--")]
            if flags:
                idx = args.index(flags[0]) + 1
                require(idx < len(args), f"{prog} -c without a command; blocked")
                check_command(args[idx], cwd, ctx, depth + 1)
        elif prog == "eval":
            check_command(" ".join(args), cwd, ctx, depth + 1)
        elif prog == "xargs":
            start = 0
            while start < len(args) and args[start].startswith("-"):
                start += 2 if args[start] in ("-I", "-n", "-P", "-L", "-d", "-E", "-s", "-J", "-R") else 1
            inner = args[start:]
            require(not (inner and os.path.basename(inner[0]) == "rm" and is_recursive_rm(inner[1:])),
                    "recursive delete of paths read from stdin (xargs rm -r); blocked")
        elif prog == "git":
            check_history(sub, sub_args)
            if sub == "push":
                check_push(git_cwd, opts, sub_args, ctx)
        elif prog == "rm" and is_recursive_rm(args):
            require(not sudo, "recursive delete with sudo; blocked")
            check_deletion(rm_targets(args), cwd, ctx)
        elif prog == "find" and ("-delete" in args or any(
                a in ("-exec", "-execdir") and i + 1 < len(args) and os.path.basename(args[i + 1]) == "rm"
                for i, a in enumerate(args))):
            roots = []
            for a in args:
                if a.startswith("-") or a in ("!", "\\("):
                    if a in ("-H", "-L", "-P"):
                        continue
                    break
                roots.append(a)
            check_deletion(roots or ["."], cwd, ctx, allow_root=True)

        if ctx["lens"]:
            require(not sudo, f"read-only reviewer ({ctx['lens']}) may not use sudo")
            check_reviewer_command(words, redirects, ctx["lens"])


def is_recursive_rm(args):
    for a in args:
        if a == "--":
            return False
        if a == "--recursive" or (a.startswith("-") and not a.startswith("--") and set("rR") & set(a[1:])):
            return True
    return False


def rm_targets(args):
    out, opts_done = [], False
    for a in args:
        if not opts_done and a == "--":
            opts_done = True
        elif opts_done or not a.startswith("-") or a == "-":
            out.append(a)
    return out


# ---- Entry point --------------------------------------------------------------------------

def check(payload, lens):
    require(isinstance(payload, dict), "hook input isn't a JSON object; blocked")
    tool, tool_input = payload.get("tool_name"), payload.get("tool_input")
    require(isinstance(tool, str) and tool, "hook input has no tool_name; blocked")
    require(isinstance(tool_input, dict), f"hook input for {tool} has no tool_input object; blocked")
    cwd = Path(payload["cwd"]) if isinstance(payload.get("cwd"), str) and payload["cwd"] else None
    project = project_dir(cwd)
    agent = payload.get("agent_type")
    require(agent is None or isinstance(agent, str), "hook input agent_type isn't a string; blocked")
    if lens is None and agent and agent.startswith("reviewer-"):
        lens = agent[len("reviewer-"):]
        require(lens in LENSES, f"{agent} has no read-only rules in guard.py; blocked")

    def base():
        try:
            value = json.loads((project / "factory" / "config.json").read_text())["base_branch"]
        except (OSError, TypeError, ValueError, KeyError) as e:
            raise Block(f"can't read base_branch from factory/config.json ({e}); push blocked")
        require(isinstance(value, str) and value, "factory/config.json base_branch is empty; push blocked")
        return value

    ctx = {"project": project, "base": base, "lens": lens}

    if tool == "Bash":
        command = tool_input.get("command")
        require(isinstance(command, str), "Bash call without a command string; blocked")
        check_command(command, cwd, ctx)
    elif tool in PATH_KEYS:
        path = tool_input.get(PATH_KEYS[tool])
        require(isinstance(path, str) and path, f"{tool} call without {PATH_KEYS[tool]}; blocked")
        require(not is_secret(path), f"{tool} on a secret file: {path}; blocked (spec §8)")
        if lens:
            require(tool not in EDIT_TOOLS, f"read-only reviewer ({lens}) may not use {tool}")
            if tool == "Write":
                check_reviewer_write(path, lens, ctx)
    elif tool in ("Grep", "Glob"):
        keys = ("path", "glob") if tool == "Grep" else ("path",)
        for key in keys:
            value = tool_input.get(key)
            require(value is None or isinstance(value, str), f"{tool} {key} isn't a string; blocked")
            require(not (value and is_secret(value)), f"{tool} on a secret file: {value}; blocked (spec §8)")


def parse_args(argv):
    if not argv:
        return None
    require(len(argv) == 2 and argv[0] == "--reviewer" and argv[1] in LENSES,
            f"usage: guard.py [--reviewer {'|'.join(sorted(LENSES))}], got {' '.join(argv)}; blocked")
    return argv[1]


def main(argv):
    try:
        lens = parse_args(argv)
        check(json.loads(sys.stdin.read()), lens)
    except Block as e:
        print(f"guard: {e}", file=sys.stderr)
        return 2
    except BaseException as e:  # fail closed: exit codes other than 2 let the call through
        print(f"guard: blocked, the hook couldn't understand this call ({type(e).__name__}: {e})", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
