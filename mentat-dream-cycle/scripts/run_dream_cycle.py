import sys
import os
import subprocess
import json
import shutil
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

class DreamCycleOrchestrator(BasePipelineOrchestrator):
    def __init__(self):
        super().__init__("DreamCycleOrchestrator")
        self.skill_dir = Path(r"C:\Users\shich\.gemini\config\skills\mentat-dream-cycle")
        self.memory_dir = Path(r"C:\Users\shich\.gemini\MEMORY")
        self.tmp_dir = Path(r"C:\Users\shich\.gemini\tmp")

    def run_gc(self):
        self.logger.info("Phase 1: Physical and Semantic GC")
        gc_script = self.skill_dir / "scripts" / "garbage_collector.py"
        if gc_script.exists():
            try:
                subprocess.run(
                    ["python", str(gc_script), "--path", str(self.tmp_dir), "--max-age", "24h"],
                    capture_output=True, text=True, encoding="utf-8"
                )
            except Exception as e:
                self.logger.error(f"GC script failed: {e}")
        else:
            self.logger.warning("garbage_collector.py not found. Skipping physical GC.")

    def diarize_hot_memory(self):
        self.logger.info("Phase 2: Hot Memory Diarization with Deduplication")
        hot_facts_path = self.memory_dir / "hot_facts.md"
        hot_facts_bak = self.memory_dir / "hot_facts.bak"
        
        if not hot_facts_path.exists() or hot_facts_path.stat().st_size == 0:
            self.logger.info("No hot facts to diarize.")
            return

        # Transactional backup
        try:
            shutil.copy2(hot_facts_path, hot_facts_bak)
        except Exception as e:
            self.logger.error(f"Backup failed: {e}")
            return

        raw_facts = self.read_file(str(hot_facts_bak))
        
        # Micro-batching via LLM with Tools
        prompt = f"""
        Extract the Top 5-8 most critical entities/facts from the following hot memory buffer.
        CRITICAL: Before extracting, you MUST use the Query_Vector_Lake tool to check if the entity or concept already exists in the local knowledge base.
        If it exists, mark the action as 'Merge' and explicitly specify the target entity name.
        If it does not exist, mark the action as 'Create'.
        
        Output them strictly in valid JSON format as a list of objects:
        [
          {{
            "entity": "Name of Entity",
            "compiled_truth": "The compressed insight",
            "action": "Create or Merge",
            "target_existing_entity": "Name of existing entity if Merge, otherwise null"
          }}
        ]
        
        Buffer:
        {raw_facts}
        """
        try:
            result = self.call_llm(
                prompt, 
                system_instruction="You are an autonomous memory dedup engine. You MUST query the Vector Lake to prevent creating duplicate nodes. Output raw JSON only.",
                tools=["Query_Vector_Lake"]
            )
            refined_path = self.memory_dir / "wiki" / ".meta" / "Entity_Backlog.md"
            self.write_file(str(refined_path), result)
            self.logger.info(f"Diarized and deduplicated entities written to {refined_path} for background watchdog ingestion.")
            
            # Reset hot facts
            self.write_file(str(hot_facts_path), "<!-- 缓冲已于近期由夜间清洗脚本清空 -->\n")
            if hot_facts_bak.exists():
                hot_facts_bak.unlink()
                
        except Exception as e:
            self.logger.error(f"Diarization failed: {e}. Restoring backup.")
            shutil.copy2(hot_facts_bak, hot_facts_path)

    def optimize_skills(self):
        self.logger.info("Phase 2.5: Skill Optimization Backward Pass")
        failure_log = self.memory_dir / "skill_audit" / "failure_batch.jsonl"
        minibatches = {}
        if failure_log.exists():
            try:
                with open(failure_log, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip(): continue
                        data = json.loads(line)
                        skill = data.get("Skill_Name", "unknown")
                        if skill not in minibatches:
                            minibatches[skill] = []
                        minibatches[skill].append(data)
                        
                # Filter noise
                high_priority = {k: v for k, v in minibatches.items() if len(v) > 1}
                if high_priority:
                    self.logger.info(f"High priority failures identified for skills: {list(high_priority.keys())}")
                    return high_priority
            except Exception as e:
                self.logger.error(f"Failed to process failure_batch.jsonl: {e}")
        return None

    def scan_orphans(self):
        self.logger.info("Phase 3: Topology Orphan Check")
        orphan_script = self.skill_dir / "scripts" / "orphan_scanner.py"
        if orphan_script.exists():
            try:
                subprocess.run(
                    ["python", str(orphan_script), "--dir", str(self.memory_dir / "wiki")],
                    capture_output=True, text=True, encoding="utf-8"
                )
                self.logger.info("Orphan scan complete.")
            except Exception as e:
                self.logger.error(f"Orphan scan failed: {e}")
        else:
            self.logger.warning("orphan_scanner.py not found. Skipping orphan scan.")

    def run_cycle(self):
        self.logger.info("Initiating Autonomous Mentat Dream Cycle (V8.0)...")
        self.run_gc()
        self.diarize_hot_memory()
        
        failuresToOptimize = self.optimize_skills()
        if failuresToOptimize:
            self.logger.info("Executing Autonomous Skill Self-Healing Protocol...")
            skill_creator_script = global_scripts_dir.parent / "mentat-skill-creator" / "scripts" / "run_skill_creator.py"
            if skill_creator_script.exists():
                for skill_name in failuresToOptimize.keys():
                    self.logger.info(f"Auto-healing skill: {skill_name}")
                    subprocess.run(
                        ["python", str(skill_creator_script), "--heal", skill_name],
                        capture_output=True, text=True, encoding="utf-8"
                    )
            else:
                self.logger.warning("mentat-skill-creator not found. Self-healing bypassed.")
                
        self.scan_orphans()
        self.logger.info("Dream Cycle background tasks complete. System has entered next epoch cleanly.")

if __name__ == "__main__":
    orchestrator = DreamCycleOrchestrator()
    orchestrator.run_cycle()
