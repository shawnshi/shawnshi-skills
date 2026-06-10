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

class LecturesScoutOrchestrator(BasePipelineOrchestrator):
    def __init__(self):
        super().__init__("LecturesScoutOrchestrator")
        self.skill_dir = Path(r"C:\Users\shich\.gemini\config\skills\hit-lectures-scout")
        self.tmp_dir = Path(r"C:\Users\shich\.gemini\tmp")

    def execute_deepxiv_scout(self):
        script_path = self.skill_dir / "assets" / "deepxiv_preprints_scout.py"
        self.logger.info(f"Executing DeepXiv preprints scout: {script_path}")
        if not script_path.exists():
            self.logger.warning("deepxiv_preprints_scout.py not found. Simulating fallback via LLM.")
            fallback_prompt_path = self.skill_dir / "assets" / "task_preprints_fallback.md"
            if fallback_prompt_path.exists():
                fallback_prompt = self.read_file(str(fallback_prompt_path))
                return self.call_llm(f"Execute fallback scout:\n{fallback_prompt}", system_instruction="You are a medical AI researcher.")
            return "Simulated DeepXiv Results (Fallbacks active)."
            
        try:
            result = subprocess.run(
                ["python", str(script_path)],
                capture_output=True,
                text=True,
                encoding="utf-8"
            )
            if result.returncode == 0:
                return result.stdout
            else:
                self.logger.warning(f"deepxiv failed: {result.stderr}. Triggering fallback subagent logic via LLM.")
                fallback_prompt = self.read_file(str(self.skill_dir / "assets" / "task_preprints_fallback.md"))
                return self.call_llm(f"Execute fallback scout:\n{fallback_prompt}")
        except Exception as e:
            self.logger.error(f"Error running deepxiv: {e}")
            return "Error during deepxiv."

    def run_scout(self):
        self.logger.info("Starting HIT Lectures Scout Pipeline (Atomized Roundtable)...")
        
        # Phase 1: Mixed Scheduling (DeepXiv + Journals)
        preprints_data = self.execute_deepxiv_scout()
        
        assets_dir = self.skill_dir / "assets"
        journals_en = assets_dir / "task_journals_en.md"
        journals_cn = assets_dir / "task_journals_cn.md"
        
        scraped_data = [f"### Preprints Data\n{preprints_data}"]
        
        for name, path in [("EN Journals", journals_en), ("CN Journals", journals_cn)]:
            self.logger.info(f"Dispatching scout for {name}...")
            if path.exists():
                prompt = self.read_file(str(path))
                result = self.call_llm(
                    prompt=f"Execute the following scouting intelligence task and extract concrete facts:\n\n{prompt}",
                    system_instruction="You are a medical AI researcher. Extract only high-value papers with Real World Evidence (RWE).",
                    temperature=0.1
                )
                scraped_data.append(f"### {name} Data\n{result}")

        merged_raw = "\n\n".join(scraped_data)
        
        # --------------------------------------------------------------------------------
        # ATOMIZED ROUNDTABLE
        # --------------------------------------------------------------------------------
        
        # Phase 2: RWE Auditor (Strict Clinical Lens)
        self.logger.info("Executing Phase 2: RWE Auditor...")
        rwe_prompt = f"""
        Raw Academic Data:
        {merged_raw}
        
        Task:
        Act as a ruthless Clinical Evidence Auditor. 
        Apply a strict RWE (Real World Evidence) check. Discard any noisy, purely theoretical, or unvalidated papers.
        Output ONLY a clean list of highly validated, empirically backed clinical AI papers with their core mechanism.
        """
        rwe_validated_data = self.call_llm(
            rwe_prompt, 
            system_instruction="You are a strict Clinical Evidence Auditor. No fluff. Reject weak papers."
        )

        # Phase 3: Solutions Architect (Tech Mapping Lens)
        self.logger.info("Executing Phase 3: Solutions Architect...")
        architect_prompt = f"""
        Validated RWE Papers:
        {rwe_validated_data}
        
        Task:
        Act as the Chief Healthcare AI Architect.
        Map these academic signals to our proprietary architectures (e.g., ACE, Logic Lake, MSL, WiNGPT).
        Specify exactly how our tech stack can ingest, replicate, or defend against these academic paradigms.
        """
        architecture_mapping = self.call_llm(
            architect_prompt, 
            system_instruction="You are a Healthcare AI Chief Architect. Focus purely on technical architecture and integration."
        )

        # Phase 4: Commercial Strategist (Business & Sales Lens)
        self.logger.info("Executing Phase 4: Commercial Strategist...")
        commercial_prompt = f"""
        Architecture Mapping:
        {architecture_mapping}
        
        Task:
        Act as the VP of Strategy & Sales.
        Convert these technical mappings into actionable business levers.
        For each major signal, provide:
        - 1 concrete R&D task.
        - 1 aggressive Sales defense script / pitch point for hospital executives.
        """
        strategic_actions = self.call_llm(
            commercial_prompt, 
            system_instruction="You are a VP of Strategy. Focus on monetization, ROI, DRG alignment, and aggressive market defense."
        )
        
        # Phase 5: Narrative Synthesis & Draft
        self.logger.info("Executing Phase 5: Narrative Synthesis...")
        report_template = ""
        template_path = self.skill_dir / "assets" / "report_template.md"
        if template_path.exists():
            report_template = self.read_file(str(template_path))
            
        final_draft = self.call_llm(
            prompt=f"Format the following aggregated intelligence using the provided template.\n\nTemplate:\n{report_template}\n\nClinical Baseline:\n{rwe_validated_data}\n\nTech Architecture:\n{architecture_mapping}\n\nCommercial Levers:\n{strategic_actions}",
            system_instruction="You are an Executive Editor. Use standard Markdown. Ensure brutal honesty, clear paradigm shifts, and actionable levers. Do not hallucinate URLs."
        )
        
        # Write draft
        draft_path = self.tmp_dir / "draft_hit_scout.md"
        self.write_file(str(draft_path), final_draft)
        self.logger.info(f"Draft saved to {draft_path}")
        
        # Phase 6: The Hard Gate
        self.logger.info("Running Hard Gate Audit...")
        gate_script = global_scripts_dir / "hit_audit_gate.py"
        if gate_script.exists():
            try:
                gate_result = subprocess.run(
                    ["python", str(gate_script), str(draft_path), "--mode", "scout"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8"
                )
                self.logger.info(f"Audit output:\n{gate_result.stdout}")
                if gate_result.returncode != 0:
                    self.logger.warning("Audit failed. Returning control to Agent for correction.")
                else:
                    self.logger.info("Audit passed.")
            except Exception as e:
                self.logger.error(f"Audit execution failed: {e}")
        
        self.logger.info("Pipeline complete. The Agent may now review the draft or handle audit corrections.")
        self.logger.info("The system Watchdog will automatically ingest any entity modifications in the background.")

if __name__ == "__main__":
    orchestrator = LecturesScoutOrchestrator()
    orchestrator.run_scout()
