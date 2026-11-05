"""Checks that each exposed parameter of Template_Material changes only the maps it should.

Needs Template_Material.sbsar from build_template_material.py, but not Designer. Usage:
    uv run python examples/verify_template_parameters.py <carpeta_con_el_sbsar>
"""

from __future__ import annotations

import hashlib
import struct
import sys
from pathlib import Path

import anyio
from mcp_client import connect

MAPS = {"baseColor", "normal", "roughness", "metallic", "height", "ambientOcclusion"}
# Parameter value -> maps expected to change. Noise feeds everything except the two flat uniforms.
EXPECTED = {
    "tint": ({"base_tint": [1, 0, 0, 1]}, {"baseColor"}),
    "normal": ({"normal_intensity": 3.0}, {"normal"}),
    "scale": ({"noise_scale": 32}, {"baseColor", "normal", "height", "ambientOcclusion"}),
}


def png_size(data: bytes) -> tuple[int, int]:
    return struct.unpack(">II", data[16:24])


def fingerprints(files: list[str], size: tuple[int, int]) -> dict[str, str]:
    prints = {}
    for file in files:
        usage = Path(file).stem.split("_")[-1]
        data = Path(file).read_bytes()
        assert png_size(data) == size, f"{file}: {png_size(data)} en vez de {size}"
        prints[usage] = hashlib.sha256(data).hexdigest()
    assert set(prints) == MAPS, sorted(prints)
    return prints


async def main(folder: Path) -> int:
    sbsar = str(folder / "Template_Material.sbsar")
    root = folder / "render_parameters"
    failures = 0
    async with connect() as tools:
        async def render(name, parameters):
            result = await tools.call(
                "render_outputs", sbsar_path=sbsar, output_dir=str(root / name), width=256, height=256, parameters=parameters
            )
            return fingerprints(result["files"], (256, 256))

        engine_default = await tools.call("render_outputs", sbsar_path=sbsar, output_dir=str(root / "engine_default"))
        fingerprints(engine_default["files"], (256, 256))
        chosen = await tools.call(
            "render_outputs", sbsar_path=sbsar, output_dir=str(root / "chosen_size"), width=1024, height=512
        )
        fingerprints(chosen["files"], (1024, 512))
        print("OK  sin width/height el motor usa 256x256; con ellos, 1024x512")

        typo = await tools.rejected("render_outputs", sbsar_path=sbsar, output_dir=str(root / "typo"), parameters={"base_tnt": 1})
        assert "no expone" in typo, typo
        print("OK  un parametro mal escrito se rechaza")

        baseline = await render("baseline", {})
        repeat = await render("baseline_repeat", {})
        assert baseline == repeat, "El render no es determinista: comparar hashes no serviria"

        for name, (parameters, expected) in EXPECTED.items():
            current = await render(name, parameters)
            changed = {usage for usage in MAPS if current[usage] != baseline[usage]}
            ok = changed == expected
            failures += not ok
            print(f"{'OK ' if ok else 'MAL'} {parameters}: cambian {sorted(changed)}; esperado {sorted(expected)}")
    return failures


if __name__ == "__main__":
    sys.exit(anyio.run(main, Path(sys.argv[1]).resolve()))
