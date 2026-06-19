import importlib.util
from pathlib import Path


def load_create_sample_pdf_module():
    script_path = Path(__file__).parents[1] / "scripts" / "create_sample_pdf.py"
    spec = importlib.util.spec_from_file_location("create_sample_pdf", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_create_sample_pdf_writes_pdf(tmp_path, monkeypatch) -> None:
    create_sample_pdf = load_create_sample_pdf_module()
    monkeypatch.chdir(tmp_path)

    create_sample_pdf.main()

    pdf_path = Path("samples/ocr_sample.pdf")
    assert pdf_path.exists()
    assert pdf_path.read_bytes().startswith(b"%PDF")
