from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
GENERATOR = SCRIPTS / "generate-from-template.py"
RENDERER = SCRIPTS / "render-diagram.py"
VALIDATOR = SCRIPTS / "validate-svg.py"


def base_diagram() -> dict[str, object]:
    return {
        "template_type": "architecture",
        "style": 1,
        "width": 800,
        "height": 480,
        "title": "Regression",
        "nodes": [
            {"id": "source", "kind": "rect", "x": 80, "y": 180, "width": 180, "height": 70, "label": "Source"},
            {"id": "target", "kind": "rect", "x": 520, "y": 180, "width": 180, "height": 70, "label": "Target"},
        ],
        "arrows": [{"source": "source", "target": "target", "label": "request"}],
    }


class GeneratorCliTests(unittest.TestCase):
    def run_generator(
        self,
        template_type: str,
        data: dict[str, object],
        *,
        output: Path | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], Path, tempfile.TemporaryDirectory[str] | None]:
        temporary: tempfile.TemporaryDirectory[str] | None = None
        if output is None:
            temporary = tempfile.TemporaryDirectory()
            output = Path(temporary.name) / "result.svg"
        input_path = output.parent / "input.json"
        input_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(GENERATOR), template_type, str(output), str(input_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return result, output, temporary

    def test_normal_generation_is_valid(self) -> None:
        result, output, temporary = self.run_generator("architecture", base_diagram())
        self.addCleanup(temporary.cleanup)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(output.exists())
        validation = subprocess.run(
            [sys.executable, str(VALIDATOR), str(output)],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(validation.returncode, 0, validation.stdout + validation.stderr)

    def test_dangling_edge_is_rejected(self) -> None:
        data = base_diagram()
        data["arrows"] = [{"source": "source", "target": "missing"}]
        result, output, temporary = self.run_generator("architecture", data)
        self.addCleanup(temporary.cleanup)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())
        self.assertIn("target", (result.stdout + result.stderr).lower())

    def test_duplicate_node_id_is_rejected(self) -> None:
        data = base_diagram()
        data["nodes"].append({"id": "source", "x": 300, "y": 300, "width": 100, "height": 50, "label": "Duplicate"})
        result, output, temporary = self.run_generator("architecture", data)
        self.addCleanup(temporary.cleanup)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())
        self.assertIn("id", (result.stdout + result.stderr).lower())

    def test_unknown_type_and_style_are_rejected(self) -> None:
        cases = [
            ("totally-unknown", base_diagram()),
            ("architecture", {**base_diagram(), "style": 99}),
            ("architecture", {**base_diagram(), "style": "Flat Iconn"}),
        ]
        for template_type, data in cases:
            with self.subTest(template_type=template_type, style=data.get("style")):
                result, output, temporary = self.run_generator(template_type, data)
                self.addCleanup(temporary.cleanup)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(output.exists())

    def test_invalid_layout_direction_and_container_reference_are_rejected(self) -> None:
        invalid_direction = base_diagram()
        invalid_direction["layout"] = {"auto": True, "direction": "SIDEWAYS"}
        invalid_container = base_diagram()
        invalid_container["nodes"][0]["container_id"] = "missing-container"
        for data in (invalid_direction, invalid_container):
            with self.subTest(data=data):
                result, output, temporary = self.run_generator("architecture", data)
                self.addCleanup(temporary.cleanup)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(output.exists())

    def test_attribute_injection_is_rejected(self) -> None:
        data = base_diagram()
        data["nodes"][0]["fill"] = 'red"/><script>alert(1)</script><rect fill="red'
        result, output, temporary = self.run_generator("architecture", data)
        self.addCleanup(temporary.cleanup)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())

    def test_failed_generation_preserves_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "important.svg"
            original = b"existing-user-artifact"
            output.write_bytes(original)
            data = base_diagram()
            data["nodes"].append({"id": "source", "x": 10, "y": 10, "width": 20, "height": 20, "label": "duplicate"})
            result, _, _ = self.run_generator("architecture", data, output=output)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(output.read_bytes(), original)

    def test_chinese_and_special_characters_round_trip_once(self) -> None:
        data = base_diagram()
        value = '研发 & <临床> “AI”'
        data["nodes"][0]["label"] = value
        result, output, temporary = self.run_generator("architecture", data)
        self.addCleanup(temporary.cleanup)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        root = ET.parse(output).getroot()
        text_values = [text for text in root.itertext() if text]
        self.assertIn(value, text_values)
        self.assertNotIn("&amp;", "".join(text_values))

    def test_dark_theme_cylinder_inherits_readable_theme_colors(self) -> None:
        data = base_diagram()
        data["template_type"] = "data-flow"
        data["style"] = 2
        data["nodes"] = [
            {
                "id": "store",
                "kind": "cylinder",
                "x": 280,
                "y": 160,
                "width": 220,
                "height": 100,
                "label": "Referral Registry",
            }
        ]
        data["arrows"] = []
        result, output, temporary = self.run_generator("data-flow", data)
        self.addCleanup(temporary.cleanup)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        root = ET.parse(output).getroot()
        themed_shapes = [
            element
            for element in root.iter()
            if element.tag.endswith("rect")
            and element.attrib.get("fill") == "#111827"
            and element.attrib.get("stroke") == "#334155"
        ]
        self.assertTrue(themed_shapes, "dark-theme cylinder must not fall back to a light hard-coded fill")
        self.assertIn("Referral Registry", list(root.itertext()))


class RenderDiagramTests(unittest.TestCase):
    def run_renderer(
        self,
        template_type: str,
        data: dict[str, object],
        base: Path,
        formats: str = "svg,json",
    ) -> subprocess.CompletedProcess[str]:
        input_path = base.parent / f"{base.name}-input.json"
        input_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return subprocess.run(
            [
                sys.executable,
                str(RENDERER),
                "--type",
                template_type,
                "--input",
                str(input_path),
                "--output",
                str(base),
                "--formats",
                formats,
                "--validate",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    def test_wrapper_publishes_svg_and_normalized_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "diagram"
            result = self.run_renderer("architecture", base_diagram(), base)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(base.with_suffix(".svg").exists())
            normalized = json.loads(base.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertEqual(normalized["template_type"], "architecture")
            self.assertIn("nodes", normalized)
            report = json.loads(result.stdout)
            self.assertTrue(report["validation"]["valid"])

    def test_wrapper_uses_canonical_type_after_alias_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "aliased"
            data = base_diagram()
            data["template_type"] = "system-architecture"
            result = self.run_renderer("system-architecture", data, base)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            normalized = json.loads(base.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertEqual(normalized["template_type"], "architecture")
            report = json.loads(result.stdout)
            self.assertEqual(report["type"], "architecture")
            self.assertEqual(report["requested_type"], "system-architecture")

    def test_directory_destination_is_rejected_before_any_target_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "diagram"
            svg_directory = base.with_suffix(".svg")
            svg_directory.mkdir()
            directory_sentinel = svg_directory / "keep.txt"
            directory_sentinel.write_bytes(b"keep-directory")
            json_target = base.with_suffix(".json")
            json_target.write_bytes(b"keep-json")

            result = self.run_renderer("architecture", base_diagram(), base)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing to replace directory", result.stderr)
            self.assertTrue(svg_directory.is_dir())
            self.assertEqual(directory_sentinel.read_bytes(), b"keep-directory")
            self.assertEqual(json_target.read_bytes(), b"keep-json")
            self.assertNotIn("Traceback", result.stderr)

    def test_destination_symlink_is_replaced_without_touching_its_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "diagram"
            target = Path(temporary) / "symlink-target.svg"
            target.write_bytes(b"external-target")
            link = base.with_suffix(".svg")
            try:
                link.symlink_to(target)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")

            result = self.run_renderer("architecture", base_diagram(), base, "svg")

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(link.is_symlink())
            self.assertEqual(target.read_bytes(), b"external-target")
            ET.parse(link)

    def test_input_json_cannot_also_be_an_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            input_path = Path(temporary) / "diagram.json"
            original = json.dumps(base_diagram(), ensure_ascii=False).encode("utf-8")
            input_path.write_bytes(original)
            result = subprocess.run(
                [
                    sys.executable,
                    str(RENDERER),
                    "--type",
                    "architecture",
                    "--input",
                    str(input_path),
                    "--output",
                    str(input_path),
                    "--formats",
                    "json",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("resolve to the same path", result.stderr)
            self.assertEqual(input_path.read_bytes(), original)
            self.assertNotIn("Traceback", result.stderr)

    def test_raw_invalid_controls_fail_before_layout_can_repair_them(self) -> None:
        cases: dict[str, dict[str, object]] = {}

        negative_canvas = base_diagram()
        negative_canvas["width"] = -1
        cases["negative-canvas"] = negative_canvas

        nonfinite_node = base_diagram()
        nonfinite_node["nodes"][0]["x"] = float("nan")
        cases["nonfinite-node"] = nonfinite_node

        negative_node_size = base_diagram()
        negative_node_size["nodes"][0]["width"] = 0
        cases["nonpositive-node-size"] = negative_node_size

        invalid_container = base_diagram()
        invalid_container["containers"] = [
            {"id": "zone", "x": 0, "y": 0, "width": -20, "height": 100, "label": "Zone"}
        ]
        cases["invalid-container"] = invalid_container

        layout_not_object = base_diagram()
        layout_not_object["layout"] = []
        cases["layout-not-object"] = layout_not_object

        layout_bad_bool = base_diagram()
        layout_bad_bool["layout"] = {"auto": 1}
        cases["layout-bad-bool"] = layout_bad_bool

        layout_bad_gap = base_diagram()
        layout_bad_gap["layout"] = {"horizontal_gap": 0}
        cases["layout-bad-gap"] = layout_bad_gap

        layout_bad_direction = base_diagram()
        layout_bad_direction["layout"] = {"direction": "BT"}
        cases["layout-bad-direction"] = layout_bad_direction

        with tempfile.TemporaryDirectory() as temporary:
            for name, data in cases.items():
                with self.subTest(name=name):
                    base = Path(temporary) / name
                    result = self.run_renderer("architecture", data, base)
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("Raw input validation failed", result.stderr)
                    self.assertFalse(base.with_suffix(".svg").exists())
                    self.assertFalse(base.with_suffix(".json").exists())

    def test_invalid_center_port_is_not_overwritten_by_auto_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "center-port"
            data = base_diagram()
            data["layout"] = {"auto": True, "direction": "TB"}
            data["arrows"][0]["source_port"] = "center"
            result = self.run_renderer("architecture", data, base)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("source_port", result.stderr)
            self.assertIn("center", (base.parent / "center-port-input.json").read_text(encoding="utf-8"))
            self.assertFalse(base.with_suffix(".svg").exists())
            self.assertFalse(base.with_suffix(".json").exists())

    def test_blocking_parent_file_returns_stable_error_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "input.json"
            input_path.write_text(json.dumps(base_diagram()), encoding="utf-8")
            blocker = root / "not-a-directory"
            blocker.write_bytes(b"blocker")
            result = subprocess.run(
                [
                    sys.executable,
                    str(RENDERER),
                    "--type",
                    "architecture",
                    "--input",
                    str(input_path),
                    "--output",
                    str(blocker / "diagram"),
                    "--formats",
                    "svg,json",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(result.stderr.startswith("Error:"), result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertEqual(blocker.read_bytes(), b"blocker")

    def test_json_only_validation_does_not_claim_a_published_svg(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "json-only"
            result = self.run_renderer("architecture", base_diagram(), base, "json")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertNotIn("file", report["validation"])
            self.assertEqual(report["validation"]["scope"], "staged-svg-not-published")
            self.assertTrue(base.with_suffix(".json").exists())
            self.assertFalse(base.with_suffix(".svg").exists())

    def test_container_references_survive_auto_layout_and_drawio_export(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "container-layout"
            data = {
                "template_type": "architecture",
                "style": 1,
                "title": "Container layout",
                "containers": [
                    {
                        "id": "clinical-zone",
                        "kind": "section",
                        "x": 80,
                        "y": 120,
                        "width": 760,
                        "height": 360,
                        "label": "Clinical zone",
                    }
                ],
                "nodes": [
                    {"id": "order", "label": "Order entry", "container_id": "clinical-zone"},
                    {"id": "review", "label": "Pharmacy review", "container_id": "clinical-zone"},
                ],
                "arrows": [{"source": "order", "target": "review", "flow": "control"}],
            }
            result = self.run_renderer("architecture", data, base, "svg,json,drawio")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            normalized = json.loads(base.with_suffix(".json").read_text(encoding="utf-8"))
            for node in normalized["nodes"]:
                self.assertEqual(node["container_id"], "clinical-zone")
                self.assertGreaterEqual(node["x"], 80)
                self.assertGreaterEqual(node["y"], 120)
                self.assertLessEqual(node["x"] + node["width"], 840)
                self.assertLessEqual(node["y"] + node["height"], 480)
            ET.parse(base.with_suffix(".drawio"))

    def test_wrapper_failure_preserves_all_existing_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "diagram"
            svg_original = b"old-svg"
            json_original = b"old-json"
            base.with_suffix(".svg").write_bytes(svg_original)
            base.with_suffix(".json").write_bytes(json_original)
            invalid = base_diagram()
            invalid["arrows"] = [{"source": "source", "target": "missing"}]
            result = self.run_renderer("architecture", invalid, base)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(base.with_suffix(".svg").read_bytes(), svg_original)
            self.assertEqual(base.with_suffix(".json").read_bytes(), json_original)

    def test_semantic_diagram_types_normalize_to_explicit_geometry(self) -> None:
        cases: dict[str, tuple[dict[str, object], callable]] = {
            "flowchart": (
                {
                    "style": 1,
                    "steps": [
                        {"id": "start", "type": "start", "label": "Start"},
                        {"id": "decision", "type": "decision", "label": "Valid?"},
                        {"id": "end", "type": "end", "label": "End"},
                        {"id": "reject", "type": "end", "label": "Reject"},
                    ],
                    "flows": [
                        {"from": "start", "to": "decision"},
                        {"from": "decision", "to": "end", "label": "yes"},
                        {"from": "decision", "to": "reject", "label": "no"},
                    ],
                },
                lambda doc: self.assertTrue(
                    any(
                        node.get("kind") == "diamond" and node.get("semantic_type") == "decision"
                        for node in doc["nodes"]
                    )
                ),
            ),
            "sequence": (
                {
                    "style": 1,
                    "participants": [{"id": "client", "label": "Client"}, {"id": "api", "label": "API"}],
                    "messages": [
                        {"from": "client", "to": "api", "label": "call", "type": "async"},
                        {"from": "api", "to": "client", "label": "result", "type": "return"},
                    ],
                },
                lambda doc: self.assertTrue(any(arrow.get("semantic_type") == "lifeline" for arrow in doc["arrows"])),
            ),
            "state-machine": (
                {
                    "style": 1,
                    "states": [
                        {"id": "initial", "type": "initial", "label": "Initial"},
                        {"id": "active", "type": "state", "label": "Active"},
                        {"id": "final", "type": "final", "label": "Final"},
                    ],
                    "transitions": [{"from": "initial", "to": "active"}, {"from": "active", "to": "final"}],
                },
                lambda doc: self.assertEqual(
                    {node.get("semantic_type") for node in doc["nodes"]},
                    {"initial", "state", "final"},
                ),
            ),
            "er-diagram": (
                {
                    "style": 1,
                    "entities": [
                        {"id": "user", "label": "User", "attributes": [{"name": "id", "key": "PK", "type": "UUID"}]},
                        {"id": "order", "label": "Order", "attributes": [{"name": "user_id", "key": "FK", "type": "UUID"}]},
                    ],
                    "relationships": [
                        {"from": "user", "to": "order", "label": "places", "from_cardinality": "1", "to_cardinality": "0..*"}
                    ],
                },
                lambda doc: self.assertTrue(any(arrow.get("semantic_type") == "relationship" for arrow in doc["arrows"])),
            ),
        }
        with tempfile.TemporaryDirectory() as temporary:
            for template_type, (data, assertion) in cases.items():
                with self.subTest(template_type=template_type):
                    base = Path(temporary) / template_type
                    result = self.run_renderer(template_type, data, base)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    normalized = json.loads(base.with_suffix(".json").read_text(encoding="utf-8"))
                    self.assertTrue(normalized.get("nodes"))
                    assertion(normalized)

    def test_cjk_png_gate_detects_missing_fonts_before_conversion(self) -> None:
        spec = importlib.util.spec_from_file_location("render_diagram_test_module", RENDERER)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(module.shutil, "which", return_value=None), mock.patch.object(
            module.platform, "system", return_value="Windows"
        ), mock.patch.dict(module.os.environ, {"WINDIR": temporary}, clear=False):
            available, source = module._has_cjk_font("中文测试")
            self.assertFalse(available)
            self.assertEqual(source, "missing")

    def test_all_semantic_fixtures_publish_svg_json_and_drawio(self) -> None:
        diagram_types = (
            "architecture",
            "data-flow",
            "flowchart",
            "sequence",
            "state-machine",
            "er-diagram",
            "use-case",
            "timeline",
        )
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            for diagram_type in diagram_types:
                with self.subTest(diagram_type=diagram_type):
                    fixture = SKILL_ROOT / "fixtures" / f"semantic-{diagram_type}.json"
                    data = json.loads(fixture.read_text(encoding="utf-8"))
                    base = output_dir / diagram_type
                    result = self.run_renderer(diagram_type, data, base, "svg,json,drawio")
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertTrue(base.with_suffix(".svg").exists())
                    self.assertTrue(base.with_suffix(".drawio").exists())
                    ET.parse(base.with_suffix(".drawio"))
                    normalized = json.loads(base.with_suffix(".json").read_text(encoding="utf-8"))
                    self.assertEqual(normalized["template_type"], diagram_type)
                    for index, node in enumerate(normalized.get("nodes", [])):
                        self.assertGreater(node.get("width", 0), 0, f"nodes[{index}].width")
                        self.assertGreater(node.get("height", 0), 0, f"nodes[{index}].height")


if __name__ == "__main__":
    unittest.main()
