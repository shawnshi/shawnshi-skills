import sys
import os
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

class IndustryRadarOrchestrator(BasePipelineOrchestrator):
    def __init__(self):
        super().__init__("IndustryRadarOrchestrator")
        self.skill_dir = Path(r"C:\Users\shich\.gemini\config\skills\hit-industry-radar")
        self.tmp_dir = Path(r"C:\Users\shich\.gemini\tmp")

    def run_radar(self):
        self.logger.info("Starting Hit Industry Radar Pipeline (Atomized Roundtable)...")
        
        assets_dir = self.skill_dir / "assets"
        tasks = [
            ("Global HIT", assets_dir / "Task_global_hit.md"),
            ("China HIT", assets_dir / "Task_china_hit.md"),
            ("Winning Baseline", assets_dir / "Task_winning_baseline.md")
        ]
        
        scraped_data = []
        
        # Phase 1: Sequential Scouting
        for name, path in tasks:
            self.logger.info(f"Dispatching scout for {name}...")
            if not path.exists():
                self.logger.warning(f"Task file not found: {path}")
                continue
                
            prompt = self.read_file(str(path))
            
            result = self.call_llm(
                prompt=f"Execute the following scouting intelligence task and extract concrete facts:\n\n{prompt}",
                system_instruction="You are a ruthless Corporate Espionage Scout. Extract raw facts, bids, dates, and version numbers. Zero commentary or fluff.",
                temperature=0.1
            )
            scraped_data.append(f"### {name} Data\n{result}")

        if not scraped_data:
            self.logger.error("No data scraped. Aborting pipeline.")
            return

        merged_raw = "\n\n".join(scraped_data)
        
        # --------------------------------------------------------------------------------
        # ATOMIZED ROUNDTABLE
        # --------------------------------------------------------------------------------
        self.logger.info("Phase 2: Roundtable Intelligence Processing...")

        # Micro-Persona 1: Data Launderer
        self.logger.info("Executing Micro-Persona: Data Launderer...")
        launder_prompt = f"""
        Raw Scout Data:
        {merged_raw}
        
        Task:
        Strip ALL marketing fluff, PR spin, and vague corporate statements.
        Return ONLY a bulleted list of hard, incontrovertible metrics: prices, bid values, version numbers, strict dates, and named personnel changes.
        """
        laundered_data = self.call_llm(
            launder_prompt, 
            system_instruction="You are a cold Data Launderer. Erase all adjectives. Output only raw numerical and factual data."
        )

        # Micro-Persona 2: Supply Chain Detective
        self.logger.info("Executing Micro-Persona: Supply Chain Detective...")
        detective_prompt = f"""
        Laundered Data:
        {laundered_data}
        
        Task:
        Analyze this clean data for hidden supply chain resonances or technical dependencies.
        (e.g., if Vendor A updates a module, does Vendor B break? Who is white-labeling whom? Which hospital is locked into which vendor's ecosystem?).
        Highlight non-obvious ecosystem dependencies.
        """
        supply_chain_links = self.call_llm(
            detective_prompt, 
            system_instruction="You are a Supply Chain Detective. Look for hidden relationships, OEM dependencies, and ecosystem vulnerabilities."
        )

        # Micro-Persona 3: Pricing War Analyst
        self.logger.info("Executing Micro-Persona: Pricing War Analyst...")
        pricing_prompt = f"""
        Laundered Data:
        {laundered_data}
        Supply Chain Links:
        {supply_chain_links}
        
        Task:
        Identify any pricing wars, bid undercutting, margin compression, or predatory pricing strategies evident in the data.
        Define the exact financial threat to our market share or specific product lines.
        """
        pricing_threats = self.call_llm(
            pricing_prompt, 
            system_instruction="You are a ruthless Pricing War Analyst. Focus exclusively on margins, bid dynamics, and predatory commercial tactics."
        )

        # Micro-Persona 4: McKinsey Partner
        self.logger.info("Executing Micro-Persona: McKinsey Partner...")
        partner_prompt = f"""
        Laundered Facts: {laundered_data}
        Supply Chain Dependencies: {supply_chain_links}
        Pricing Threats: {pricing_threats}
        
        Task:
        Synthesize these findings into exactly 1-2 brutal strategic verdicts and immediate counter-measures.
        Do not explain the facts, just deliver the verdict based on them.
        """
        partner_verdict = self.call_llm(
            partner_prompt, 
            system_instruction="You are a Tier-1 McKinsey Healthcare IT Partner. Deliver cold, decisive strategic verdicts."
        )

        # Phase 3: Executive Editor
        self.logger.info("Phase 3: Executive Drafting...")
        draft_prompt = f"""
        Roundtable Insights:
        - Hard Metrics: {laundered_data}
        - Supply Chain: {supply_chain_links}
        - Pricing Threats: {pricing_threats}
        - Strategic Verdict: {partner_verdict}
        
        Task:
        Format these insights into a highly aggressive, actionable strategy brief.
        Ensure brutal honesty and clear action levers. Do not add any new facts not present in the roundtable insights.
        """
        final_draft = self.call_llm(
            draft_prompt, 
            system_instruction="You are an Executive Editor. Use standard Markdown. Strip all fluff. Ensure the brief is lethal and readable in 3 minutes."
        )
        
        # Output final physical artifact
        draft_path = self.tmp_dir / "draft_hit_radar.md"
        self.write_file(str(draft_path), final_draft)
        
        self.logger.info(f"Pipeline complete. Draft successfully saved to {draft_path}")
        self.logger.info("The system Watchdog will automatically ingest any entity modifications in the background.")

if __name__ == "__main__":
    orchestrator = IndustryRadarOrchestrator()
    orchestrator.run_radar()
