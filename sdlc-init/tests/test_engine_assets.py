"""Engine-root resolution, asset completeness, and honest provenance (#38).

These are the fast unit tests. The end-to-end proof — build a wheel, install it
non-editably, run `sdlc init` from outside any checkout — lives in
`harness/selfci/tests/test_artifact_smoke.py`, because the defect this closes
was invisible to every test that ran against importable source.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sdlc_init import engine_assets as ea
from sdlc_init import harness_map as hm
from sdlc_init.manifest import InitManifest, build_repo_manifest

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_required_assets_covers_every_map_source():
    """The asset list is derived from harness_map, not restated beside it.

    A template added to FILE_MAP but forgotten in the packaging list is exactly
    how a payload ships incomplete, so the derivation is the contract.
    """
    required = set(ea.required_assets())
    assert required, "asset list must not be empty"

    for src, _dest in hm.FILE_MAP:
        assert f"harness/{src}" in required
    for src, _dest in hm.DIR_MAP:
        assert f"harness/{src}" in required
    for src, _dest in hm.ENGINE_VENDOR_MAP:
        assert src in required
    for src, _dest in hm.ENGINE_VENDOR_DIRS:
        assert src in required
    assert f"harness/{hm.SKILLS_SRC}" in required


def test_required_assets_all_present_in_this_checkout():
    """The checkout itself satisfies the contract — a positive control.

    Without this, `missing_assets` could return everything always and the
    planted-negative test below would still pass.
    """
    assert ea.missing_assets(REPO_ROOT) == []


def test_missing_assets_names_what_is_absent(tmp_path):
    missing = ea.missing_assets(tmp_path)
    assert set(missing) == set(ea.required_assets())


def test_missing_assets_discriminates_a_single_gap(tmp_path):
    """Remove exactly one asset from an otherwise complete root.

    `test_missing_assets_names_what_is_absent` uses an empty dir, so it would
    pass against a check that always reports everything missing. This is the
    version that fails if the check is not actually per-path.
    """
    victim = "harness/templates/CLAUDE.md.tmpl"
    for rel in ea.required_assets():
        source = REPO_ROOT / rel
        target = tmp_path / rel
        if rel == victim:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            target.mkdir(exist_ok=True)
        else:
            target.write_bytes(b"stub")
    assert ea.missing_assets(tmp_path) == [victim]


def test_require_complete_raises_and_names_the_gap(tmp_path):
    root = ea.EngineRoot(tmp_path, ea.PROVENANCE_PACKAGE, "9.9.9")
    with pytest.raises(SystemExit) as excinfo:
        ea.require_complete(root)
    message = str(excinfo.value)
    assert "incomplete" in message
    assert "harness/" in message


def test_require_complete_passes_on_this_checkout():
    ea.require_complete(ea.EngineRoot(REPO_ROOT, ea.PROVENANCE_CHECKOUT))


def test_resolve_prefers_explicit_path(tmp_path):
    resolved = ea.resolve(tmp_path)
    assert resolved.path == tmp_path.resolve()
    assert resolved.provenance == ea.PROVENANCE_CHECKOUT


def test_resolve_prefers_payload_over_checkout(tmp_path, monkeypatch):
    payload = tmp_path / "_payload"
    payload.mkdir()
    monkeypatch.setattr(ea, "packaged_root", lambda: payload)
    monkeypatch.setattr(ea, "checkout_root", lambda: tmp_path / "checkout")
    resolved = ea.resolve()
    assert resolved.path == payload
    assert resolved.is_package


def test_resolve_falls_back_to_checkout(monkeypatch):
    monkeypatch.setattr(ea, "packaged_root", lambda: None)
    resolved = ea.resolve()
    assert resolved.provenance == ea.PROVENANCE_CHECKOUT
    assert resolved.path == REPO_ROOT


def test_resolve_fails_loudly_when_nothing_resolves(monkeypatch):
    monkeypatch.setattr(ea, "packaged_root", lambda: None)
    monkeypatch.setattr(ea, "checkout_root", lambda: None)
    with pytest.raises(SystemExit) as excinfo:
        ea.resolve()
    assert "--engine-root" in str(excinfo.value)


def test_payload_digest_changes_when_any_asset_changes(tmp_path):
    root = tmp_path
    (root / "harness" / "templates").mkdir(parents=True)
    target = root / "harness" / "templates" / "CLAUDE.md.tmpl"
    target.write_text("one", encoding="utf-8")
    first = ea.payload_digest(root)
    target.write_text("two", encoding="utf-8")
    assert ea.payload_digest(root) != first


def test_packaged_provenance_records_version_and_digest(tmp_path):
    record = ea.provenance_record(ea.EngineRoot(tmp_path, ea.PROVENANCE_PACKAGE, "0.6.0"))
    assert record["kind"] == "package"
    assert record["package_version"] == "0.6.0"
    assert record["payload_digest"].startswith("sha256:")


def test_checkout_provenance_carries_no_payload_digest(tmp_path):
    record = ea.provenance_record(ea.EngineRoot(tmp_path, ea.PROVENANCE_CHECKOUT, "0.6.0"))
    assert record["kind"] == "checkout"
    assert "payload_digest" not in record


def test_manifest_from_a_package_never_carries_a_git_sha(tmp_path):
    """The #38 acceptance criterion, asserted at the manifest boundary.

    `git rev-parse` inside site-packages can succeed by walking up into whatever
    repository contains the environment. A packaged install must therefore not
    call it at all — the release identity is the version plus payload digest.
    """
    manifest = InitManifest(
        project_name="P", owner="@o", target=tmp_path, engine_root=tmp_path,
        engine_provenance={"kind": "package", "package_version": "0.6.0",
                           "payload_digest": "sha256:abc"},
    )
    built = build_repo_manifest(manifest, "2026-09-12", [{"status": "ok"}])
    engine = built["engine"]
    assert engine["sha"] is None
    assert engine["version"] == "0.6.0"
    assert engine["provenance"]["payload_digest"] == "sha256:abc"


def test_manifest_from_a_checkout_still_records_its_commit(tmp_path):
    manifest = InitManifest(
        project_name="P", owner="@o", target=tmp_path, engine_root=REPO_ROOT,
        engine_provenance={"kind": "checkout", "package_version": "unknown"},
    )
    built = build_repo_manifest(manifest, "2026-09-12", [{"status": "ok"}])
    assert built["engine"]["provenance"]["kind"] == "checkout"
    # 40-hex when this tree is a git checkout; 'unknown' in an exported archive.
    sha = built["engine"]["sha"]
    assert sha == "unknown" or (len(sha) == 40 and int(sha, 16) >= 0)


def test_manifest_json_round_trips(tmp_path):
    manifest = InitManifest(
        project_name="P", owner="@o", target=tmp_path, engine_root=tmp_path,
        engine_provenance={"kind": "package", "package_version": "0.6.0",
                           "payload_digest": "sha256:abc"},
    )
    built = build_repo_manifest(manifest, "2026-09-12", [{"status": "ok"}])
    assert json.loads(json.dumps(built))["engine"]["sha"] is None
