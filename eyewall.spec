# PyInstaller spec: one-file console build of eyewall, the same on Windows, Linux and macOS.
# Build with scripts/build_exe.ps1 on Windows, or `python -m PyInstaller --noconfirm --workpath .pyi-build eyewall.spec`.
import importlib.util

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# The map data, the Textual stylesheet and the recorded demo storm are read from files at run time, so each goes in at
# the path the package expects (src/eyewall/sources/bundle.py looks for eyewall/demo/erin2025 next to the code).
datas = [
    ("src/eyewall/mapdata/*.bin", "eyewall/mapdata"),
    ("src/eyewall/mapdata/ATTRIBUTION.md", "eyewall/mapdata"),
    ("src/eyewall/ui/app.tcss", "eyewall/ui"),
    ("tests/fixtures/replay/erin2025", "eyewall/demo/erin2025"),
]
datas += collect_data_files("textual")
hiddenimports = collect_submodules("textual.widgets")

# Libraries that are optional or Windows-only dependencies of the package: bundle them when they are installed, so
# the binary also works on a system with no zone files and in the graphics screen.
for name in ("tzdata", "textual_image"):
    if importlib.util.find_spec(name) is not None:
        datas += collect_data_files(name)
        hiddenimports += collect_submodules(name)

a = Analysis(
    ["src/eyewall/__main__.py"],
    pathex=["src"],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pytest", "respx", "hypothesis", "mypy", "ruff"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="eyewall",
    console=True,
    upx=False,
)
