"""Validate the distributions and print their checksums, without uploading."""

import hashlib
import pathlib
import subprocess
import sys
import tarfile
import zipfile
from email.parser import Parser


def main() -> None:
    dist = pathlib.Path("dist")
    wheels, sources = sorted(dist.glob("*.whl")), sorted(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        raise SystemExit("dist/ must contain exactly one wheel and one source distribution")
    files = wheels + sources
    subprocess.check_call([sys.executable, "-m", "twine", "check", "--strict", *map(str, files)])
    with zipfile.ZipFile(wheels[0]) as wheel:
        names = wheel.namelist()
        assert "bondbyisin/client.py" in names and "bondbyisin/py.typed" in names
        assert all(name.startswith(("bondbyisin/", "bondbyisin-")) for name in names)
        metadata = Parser().parsestr(
            wheel.read(next(n for n in names if n.endswith("/METADATA"))).decode()
        )
        assert metadata["Name"] == "bondbyisin"
        runtime = [r for r in metadata.get_all("Requires-Dist", []) if "extra ==" not in r]
        assert len(runtime) == 1 and runtime[0].startswith("requests")
    with tarfile.open(sources[0]) as source:
        names = source.getnames()
        assert any(n.endswith("/.github/workflows/release.yml") for n in names)
        assert any(n.endswith("/tests/test_client.py") for n in names)
        assert not any("/.env" in n or "/.venv/" in n or "__pycache__" in n for n in names)
    for path in files:
        print(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}  {path.stat().st_size} bytes"
        )


if __name__ == "__main__":
    main()
