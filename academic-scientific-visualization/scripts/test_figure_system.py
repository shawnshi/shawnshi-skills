#!/usr/bin/env python3
"""Regression and negative tests for the scientific-figure runtime."""

from __future__ import annotations

import json
import hashlib
import os
import sys
import tempfile
import textwrap
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", tempfile.mkdtemp(prefix="academic-sciviz-test-mpl-"))

import matplotlib as mpl
import matplotlib.pyplot as plt
from PIL import Image

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from figure_export import (
    CheckStatus,
    ExportValidationError,
    export_publication_figure,
    inspect_artifact,
    verify_artifact,
    verify_font_embedding,
    verify_profile,
)
from font_preflight import inspect_font
from figure_pipeline import run_pipeline, validate_job
from statistics_gate import derive_significance_label, validate_statistics
from style_presets import (
    create_style_template,
    get_profile,
    get_style,
    publication_style,
)


def make_figure(width_mm: float = 89.0, height_mm: float = 50.0):
    fig, ax = plt.subplots(figsize=(width_mm / 25.4, height_mm / 25.4))
    ax.plot([0, 1, 2], [0, 1, 0], marker="o")
    ax.set_xlabel("Time (h)")
    ax.set_ylabel("Response (a.u.)")
    return fig


def _sha256_for_test(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def valid_comparison() -> dict:
    return {
        "comparison_id": "control_vs_treatment",
        "groups": ["Control", "Treatment"],
        "analysis_unit": "animal",
        "test": "two-sided Welch t-test",
        "source": "analysis/results.json",
        "p_value": 0.001,
        "adjusted_p_value": 0.051,
        "family": {"id": "primary", "size": 2},
        "correction": "Holm",
        "effect_size": {"name": "mean difference", "value": 1.2},
        "confidence_interval": {"level": 0.95, "lower": 0.3, "upper": 2.1},
    }


def valid_job() -> dict:
    return {
        "schema_version": 1,
        "mode": "create",
        "question": "Compare response over time",
        "source": {
            "kind": "raw_data",
            "sensitivity": "public",
            "data_path": "data.csv",
            "package_data": True,
            "package_data_authorized": True,
        },
        "target": {
            "profile": "generic-draft",
            "submission_stage": "draft",
            "figure_type": "combination",
            "column": "single",
            "formats": ["png"],
            "font": {"family": "DejaVu Sans"},
            "labels": ["Time (h)", "Response (a.u.)", "Control", "Treatment"],
        },
        "analysis": {
            "analysis_unit": "animal",
            "sample_size": {"Control": 10, "Treatment": 10},
            "missing_data": "none",
            "transformation": "none",
            "uncertainty": "95% CI",
            "variables": [{"name": "time", "unit": "h"}],
            "annotations_requested": False,
        },
        "delivery": {"base_name": "figure1"},
        "caption": "Figure 1. Response over time.",
    }


class StyleTests(unittest.TestCase):
    def test_unknown_style_is_rejected(self):
        with self.assertRaises(ValueError):
            get_style("not-a-style")

    def test_context_restores_global_state(self):
        original = mpl.rcParams["font.size"]
        with publication_style("presentation"):
            self.assertEqual(mpl.rcParams["font.size"], 14)
        self.assertEqual(mpl.rcParams["font.size"], original)

    def test_style_template_serializes_cycler(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = create_style_template(str(Path(tmp) / "style.mplstyle"))
            self.assertTrue(output.is_file())
            self.assertIn("axes.prop_cycle", output.read_text(encoding="utf-8"))

    def test_invalid_column_does_not_fall_through(self):
        from style_presets import configure_for_journal

        with self.assertRaises(ValueError):
            configure_for_journal("nature", "wide")


class StatisticsTests(unittest.TestCase):
    def test_literal_stars_are_rejected(self):
        comparison = valid_comparison()
        comparison["stars"] = "***"
        payload = {"schema_version": 1, "annotations_requested": True, "comparisons": [comparison]}
        self.assertEqual(validate_statistics(payload)["status"], "FAIL")

    def test_multiplicity_requires_adjusted_p(self):
        comparison = valid_comparison()
        comparison.pop("adjusted_p_value")
        payload = {"schema_version": 1, "annotations_requested": True, "comparisons": [comparison]}
        self.assertEqual(validate_statistics(payload)["status"], "FAIL")

    def test_label_uses_adjusted_value_and_boundary_is_stable(self):
        comparison = valid_comparison()
        self.assertEqual(derive_significance_label(comparison, "stars"), "ns")
        comparison["adjusted_p_value"] = 0.049
        self.assertEqual(derive_significance_label(comparison, "stars"), "*")
        comparison["adjusted_p_value"] = 0.05
        self.assertEqual(derive_significance_label(comparison, "stars"), "ns")

    def test_nan_p_value_is_rejected(self):
        comparison = valid_comparison()
        comparison["p_value"] = float("nan")
        payload = {"schema_version": 1, "annotations_requested": True, "comparisons": [comparison]}
        self.assertEqual(validate_statistics(payload)["status"], "FAIL")


class ExportTests(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def test_formats_string_is_rejected(self):
        fig = make_figure()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(TypeError):
                export_publication_figure(fig, Path(tmp) / "figure", "pdf")

    def test_missing_parent_never_falls_back_to_cwd(self):
        fig = make_figure()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "missing" / "figure"
            accidental = Path.cwd() / "figure.pdf"
            accidental.unlink(missing_ok=True)
            with self.assertRaises(FileNotFoundError):
                export_publication_figure(fig, target, ("pdf",))
            self.assertFalse(accidental.exists())

    def test_pdf_uses_finished_physical_size_and_embedded_fonts(self):
        fig = make_figure(89.0, 50.0)
        with tempfile.TemporaryDirectory() as tmp:
            report = export_publication_figure(
                fig,
                Path(tmp) / "nature_figure",
                ("pdf",),
                1000,
                profile_name="nature-final",
                figure_type="line_art",
                column="single",
            )
            self.assertEqual(report.overall_status, CheckStatus.PASS)
            metadata = inspect_artifact(report.paths[0])
            self.assertAlmostEqual(metadata["width_mm"], 89.0, delta=0.6)
            font_checks = [check for check in report.artifacts[0].checks if check.check_id == "pdf.font_embedding"]
            self.assertEqual(font_checks[0].status, CheckStatus.PASS)
            type_checks = [check for check in report.artifacts[0].checks if check.check_id == "pdf.font_type"]
            self.assertEqual(type_checks[0].status, CheckStatus.PASS)
            self.assertNotIn("Type 3", type_checks[0].observed)

    def test_tight_crop_fails_and_leaves_no_formal_artifact(self):
        fig = make_figure()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "tight"
            with self.assertRaises(ExportValidationError):
                export_publication_figure(fig, target, ("pdf",), bbox_inches="tight")
            self.assertFalse(target.with_suffix(".pdf").exists())

    def test_failed_overwrite_preserves_but_does_not_commit_old_artifact(self):
        fig = make_figure()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "figure"
            first = export_publication_figure(fig, target, ("png",), 300)
            original_hash = _sha256_for_test(target.with_suffix(".png"))
            self.assertTrue(first.artifacts_committed)
            report = export_publication_figure(
                fig,
                target,
                ("png",),
                300,
                bbox_inches="tight",
                overwrite=True,
                strict=False,
            )
            self.assertEqual(report.overall_status, CheckStatus.FAIL)
            self.assertFalse(report.artifacts_committed)
            self.assertEqual(_sha256_for_test(target.with_suffix(".png")), original_hash)

    def test_plos_tiff_is_rgb_lzw_no_alpha_with_requested_ppi(self):
        fig = make_figure(89.0, 50.0)
        with tempfile.TemporaryDirectory() as tmp:
            report = export_publication_figure(
                fig,
                Path(tmp) / "plos_figure",
                ("tiff",),
                600,
                profile_name="plos-one-final",
                figure_type="combination",
            )
            self.assertEqual(report.overall_status, CheckStatus.PASS)
            with Image.open(report.paths[0]) as image:
                self.assertEqual(image.mode, "RGB")
                self.assertNotIn("A", image.getbands())
                self.assertEqual(image.info.get("compression"), "tiff_lzw")
                self.assertGreaterEqual(min(image.info["dpi"]), 599)

    def test_atomic_batch_removes_first_temp_when_second_save_fails(self):
        fig = make_figure()
        original = fig.savefig
        calls = 0

        def flaky(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("synthetic second-format failure")
            return original(*args, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(fig, "savefig", side_effect=flaky):
                with self.assertRaises(RuntimeError):
                    export_publication_figure(fig, Path(tmp) / "batch", ("png", "pdf"))
            self.assertFalse((Path(tmp) / "batch.png").exists())
            self.assertFalse((Path(tmp) / "batch.pdf").exists())
            self.assertEqual(list(Path(tmp).glob(".*.tmp.*")), [])

    def test_stale_profile_is_not_checked(self):
        profile = get_profile("nature")
        profile["verification"]["review_due_on"] = (date.today() - timedelta(days=1)).isoformat()
        statuses = {check.check_id: check.status for check in verify_profile(profile)}
        self.assertEqual(statuses["profile.freshness"], CheckStatus.NOT_CHECKED)

    def test_missing_pdffonts_is_not_checked_not_true(self):
        fig = make_figure()
        with tempfile.TemporaryDirectory() as tmp:
            report = export_publication_figure(fig, Path(tmp) / "font_check", ("pdf",))
            with mock.patch("figure_export.shutil.which", return_value=None):
                self.assertIsNone(verify_font_embedding(report.paths[0]))

    def test_noncompliant_tiff_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.tiff"
            Image.new("RGBA", (300, 200), (255, 0, 0, 128)).save(
                path, format="TIFF", dpi=(72, 72), compression="raw"
            )
            report = verify_artifact(
                path,
                profile=get_profile("plos"),
                figure_type="combination",
            )
            failed = {check.check_id for check in report.checks if check.status == CheckStatus.FAIL}
            self.assertTrue({"raster.ppi", "raster.alpha", "tiff.compression"} <= failed)

    def test_user_constraints_can_be_stricter_than_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gray.tiff"
            Image.new("L", (600, 600), 128).save(
                path, format="TIFF", dpi=(600, 600), compression="tiff_lzw"
            )
            report = verify_artifact(
                path,
                profile=get_profile("plos"),
                figure_type="combination",
                artifact_constraints={"color_mode": "RGB", "exact_ppi": 600, "single_frame": True},
            )
            checks = {check.check_id: check.status for check in report.checks}
            self.assertEqual(checks["raster.color_mode"], CheckStatus.PASS)
            self.assertEqual(checks["user.color_mode"], CheckStatus.FAIL)
            self.assertEqual(checks["user.exact_ppi"], CheckStatus.PASS)
            self.assertEqual(checks["user.single_frame"], CheckStatus.PASS)

    def test_plos_raster_above_maximum_ppi_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "oversampled.tiff"
            Image.new("RGB", (4200, 2400), "white").save(
                path, format="TIFF", dpi=(1200, 1200), compression="tiff_lzw"
            )
            report = verify_artifact(path, profile=get_profile("plos"), figure_type="combination")
            checks = {check.check_id: check.status for check in report.checks}
            self.assertEqual(checks["raster.ppi"], CheckStatus.PASS)
            self.assertEqual(checks["raster.max_ppi"], CheckStatus.FAIL)

    def test_profile_file_limit_uses_decimal_megabytes(self):
        from figure_export import verify_artifact

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "large.tiff"
            Image.new("RGB", (100, 100), "white").save(
                path, format="TIFF", dpi=(600, 600), compression="tiff_lzw"
            )
            with path.open("ab") as handle:
                handle.truncate(10_000_001)
            report = verify_artifact(
                path,
                profile=get_profile("plos"),
                figure_type="combination",
            )
            size_check = [check for check in report.checks if check.check_id == "profile.max_file_size"][0]
            self.assertEqual(size_check.status, CheckStatus.FAIL)

    def test_multipage_tiff_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "multipage.tiff"
            first = Image.new("RGB", (600, 600), "white")
            second = Image.new("RGB", (600, 600), "black")
            first.save(
                path,
                format="TIFF",
                save_all=True,
                append_images=[second],
                dpi=(600, 600),
                compression="tiff_lzw",
            )
            report = verify_artifact(path, profile=get_profile("plos"), figure_type="combination")
            frames = [check for check in report.checks if check.check_id == "tiff.frames"][0]
            self.assertEqual(frames.status, CheckStatus.FAIL)


class FontAndContractTests(unittest.TestCase):
    def test_missing_cjk_glyph_fails(self):
        checks = inspect_font(family="DejaVu Sans", texts=["中文"])
        coverage = [check for check in checks if check.check_id == "font.glyph_coverage"][0]
        self.assertEqual(coverage.status, CheckStatus.FAIL)

    def test_sensitive_source_requires_deidentification(self):
        job = valid_job()
        job["source"] = {"kind": "raw_data", "sensitivity": "sensitive", "external_sharing": False}
        self.assertEqual(validate_job(job)["status"], "FAIL")

    def test_sensitive_execution_path_is_scanned_for_identifiers(self):
        job = valid_job()
        job["source"].update({
            "sensitivity": "sensitive",
            "deidentified": True,
            "external_sharing": False,
            "package_data": False,
            "privacy_review": {"status": "PASS", "reviewer": "privacy-officer"},
        })
        report = validate_job(job, execution_paths=["/tmp/MRN_ZXCV4826_job.json"])
        identifier_check = next(
            check for check in report["checks"]
            if check["check_id"] == "job.source.identifier_value_scan"
        )
        self.assertEqual(identifier_check["status"], "FAIL")
        self.assertEqual(identifier_check["observed"][0]["location"], "job.execution_paths[0]")

    def test_evidence_image_rejects_generative_editing(self):
        job = valid_job()
        job["source"].update({
            "evidence_image": True,
            "original_read_only": True,
            "generative_editing": True,
            "transformations": [],
        })
        self.assertEqual(validate_job(job)["status"], "FAIL")

    def test_unknown_profile_never_falls_back(self):
        job = valid_job()
        job["target"]["profile"] = "unknown-journal"
        self.assertEqual(validate_job(job)["status"], "FAIL")

    def test_minimal_manuscript_set_is_rejected(self):
        job = valid_job()
        job["mode"] = "manuscript_set"
        job["figures"] = [{"id": "figure1"}, {"id": "figure2"}]
        self.assertEqual(validate_job(job)["status"], "FAIL")


class PipelineIntegrationTests(unittest.TestCase):
    def test_visual_audit_manifest_binds_exact_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "figure.tiff"
            Image.new("RGB", (2100, 1200), "white").save(
                artifact,
                format="TIFF",
                dpi=(600, 600),
                compression="tiff_lzw",
            )
            job = {
                "schema_version": 1,
                "mode": "visual_audit",
                "question": "Verify the finished PLOS ONE figure",
                "source": {
                    "kind": "existing_figure",
                    "sensitivity": "public",
                    "figure_path": "figure.tiff",
                },
                "target": {
                    "profile": "plos-one-final",
                    "submission_stage": "final",
                    "figure_type": "combination",
                    "font": {"family": "DejaVu Sans"},
                    "labels": [],
                    "requirements": {
                        "color_mode": "RGB",
                        "exact_ppi": 600,
                        "single_frame": True,
                    },
                },
                "analysis": {"annotations_requested": False},
                "delivery": {"base_name": "figure_audit"},
                "caption": "Audited PLOS ONE figure.",
            }
            job_path = root / "audit.json"
            job_path.write_text(json.dumps(job), encoding="utf-8")
            bundle = root / "bundle"
            preview = run_pipeline(job_path=job_path, output_dir=bundle, stage="preview")
            self.assertEqual(preview["status"], "PASS")
            for relative in (
                "preview/figure_audit.png",
                "preview/figure_audit.grayscale.png",
                "preview/figure_audit.protanopia.png",
            ):
                self.assertTrue((bundle / relative).is_file(), relative)
            unreviewed = run_pipeline(job_path=job_path, output_dir=bundle, stage="final")
            self.assertEqual(unreviewed["status"], "NOT_CHECKED")
            self.assertEqual(unreviewed["verification_level"], "draft")
            review = {
                "schema_version": 1,
                "reviewer": "test-reviewer",
                "input_hash": preview["input_hash"],
                "checks": {name: "PASS" for name in (
                    "crop",
                    "overlap",
                    "legibility",
                    "glyphs",
                    "accessibility",
                    "data_alignment",
                )},
            }
            review_path = root / "review.json"
            review_path.write_text(json.dumps(review), encoding="utf-8")
            final = run_pipeline(
                job_path=job_path,
                output_dir=bundle,
                stage="final",
                visual_review_path=review_path,
            )
            self.assertEqual(final["verification_level"], "journal_verified")
            manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["audited_artifacts"]), 1)
            self.assertEqual(manifest["audited_artifacts"][0]["format"], "tiff")
            self.assertEqual(manifest["audited_artifacts"][0]["sha256"], _sha256_for_test(artifact))

    def test_preview_pipeline_creates_standard_bundle_and_cache(self):
        job = valid_job()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.csv").write_text("time,response\n0,0\n1,1\n2,0\n", encoding="utf-8")
            job_path = root / "job.json"
            job_path.write_text(json.dumps(job), encoding="utf-8")
            plot_script = root / "plot.py"
            plot_script.write_text(textwrap.dedent(
                """
                import matplotlib.pyplot as plt

                def build_figure(job):
                    fig, ax = plt.subplots(figsize=(89 / 25.4, 50 / 25.4))
                    ax.plot([0, 1, 2], [0, 1, 0], marker="o", label="Control")
                    ax.set_xlabel("Time (h)")
                    ax.set_ylabel("Response (a.u.)")
                    ax.legend()
                    return fig
                """
            ), encoding="utf-8")
            output = root / "bundle"
            result = run_pipeline(
                job_path=job_path,
                output_dir=output,
                stage="preview",
                plot_script=plot_script,
            )
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["verification_level"], "draft")
            for relative in (
                "preview/figure1.png",
                "preview/figure1.grayscale.png",
                "preview/figure1.protanopia.png",
                "qa/figure_qa.json",
                "qa/preflight.json",
                "source/job.public.json",
                "captions/figure1.md",
                "manifest.json",
            ):
                self.assertTrue((output / relative).is_file(), relative)
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["source_data_packaged"])
            self.assertEqual(manifest["reproducibility_level"], "self_contained_inputs")
            public_job = json.loads((output / "source/job.public.json").read_text(encoding="utf-8"))
            packaged_data = output / "source" / public_job["source"]["data_path"]
            self.assertTrue(packaged_data.is_file())
            cached = run_pipeline(
                job_path=job_path,
                output_dir=output,
                stage="preview",
                plot_script=plot_script,
                changed_only=True,
            )
            self.assertTrue(cached["cached"])
            plot_script.write_text(plot_script.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
            changed = run_pipeline(
                job_path=job_path,
                output_dir=output,
                stage="preview",
                plot_script=plot_script,
                changed_only=True,
            )
            self.assertFalse(changed.get("cached", False))
            rerun = run_pipeline(
                job_path=output / "source/job.public.json",
                output_dir=root / "rerun",
                stage="preview",
                plot_script=output / "source/plot.py",
            )
            self.assertEqual(rerun["status"], "PASS")
            self.assertEqual(rerun["input_hash"], changed["input_hash"])

    def test_actual_cjk_text_cannot_bypass_declared_label_preflight(self):
        job = valid_job()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.csv").write_text("x,y\n0,0\n1,1\n", encoding="utf-8")
            job_path = root / "job.json"
            job_path.write_text(json.dumps(job), encoding="utf-8")
            plot_script = root / "plot.py"
            plot_script.write_text(textwrap.dedent(
                """
                import matplotlib.pyplot as plt

                def build_figure(job):
                    fig, ax = plt.subplots(figsize=(89 / 25.4, 50 / 25.4))
                    ax.plot([0, 1], [0, 1])
                    ax.set_xlabel("时间（小时）")
                    ax.set_ylabel("响应值")
                    return fig
                """
            ), encoding="utf-8")
            output = root / "bundle"
            result = run_pipeline(job_path=job_path, output_dir=output, stage="preview", plot_script=plot_script)
            self.assertEqual(result["status"], "FAIL")
            self.assertFalse((output / "preview/figure1.png").exists())
            runtime = json.loads((output / "qa/runtime_figure_checks.json").read_text(encoding="utf-8"))
            failed = {item["check_id"] for item in runtime["checks"] if item["status"] == "FAIL"}
            self.assertTrue({"figure.text_contract", "font.glyph_coverage"} <= failed)

    def test_plot_script_source_mutation_is_blocked(self):
        job = valid_job()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data.csv"
            data.write_text("x,y\n0,0\n1,1\n", encoding="utf-8")
            job_path = root / "job.json"
            job_path.write_text(json.dumps(job), encoding="utf-8")
            plot_script = root / "plot.py"
            plot_script.write_text(textwrap.dedent(
                """
                from pathlib import Path
                import matplotlib.pyplot as plt

                def build_figure(job):
                    Path(__file__).with_name("data.csv").write_text("modified")
                    fig, ax = plt.subplots(figsize=(89 / 25.4, 50 / 25.4))
                    ax.plot([0, 1], [0, 1])
                    ax.set_xlabel("Time (h)")
                    ax.set_ylabel("Response (a.u.)")
                    return fig
                """
            ), encoding="utf-8")
            output = root / "bundle"
            result = run_pipeline(job_path=job_path, output_dir=output, stage="preview", plot_script=plot_script)
            self.assertEqual(result["status"], "FAIL")
            self.assertFalse((output / "preview/figure1.png").exists())
            runtime = json.loads((output / "qa/runtime_figure_checks.json").read_text(encoding="utf-8"))
            mutation = [item for item in runtime["checks"] if item["check_id"] == "integrity.source_unchanged"][0]
            self.assertEqual(mutation["status"], "FAIL")
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(manifest["source_data_packaged"])
            self.assertEqual(manifest["reproducibility_level"], "code_and_hashes_only")
            self.assertFalse((output / "source/data").exists())

    def test_nature_final_binds_review_stats_and_non_type3_pdf(self):
        job = valid_job()
        job["target"].update({
            "profile": "nature-final",
            "submission_stage": "final",
            "figure_type": "line_art",
            "column": "single",
            "formats": ["pdf"],
            "labels": [
                "Time (h)",
                "Response (a.u.)",
                "Control",
                "Treatment",
                "p = 0.016",
            ],
        })
        job["analysis"]["annotations_requested"] = True
        job["statistics_file"] = "stats.json"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.csv").write_text("time,control,treatment\n0,0,0.2\n1,1,1.4\n", encoding="utf-8")
            stats_payload = {
                "schema_version": 1,
                "annotations_requested": True,
                "comparisons": [{**valid_comparison(), "adjusted_p_value": 0.016}],
            }
            (root / "stats.json").write_text(json.dumps(stats_payload), encoding="utf-8")
            job_path = root / "job.json"
            job_path.write_text(json.dumps(job), encoding="utf-8")
            plot_script = root / "plot.py"
            plot_script.write_text(textwrap.dedent(
                """
                import json
                from pathlib import Path
                import matplotlib.pyplot as plt
                from statistics_gate import derive_significance_label

                def build_figure(job):
                    evidence_path = Path(__file__).parent / job["statistics_file"]
                    comparison = json.loads(evidence_path.read_text())["comparisons"][0]
                    label = derive_significance_label(comparison, "exact")
                    fig, ax = plt.subplots(figsize=(89 / 25.4, 55 / 25.4))
                    ax.plot([0, 1], [0, 1], marker="o", label="Control")
                    ax.plot([0, 1], [0.2, 1.4], marker="s", linestyle="--", label="Treatment")
                    ax.set_xlabel("Time (h)")
                    ax.set_ylabel("Response (a.u.)")
                    ax.text(0.5, 1.2, label)
                    ax.legend()
                    return fig
                """
            ), encoding="utf-8")
            bundle = root / "bundle"
            preview = run_pipeline(
                job_path=job_path,
                output_dir=bundle,
                stage="preview",
                plot_script=plot_script,
            )
            self.assertEqual(preview["status"], "PASS")
            review = {
                "schema_version": 1,
                "reviewer": "test-reviewer",
                "input_hash": preview["input_hash"],
                "checks": {name: "PASS" for name in (
                    "crop",
                    "overlap",
                    "legibility",
                    "glyphs",
                    "accessibility",
                    "data_alignment",
                )},
            }
            review_path = root / "visual_review.json"
            review_path.write_text(json.dumps(review), encoding="utf-8")
            final = run_pipeline(
                job_path=job_path,
                output_dir=bundle,
                stage="final",
                plot_script=plot_script,
                visual_review_path=review_path,
            )
            self.assertEqual(final["status"], "PASS")
            self.assertEqual(final["verification_level"], "journal_verified")
            pdf_checks = {
                check["check_id"]: check
                for check in final["exports"][0]["artifacts"][0]["checks"]
            }
            self.assertEqual(pdf_checks["pdf.font_type"]["status"], "PASS")
            self.assertNotIn("Type 3", pdf_checks["pdf.font_type"]["observed"])
            public_job = json.loads((bundle / "source/job.public.json").read_text(encoding="utf-8"))
            self.assertEqual(public_job["statistics_file"], "../stats/statistics.json")
            self.assertTrue((bundle / "source" / public_job["statistics_file"]).resolve().is_file())


if __name__ == "__main__":
    unittest.main()
