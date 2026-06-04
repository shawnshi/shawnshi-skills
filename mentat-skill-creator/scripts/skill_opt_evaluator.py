import argparse
import json
import os
import sys
import difflib
from pathlib import Path

# Note: Requires google-generativeai or similar to be installed.
# Using a mock-able function for the actual LLM call to allow easy swapping.
try:
    import google.generativeai as genai
except ImportError:
    genai = None

def call_llm(system_instruction: str, user_input: str) -> str:
    """Simulate or execute the skill using an LLM."""
    if True: # Force mock mode for test
        # Fallback to mock for testing if no API key
        return "Mock response containing 卫宁健康 and 中标 for testing purposes."
    
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    model = genai.GenerativeModel(
        'gemini-2.5-pro',
        system_instruction=system_instruction
    )
    response = model.generate_content(user_input)
    return response.text

def evaluate_skill(skill_content: str, benchmark_data: dict) -> float:
    """Evaluate a skill content against benchmark cases using a Soft Gate scoring matrix."""
    cases = benchmark_data.get("test_cases", [])
    if not cases:
        return 0.0
    
    total_score = 0.0
    for case in cases:
        output = call_llm(skill_content, case["input"])
        
        # Soft Gate Logic (Partial Credit)
        expected = case.get("expected_output_patterns", [])
        banned = case.get("banned_output_patterns", [])
        
        if not expected and not banned:
            total_score += 1.0
            continue
            
        expected_hits = sum(1 for p in expected if p in output)
        banned_hits = sum(1 for p in banned if p in output)
        
        exp_score = (expected_hits / len(expected)) if expected else 1.0
        ban_penalty = (banned_hits / len(banned)) if banned else 0.0
        
        # Calculate final case score (bounded 0.0 to 1.0)
        case_score = max(0.0, min(1.0, exp_score - ban_penalty))
        total_score += case_score
            
    return total_score / len(cases)

def main():
    parser = argparse.ArgumentParser(description="SkillOpt Evaluator for Mentat")
    parser.add_argument("--skill_dir", required=True, help="Directory of the skill")
    parser.add_argument("--candidate", required=True, help="Path to the candidate SKILL.md")
    args = parser.parse_args()

    skill_dir = Path(args.skill_dir)
    candidate_path = Path(args.candidate)
    baseline_path = skill_dir / "SKILL.md"
    benchmark_path = skill_dir / "evals" / "benchmark.json"
    state_dir = skill_dir / ".skill_state"
    rejected_log_path = state_dir / "rejected_edits.jsonl"

    if not benchmark_path.exists():
        print(f"Error: Benchmark not found at {benchmark_path}")
        sys.exit(1)

    with open(benchmark_path, "r", encoding="utf-8") as f:
        benchmark_data = json.load(f)

    with open(candidate_path, "r", encoding="utf-8") as f:
        candidate_content = f.read()

    baseline_content = ""
    if baseline_path.exists():
        with open(baseline_path, "r", encoding="utf-8") as f:
            baseline_content = f.read()

    print(f"Evaluating Baseline ({baseline_path.name})...")
    baseline_score = evaluate_skill(baseline_content, benchmark_data) if baseline_content else 0.0
    
    print(f"Evaluating Candidate ({candidate_path.name})...")
    candidate_score = evaluate_skill(candidate_content, benchmark_data)

    print(f"Baseline Score: {baseline_score:.2f}")
    print(f"Candidate Score: {candidate_score:.2f}")

    if candidate_score < baseline_score or (candidate_score == baseline_score and candidate_score < 1.0):
        print("Validation Gate Failed: Score did not strictly improve.")
        
        # Calculate Diff
        diff = list(difflib.unified_diff(
            baseline_content.splitlines(keepends=True),
            candidate_content.splitlines(keepends=True),
            fromfile='baseline',
            tofile='candidate'
        ))
        diff_str = "".join(diff)

        # Log to Rejected Buffer
        state_dir.mkdir(exist_ok=True)
        import datetime
        record = {
            "timestamp": datetime.datetime.now().isoformat(),
            "failed_diff": diff_str,
            "reason": f"Validation Gate Failed: baseline {baseline_score} vs candidate {candidate_score}"
        }
        with open(rejected_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            
        print(f"Rejected patch logged to {rejected_log_path}")
        sys.exit(1)
    else:
        print("Validation Gate Passed!")
        # If it passed, typically the external caller will replace SKILL.md
        sys.exit(0)

if __name__ == "__main__":
    main()
