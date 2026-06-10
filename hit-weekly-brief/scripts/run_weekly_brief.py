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

class WeeklyBriefOrchestrator(BasePipelineOrchestrator):
    def __init__(self):
        super().__init__("WeeklyBriefOrchestrator")
        self.skill_dir = Path(r"C:\Users\shich\.gemini\config\skills\hit-weekly-brief")
        self.tmp_dir = Path(r"C:\Users\shich\.gemini\tmp")

    def run_brief(self):
        self.logger.info("Starting HIT Weekly Brief Pipeline (Atomized Lobster Architecture)...")
        
        # Phase 1: 4-Way Sequential Sandboxed Map-Reduce
        assets_dir = self.skill_dir / "assets"
        tasks = [
            ("Strategy", assets_dir / "Task_strategy.md"),
            ("Policy", assets_dir / "Task_policy.md"),
            ("Tech", assets_dir / "Task_tech.md"),
            ("Serendipity", assets_dir / "Task_serendipity.md")
        ]
        
        scraped_data = []
        for name, path in tasks:
            self.logger.info(f"Dispatching scout for {name}...")
            if not path.exists():
                self.logger.warning(f"Task file not found: {path}")
                continue
                
            prompt = self.read_file(str(path))
            result = self.call_llm(
                prompt=f"Execute the following scouting intelligence task and extract concrete facts:\n\n{prompt}",
                system_instruction=f"You are a Top-Tier Consulting Analyst specializing in {name}. Extract high-density signals.",
                temperature=0.2
            )
            scraped_data.append(f"### {name} Pipeline Data\n{result}")

        merged_raw = "\n\n".join(scraped_data)
        
        # --------------------------------------------------------------------------------
        # ATOMIZED ROUNDTABLE
        # --------------------------------------------------------------------------------
        self.logger.info("Phase 2: Roundtable Intelligence Processing...")

        # Micro-Persona 1: Concept Translator
        self.logger.info("Executing Micro-Persona: Concept Translator...")
        translator_prompt = f"""
        Raw Data from 4 dimensions:
        {merged_raw}
        
        Task:
        Focus exclusively on the 'Serendipity' and 'Tech' data.
        Perform Semantic Translation: Translate non-healthcare concepts (e.g. edge computing, manufacturing IoT, generative UI) into brutal Medical IT realities (e.g. Point-of-care analysis, medical device integration, EMR UI generation).
        """
        translated_concepts = self.call_llm(
            translator_prompt, 
            system_instruction="You are a Cross-Domain Technology Translator. Force cross-pollination between general tech and rigid healthcare IT systems."
        )

        # Micro-Persona 2: Consensus Weaver
        self.logger.info("Executing Micro-Persona: Consensus Weaver...")
        weaver_prompt = f"""
        Translated Concepts: {translated_concepts}
        Raw Data: {merged_raw}
        
        Task:
        Identify the "Maximum Consensus" (what everyone agrees will happen) and "Hidden Threat" (the risk no one is talking about) across all pipelines.
        """
        consensus_threats = self.call_llm(
            weaver_prompt, 
            system_instruction="You are a macro-level Consensus Weaver. Extract the core market movement and its silent vulnerabilities."
        )

        # Micro-Persona 3: Contrarian Analyst
        self.logger.info("Executing Micro-Persona: Contrarian Analyst...")
        contrarian_prompt = f"""
        Consensus & Threats:
        {consensus_threats}
        
        Task:
        Find and highlight at least 1 piece of evidence or logic that CONTRADICTS the mainstream consensus you just read.
        Attack the consensus.
        """
        contrarian_view = self.call_llm(
            contrarian_prompt, 
            system_instruction="You are a cynical Contrarian Analyst. Disprove the consensus. Look for the black swan."
        )

        # Micro-Persona 4: Solution Mapper
        self.logger.info("Executing Micro-Persona: Solution Mapper...")
        mapper_prompt = f"""
        Threats: {consensus_threats}
        Contrarian View: {contrarian_view}
        
        Task:
        Provide actionable insights mapped to specific enterprise software or consulting solutions. 
        What should we BUILD, BUY, or SELL this week to exploit these insights?
        """
        actionable_solutions = self.call_llm(
            mapper_prompt, 
            system_instruction="You are a Commercial Solution Mapper. Translate threats and contrarian views into products and services we can sell."
        )

        # Phase 4: Narrative Synthesis
        self.logger.info("Drafting final strategic brief...")
        report_template = ""
        template_path = self.skill_dir / "resources" / "template.md"
        if template_path.exists():
            report_template = self.read_file(str(template_path))
            
        final_draft = self.call_llm(
            prompt=f"Format these insights using the following template.\n\nTemplate:\n{report_template}\n\nTranslated Concepts:\n{translated_concepts}\n\nConsensus & Threats:\n{consensus_threats}\n\nContrarian View:\n{contrarian_view}\n\nSolutions:\n{actionable_solutions}",
            system_instruction="Use standard Markdown. Ensure brutal honesty, S-I-A logical framing, and cold ROI-driven business language. Never use [Link] placeholders. Ensure 'Contrarian' viewpoint is explicitly included."
        )
        
        # Write draft
        draft_path = self.tmp_dir / "draft_hit_brief.md"
        self.write_file(str(draft_path), final_draft)
        self.logger.info(f"Draft saved to {draft_path}")
        
        # Phase 5: The Hard Gate
        self.logger.info("Running Hard Gate Audit...")
        gate_script = global_scripts_dir / "hit_audit_gate.py"
        if gate_script.exists():
            try:
                gate_result = subprocess.run(
                    ["python", str(gate_script), str(draft_path), "--mode", "brief"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8"
                )
                self.logger.info(f"Audit output:\n{gate_result.stdout}")
                if gate_result.returncode != 0:
                    self.logger.warning("Audit failed. Returning control to Agent for manual correction.")
                else:
                    self.logger.info("Audit passed.")
            except Exception as e:
                self.logger.error(f"Audit execution failed: {e}")
        
        self.logger.info("Pipeline complete. The Agent may now review the draft or handle audit corrections.")
        self.logger.info("The system Watchdog will automatically ingest any entity modifications in the background.")

if __name__ == "__main__":
    orchestrator = WeeklyBriefOrchestrator()
    orchestrator.run_brief()
