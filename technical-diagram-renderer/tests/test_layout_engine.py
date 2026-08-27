#!/usr/bin/env python3
"""Regression tests for the dependency-free generic layout engine."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from layout_engine import apply_auto_layout, estimate_text_width, wrap_text  # noqa: E402
from export_drawio import build_drawio_tree  # noqa: E402


def bounds(node):
    return (
        float(node["x"]),
        float(node["y"]),
        float(node["x"]) + float(node.get("width", 180)),
        float(node["y"]) + float(node.get("height", 76)),
    )


def separated(first, second, gap):
    a_left, a_top, a_right, a_bottom = bounds(first)
    b_left, b_top, b_right, b_bottom = bounds(second)
    return (
        a_right + gap <= b_left
        or b_right + gap <= a_left
        or a_bottom + gap <= b_top
        or b_bottom + gap <= a_top
    )


class TextHelpersTest(unittest.TestCase):
    def test_cjk_is_wider_than_same_length_latin(self):
        self.assertGreater(estimate_text_width("门诊系统", 18), estimate_text_width("abcd", 18))

    def test_mixed_text_wrap_is_deterministic_and_within_budget(self):
        text = "门诊医生工作站 Intelligent Coding Assistant"
        first = wrap_text(text, 126, 18)
        second = wrap_text(text, 126, 18)
        self.assertEqual(first, second)
        self.assertGreater(len(first.splitlines()), 1)
        for line in first.splitlines():
            self.assertLessEqual(estimate_text_width(line, 18), 126.01)

    def test_existing_newlines_are_retained(self):
        self.assertEqual(wrap_text("第一层\\nSecond", 300), "第一层\nSecond")


class AutoLayoutTest(unittest.TestCase):
    def test_does_not_mutate_input_and_preserves_existing_coordinates(self):
        source = {
            "nodes": [
                {"id": "a", "x": 30, "y": 120, "width": 140, "height": 64},
                {"id": "b", "x": 280, "y": 120, "width": 140, "height": 64},
            ],
            "arrows": [{"source": "a", "target": "b"}],
        }
        snapshot = copy.deepcopy(source)
        result = apply_auto_layout(source, "architecture")

        self.assertEqual(source, snapshot)
        self.assertEqual((result["nodes"][0]["x"], result["nodes"][0]["y"]), (30, 120))
        self.assertEqual((result["nodes"][1]["x"], result["nodes"][1]["y"]), (280, 120))
        self.assertFalse(result["_layout_stats"]["enabled"])
        self.assertEqual(result["_layout_stats"]["positioned_nodes"], 0)
        self.assertEqual(result["arrows"][0]["source_port"], "right")
        self.assertEqual(result["arrows"][0]["target_port"], "left")

    def test_complete_coordinates_receive_explicit_dimensions_for_drawio(self):
        long_label = "临床应用与专科协同服务中心"
        source = {
            "template_type": "architecture",
            "nodes": [
                {"id": "clinical", "kind": "rect", "x": 80, "y": 150, "label": long_label},
                {"id": "data", "kind": "cylinder", "x": 420, "y": 310, "label": "数据中心"},
            ],
            "arrows": [{"source": "clinical", "target": "data", "flow": "data"}],
        }
        snapshot = copy.deepcopy(source)
        result = apply_auto_layout(source, "architecture")

        self.assertEqual(source, snapshot)
        self.assertFalse(result["_layout_stats"]["enabled"])
        self.assertEqual(result["_layout_stats"]["positioned_nodes"], 0)
        self.assertEqual(result["_layout_stats"]["dimensions_assigned"], 4)
        self.assertEqual(result["nodes"][0]["label"], long_label)
        self.assertEqual(
            [(node["x"], node["y"]) for node in result["nodes"]],
            [(80, 150), (420, 310)],
        )
        for node in result["nodes"]:
            self.assertIsInstance(node["width"], (int, float))
            self.assertIsInstance(node["height"], (int, float))
            self.assertGreater(node["width"], 0)
            self.assertGreater(node["height"], 0)

        # The normalized architecture must satisfy the draw.io exporter's
        # explicit geometry contract without any additional fallback defaults.
        tree = build_drawio_tree(result)
        geometries = tree.getroot().findall(".//mxGeometry")
        vertex_geometries = [item for item in geometries if item.get("width") is not None]
        self.assertEqual(len(vertex_geometries), 2)
        self.assertTrue(all(float(item.get("width", "0")) > 0 for item in vertex_geometries))
        self.assertTrue(all(float(item.get("height", "0")) > 0 for item in vertex_geometries))

    def test_chain_uses_topological_layers_and_vertical_ports(self):
        source = {
            "width": 960,
            "height": 540,
            "title": "Clinical Coding",
            "nodes": [
                {"id": "input", "label": "病历输入"},
                {"id": "reason", "label": "编码推理"},
                {"id": "output", "label": "ICD-11建议"},
            ],
            "arrows": [
                {"source": "input", "target": "reason"},
                {"source": "reason", "target": "output"},
            ],
        }
        result = apply_auto_layout(source, "architecture")
        nodes = {node["id"]: node for node in result["nodes"]}

        self.assertLess(nodes["input"]["y"], nodes["reason"]["y"])
        self.assertLess(nodes["reason"]["y"], nodes["output"]["y"])
        self.assertEqual(result["_layout_stats"]["layers"], 3)
        self.assertEqual(result["_layout_stats"]["overlap_warnings"], 0)
        for arrow in result["arrows"]:
            self.assertEqual(arrow["source_port"], "bottom")
            self.assertEqual(arrow["target_port"], "top")

    def test_cycle_has_stable_fallback(self):
        source = {
            "layout": {"auto": True},
            "nodes": [
                {"id": "a", "x": 700, "y": 400, "label": "A"},
                {"id": "b", "x": 20, "y": 20, "label": "B"},
                {"id": "c", "x": 300, "y": 30, "label": "C"},
            ],
            "arrows": [
                {"source": "a", "target": "b"},
                {"source": "b", "target": "c"},
                {"source": "c", "target": "a"},
            ],
        }
        first = apply_auto_layout(source, "flowchart")
        second = apply_auto_layout(source, "flowchart")

        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        self.assertTrue(first["_layout_stats"]["cycle_fallback"])
        self.assertEqual(first["_layout_stats"]["cyclic_components"], 1)
        self.assertEqual(len({node["y"] for node in first["nodes"]}), 1)
        for left_index, left in enumerate(first["nodes"]):
            for right in first["nodes"][left_index + 1 :]:
                self.assertTrue(separated(left, right, first["_layout_stats"]["minimum_gap"]))

    def test_partial_coordinate_is_preserved(self):
        source = {
            "nodes": [
                {"id": "fixed", "x": 80, "y": 130, "width": 160, "height": 64},
                {"id": "partial", "x": 410, "label": "Only Y is automatic"},
            ],
            "arrows": [{"source": "fixed", "target": "partial"}],
        }
        result = apply_auto_layout(source, "architecture")
        partial = result["nodes"][1]

        self.assertEqual(partial["x"], 410)
        self.assertIn("y", partial)
        self.assertEqual(result["_layout_stats"]["partial_axes_preserved"], 1)

    def test_fixed_obstacle_does_not_reverse_automatic_layer_order(self):
        source = {
            "nodes": [
                {"id": "obstacle", "x": 390, "y": 105, "width": 180, "height": 180},
                {"id": "source", "label": "Source"},
                {"id": "target", "label": "Target"},
            ],
            "arrows": [{"source": "source", "target": "target"}],
        }
        result = apply_auto_layout(source, "architecture")
        nodes = {node["id"]: node for node in result["nodes"]}

        self.assertLess(
            float(nodes["source"]["y"]) + float(nodes["source"]["height"]),
            float(nodes["target"]["y"]),
        )

    def test_assigned_container_region_is_respected_when_capacity_is_sufficient(self):
        source = {
            "width": 1000,
            "height": 650,
            "containers": [
                {"id": "clinical", "x": 80, "y": 150, "width": 840, "height": 360, "label": "临床层"}
            ],
            "nodes": [
                {"id": "a", "container": "clinical", "label": "医生站"},
                {"id": "b", "container": "clinical", "label": "护士站"},
            ],
            "arrows": [{"source": "a", "target": "b"}],
        }
        result = apply_auto_layout(source, "architecture")
        container = result["containers"][0]
        left = container["x"]
        top = container["y"]
        right = left + container["width"]
        bottom = top + container["height"]
        for node in result["nodes"]:
            node_left, node_top, node_right, node_bottom = bounds(node)
            self.assertGreater(node_left, left)
            self.assertGreater(node_top, top)
            self.assertLess(node_right, right)
            self.assertLess(node_bottom, bottom)
        self.assertEqual(result["_layout_stats"]["container_overflow"], 0)

    def test_stale_route_hints_are_removed_only_for_moved_endpoints(self):
        source = {
            "nodes": [
                {"id": "a", "x": 40, "y": 130},
                {"id": "b", "label": "Auto"},
                {"id": "c", "x": 700, "y": 130},
            ],
            "arrows": [
                {
                    "source": "a",
                    "target": "b",
                    "route_points": [[200, 200]],
                    "corridor_x": [220],
                },
                {
                    "source": "a",
                    "target": "c",
                    "route_points": [[300, 100]],
                },
            ],
        }
        result = apply_auto_layout(source, "architecture")

        self.assertNotIn("route_points", result["arrows"][0])
        self.assertNotIn("corridor_x", result["arrows"][0])
        self.assertIn("route_points", result["arrows"][1])
        self.assertEqual(result["_layout_stats"]["route_hints_removed"], 2)

    def test_widescreen_expansion_preserves_aspect_ratio(self):
        nodes = [{"id": f"n{index}", "label": f"Node {index}"} for index in range(9)]
        arrows = [
            {"source": f"n{index}", "target": f"n{index + 1}"} for index in range(len(nodes) - 1)
        ]
        result = apply_auto_layout(
            {"width": 960, "height": 540, "nodes": nodes, "arrows": arrows}, "architecture"
        )
        final_width, final_height = result["_layout_stats"]["canvas"]["final"]

        self.assertTrue(result["_layout_stats"]["canvas"]["expanded"])
        self.assertAlmostEqual(final_width / final_height, 16 / 9, places=2)


if __name__ == "__main__":
    unittest.main()
