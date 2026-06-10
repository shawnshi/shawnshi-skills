import sys
import os
import subprocess
from pathlib import Path

# Mount the global scripts directory
global_scripts_dir = Path(r"C:\Users\shich\.gemini\config\skills\scripts")
if str(global_scripts_dir) not in sys.path:
    sys.path.insert(0, str(global_scripts_dir))

try:
    from orchestrator import BasePipelineOrchestrator
except ImportError:
    print("Error: Could not import BasePipelineOrchestrator. Make sure it exists in config/skills/scripts/")
    sys.exit(1)

class IntelligenceHubOrchestrator(BasePipelineOrchestrator):
    def __init__(self):
        super().__init__("IntelligenceHubOrchestrator")
        self.skill_dir = Path(r"C:\Users\shich\.gemini\config\skills\personal-intelligence-hub")
        self.workspace = Path(r"C:\Users\shich\.gemini\MEMORY\raw\news\_runtime\personal-intelligence-hub")
        self.workspace.mkdir(parents=True, exist_ok=True)

    def run_hub(self):
        self.logger.info("Starting Personal Intelligence Hub Pipeline...")
        
        # 1. Phase 1 & 2: Fetch & Refine
        self.logger.info("Phase 1 & 2: Running Fetch & Refine...")
        phase1_2_script = self.skill_dir / "scripts" / "run_phase1_2.py"
        if phase1_2_script.exists():
            try:
                subprocess.run(["python", str(phase1_2_script)], capture_output=True, text=True, encoding="utf-8")
                self.logger.info("run_phase1_2.py completed.")
            except Exception as e:
                self.logger.error(f"run_phase1_2.py failed: {e}")
        else:
            self.logger.warning("run_phase1_2.py not found. Simulating data generation for demonstration.")
            candidates_path = self.workspace / "intelligence_candidates.json"
            if not candidates_path.exists():
                self.write_file(str(candidates_path), '{"candidates": [{"id": "1", "title": "Example News", "content": "Sample"}]}')
        
        # 2. Phase 3: Semantic Deduction
        self.logger.info("Phase 3: Semantic Deduction via Orchestrator LLM...")
        candidates_path = self.workspace / "intelligence_candidates.json"
        if candidates_path.exists():
            candidates_data = self.read_file(str(candidates_path))
            deduction_prompt = f"""
            Raw Candidates:
            {candidates_data}
            
            Task:
            1. Perform Phase 3 Semantic Deduction. Apply the quality contract (Fact -> Connection -> Deduction -> Actionability).
            2. Insert double brackets [[ ]] for core entities.
            3. Return the fully refined global JSON containing 'punchline', 'insights', 'digest', and 'top_10'.
            """
            refined_json_text = self.call_llm(deduction_prompt, system_instruction="You are a Strategic Intelligence Analyst. Return valid JSON only. Do NOT return markdown code blocks.")
            
            # Clean up the markdown block if LLM returned it
            refined_json_text = refined_json_text.strip()
            if refined_json_text.startswith("```json"):
                refined_json_text = refined_json_text.split("```json", 1)[1]
            if refined_json_text.endswith("```"):
                refined_json_text = refined_json_text.rsplit("```", 1)[0]
                
            refined_path = self.workspace / "intelligence_current_refined.json"
            self.write_file(str(refined_path), refined_json_text.strip())
            self.logger.info("Semantic Deduction completed and saved to intelligence_current_refined.json.")
        else:
            self.logger.error(f"Cannot find {candidates_path}. Halting pipeline.")
            return
            
        # 3. Phase 4: Validation & Forge
        self.logger.info("Phase 4: Running Validation, Adversarial Audit, and Forging...")
        scripts_to_run = ["validate_refined_json.py", "adversarial_audit.py", "forge.py"]
        
        for script_name in scripts_to_run:
            script_path = self.skill_dir / "scripts" / script_name
            if script_path.exists():
                try:
                    res = subprocess.run(["python", str(script_path)], capture_output=True, text=True, encoding="utf-8")
                    self.logger.info(f"{script_name} output:\n{res.stdout}")
                    if res.returncode != 0:
                        self.logger.warning(f"{script_name} returned non-zero exit code. Review required.")
                except Exception as e:
                    self.logger.error(f"Failed to run {script_name}: {e}")
            else:
                self.logger.warning(f"{script_name} not found. Skipping physical execution.")
                
        self.logger.info("Pipeline complete. The Agent may now review the generated briefing.")

if __name__ == "__main__":
    orchestrator = IntelligenceHubOrchestrator()
    orchestrator.run_hub()
