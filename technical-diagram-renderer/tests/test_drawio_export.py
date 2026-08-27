from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import export_drawio  # noqa: E402


def node(node_id: str, kind: str, x: int) -> dict:
    return {
        "id": node_id,
        "kind": kind,
        "x": x,
        "y": 100,
        "width": 120,
        "height": 70,
        "label": node_id,
    }


class DrawioExportTests(unittest.TestCase):
    def test_builds_parseable_uncompressed_mxgraph(self) -> None:
        document = {
            "title": "API & data flow",
            "containers": [
                {
                    "id": "boundary",
                    "kind": "container",
                    "x": 10,
                    "y": 50,
                    "width": 650,
                    "height": 250,
                    "label": "Trust boundary",
                }
            ],
            "nodes": [node("client", "rect", 40), node("decision", "diamond", 300)],
            "arrows": [
                {
                    "id": "request",
                    "source": "client",
                    "target": "decision",
                    "flow": "data",
                    "label": "request",
                    "source_port": "right",
                    "target_port": "left",
                    "route_points": [[220, 135], {"x": 260, "y": 135}],
                }
            ],
        }
        tree = export_drawio.build_drawio_tree(document)
        payload = ET.tostring(tree.getroot(), encoding="utf-8")
        root = ET.fromstring(payload)

        self.assertEqual(root.tag, "mxfile")
        self.assertEqual(root.get("compressed"), "false")
        diagram = root.find("diagram")
        self.assertIsNotNone(diagram)
        self.assertIsNotNone(diagram.find("mxGraphModel"))
        self.assertFalse(diagram.text and diagram.text.strip())

        cells = root.findall(".//mxCell")
        cell_ids = [cell.get("id") for cell in cells]
        self.assertEqual(len(cell_ids), len(set(cell_ids)))
        vertices = {cell.get("id") for cell in cells if cell.get("vertex") == "1"}
        edge = next(cell for cell in cells if cell.get("edge") == "1")
        self.assertIn(edge.get("source"), vertices)
        self.assertIn(edge.get("target"), vertices)
        self.assertIn("exitX=1", edge.get("style", ""))
        self.assertIn("entryX=0", edge.get("style", ""))
        self.assertEqual(len(edge.findall("./mxGeometry/Array/mxPoint")), 2)

    def test_elementtree_keeps_injection_as_plain_text(self) -> None:
        attack = '\"/><script>alert(1)</script><mxCell value=\"'
        document = {
            "title": attack,
            "nodes": [
                {
                    "id": "node&\"<1>",
                    "kind": "rect",
                    "x": 10,
                    "y": 20,
                    "width": 100,
                    "height": 60,
                    "label": attack,
                }
            ],
            "arrows": [],
        }
        payload = ET.tostring(export_drawio.build_drawio_tree(document).getroot(), encoding="utf-8")
        root = ET.fromstring(payload)
        self.assertEqual(root.findall(".//script"), [])
        cell = next(item for item in root.findall(".//mxCell") if item.get("vertex") == "1")
        self.assertEqual(cell.get("value"), attack)
        self.assertEqual(cell.get("data-id"), "node&\"<1>")
        self.assertIn("html=0", cell.get("style", ""))

    def test_required_node_kind_styles_are_mapped(self) -> None:
        kinds = ["rect", "diamond", "ellipse", "cylinder", "actor", "entity", "state"]
        document = {
            "nodes": [node(kind, kind, index * 150) for index, kind in enumerate(kinds)],
            "arrows": [],
        }
        root = export_drawio.build_drawio_tree(document).getroot()
        styles = {
            cell.get("data-id"): cell.get("style", "")
            for cell in root.findall(".//mxCell")
            if cell.get("vertex") == "1"
        }
        expected_tokens = {
            "rect": "rounded=0",
            "diamond": "shape=rhombus",
            "ellipse": "ellipse",
            "cylinder": "shape=cylinder3",
            "actor": "shape=umlActor",
            "entity": "shape=swimlane",
            "state": "rounded=1",
        }
        for kind, token in expected_tokens.items():
            with self.subTest(kind=kind):
                self.assertIn(token, styles[kind])
                self.assertIn("html=0", styles[kind])

    def test_semantic_node_kinds_degrade_to_safe_base_shapes(self) -> None:
        aliases = {
            "double_rect": "rounded=0",
            "document": "rounded=0",
            "folder": "rounded=0",
            "terminal": "rounded=0",
            "hexagon": "shape=rhombus",
            "circle_cluster": "ellipse",
            "user_avatar": "shape=umlActor",
            "bot": "rounded=0",
            "speech": "rounded=0",
            "icon_box": "rounded=0",
            "initial": "ellipse",
            "final": "ellipse",
            "terminator": "ellipse",
            "process": "rounded=0",
            "participant": "rounded=0",
            "data-store": "shape=cylinder3",
            "use-case": "ellipse",
            "timeline-event": "rounded=0",
            "milestone": "ellipse",
        }
        document = {
            "nodes": [
                node(kind, kind, index * 150) for index, kind in enumerate(aliases)
            ],
            "arrows": [],
        }
        root = export_drawio.build_drawio_tree(document).getroot()
        styles = {
            cell.get("data-id"): cell.get("style", "")
            for cell in root.findall(".//mxCell")
            if cell.get("vertex") == "1"
        }
        for kind, token in aliases.items():
            with self.subTest(kind=kind):
                self.assertIn(token, styles[kind])
                self.assertIn("html=0", styles[kind])

    def test_duplicate_ids_fail(self) -> None:
        document = {
            "containers": [
                {"id": "same", "x": 0, "y": 0, "width": 400, "height": 300}
            ],
            "nodes": [node("same", "rect", 20)],
            "arrows": [],
        }
        with self.assertRaisesRegex(export_drawio.DrawioExportError, "duplicates id"):
            export_drawio.build_drawio_tree(document)

    def test_dangling_edge_fails(self) -> None:
        document = {
            "nodes": [node("known", "rect", 20)],
            "arrows": [{"source": "known", "target": "missing"}],
        }
        with self.assertRaisesRegex(export_drawio.DrawioExportError, "unknown id 'missing'"):
            export_drawio.build_drawio_tree(document)

    def test_complete_coordinate_edge_uses_explicit_mxgeometry_points(self) -> None:
        document = {
            "nodes": [],
            "arrows": [
                {
                    "id": "lifeline",
                    "x1": 120,
                    "y1": 180,
                    "x2": 120,
                    "y2": 520,
                    "flow": "neutral",
                    "marker_end": False,
                    "route_points": [[150, 260], {"x": 150, "y": 420}],
                }
            ],
        }
        root = export_drawio.build_drawio_tree(document).getroot()
        edge = next(cell for cell in root.findall(".//mxCell") if cell.get("edge") == "1")
        self.assertIsNone(edge.get("source"))
        self.assertIsNone(edge.get("target"))
        geometry = edge.find("mxGeometry")
        self.assertIsNotNone(geometry)
        source_point = geometry.find("mxPoint[@as='sourcePoint']")
        target_point = geometry.find("mxPoint[@as='targetPoint']")
        self.assertEqual((source_point.get("x"), source_point.get("y")), ("120", "180"))
        self.assertEqual((target_point.get("x"), target_point.get("y")), ("120", "520"))
        self.assertEqual(len(geometry.findall("./Array/mxPoint")), 2)
        self.assertIn("endArrow=none", edge.get("style", ""))

    def test_partial_or_ambiguous_edge_endpoints_fail(self) -> None:
        base_nodes = [node("a", "rect", 0), node("b", "rect", 200)]
        invalid_arrows = [
            {"source": "a"},
            {"x1": 10, "y1": 20, "x2": 30},
            {"source": "a", "target": "b", "x1": 10, "y1": 20, "x2": 30, "y2": 40},
            {"x1": 10, "y1": 20, "x2": 30, "y2": 40, "source_port": "right"},
            {"x1": float("nan"), "y1": 20, "x2": 30, "y2": 40},
            {},
        ]
        for arrow in invalid_arrows:
            with self.subTest(arrow=arrow):
                with self.assertRaises(export_drawio.DrawioExportError):
                    export_drawio.build_drawio_tree({"nodes": base_nodes, "arrows": [arrow]})

    def test_unknown_kind_relationship_and_port_fail(self) -> None:
        cases = [
            {
                "nodes": [node("a", "mystery-shape", 0)],
                "arrows": [],
            },
            {
                "nodes": [node("a", "rect", 0), node("b", "rect", 200)],
                "arrows": [{"source": "a", "target": "b", "flow": "teleport"}],
            },
            {
                "nodes": [node("a", "rect", 0), node("b", "rect", 200)],
                "arrows": [
                    {"source": "a", "target": "b", "source_port": "somewhere"}
                ],
            },
        ]
        for document in cases:
            with self.subTest(document=document):
                with self.assertRaises(export_drawio.DrawioExportError):
                    export_drawio.build_drawio_tree(document)

    def test_non_finite_geometry_and_xml_control_character_fail(self) -> None:
        bad_number = {"nodes": [node("a", "rect", float("nan"))], "arrows": []}
        bad_text_node = node("a", "rect", 0)
        bad_text_node["label"] = "bad\x00text"
        bad_text = {"nodes": [bad_text_node], "arrows": []}
        for document in (bad_number, bad_text):
            with self.subTest(document=document):
                with self.assertRaises(export_drawio.DrawioExportError):
                    export_drawio.build_drawio_tree(document)

    def test_cli_success_and_failure_preserves_existing_output(self) -> None:
        script = SCRIPTS_DIR / "export_drawio.py"
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            input_path = temporary / "input.json"
            output_path = temporary / "output.drawio"

            valid = {
                "nodes": [node("a", "rect", 0), node("b", "ellipse", 220)],
                "arrows": [{"source": "a", "target": "b"}],
            }
            input_path.write_text(json.dumps(valid), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(script), str(input_path), str(output_path)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            parsed = ET.parse(str(output_path)).getroot()
            self.assertEqual(parsed.tag, "mxfile")

            sentinel = b"known-good-existing-output"
            output_path.write_bytes(sentinel)
            invalid = {
                "nodes": [node("a", "rect", 0)],
                "arrows": [{"source": "a", "target": "missing"}],
            }
            input_path.write_text(json.dumps(invalid), encoding="utf-8")
            failed = subprocess.run(
                [sys.executable, str(script), str(input_path), str(output_path)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("unknown id", failed.stderr)
            self.assertEqual(output_path.read_bytes(), sentinel)

    def test_sequence_fixture_renders_svg_json_and_drawio_with_matching_edges(self) -> None:
        fixture = SKILL_ROOT / "fixtures" / "semantic-sequence.json"
        renderer = SCRIPTS_DIR / "render-diagram.py"
        with tempfile.TemporaryDirectory() as temporary_directory:
            base = Path(temporary_directory) / "sequence"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(renderer),
                    "--type",
                    "sequence",
                    "--input",
                    str(fixture),
                    "--output",
                    str(base),
                    "--formats",
                    "svg,json,drawio",
                    "--validate",
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            svg_root = ET.parse(str(base.with_suffix(".svg"))).getroot()
            normalized = json.loads(base.with_suffix(".json").read_text(encoding="utf-8"))
            drawio_root = ET.parse(str(base.with_suffix(".drawio"))).getroot()
            expected_edges = len(normalized["arrows"])
            drawio_edges = drawio_root.findall(".//mxCell[@edge='1']")
            svg_edges = [
                child
                for child in list(svg_root)
                if child.tag.rsplit("}", 1)[-1] == "path" and child.get("fill") == "none"
            ]
            self.assertEqual(len(drawio_edges), expected_edges)
            self.assertEqual(len(svg_edges), expected_edges)


if __name__ == "__main__":
    unittest.main()
