import json
from pathlib import Path

import pytest

from backend.app.domain.document_set import DocumentSet
from data_generator.__main__ import main
from data_generator.generate import generate
from data_generator.output import write_dataset
from data_generator.tests.helpers import assert_set_consistent


def _files(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


def test_same_seed_gives_byte_identical_output(tmp_path: Path) -> None:
    first = write_dataset(generate(42, 8), seed=42, out_dir=tmp_path / "a")
    second = write_dataset(generate(42, 8), seed=42, out_dir=tmp_path / "b")
    assert _files(first) == _files(second)


def test_different_seed_gives_different_output(tmp_path: Path) -> None:
    a = write_dataset(generate(42, 8), seed=42, out_dir=tmp_path, render_pdfs=False)
    b = write_dataset(generate(43, 8), seed=43, out_dir=tmp_path, render_pdfs=False)
    assert _files(a) != _files(b)


def test_adding_sets_keeps_earlier_sets_identical() -> None:
    assert generate(42, 9)[:8] == generate(42, 8)


def test_layout_and_manifest(tmp_path: Path) -> None:
    root = write_dataset(generate(42, 8), seed=42, out_dir=tmp_path, render_pdfs=False)
    assert root == tmp_path / "seed-42"
    assert sorted(p.name for p in root.iterdir()) == [
        "manifest.json",
        *(f"set-{i:03d}" for i in range(1, 9)),
    ]
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["seed"] == 42
    assert len(manifest["sets"]) == 8
    assert sum(s["clean"] for s in manifest["sets"]) == 2


def test_ground_truth_round_trips_and_clean_sets_are_consistent(tmp_path: Path) -> None:
    root = write_dataset(generate(42, 8), seed=42, out_dir=tmp_path, render_pdfs=False)
    for path in sorted(root.glob("set-*/ground_truth.json")):
        doc_set = DocumentSet.model_validate_json(path.read_bytes())
        if doc_set.is_clean:
            assert_set_consistent(doc_set)


def test_ground_truth_stores_amounts_as_strings(tmp_path: Path) -> None:
    root = write_dataset(generate(42, 8), seed=42, out_dir=tmp_path, render_pdfs=False)
    data = json.loads((root / "set-001" / "ground_truth.json").read_text())
    assert isinstance(data["invoices"][0]["gross_total"], str)


def test_existing_output_is_not_overwritten_without_force(tmp_path: Path) -> None:
    write_dataset(generate(42, 8), seed=42, out_dir=tmp_path, render_pdfs=False)
    with pytest.raises(FileExistsError, match="--force"):
        write_dataset(generate(42, 8), seed=42, out_dir=tmp_path, render_pdfs=False)
    write_dataset(generate(42, 8), seed=42, out_dir=tmp_path, force=True, render_pdfs=False)


def test_force_removes_stale_sets(tmp_path: Path) -> None:
    write_dataset(generate(42, 9), seed=42, out_dir=tmp_path, render_pdfs=False)
    root = write_dataset(generate(42, 8), seed=42, out_dir=tmp_path, force=True, render_pdfs=False)
    assert not (root / "set-009").exists()


def test_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--seed", "7", "--sets", "8", "--out", str(tmp_path)])
    assert code == 0
    assert (tmp_path / "seed-7" / "set-008" / "ground_truth.json").is_file()
    assert "8 sets" in capsys.readouterr().out


def test_pdfs_are_written_and_listed_in_the_manifest(tmp_path: Path) -> None:
    root = write_dataset(generate(42, 8), seed=42, out_dir=tmp_path)
    manifest = json.loads((root / "manifest.json").read_text())
    for entry in manifest["sets"]:
        assert entry["files"]
        for name in entry["files"].values():
            assert (root / entry["set_id"] / name).read_bytes().startswith(b"%PDF")
    duplicate_set = manifest["sets"][7]
    assert duplicate_set["errors"] == ["duplicate_invoice"]
    assert sorted(duplicate_set["files"].values()) == ["dn.pdf", "inv-1.pdf", "inv-2.pdf", "po.pdf"]


def test_cli_no_pdf(tmp_path: Path) -> None:
    assert main(["--seed", "7", "--sets", "8", "--out", str(tmp_path), "--no-pdf"]) == 0
    assert not list((tmp_path / "seed-7").rglob("*.pdf"))
