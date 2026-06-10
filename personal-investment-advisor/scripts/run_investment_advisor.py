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

class InvestmentAdvisorOrchestrator(BasePipelineOrchestrator):
    def __init__(self):
        super().__init__("InvestmentAdvisorOrchestrator")
        self.skill_dir = Path(r"C:\Users\shich\.gemini\config\skills\personal-investment-advisor")
        self.workspace = Path(r"C:\Users\shich\.gemini\MEMORY\raw\stocks")
        self.tmp_dir = Path(r"C:\Users\shich\.gemini\tmp")
        self.workspace.mkdir(parents=True, exist_ok=True)

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

    def run_investment(self, symbol: str, mode: str):
        self.logger.info(f"Starting Personal Investment Advisor Pipeline for {symbol}...")
        
        # Phase 1: Fetch
        self.logger.info("Phase 1: Fetching Market & Portfolio Data...")
        market_data = self.run_scripts("yf.py", [symbol, "--json", "--lean"])
        
        portfolio_file = self.workspace / "portfolio_positions.json"
        portfolio_data = ""
        if portfolio_file.exists():
            portfolio_data = self.run_scripts("portfolio_loader.py", ["--positions-file", str(portfolio_file)])

        # Phase 2: Analyze
        self.logger.info("Phase 2: Generating Deep Quantitative Analysis JSON...")
        prompt = f"""
        Symbol: {symbol}
        Mode: {mode}
        
        Market Data:
        {market_data}
        
        Portfolio Data:
        {portfolio_data}
        
        Task:
        Act as the 'stock_analyzer'. Output a strictly formatted JSON following 'dashboard_schema.json'.
        Must include explicit target prices, stop-loss, and 'position_advice' if portfolio data indicates holding.
        Ensure math consistency (e.g. Stop Loss < Current Price).
        """
        
        raw_json_str = self.call_llm(prompt, system_instruction="You are a ruthless Quantitative Hedge Fund Manager. Output ONLY valid JSON.")
        
        # Clean markdown
        raw_json_str = raw_json_str.strip()
        if raw_json_str.startswith("```json"):
            raw_json_str = raw_json_str.split("```json", 1)[1]
        if raw_json_str.endswith("```"):
            raw_json_str = raw_json_str.rsplit("```", 1)[0]
            
        json_payload_path = self.tmp_dir / f"investment_dashboard_{symbol}.json"
        self.write_file(str(json_payload_path), raw_json_str.strip())
        
        # Phase 3: Gate
        self.logger.info("Phase 3: Running Math & Logic Gates...")
        gate_out = self.run_scripts("dashboard_gate.py", [str(json_payload_path)])
        math_gate_out = self.run_scripts("dashboard_math_gate.py", [str(json_payload_path)])
        
        self.logger.info(f"Gate checks: \n{gate_out}\n{math_gate_out}")
        
        # Phase 4: Archive
        self.logger.info("Phase 4: Archiving and Generating Final Markdown...")
        archive_out = self.run_scripts("save_dashboard.py", [str(json_payload_path)])
        self.logger.info(f"Archive output: {archive_out}")
        
        self.logger.info("Pipeline complete. The final markdown is in the MEMORY/raw/stocks directory. Agent can now deliver the analysis summary.")

    def run_sync(self):
        self.logger.info("Running Portfolio Outcome Sync...")
        out = self.run_scripts("decision_outcome_report.py", ["--sync"])
        self.logger.info(f"Sync output: {out}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=["analyze", "sync"], default="analyze", help="Action to perform")
    parser.add_argument("--symbol", help="Stock symbol to analyze")
    parser.add_argument("--mode", choices=["trading", "thesis"], default="trading", help="Analysis mode")
    args = parser.parse_args()
    
    orchestrator = InvestmentAdvisorOrchestrator()
    if args.action == "analyze":
        if not args.symbol:
            print("Error: --symbol is required for analyze action.")
            sys.exit(1)
        orchestrator.run_investment(args.symbol, args.mode)
    elif args.action == "sync":
        orchestrator.run_sync()
