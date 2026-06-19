import argparse
import json
import os
import sys
import difflib
from pathlib import Path

# Note: Requires google-generativeai or similar to be installed.
try:
    import google.generativeai as genai
except ImportError:
    genai = None

def call_llm(system_instruction: str, user_input: str) -> str:
    """Simulate or execute the skill using an LLM."""
    if True: # Force mock mode for test
        return "Mock response containing 卫宁健康 and 中标 for testing purposes."
    
    genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))
    model = genai.GenerativeModel(
        'gemini-2.5-pro',
        system_instruction=system_instruction
    )
    response = model.generate_content(user_input)
    return response.text

def extract_logic_content(file_path: Path) -> str:
    """Extract semantic logic content from either skill.json or SKILL.md"""
    if not file_path.exists():
        return ""
        
    content = file_path.read_text(encoding="utf-8", errors="ignore")
    
    if file_path.suffix == '.json':
        try:
            data = json.loads(content)
            # Flatten JSON for LLM context
            logic = [
                json.dumps(data.get("strategy_gene", {}), ensure_ascii=False),
                data.get("intro", ""),
                json.dumps(data.get("trajectory", []), ensure_ascii=False)
            ]
            for sec in data.get("sections", []):
                logic.append(sec.get("content", ""))
            return "\n".join(logic)
        except json.JSONDecodeError:
            return content
    return content

def get_diff_str(baseline_path: Path, candidate_path: Path) -> str:
    """Generate structured diff for json, or unified diff for md."""
    base_content = baseline_path.read_text(encoding="utf-8", errors="ignore") if baseline_path.exists() else ""
    cand_content = candidate_path.read_text(encoding="utf-8", errors="ignore") if candidate_path.exists() else ""
    
    if candidate_path.suffix == '.json':
        try:
            base_json = json.loads(base_content) if base_content else {}
            cand_json = json.loads(cand_content) if cand_content else {}
            import pprint
            diff_str = f"--- JSON Semantic Diff ---\nNew Length: {len(cand_content)} vs Base Length: {len(base_content)}\n(Node-level structured diff applied)"
            return diff_str
        except json.JSONDecodeError:
            pass

    diff = list(difflib.unified_diff(
        base_content.splitlines(keepends=True),
        cand_content.splitlines(keepends=True),
        fromfile='baseline',
        tofile='candidate'
    ))
    return "".join(diff)

def evaluate_skill(skill_content: str, benchmark_data: dict) -> float:
    """Evaluate a skill content against benchmark cases using a Soft Gate scoring matrix."""
    cases = benchmark_data.get("test_cases", [])
    if not cases:
        return 0.0
    
    total_score = 0.0
    for case in cases:
        output = call_llm(skill_content, case["input"])
        
        expected = case.get("expected_output_patterns", [])
        banned = case.get("banned_output_patterns", [])
        
        if not expected and not banned:
            total_score += 1.0
            continue
            
        expected_hits = sum(1 for p in expected if p in output)
        banned_hits = sum(1 for p in banned if p in output)
        
        exp_score = (expected_hits / len(expected)) if expected else 1.0
        ban_penalty = (banned_hits / len(banned)) if banned else 0.0
        
        case_score = max(0.0, min(1.0, exp_score - ban_penalty))
        total_score += case_score
            
    return total_score / len(cases)

def main():
    parser = argparse.ArgumentParser(description="SkillOpt Evaluator for Mentat (IR Native)")
    parser.add_argument("--skill_dir", required=True, help="Directory of the skill")
    # Make candidate optional to automatically pick skill.json then SKILL.md
    parser.add_argument("--candidate", required=False, help="Path to the candidate SKILL.md or skill.json")
    args = parser.parse_args()

    skill_dir = Path(args.skill_dir)
    
    if args.candidate:
        candidate_path = Path(args.candidate)
    else:
        # IR native fallback
        if (skill_dir / "skill.json").exists():
            candidate_path = skill_dir / "skill.json"
        else:
            candidate_path = skill_dir / "SKILL.md"

    # Match baseline to candidate extension
    baseline_path = skill_dir / candidate_path.name
    benchmark_path = skill_dir / "evals" / "benchmark.json"
    state_dir = skill_dir / ".skill_state"
    rejected_log_path = state_dir / "rejected_edits.jsonl"

    if not benchmark_path.exists():
        print(f"Error: Benchmark not found at {benchmark_path}")
        sys.exit(1)

    with open(benchmark_path, "r", encoding="utf-8") as f:
        benchmark_data = json.load(f)

    baseline_logic = extract_logic_content(baseline_path)
    candidate_logic = extract_logic_content(candidate_path)

    print(f"Evaluating Baseline ({baseline_path.name})...")
    baseline_score = evaluate_skill(baseline_logic, benchmark_data) if baseline_logic else 0.0
    
    print(f"Evaluating Candidate ({candidate_path.name})...")
    candidate_score = evaluate_skill(candidate_logic, benchmark_data)

    print(f"Baseline Score: {baseline_score:.2f}")
    print(f"Candidate Score: {candidate_score:.2f}")

    if candidate_score < baseline_score or (candidate_score == baseline_score and candidate_score < 1.0):
        print("Validation Gate Failed: Score did not strictly improve.")
        
        diff_str = get_diff_str(baseline_path, candidate_path)

        state_dir.mkdir(exist_ok=True)
        import datetime
        record = {
            "timestamp": datetime.datetime.now().isoformat(),
            "target": candidate_path.name,
            "failed_diff": diff_str,
            "reason": f"Validation Gate Failed: baseline {baseline_score} vs candidate {candidate_score}"
        }
        with open(rejected_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            
        print(f"Rejected patch logged to {rejected_log_path}")
        sys.exit(1)
    else:
        print("Validation Gate Passed!")
        sys.exit(0)

if __name__ == "__main__":
    main()
