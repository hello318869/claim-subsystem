"""Collect auditable delivery metrics after the coordinator freezes the source.

This script does not execute tests, start a server, seed a database, read .env,
or read AI session logs. Its only pytest invocation uses --collect-only.
Primary LOC is physical source-file lines, including blank lines/comments.
Documents, configuration files, JSON data, caches and baseline copies are not LOC.
Run --help while preparing; use --final only after the source is ready.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
EXTENSIONS = {".py", ".js", ".cjs", ".mjs", ".html", ".css", ".ps1", ".sh"}
IGNORED_DIRECTORIES = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "tmp", "baseline", "dist", "build",
}
DEEPSEEK_SCRIPTS = {"init_db.py", "seed_demo.py", "evaluate_matching.py", "benchmark.py"}
CODEX_SCRIPTS = {"local_mysql.ps1", "collect_metrics.py"}
COLLECTOR = r'''
import json, pathlib, sys
sys.dont_write_bytecode = True
import pytest
target = pathlib.Path(sys.argv[1])
class Recorder:
    def pytest_collection_finish(self, session):
        target.write_text(json.dumps({
            "nodeids": [item.nodeid.replace("\\", "/") for item in session.items],
            "rootpath": str(session.config.rootpath),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
result = pytest.main(["tests", "--collect-only", "-q", "-p", "no:cacheprovider"],
                     plugins=[Recorder()])
sys.exit(int(result))
'''


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def safe_source_files(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    files = []
    for current, directories, filenames in os.walk(folder, followlinks=False):
        directories[:] = sorted(d for d in directories if d not in IGNORED_DIRECTORIES)
        for filename in sorted(filenames):
            path = Path(current) / filename
            if path.suffix.lower() not in EXTENSIONS:
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(WORKSPACE.resolve()):
                raise RuntimeError(f"Refusing source symlink or out-of-workspace file: {path}")
            files.append(path)
    return sorted(files)


def primary_ai(category: str, path: Path, overrides: dict[str, str]) -> str:
    key = path.relative_to(WORKSPACE).as_posix()
    if key in overrides:
        return overrides[key]
    if category == "delivery_tools":
        return "Codex"
    if category in {"product_backend", "product_frontend", "test_code"}:
        return "DeepSeek"
    if path.name in CODEX_SCRIPTS or path.name.startswith("ui_"):
        return "Codex"
    if path.name in DEEPSEEK_SCRIPTS:
        return "DeepSeek"
    return "Unverified"


def source_metrics(include_root_tools: bool, overrides: dict[str, str]) -> list[dict]:
    scopes = [
        ("product_backend", ROOT / "app"),
        ("product_frontend", ROOT / "web"),
        ("test_code", ROOT / "tests"),
        ("auxiliary_scripts", ROOT / "scripts"),
    ]
    if include_root_tools:
        scopes.append(("delivery_tools", WORKSPACE / "tools"))
    records = []
    for category, folder in scopes:
        for path in safe_source_files(folder):
            lines = path.read_text(encoding="utf-8-sig").splitlines()
            records.append({
                "path": path.relative_to(WORKSPACE).as_posix(),
                "category": category,
                "physical_loc": len(lines),
                "nonempty_loc": sum(bool(line.strip()) for line in lines),
                "primary_ai": primary_ai(category, path, overrides),
                "sha256": sha256(path),
            })
    return records


def collect_pytest(python: str) -> dict:
    environment = os.environ.copy()
    environment.pop("PYTEST_ADDOPTS", None)
    environment.pop("PYTEST_PLUGINS", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    with tempfile.TemporaryDirectory(prefix="claim-metrics-") as temporary:
        output = Path(temporary) / "collected.json"
        command = [python, "-c", COLLECTOR, str(output)]
        completed = subprocess.run(command, cwd=ROOT, env=environment,
                                   capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=180)
        if completed.returncode != 0 or not output.is_file():
            raise RuntimeError(
                f"pytest --collect-only failed (exit {completed.returncode}). "
                "No metrics were finalized. Run collection directly to diagnose; "
                "this collector does not print possibly sensitive import output."
            )
        result = json.loads(output.read_text(encoding="utf-8"))
    nodeids = result["nodeids"]
    if len(nodeids) != len(set(nodeids)):
        raise RuntimeError("pytest returned duplicate node IDs; refusing an ambiguous case count.")
    groups = {name: sum(node.startswith(f"tests/{name}/") for node in nodeids)
              for name in ("unit", "integration", "performance")}
    groups["other"] = len(nodeids) - sum(groups.values())
    return {"method": "pytest tests --collect-only -q -p no:cacheprovider",
            "python": python, "plugin_autoload": False, "exit_code": 0,
            "collected_cases": len(nodeids), "by_directory": groups,
            "nodeids": nodeids,
            "meaning": "Actual collected nodes include parametrizations and skip-marked nodes; collection is not execution or passing evidence."}


def selector_matches(selector: str, nodeid: str) -> bool:
    selector = selector.rstrip("/")
    return (nodeid == selector or nodeid.startswith(selector + "::")
            or nodeid.startswith(selector + "[") or nodeid.startswith(selector + "/"))


def traceability(rtm_paths: list[Path], nodeids: list[str]) -> dict:
    reports = []
    union = set()
    for rtm in rtm_paths:
        rows = list(csv.DictReader(rtm.open(encoding="utf-8-sig", newline="")))
        if rows and not {"需求ID", "测试用例"}.issubset(rows[0]):
            raise RuntimeError(f"Unknown RTM column names: {rtm.name}")
        quality_nodes = set()
        requirements = []
        warnings = []
        for row in rows:
            requirement = row["需求ID"].strip()
            selectors, checks, unresolved = [], [], []
            matched_nodes = set()
            for fragment in re.split(r"[;；]", row.get("测试用例", "")):
                fragment = fragment.strip().strip("`")
                if not fragment:
                    continue
                if fragment.startswith("tests/"):
                    selector = re.split(r"[（(]", fragment, maxsplit=1)[0].strip()
                    matches = sorted(n for n in nodeids if selector_matches(selector, n))
                    selectors.append({"selector": selector, "expanded_case_count": len(matches)})
                    if not matches:
                        unresolved.append(fragment)
                    matched_nodes.update(matches)
                elif re.match(r"(?:python(?:3)?\s+)?scripts/", fragment):
                    checks.append(fragment)
                else:
                    unresolved.append(fragment)
            quality = requirement.startswith("QR-")
            if quality:
                quality_nodes.update(matched_nodes)
            for unresolved_value in unresolved:
                warnings.append({"requirement": requirement,
                                 "unresolved_test_reference": unresolved_value,
                                 "status": row.get("变更状态", "")})
            requirements.append({"requirement_id": requirement, "is_quality": quality,
                                 "status": row.get("变更状态", ""),
                                 "selectors": selectors, "nodeids": sorted(matched_nodes),
                                 "auxiliary_validation_commands_not_counted_as_pytest": checks})
        union.update(quality_nodes)
        reports.append({"path": relative(rtm), "sha256": sha256(rtm),
                        "quality_case_count_deduplicated": len(quality_nodes),
                        "quality_nodeids": sorted(quality_nodes),
                        "requirements": requirements, "unresolved_references": warnings})
    return {"rtms": reports, "quality_case_count_deduplicated_across_rtms": len(union),
            "quality_nodeids": sorted(union),
            "method": "Expand concrete pytest selectors and file/directory suite references against collected nodes, then deduplicate exact parametrized node IDs. Scripts, benchmark requests and manual UI checks are separate evidence, not pytest cases."}


def git_information(git: str, milestone_specs: list[str]) -> dict:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"

    def read(*arguments: str, required: bool = True) -> str:
        result = subprocess.run([git, "-C", str(ROOT), *arguments], env=environment,
                                capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=30)
        if result.returncode and required:
            raise RuntimeError(f"Read-only git command failed: {' '.join(arguments[:2])}")
        return result.stdout.strip() if not result.returncode else ""

    top = Path(read("rev-parse", "--show-toplevel")).resolve()
    if top != ROOT.resolve():
        raise RuntimeError("Git repository does not belong exactly to claim-subsystem.")
    tags = read("tag", "--list").splitlines()
    milestones = []
    labels, commits = set(), set()
    for specification in milestone_specs:
        if "=" not in specification:
            raise RuntimeError("Every milestone must use LABEL=GIT_REF.")
        label, reference = specification.split("=", 1)
        if not label or not reference or label in labels:
            raise RuntimeError("Milestone labels and references must be nonempty; labels must be unique.")
        commit = read("rev-parse", "--verify", reference + "^{commit}")
        if commit in commits:
            raise RuntimeError("Two milestone labels resolve to one commit; refusing to inflate iteration count.")
        labels.add(label)
        commits.add(commit)
        milestones.append({"label": label, "supplied_ref": reference, "commit": commit})
    return {"repository": str(top), "head": read("rev-parse", "HEAD"),
            "branch": read("branch", "--show-current"),
            "reachable_commit_count": int(read("rev-list", "--count", "HEAD")),
            "tag_count": len(tags), "tags": tags,
            "describe": read("describe", "--always", "--dirty", "--tags"),
            "explicit_git_verified_milestone_count": len(milestones), "milestones": milestones,
            "status_porcelain": read("status", "--porcelain=v1", "--untracked-files=normal"),
            "commit_log": read("log", "--format=%H%x09%ad%x09%s", "--date=iso-strict").splitlines(),
            "version_note": "Git tags are counted literally. A supplied document release label is not an automatically verified Git tag or an inferred iteration count."}


def attachment_manifest(records: list[dict]) -> list[str]:
    files = {record["path"] for record in records}
    for name in ("README.md", "requirements.txt", "pyproject.toml", "pytest.ini", ".gitignore", ".env.example"):
        path = ROOT / name
        if path.is_file():
            files.add(path.relative_to(WORKSPACE).as_posix())
    # Fixed, synthetic input data is reproducibility material, but never LOC.
    for path in (ROOT / "tests" / "fixtures").rglob("*.json"):
        if path.name == "seed-world.json":
            continue  # Generated local run manifest; rebuild via seed_test_world.py.
        if any(part in IGNORED_DIRECTORIES for part in path.relative_to(ROOT).parts):
            continue
        files.add(path.relative_to(WORKSPACE).as_posix())
    return sorted(files)


def markdown_report(result: dict) -> str:
    lines = ["# 交付统计", "", f"快照时间：{result['generated_at_utc']}。提交标签：{result['release_label']}。",
             "", "## 统计口径", "",
             "代码行数为实际源文件物理行数，包含空行、纯注释行、docstring 和内嵌脚本文本；另报非空行数。",
             "MD/DOCX/PDF 等文档、JSON 合成或运行数据、配置文件、baseline 副本、tmp、缓存、凭据与 Git 元数据均不计代码行。",
             "产品代码包括 Python 后端及 HTML/CSS/JavaScript 前端；测试代码包括用例、conftest、夹具和负载工具；辅助脚本单列。根目录交付工具另列，不混入项目总代码。",
             "", "| 分类 | 文件数 | 物理行数 | 非空行数 |", "| --- | ---: | ---: | ---: |"]
    for category, values in result["source_summary"].items():
        lines.append(f"| {category} | {values['files']} | {values['physical_loc']} | {values['nonempty_loc']} |")
    lines += ["", f"项目总代码物理行数：{result['project_total_physical_loc']}。",
              f"包含根目录交付工具的全部源文件物理行数：{result['all_source_physical_loc']}。",
              "", "## AI 辅助来源", "",
              "业务与测试代码主要由 DeepSeek 生成，Codex 负责代理交互、审查及环境和 UI 验证工具。文件来源归类不等于逐行生成比例，也不代表学生手写贡献。",
              "学生独立手写行数没有可核验的逐行归属记录，本统计不申报该数值。", "",
              "| 主要 AI 来源 | 物理行数 |", "| --- | ---: |"]
    for owner, count in result["ai_assisted_source_lines"].items():
        lines.append(f"| {owner} | {count} |")
    tests = result["pytest_collection"]
    lines += ["", "## 测试与追溯", "",
              f"pytest --collect-only 实际收集 {tests['collected_cases']} 个参数化展开节点；本命令不执行业务测试，不声称这些节点全部通过。",
              f"目录分项：{json.dumps(tests['by_directory'], ensure_ascii=False)}。",
              f"RTM 中 QR 质量需求映射的实际 pytest 节点跨矩阵去重后为 {result['traceability']['quality_case_count_deduplicated_across_rtms']} 个。",
              "文件或目录级套件引用按实际收集节点展开。benchmark/evaluate 脚本、HTTP 请求数和手工 UI 检查不计入 pytest 用例数。"]
    for rtm in result["traceability"]["rtms"]:
        lines += ["", f"- {rtm['path']}：质量需求用例去重 {rtm['quality_case_count_deduplicated']} 个；未解析测试引用 {len(rtm['unresolved_references'])} 项。"]
    git = result["git"]
    lines += ["", "## Git 与版本", "",
              f"HEAD：`{git['head']}`；可达提交数：{git['reachable_commit_count']}；实际 Git 标签数：{git['tag_count']}。",
              f"Git describe：`{git['describe']}`。",
              "文档提交标签与 Git 标签分别记录；不根据文件名或提交信息猜测迭代版本数。",
              f"显式提供并经 Git 验证的不同版本里程碑：{git['explicit_git_verified_milestone_count']} 个。未提供版本映射时不推断迭代数。",
              f"生成本统计文件之前，源快照存在未提交变更：{'是' if git['status_porcelain'] else '否'}。", "",
              "## 代码附件", "",
              "同目录 submission-code-manifest.txt 仅列代码附件允许项，未创建压缩包。清单排除 .env、.env.test、.git、tmp、运行日志、真实凭据、生成的 seed-world.json，以及新旧 AI 会话。",
              "JSON 固定合成数据允许作为复现输入附件，但不计代码行。正式报告、经核验的截图及真实 AI 协作证据由提交总包另外显式选入，不按目录递归打包。",
              "", "本统计的文件 SHA-256、全部 pytest node ID、逐条 RTM 展开、来源与 Git 日志均见同目录 JSON。", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--final", action="store_true", help="Only use after the coordinator freezes all source and RTMs.")
    parser.add_argument("--release-label", required=True, help="Document release label; not counted as a Git tag.")
    parser.add_argument("--rtm", action="append", default=[], help="Project-relative RTM CSV; repeat for baseline/final matrices.")
    parser.add_argument("--python", default=sys.executable, help="Project Python with pytest and application dependencies installed.")
    parser.add_argument("--git", default=shutil.which("git"), help="Git executable; read-only commands only.")
    parser.add_argument("--milestone", action="append", default=[], help="Explicit implemented version LABEL=GIT_REF; repeated distinct refs are verified read-only, never inferred from filenames.")
    parser.add_argument("--include-root-tools", action="store_true", help="Also report workspace/tools separately from project LOC.")
    parser.add_argument("--provenance-overrides", type=Path, help="Optional JSON object: workspace-relative source path -> primary AI label.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "evidence" / "statistics")
    args = parser.parse_args()
    if not args.final:
        parser.error("No statistics collected: wait for final readiness, then explicitly pass --final.")
    if not args.git:
        parser.error("Git executable not found; supply --git.")
    overrides = {}
    if args.provenance_overrides:
        overrides = json.loads(args.provenance_overrides.read_text(encoding="utf-8-sig"))
        if not isinstance(overrides, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in overrides.items()):
            parser.error("Provenance overrides must be a JSON object of path -> label.")
    rtms = [ROOT / path for path in (args.rtm or ["docs/rtm-v1.0.csv", "docs/rtm-v1.1.csv"])]
    if any(not path.is_file() or not path.resolve().is_relative_to(ROOT.resolve()) for path in rtms):
        parser.error("Every RTM must exist inside the project.")
    rtm_hashes = {str(path): sha256(path) for path in rtms}
    records = source_metrics(args.include_root_tools, overrides)
    collection = collect_pytest(args.python)
    tracing = traceability(rtms, collection["nodeids"])
    git = git_information(args.git, args.milestone)
    if records != source_metrics(args.include_root_tools, overrides) or rtm_hashes != {str(path): sha256(path) for path in rtms}:
        raise RuntimeError("Source or RTM changed during collection. No statistics finalized; retry after freeze.")
    summary, ai = {}, {}
    for record in records:
        group = summary.setdefault(record["category"], {"files": 0, "physical_loc": 0, "nonempty_loc": 0})
        group["files"] += 1
        group["physical_loc"] += record["physical_loc"]
        group["nonempty_loc"] += record["nonempty_loc"]
        ai[record["primary_ai"]] = ai.get(record["primary_ai"], 0) + record["physical_loc"]
    result = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "release_label": args.release_label,
              "loc_policy": "Physical source-file lines including blank lines, comments, docstrings and embedded scripts; nonempty lines reported separately. Documents, JSON, configuration, credentials, caches, tmp and baseline copies excluded.",
              "source_summary": summary, "source_files": records,
              "project_total_physical_loc": sum(r["physical_loc"] for r in records if r["category"] != "delivery_tools"),
              "all_source_physical_loc": sum(r["physical_loc"] for r in records),
              "ai_assisted_source_lines": ai, "student_independently_written_lines": None,
              "ai_provenance_note": "File-scope primary-generator attribution supplied by the coordinator; not a line-by-line authorship proof or student contribution claim.",
              "pytest_collection": collection, "traceability": tracing, "git": git,
              "code_attachment_files": attachment_manifest(records)}
    output = args.output_dir.resolve()
    if not output.is_relative_to(ROOT.resolve()):
        parser.error("Metrics output must stay inside the project.")
    output.mkdir(parents=True, exist_ok=True)
    (output / "delivery-metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "delivery-metrics.md").write_text(markdown_report(result), encoding="utf-8")
    (output / "submission-code-manifest.txt").write_text("\n".join(result["code_attachment_files"]) + "\n", encoding="utf-8")
    print(f"Metrics finalized in {output}; no tests executed and no database connected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
