"""
<!-- Standard Header -->
@Input: debate_results.json (Agent evaluations of options)
@Output: game_theory_analysis.json (Optimal consensus point)
@Pos: Phase 3 (Synthesis & Reconstruction)
@Maintenance Protocol: Scoring logic updates must sync SKILL.md.
"""
import sys
import json
import argparse

class GameTheoryResolver:
    """
    智力博弈论解析器 (V1.0):
    计算多代理博弈后的“纳什均衡解”。针对不同选项评估稳定性与摩擦力。
    """
    def __init__(self, data):
        self.data = data # Expected format: { "options": [ { "name": "A", "agent_scores": [0.8, 0.7], "friction": 0.2 } ] }

    def resolve_consensus(self):
        results = []
        for option in self.data.get("options", []):
            scores = option.get("agent_scores", [])
            avg_score = sum(scores) / len(scores) if scores else 0
            friction = option.get("friction", 0.5)
            # Stability = Average Score * (1 - Friction)
            stability = avg_score * (1 - friction)
            
            results.append({
                "option": option.get("name"),
                "stability": round(stability, 2),
                "avg_score": round(avg_score, 2),
                "friction": friction
            })
            
        # Sort by stability (highest first)
        results.sort(key=lambda x: x["stability"], reverse=True)
        return results

def main():
    parser = argparse.ArgumentParser(description="Resolve game theory consensus from debate results.")
    parser.add_argument("input", help="Path to debate_results.json")
    args = parser.parse_args()

    try:
        with open(args.input, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        resolver = GameTheoryResolver(data)
        analysis = resolver.resolve_consensus()
        
        print(json.dumps({
            "status": "Success",
            "optimal_consensus_point": analysis[0] if analysis else None,
            "full_analysis": analysis
        }, indent=4))
        
    except Exception as e:
        print(json.dumps({"status": "Error", "message": str(e)}, indent=4))

if __name__ == "__main__":
    main()
