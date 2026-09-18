"""Merge a .gltf + external .bin + external textures into one self-contained
JSON file (everything as base64 data URIs), then save with a .json extension
so it's uploadable via the Artifact assets capability (which rejects .gltf/.bin
but accepts .json).

Usage: python embed_gltf.py <folder-containing-one-gltf-and-its-resources>
"""
import base64
import json
import mimetypes
import sys
from pathlib import Path


def embed(folder: Path):
    gltf_files = list(folder.glob("*.gltf"))
    if len(gltf_files) != 1:
        raise RuntimeError(f"Expected exactly one .gltf in {folder}, found {len(gltf_files)}")
    gltf_path = gltf_files[0]
    data = json.loads(gltf_path.read_text())

    for buf in data.get("buffers", []):
        uri = buf.get("uri")
        if uri and not uri.startswith("data:"):
            content = (folder / uri).read_bytes()
            b64 = base64.b64encode(content).decode("ascii")
            buf["uri"] = f"data:application/octet-stream;base64,{b64}"

    for img in data.get("images", []):
        uri = img.get("uri")
        if uri and not uri.startswith("data:"):
            content = (folder / uri).read_bytes()
            mime = mimetypes.guess_type(uri)[0] or "application/octet-stream"
            b64 = base64.b64encode(content).decode("ascii")
            img["uri"] = f"data:{mime};base64,{b64}"

    out_path = gltf_path.with_suffix(".json")
    out_path.write_text(json.dumps(data))
    print(f"{gltf_path.name} -> {out_path.name} ({out_path.stat().st_size / 1024 / 1024:.2f} MB)")
    return out_path


if __name__ == "__main__":
    embed(Path(sys.argv[1]))
