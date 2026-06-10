import sys
import os
import subprocess
import argparse
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

class HealthAnalysisOrchestrator(BasePipelineOrchestrator):
    def __init__(self):
        super().__init__("HealthAnalysisOrchestrator")
        self.skill_dir = Path(r"C:\Users\shich\.gemini\config\skills\personal-health-analysis")
        self.tmp_dir = Path(r"C:\Users\shich\.gemini\tmp")

    def run_scripts(self, script_name: str, args: list):
        script_path = self.skill_dir / "scripts" / script_name
        if script_path.exists():
            try:
                cmd = ["python", str(script_path)] + args
                self.logger.info(f"Running: {' '.join(cmd)}")
                res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
                return res.stdout
            except Exception as e:
                self.logger.error(f"Failed to run {script_name}: {e}")
                return ""
        else:
            self.logger.warning(f"Script not found: {script_name}")
            return f"[{script_name} Mock Output for pipeline testing]"

    def run_health(self, level: int, days: int):
        self.logger.info(f"Starting Personal Health Analysis Pipeline (Level {level}, Days {days})...")
        
        # Phase 0: Sync
        self.logger.info("Phase 0: Synchronizing Garmin Data...")
        self.run_scripts("sync_health_data.py", [])
        
        # Phase 1 & 2: Extract & Intelligence
        self.logger.info("Phase 1 & 2: Extracting physiological intelligence...")
        
        if level == 1:
            raw_data = self.run_scripts("garmin_intelligence.py", ["readiness", "--days", str(days)])
            prompt = f"""
            Raw Data: {raw_data}
            Level 1 (Micro-Tactics) Request: Output a military-style < 50-word directive based on readiness. Do not output a full report.
            """
        else:
            summary = self.run_scripts("garmin_data.py", ["summary", "--days", str(days)])
            insight = self.run_scripts("garmin_intelligence.py", ["insight_cn", "--days", str(days)])
            flu_check = self.run_scripts("garmin_intelligence.py", ["flu_risk", "--days", str(days)])
            
            raw_data = f"Summary:\n{summary}\n\nInsight:\n{insight}\n\nFlu Check:\n{flu_check}"
            
            prompt = f"""
            Raw Data: 
            {raw_data}
            
            Level {level} Request: Output a CMO-level 4-layer executive briefing.
            Include:
            - System Momentum (Is it super-compensation or entropy?)
            - Execution Bandwidth (Cognitive and Physical readiness)
            - Frictions & Risks (Highlight Garmin Flu risk if any)
            - Tactical Directives
            Keep it strictly business-oriented. High density. BLUF (Bottom Line Up Front) format.
            """
            
            if level == 3:
                self.logger.info("Phase 3: Generating Strategic Tactical Board (HTML Dashboard)...")
                chart_output = self.run_scripts("garmin_chart.py", ["dashboard", "--days", str(days)])
                prompt += f"\n\nSystem generated an HTML dashboard at `{self.skill_dir.parent.parent}/MEMORY/raw/garmin/tactical_board.html`. Please mention this link in your report."
                
        # Phase 3: Executive Output via LLM
        self.logger.info("Phase 3: Generating Executive Output via LLM...")
        final_briefing = self.call_llm(prompt, system_instruction="You are the Chief Medical Officer and Strategic Architect.")
        
        # Save to payload
        payload_path = self.tmp_dir / f"health_audit_payload_L{level}.md"
        self.write_file(str(payload_path), final_briefing.strip())
        self.logger.info(f"Payload saved to {payload_path}")
        self.logger.info("Pipeline complete. Agent can now deliver the briefing.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--level", type=int, choices=[1, 2, 3], default=2, help="Output level (1=Micro, 2=Daily, 3=Strategic)")
    parser.add_argument("--days", type=int, default=7, help="Days to analyze")
    args = parser.parse_args()
    
    orchestrator = HealthAnalysisOrchestrator()
    orchestrator.run_health(args.level, args.days)
