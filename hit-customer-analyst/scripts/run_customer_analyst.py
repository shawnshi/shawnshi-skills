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

class CustomerAnalystOrchestrator(BasePipelineOrchestrator):
    def __init__(self):
        super().__init__("CustomerAnalystOrchestrator")
        self.skill_dir = Path(r"C:\Users\shich\.gemini\config\skills\hit-customer-analyst")
        self.tmp_dir = Path(r"C:\Users\shich\.gemini\tmp")

    def run_analyst(self, target_intent: str, vendor_mode: str = "winmed"):
        self.logger.info(f"Starting HIT Customer Analyst Pipeline. Target Intent: {target_intent}, Mode: {vendor_mode}")
        
        # 1. Historical Query
        self.logger.info("Querying historical Logic Lake context (simulated or injected via Agent)...")
        lake_history = "Historical Context: [To be enriched by local graph vectors.]"
        
        # 2. 4-Dimension Recon (Offloaded Map-Reduce)
        dimensions = [
            "Institution Overview (Budgets, Ratings, Planning)",
            "Decision Chain Topology (Key people, Factions, Power struggles)",
            "Vendor Landscape (Incumbents, Weaknesses, Core systems)",
            "Politics & Governance (Committees, Standards roles)"
        ]
        
        scraped_data = [f"### Logic Lake History\n{lake_history}"]
        for dim in dimensions:
            self.logger.info(f"Dispatching scout for {dim}...")
            result = self.call_llm(
                prompt=f"Target Account & Intent: {target_intent}\nRecon Dimension: {dim}\nExecute deep reconnaissance and return structured facts with full URLs. If a fact cannot be found, explicitly write 【信息缺口】.",
                system_instruction="You are an elite enterprise sales espionage analyst. Provide hard facts only.",
                temperature=0.1
            )
            scraped_data.append(f"### {dim}\n{result}")

        merged_raw = "\n\n".join(scraped_data)
        
        # 3. Validate & Synthesize
        self.logger.info("Executing Phase 2 & 3: Validation, Red Teaming, and Synthesis...")
        template_path = self.skill_dir / "assets" / "briefing_template.md"
        report_template = ""
        if template_path.exists():
            report_template = self.read_file(str(template_path))
            
        synthesis_prompt = f"""
        Raw Intelligence:
        {merged_raw}
        
        Task:
        1. Validate: Ensure core systems have double verification or mark 【信息缺口】. Verify URLs.
        2. Synthesize using {vendor_mode} mode constraints.
        3. Create Two-way Cognitive Matrix, Demo Script, Lethal Objections, and Red-team prep.
        
        Format output strictly matching this template:
        {report_template}
        """
        
        final_draft = self.call_llm(
            synthesis_prompt,
            system_instruction="You are a Tier-1 Account Executive / Strategy Partner. Deliver cold, actionable sales strategy."
        )
        
        # 4. Save Draft & Gate
        draft_path = self.tmp_dir / "draft_hit_customer.md"
        self.write_file(str(draft_path), final_draft)
        self.logger.info(f"Draft saved to {draft_path}")
        
        self.logger.info("Running Hard Gate Audit...")
        gate_script = self.skill_dir / "scripts" / "brief_gate.py"
        if gate_script.exists():
            try:
                gate_result = subprocess.run(
                    ["python", str(gate_script), str(draft_path)],
                    capture_output=True, text=True, encoding="utf-8"
                )
                self.logger.info(f"Audit output:\n{gate_result.stdout}")
                if gate_result.returncode != 0:
                    self.logger.warning("Audit failed. Returning control to Agent for manual correction.")
                else:
                    self.logger.info("Audit passed.")
            except Exception as e:
                self.logger.error(f"Audit execution failed: {e}")
        else:
            self.logger.warning("brief_gate.py not found. Skipping physical audit.")
            
        self.logger.info("Pipeline complete. The Agent may now review the draft, handle corrections, and physically archive the file.")
        self.logger.info("System Watchdog will ingest any entity modifications in the background.")

if __name__ == "__main__":
    intent = sys.argv[1] if len(sys.argv) > 1 else "Default Hospital Due Diligence"
    mode = sys.argv[2] if len(sys.argv) > 2 else "winmed"
    orchestrator = CustomerAnalystOrchestrator()
    orchestrator.run_analyst(intent, mode)
