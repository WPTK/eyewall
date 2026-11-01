"""The meta-tests. The inventory (every key, clickable, menu entry and README claim) minus what the checks exercised must be
empty, and every README key and flag must have a claim with a proof. Both print their counts."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.uat.inventory import claims, registry
from tests.uat.inventory.inventory import palette_items, static_click_items, static_key_items
from tests.uat.inventory.matrix import results_for
from tests.uat.inventory.registry import World
from tests.uat.inventory.runner import all_results, saved_dynamic

pytestmark = pytest.mark.uat
ROOT = Path(__file__).resolve().parents[3]
INTERNAL = ("crash:", "click:crash:")


async def inventory_and_results() -> tuple[set[str], dict[str, str | None]]:
    results = await all_results()
    if not any(i.startswith("click:footer:") for i in saved_dynamic()):
        await results_for(World("demo", (120, 30)))
    inventory = static_key_items() | static_click_items() | palette_items() | claims.items() | saved_dynamic()
    return inventory, {k: v for k, v in results.items() if not k.startswith(INTERNAL)}


async def test_every_input_has_a_test() -> None:
    inventory, results = await inventory_and_results()
    registry.RESULTS.update(results)
    print("\ninventory:", len(inventory), "items;", registry.summary(inventory))
    missing = sorted(inventory - set(results))
    assert not missing, f"{len(missing)} inputs have no covering test:\n  " + "\n  ".join(missing)


async def test_no_orphan_checks() -> None:
    inventory, results = await inventory_and_results()
    orphans = sorted(set(results) - inventory)
    assert not orphans, "checks report items the inventory does not have (renamed key?):\n  " + "\n  ".join(orphans)


def readme_keys() -> set[str]:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    section = text.split("## Mouse and keyboard")[1].split("## First run")[0]
    tokens: set[str] = set()
    for line in section.splitlines():
        if not line.startswith("|") or set(line) <= set("|- "):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells[0] in ("Key", "Screen"):
            continue
        for cell in cells[:-1]:
            tokens |= set(re.findall(r"`([^`]+)`", cell))
            if cell == "Arrow keys":
                tokens.add("Arrow keys")
    return tokens


def readme_flags() -> set[str]:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    section = text.split("## Command line")[1].split("## Replay")[0]
    return set(re.findall(r"(?<![\w-])(--[a-z][a-z-]*)", section))


def resolve(proof: str, known: set[str]) -> bool:
    if "::" in proof:
        path, name = proof.split("::")
        return f"def {name}(" in (ROOT / path).read_text(encoding="utf-8")
    if proof.endswith("*"):
        return any(r.startswith(proof[:-1]) for r in known)
    return proof in known


async def test_claims_traceability() -> None:
    _, results = await inventory_and_results()
    known = set(results) | static_key_items() | palette_items()
    table = claims.table()
    problems: list[str] = []
    for token in sorted(readme_keys()):
        token = claims.KEY_ALIASES.get(token, token)
        if f"key-{token}" not in table:
            problems.append(f"README key `{token}` has no claim in tests/uat/inventory/claims.py")
    for flag in sorted(readme_flags()):
        if f"flag-{flag}" not in table:
            problems.append(f"README flag {flag} has no claim")
    for cid, (_, proofs) in table.items():
        if not proofs:
            problems.append(f"claim {cid} has no proof")
        for proof in proofs:
            if not resolve(proof, known):
                problems.append(f"claim {cid}: proof {proof} does not exist")
    print(f"\nREADME claims: {len(table)} ({len(readme_keys())} key tokens, {len(readme_flags())} flags)")
    assert not problems, "\n  " + "\n  ".join(problems)
