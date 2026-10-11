from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.db import audit

EXCLUDE_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules", "runtime", "data_cache"}
DEPENDENCY_NAMES = {
    "requirements.txt", "requirements-dev.txt", "pyproject.toml", "package.json",
    "package-lock.json", "poetry.lock", "Pipfile", "Pipfile.lock", "environment.yml",
}
COMPONENT_RULES = [
    ("model", lambda p: any(x in p.as_posix().lower() for x in ("app/ml/", "/model", "models/", "/predict", "/feature"))),
    ("data", lambda p: any(x in p.as_posix().lower() for x in ("app/data/", "data/", "/provider", "/dataset"))),
    ("services", lambda p: any(x in p.as_posix().lower() for x in ("app/services/", "/service", "/api/"))),
    ("frontend", lambda p: any(x in p.as_posix().lower() for x in ("frontend/", "/web/", "/ui/", "/static/"))),
    ("dependencies", lambda p: p.name.lower() in {x.lower() for x in DEPENDENCY_NAMES}),
    ("config", lambda p: p.name.lower() in {"config.py", ".env.example", "dockerfile", "docker-compose.yml", "settings.py"}),
    ("docs", lambda p: p.suffix.lower() in {".md", ".rst", ".txt"} and p.name.lower() not in DEPENDENCY_NAMES),
]
RISK = {
    "model": ("HIGH", 1.0, "Prediction/model logic changed"),
    "services": ("HIGH", 0.9, "Service/API orchestration changed"),
    "dependencies": ("HIGH", 0.9, "Runtime dependency changed"),
    "data": ("HIGH", 0.85, "Market/data provider changed"),
    "config": ("MEDIUM", 0.65, "Runtime configuration changed"),
    "frontend": ("LOW", 0.15, "Presentation layer changed"),
    "docs": ("LOW", 0.05, "Documentation changed"),
    "other": ("MEDIUM", 0.5, "Other tracked file changed"),
}

class RepositoryMonitor:
    def __init__(self, path: Path | None = None):
        self._explicit_path = path is not None
        self.path = Path(path or settings.monitored_repo).resolve()
        self.path.mkdir(parents=True, exist_ok=True)
        self.state_path = settings.runtime_dir / "repository_state.json"
        self.source_meta = settings.runtime_dir / "repository_source.json"
        self._hash_cache: dict[str, tuple[int, int, int, str]] = {}
        self._manifest_cache: dict[str, Any] | None = None
        self._findings_cache: tuple[str, list[dict[str, Any]]] | None = None

    def _save_source(self, meta: dict[str, Any]) -> dict[str, Any]:
        self.source_meta.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        # A new repository source gets a fresh trust lifecycle.
        if self.state_path.exists():
            self.state_path.unlink()
        self._manifest_cache = None
        self._findings_cache = None
        self._hash_cache.clear()
        audit("repository-source", "changed", meta)
        return meta

    def set_path(self, path: str) -> dict[str, Any]:
        p = Path(path).expanduser().resolve()
        if not p.exists() or not p.is_dir():
            raise ValueError("Repository path must exist and be a directory.")
        return self._save_source({"type": "local", "scope": "model", "path": str(p)})

    def clone_public_github(self, url: str) -> dict[str, Any]:
        if not url.startswith(("https://github.com/", "http://github.com/")):
            raise ValueError("Enter a public GitHub HTTPS URL.")
        clean = url.rstrip("/")
        if clean.endswith(".git"):
            clean = clean[:-4]
        if clean.count("/") < 4:
            raise ValueError("Enter a repository URL like https://github.com/owner/repository.")
        repo_part = clean.rsplit("/", 1)[-1]
        repo_slug = re.sub(r"[^A-Za-z0-9_.-]", "_", repo_part or "repository")
        # Use a new clone directory for every source change. This avoids deleting or
        # rewriting a prior .git pack while antivirus/indexers still have it open.
        target = settings.runtime_dir / "github_repos" / f"{repo_slug}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", "--no-tags", clean, str(target)],
                check=True, capture_output=True, text=True, timeout=180,
            )
        except FileNotFoundError as exc:
            raise ValueError("Git is not installed or not available on PATH.") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "Git clone failed.").strip()
            shutil.rmtree(target, ignore_errors=True)
            raise ValueError(detail[-900:]) from exc
        self.path = target.resolve()
        commit = self._git_head(self.path)
        return self._save_source({
            "type": "github-public", "scope": "external", "url": clean,
            "path": str(self.path), "remote_commit": commit,
        })

    @staticmethod
    def _git_head(path: Path) -> str | None:
        try:
            return subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                                  check=True, capture_output=True, text=True, timeout=15).stdout.strip()
        except Exception:
            return None

    def refresh_public_github(self) -> dict[str, Any]:
        source = self.source()
        if source.get("type") != "github-public":
            raise ValueError("There is no public GitHub repository currently monitored.")
        if not self.path.exists():
            raise ValueError("The monitored clone no longer exists. Clone it again.")
        try:
            status = subprocess.run(["git", "-C", str(self.path), "status", "--porcelain"],
                                    check=True, capture_output=True, text=True, timeout=15).stdout.strip()
            if status:
                raise ValueError("Local changes are present in the monitored clone. Use CHECK FOR UPDATES to audit them before refreshing from GitHub.")
            subprocess.run(["git", "-C", str(self.path), "fetch", "--depth", "1", "origin", "HEAD"],
                           check=True, capture_output=True, text=True, timeout=180)
            subprocess.run(["git", "-C", str(self.path), "reset", "--hard", "FETCH_HEAD"],
                           check=True, capture_output=True, text=True, timeout=60)
        except subprocess.CalledProcessError as exc:
            raise ValueError((exc.stderr or exc.stdout or "Unable to refresh the GitHub repository.").strip()[-900:]) from exc
        source["remote_commit"] = self._git_head(self.path)
        self.source_meta.write_text(json.dumps(source, indent=2), encoding="utf-8")
        self._manifest_cache = None
        self._findings_cache = None
        return self.scan(False, record_audit=True)

    def bind_to_model(self) -> dict[str, Any]:
        source = self.source()
        source["scope"] = "model"
        return self._save_source(source)

    def source(self) -> dict[str, Any]:
        if self._explicit_path:
            return {"type": "local", "scope": "model", "path": str(self.path)}
        if self.source_meta.exists():
            try:
                data = json.loads(self.source_meta.read_text(encoding="utf-8"))
                if data.get("path"):
                    self.path = Path(data["path"]).resolve()
                return data
            except Exception:
                pass
        return {"type": "local", "scope": "model", "path": str(self.path)}

    def _files(self):
        """Yield tracked files without traversing excluded directories such as .git."""
        if not self.path.exists():
            return
        for root, dirs, files in os.walk(self.path, topdown=True, onerror=lambda _err: None):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            root_path = Path(root)
            for filename in files:
                p = root_path / filename
                try:
                    if p.stat().st_size > 5 * 1024 * 1024:
                        continue
                except OSError:
                    continue
                yield p

    @staticmethod
    def _component(rel: Path) -> str:
        for name, rule in COMPONENT_RULES:
            try:
                if rule(rel):
                    return name
            except Exception:
                continue
        return "other"

    def _hash_file(self, p: Path) -> str:
        stat = p.stat()
        key = p.as_posix()
        cached = self._hash_cache.get(key)
        if cached and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_ctime_ns and cached[2] == stat.st_size:
            return cached[3]
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        digest = h.hexdigest()
        self._hash_cache[key] = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, digest)
        return digest

    def manifest(self) -> dict[str, Any]:
        source_path = str(self.path)
        if self._manifest_cache and self._manifest_cache.get("path") == source_path:
            # Recheck cheap metadata before rehashing.
            files = self._manifest_cache["files"]
        else:
            files = {}
        new_files: dict[str, dict[str, Any]] = {}
        components: dict[str, list[tuple[str, str]]] = {}
        for p in self._files() or []:
            rel = p.relative_to(self.path)
            rel_key = rel.as_posix()
            digest = self._hash_file(p)
            component = self._component(rel)
            new_files[rel_key] = {"sha256": digest, "size": p.stat().st_size, "component": component}
            components.setdefault(component, []).append((rel_key, digest))
        component_hashes = {
            c: hashlib.sha256(json.dumps(sorted(rows), separators=(",", ":")).encode()).hexdigest()
            for c, rows in components.items()
        }
        overall = hashlib.sha256(json.dumps(sorted((k, v["sha256"]) for k, v in new_files.items()), separators=(",", ":")).encode()).hexdigest()
        result = {"fingerprint": overall, "files": new_files, "components": component_hashes,
                  "generated_at": datetime.now().astimezone().isoformat(), "path": source_path}
        self._manifest_cache = result
        return result

    def _security_scan(self, fingerprint: str):
        if self._findings_cache and self._findings_cache[0] == fingerprint:
            return list(self._findings_cache[1])
        findings: list[dict[str, Any]] = []
        patterns = [
            ("HIGH", "security/dynamic-eval", re.compile(r"\beval\s*\("), "Dynamic eval() can execute untrusted code."),
            ("HIGH", "security/exec", re.compile(r"\bexec\s*\("), "Dynamic exec() can execute untrusted code."),
            ("HIGH", "security/private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"), "Private key material appears in source."),
            ("HIGH", "security/token", re.compile(r"(?i)(api[_-]?key|secret|token)\s*=\s*['\"][A-Za-z0-9_\-]{16,}['\"]"), "Credential-like hardcoded value appears in source."),
            ("MEDIUM", "quality/shell-true", re.compile(r"shell\s*=\s*True"), "Shell execution broadens command-injection risk."),
            ("LOW", "quality/debug-print", re.compile(r"\bprint\s*\("), "Debug print remains in tracked code."),
            ("LOW", "quality/todo", re.compile(r"\b(?:TODO|FIXME)\b"), "TODO/FIXME marker remains in tracked source."),
        ]
        text_exts = {".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yml", ".yaml", ".toml", ".ini", ".env", ".java", ".go", ".rs", ".c", ".cpp"}
        for p in self._files() or []:
            if p.suffix.lower() not in text_exts:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            rel = p.relative_to(self.path).as_posix()
            for sev, rule, pattern, msg in patterns:
                count = 0
                for match in pattern.finditer(text):
                    line = text[:match.start()].count("\n") + 1
                    findings.append({"severity": sev, "rule": rule, "message": msg, "file": rel, "line": line})
                    count += 1
                    if count >= 3:
                        break
        if settings.deep_security_scan:
            findings.extend(self._deep_security_findings())
        self._findings_cache = (fingerprint, findings)
        return list(findings)

    def _deep_security_findings(self) -> list[dict[str, Any]]:
        """Optional external scanners. Disabled by default to keep routine scans fast."""
        findings: list[dict[str, Any]] = []
        python_exe = shutil.which("python")
        bandit = shutil.which("bandit")
        if bandit or python_exe:
            try:
                cmd = [bandit or python_exe, "-r", str(self.path), "-f", "json", "-q"] if bandit else [python_exe, "-m", "bandit", "-r", str(self.path), "-f", "json", "-q"]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
                if result.stdout.strip():
                    payload = json.loads(result.stdout)
                    for item in payload.get("results", [])[:100]:
                        findings.append({
                            "severity": str(item.get("issue_severity", "LOW")).upper(),
                            "rule": f"bandit/{item.get('test_id', 'unknown')}",
                            "message": item.get("issue_text", "Bandit finding"),
                            "file": str(item.get("filename", "")).replace(str(self.path), "").lstrip("/\\"),
                            "line": int(item.get("line_number") or 0),
                            "source": "bandit",
                        })
            except Exception:
                pass
        pip_audit = shutil.which("pip-audit")
        requirements = [self.path / name for name in DEPENDENCY_NAMES if (self.path / name).name.startswith("requirements")]
        if pip_audit and requirements:
            try:
                result = subprocess.run([pip_audit, "-r", str(requirements[0]), "-f", "json"], capture_output=True, text=True, timeout=60)
                if result.stdout.strip():
                    payload = json.loads(result.stdout)
                    for item in payload if isinstance(payload, list) else payload.get("dependencies", []):
                        vulns = item.get("vulns") or []
                        for vuln in vulns[:20]:
                            findings.append({
                                "severity": "HIGH",
                                "rule": f"pip-audit/{vuln.get('id', 'vulnerability')}",
                                "message": f"{item.get('name', 'dependency')} {item.get('version', '')} has a known vulnerability.",
                                "file": str(requirements[0].relative_to(self.path)),
                                "line": 0,
                                "source": "pip-audit",
                            })
            except Exception:
                pass
        return findings

    def _impact(self, before: dict[str, Any] | None, after: dict[str, Any]) -> dict[str, Any]:
        if not before:
            return {"added": len(after["files"]), "modified": 0, "removed": 0, "dependency_change": False,
                    "prediction_affecting": True, "items": [], "revalidation": "FULL"}
        old = before.get("files", {})
        new = after.get("files", {})
        added = sorted(set(new) - set(old))
        removed = sorted(set(old) - set(new))
        modified = sorted(k for k in set(old) & set(new) if old[k]["sha256"] != new[k]["sha256"])
        items: list[dict[str, Any]] = []
        max_risk = 0.0
        prediction_affecting = False
        for kind, paths in [("added", added), ("modified", modified), ("removed", removed)]:
            for path in paths:
                component = (new.get(path) or old.get(path)).get("component", "other")
                sev, score, reason = RISK.get(component, RISK["other"])
                max_risk = max(max_risk, score)
                if component in {"model", "services", "dependencies", "data", "config"}:
                    prediction_affecting = True
                items.append({"kind": kind, "path": path, "component": component, "impact": sev, "reason": reason,
                              "prediction_affecting": component in {"model", "services", "dependencies", "data", "config"}})
        dep = any((new.get(p) or old.get(p)).get("component") == "dependencies" for p in set(added + removed + modified))
        if dep:
            max_risk = max(max_risk, 0.9)
            prediction_affecting = True
        if not items:
            depth = "NONE"
        elif max_risk >= 0.9:
            depth = "FULL"
        elif max_risk >= 0.6:
            depth = "MODEL + DATA"
        elif max_risk >= 0.2:
            depth = "TARGETED"
        else:
            depth = "AUDIT-ONLY"
        return {"added": len(added), "modified": len(modified), "removed": len(removed),
                "dependency_change": dep, "prediction_affecting": prediction_affecting,
                "items": items[:80], "revalidation": depth}

    def scan(self, accept: bool = False, record_audit: bool = True) -> dict[str, Any]:
        source = self.source()
        current = self.manifest()
        findings = self._security_scan(current["fingerprint"])
        baseline = None
        if self.state_path.exists():
            try:
                state = json.loads(self.state_path.read_text(encoding="utf-8"))
                baseline = state.get("accepted")
                if baseline and baseline.get("path") != current.get("path"):
                    baseline = None
            except Exception:
                baseline = None
        impact = self._impact(baseline, current)
        current_match = bool(baseline and baseline.get("fingerprint") == current.get("fingerprint"))
        state = "CURRENT" if current_match else ("AWAITING BASELINE" if baseline is None else "STALE")
        if accept:
            self.state_path.write_text(json.dumps({
                "accepted": current, "accepted_findings": findings,
                "accepted_at": datetime.now().astimezone().isoformat(), "scope": source.get("scope", "model")
            }, indent=2), encoding="utf-8")
            state = "CURRENT"
            if record_audit:
                audit("repository-scan", "accepted", {"fingerprint": current["fingerprint"], "findings": findings, "impact": impact})
        elif record_audit:
            audit("repository-check", state.lower(), {"fingerprint": current["fingerprint"], "impact": impact})
        severity_counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for finding in findings:
            severity_counts[finding.get("severity", "LOW")] = severity_counts.get(finding.get("severity", "LOW"), 0) + 1
        security_score = max(0, 100 - sum({"HIGH": 35, "MEDIUM": 15, "LOW": 4}.get(f["severity"], 1) for f in findings))
        security_blocking = any(f.get("severity") == "HIGH" for f in findings)
        return {
            "state": state, "scope": source.get("scope", "model"), "source": source,
            "current": current, "accepted": baseline, "impact": impact,
            "findings": findings, "security_score": security_score, "severity_counts": severity_counts,
            "security_blocking": security_blocking,
            "revalidation_required": (state == "STALE" and (source.get("scope") == "model" and impact.get("prediction_affecting", True))) or (security_blocking and source.get("scope") == "model"),
            "baseline_definition": "An accepted baseline stores the repository fingerprint, file manifest, component fingerprints, dependency state and accepted security findings for one repository snapshot. Future checks compare against this exact snapshot; accepting a baseline does not certify the repository as safe.",
            "monitoring_definition": "Clone & Monitor creates or selects a local repository snapshot, fingerprints tracked files, checks security/code quality and compares every later check against the last accepted baseline. External repositories are audit-only until explicitly bound to model trust.",
        }

    def _restore_model_workspace(self):
        if self.path.resolve() != settings.monitored_repo.resolve():
            return
        seed = {
            "app/ml/model.py": "# monitored model component\nMODEL_VERSION = '4.0'\n",
            "app/data/provider.py": "# monitored market provider component\nPROVIDER = 'market-data'\n",
            "app/services/trust.py": "# monitored trust component\nTRUST_POLICY = 'baseline'\n",
            "frontend/index.html": "<!-- monitored presentation component -->\n",
            "requirements.txt": "numpy>=2.1\nscikit-learn>=1.6\n",
            "README.md": "# Monitored model environment\n",
        }
        for rel, content in seed.items():
            p = self.path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")

    def reset(self):
        # Reset always returns the application to its model workspace so an external
        # repository can be audited and then cleanly detached before the market model
        # workflow is demonstrated again.
        self.path = settings.monitored_repo.resolve()
        self._save_source({"type": "local", "scope": "model", "path": str(self.path)})
        if self.state_path.exists():
            self.state_path.unlink()
        self._restore_model_workspace()
        self._manifest_cache = None
        self._findings_cache = None
        audit("repository-reset", "ok", {"path": str(self.path), "scope": "model"})
        return self.scan(False)

    def simulate_overnight(self):
        if self.path.resolve() != settings.monitored_repo.resolve():
            raise ValueError("The overnight simulation only applies to the built-in model environment. Use CHECK FOR UPDATES or REFRESH REMOTE for an external GitHub repository.")
        model_file = self.path / "app" / "ml" / "model.py"
        dep_file = self.path / "requirements.txt"
        stamp = datetime.now().astimezone().strftime("%Y%m%d%H%M%S")
        base = model_file.read_text(encoding="utf-8") if model_file.exists() else "# monitored model\n"
        model_file.write_text(base.rstrip() + f"\n# overnight update {stamp}: feature threshold changed\nprint(\"temporary diagnostics\")\n", encoding="utf-8")
        dep_file.write_text("numpy>=2.1\nscikit-learn>=1.7\n# overnight dependency update\n", encoding="utf-8")
        self._manifest_cache = None
        self._findings_cache = None
        audit("overnight-simulation", "changed", {"model_file": str(model_file), "dependency_file": str(dep_file)})
        return self.scan(False)
