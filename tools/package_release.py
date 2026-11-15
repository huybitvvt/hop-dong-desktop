"""Create a portable release and include rebuildable source and license texts."""
from __future__ import annotations

import importlib.metadata as metadata
from pathlib import Path
import shutil
import urllib.request
import zipfile
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def runtime_distributions(root):
    queue = [(Requirement(line).name, Requirement(line).extras) for line in (root / "requirements.txt").read_text().splitlines() if line.strip() and not line.startswith("#")]
    seen = set()
    distributions = {}
    while queue:
        name, extras = queue.pop()
        identity = (canonicalize_name(name), tuple(sorted(extras)))
        if identity in seen:
            continue
        seen.add(identity)
        dist = metadata.distribution(name)
        distributions[canonicalize_name(name)] = dist
        for raw in dist.requires or []:
            requirement = Requirement(raw)
            if requirement.marker and not any(requirement.marker.evaluate({"extra": extra}) for extra in extras or {""}):
                continue
            queue.append((requirement.name, requirement.extras))
    return sorted(distributions.values(), key=lambda d: d.metadata.get("Name", "").lower())


def package():
    root = Path(__file__).resolve().parents[1]
    release = root / "dist" / "HopDongAI"
    if not (release / "HopDongAI.exe").is_file():
        raise RuntimeError("Build executable before packaging")
    shutil.copy2(root / "README.md", release / "HUONG-DAN.md")
    shutil.copy2(root / "BAN-GIAO.md", release / "BAT-DAU.md")
    source = release / "source"
    source.mkdir(exist_ok=True)
    for name in ["main.py", "requirements.txt", "requirements-dev.txt", "requirements.lock.txt", "HopDongAI.spec", "Build.ps1", "README.md", "BAN-GIAO.md", "pytest.ini"]:
        shutil.copy2(root / name, source / name)
    for name in ["contract_app", "assets", "tests"]:
        shutil.copytree(root / name, source / name, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (source / "tools").mkdir(exist_ok=True)
    for name in ["create_demo.py", "create_icon.py", "package_release.py", "verify_release.py"]:
        shutil.copy2(root / "tools" / name, source / "tools" / name)
    licenses = release / "licenses"
    licenses.mkdir(exist_ok=True)
    notices = ["# Third-party software", "", "The application includes unmodified third-party packages. Their respective licenses apply. Application source and build instructions are supplied in source/ so it can be rebuilt with modified or replacement libraries.", "", "PySide6 / Qt: LGPL-3.0 option; https://www.qt.io/licensing/open-source-lgpl-obligations and https://code.qt.io/cgit/pyside/pyside-setup.git/", "", "docxtpl: LGPL-2.1-only; https://github.com/elapouya/python-docx-template", "", "Noto Sans: SIL Open Font License 1.1; assets/fonts/OFL.txt; https://github.com/google/fonts/tree/main/ofl/notosans", "", "## Installed package inventory", ""]
    for dist in runtime_distributions(root):
        name = dist.metadata.get("Name", "unknown")
        license_name = dist.metadata.get("License-Expression") or dist.metadata.get("License", "See package license")
        license_name = license_name.splitlines()[0][:160]
        notices.append(f"- {name} {dist.version}: {license_name}")
        for item in dist.files or []:
            path = Path(str(item))
            if any("license" in part.lower() or part.lower().startswith("copying") for part in path.parts) and path.suffix.lower() in (".txt", ".md", ".rst", ""):
                original = Path(dist.locate_file(item))
                if original.is_file():
                    target = licenses / name / path.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if not target.exists():
                        shutil.copy2(original, target)
    # docxtpl 0.20.2 lacks its license text in the wheel. Supply the verbatim licenses.
    license_urls = {
        "LGPL-2.1.txt": "https://raw.githubusercontent.com/spdx/license-list-data/main/text/LGPL-2.1-only.txt",
        "LGPL-3.0.txt": "https://raw.githubusercontent.com/spdx/license-list-data/main/text/LGPL-3.0-only.txt",
        "GPL-3.0.txt": "https://raw.githubusercontent.com/spdx/license-list-data/main/text/GPL-3.0-only.txt",
    }
    for name, url in license_urls.items():
        target = licenses / name
        if not target.exists():
            with urllib.request.urlopen(url, timeout=30) as response:
                target.write_bytes(response.read())
    (release / "THIRD_PARTY_NOTICES.md").write_text("\n".join(notices), encoding="utf-8")
    archive_path = root / "dist" / "HopDongAI-Windows.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in release.rglob("*"):
            if path.is_file():
                archive.write(path, Path("HopDongAI") / path.relative_to(release))
    print(f"RELEASE_OK: {archive_path.name} ({archive_path.stat().st_size / 1024**2:.1f} MB)")


if __name__ == "__main__":
    package()
