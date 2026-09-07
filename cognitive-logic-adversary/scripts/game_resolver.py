"""
<!-- Standard Header -->
@Input: debate_results.json (Agent evaluations of options)
@Output: game_theory_analysis.json (Optimal consensus point)
@Pos: Phase 3 (Synthesis & Reconstruction)
@Version: 2.0
@Maintenance Protocol: Scoring logic updates must sync SKILL.md.
"""
import argparse
import json
import math
from typing import Any, Dict, List, NoReturn


class GameTheoryResolver:
    """
    智力博弈论解析器 (V2.0):
    多维度评估代理辩论结果，计算加权共识、帕累托前沿、稳定性得分。

    Input format:
    {
        "options": [
            {
                "name": "A",
                "agent_scores": [
                    {"agent": "EN-1", "score": 0.8, "confidence": 0.9},
                    {"agent": "AR-2", "score": 0.6, "confidence": 0.7}
                ],
                "friction": 0.2,
                "risk_level": "medium"
            }
        ]
    }
    """

    RISK_PENALTY = {"low": 0.0, "medium": 0.15, "high": 0.35, "critical": 0.6}

    def __init__(self, data: Dict[str, Any]):
        if not isinstance(data, dict):
            raise ValueError("top-level JSON must be an object")
        options = data.get("options")
        if not isinstance(options, list) or not options:
            raise ValueError("options must be a non-empty array")
        names = set()
        for index, option in enumerate(options):
            path = f"options[{index}]"
            if not isinstance(option, dict):
                raise ValueError(f"{path} must be an object")
            name = option.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ValueError(f"{path}.name must be a non-empty string")
            if name in names:
                raise ValueError(f"{path}.name is duplicated: {name!r}")
            names.add(name)
            scores = option.get("agent_scores")
            if not isinstance(scores, list) or not scores:
                raise ValueError(f"{path}.agent_scores must be a non-empty array")
            structured = isinstance(scores[0], dict)
            for score_index, entry in enumerate(scores):
                score_path = f"{path}.agent_scores[{score_index}]"
                if structured:
                    if not isinstance(entry, dict):
                        raise ValueError(f"{score_path} must be an object; mixed formats are invalid")
                    self._validate_unit_number(entry.get("score"), f"{score_path}.score")
                    self._validate_unit_number(entry.get("confidence", 1.0), f"{score_path}.confidence")
                    if "agent" in entry and (not isinstance(entry["agent"], str) or not entry["agent"].strip()):
                        raise ValueError(f"{score_path}.agent must be a non-empty string when supplied")
                else:
                    self._validate_unit_number(entry, score_path)
            self._validate_unit_number(option.get("friction", 0.5), f"{path}.friction")
            risk = option.get("risk_level", "medium")
            if not isinstance(risk, str) or risk not in self.RISK_PENALTY:
                raise ValueError(f"{path}.risk_level must be low, medium, high, or critical")
        self.data = data
        self.options = options

    @staticmethod
    def _validate_unit_number(value: Any, path: str) -> None:
        # Range check precedes isfinite so arbitrarily large JSON integers do not overflow.
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not 0 <= value <= 1 or not math.isfinite(value)):
            raise ValueError(f"{path} must be a finite number in [0, 1], not a boolean")

    def _extract_scores(self, option: Dict) -> List[float]:
        """Extract raw scores, supporting both flat and structured formats."""
        raw = option.get("agent_scores", [])
        if not raw:
            return []
        if isinstance(raw[0], (int, float)):
            return [float(s) for s in raw]
        return [entry.get("score", 0.0) for entry in raw]

    def _extract_confidences(self, option: Dict) -> List[float]:
        """Extract confidence weights. Default 1.0 if not structured."""
        raw = option.get("agent_scores", [])
        if not raw or isinstance(raw[0], (int, float)):
            return [1.0] * len(raw)
        return [entry.get("confidence", 1.0) for entry in raw]

    def weighted_consensus(self, option: Dict) -> float:
        """Confidence-weighted average score."""
        scores = self._extract_scores(option)
        confidences = self._extract_confidences(option)
        if not scores:
            return 0.0
        total_weight = sum(confidences)
        if total_weight == 0:
            return 0.0
        return sum(s * c for s, c in zip(scores, confidences)) / total_weight

    def consensus_distance(self, option: Dict) -> float:
        """Standard deviation of scores — lower means stronger consensus."""
        scores = self._extract_scores(option)
        if len(scores) < 2:
            return 0.0
        mean = sum(scores) / len(scores)
        variance = sum((s - mean) ** 2 for s in scores) / len(scores)
        return round(variance ** 0.5, 4)

    def stability_score(self, option: Dict) -> float:
        """
        Stability = WeightedConsensus * (1 - Friction) * (1 - RiskPenalty) * (1 - ConsensusDistance)
        Higher is better. Penalizes high friction, high risk, and low agreement.
        """
        wc = self.weighted_consensus(option)
        friction = option.get("friction", 0.5)
        risk = option.get("risk_level", "medium")
        risk_pen = self.RISK_PENALTY.get(risk, 0.15)
        cd = self.consensus_distance(option)
        return round(wc * (1 - friction) * (1 - risk_pen) * (1 - cd), 4)

    def resolve_consensus(self) -> List[Dict]:
        """Compute full analysis for all options, sorted by stability."""
        results = []
        for option in self.options:
            scores = self._extract_scores(option)
            results.append({
                "option": option.get("name", "Unknown"),
                "stability": self.stability_score(option),
                "weighted_consensus": round(self.weighted_consensus(option), 4),
                "consensus_distance": self.consensus_distance(option),
                "friction": option.get("friction", 0.5),
                "risk_level": option.get("risk_level", "medium"),
                "agent_count": len(scores),
                "score_range": [round(min(scores), 2), round(max(scores), 2)] if scores else [0, 0],
            })
        results.sort(key=lambda x: x["stability"], reverse=True)
        return results

    def pareto_frontier(self) -> List[Dict]:
        """
        Identify Pareto-optimal options:
        An option is Pareto-optimal if no other option has BOTH
        higher weighted_consensus AND lower consensus_distance.
        """
        all_results = self.resolve_consensus()
        frontier = []
        for candidate in all_results:
            dominated = False
            for other in all_results:
                if other["option"] == candidate["option"]:
                    continue
                if (other["weighted_consensus"] >= candidate["weighted_consensus"] and
                    other["consensus_distance"] <= candidate["consensus_distance"] and
                    (other["weighted_consensus"] > candidate["weighted_consensus"] or
                     other["consensus_distance"] < candidate["consensus_distance"])):
                    dominated = True
                    break
            if not dominated:
                frontier.append(candidate)
        return frontier

    def text_chart(self, results: List[Dict], width: int = 40) -> str:
        """Generate a simple text bar chart for stability scores."""
        if not results:
            return "  (No data)\n"
        max_stability = max(r["stability"] for r in results) or 1
        lines = []
        for r in results:
            bar_len = int((r["stability"] / max_stability) * width)
            bar = "█" * bar_len + "░" * (width - bar_len)
            lines.append(f"  {r['option']:>12s} |{bar}| {r['stability']:.4f}")
        return "\n".join(lines)


class InputArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ValueError(message)


def main() -> int:
    parser = InputArgumentParser(
        description="Game Theory Resolver V2.0 — Compute weighted consensus, "
                    "stability scores, and Pareto frontier from debate results."
    )
    parser.add_argument("input", help="Path to debate_results.json")
    parser.add_argument("--pareto", action="store_true", help="Also compute Pareto frontier")
    parser.add_argument("--chart", action="store_true", help="Include text bar chart")
    try:
        args = parser.parse_args()
        with open(args.input, 'r', encoding='utf-8') as f:
            data = json.load(f)
        resolver = GameTheoryResolver(data)
    except (OSError, ValueError) as exc:
        # JSON/UTF-8/Schema and argument failures are expected input errors.
        print(json.dumps({"status": "Error", "message": str(exc)}, indent=4))
        return 2

    # Computation defects deliberately propagate with the original traceback.
    analysis = resolver.resolve_consensus()
    output = {
        "status": "Success",
        "version": "2.0",
        "optimal_consensus_point": analysis[0] if analysis else None,
        "full_analysis": analysis,
    }
    if args.pareto:
        output["pareto_frontier"] = resolver.pareto_frontier()
    if args.chart:
        output["stability_chart"] = resolver.text_chart(analysis)
    print(json.dumps(output, indent=4, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
