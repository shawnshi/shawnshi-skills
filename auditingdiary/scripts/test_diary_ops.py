import os
import shutil
import tempfile
import sys
import subprocess
import json

def run_cmd(args):
    """Run diary_ops.py with the given args and return the parsed JSON."""
    cmd = [sys.executable, "c:/Users/shich/.gemini/skills/auditingdiary/scripts/diary_ops.py"] + args
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(cmd, capture_output=True, text=True, env=env, encoding="utf-8")
    try:
        if not result.stdout.strip():
            print(f"Empty stdout. stderr: {result.stderr}")
            return None
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"Failed to parse JSON. stdout: {result.stdout}, stderr: {result.stderr}")
        return None

def main():
    test_dir = tempfile.mkdtemp()
    try:
        # 1. Test Prepend
        content_q1 = "# 2026-03-30\nThis is Q1 data.\n#Strategy/MedicalAI\n专注度: ⭐⭐⭐⭐\n情绪状态: 😊"
        content_q2 = "# 2026-04-02\nThis is Q2 data.\n#Strategy/Data\n专注度: ⭐⭐⭐⭐\n情绪状态: 😐"
        
        file1 = os.path.join(test_dir, "content1.txt")
        file2 = os.path.join(test_dir, "content2.txt")
        with open(file1, "w", encoding="utf-8") as f: f.write(content_q1)
        with open(file2, "w", encoding="utf-8") as f: f.write(content_q2)

        res1 = run_cmd(["prepend", "--file", test_dir, "--content_file", file1])
        res2 = run_cmd(["prepend", "--file", test_dir, "--content_file", file2])

        assert res1 and res1.get("status") == "success", f"Prepend 1 failed: {res1}"
        assert res2 and res2.get("status") == "success", f"Prepend 2 failed: {res2}"

        # Check if files were created
        q1_file = os.path.join(test_dir, "2026-Q1.md")
        q2_file = os.path.join(test_dir, "2026-Q2.md")
        assert os.path.exists(q1_file), f"{q1_file} not found"
        assert os.path.exists(q2_file), f"{q2_file} not found"

        # 2. Test Read across quarters
        res_read = run_cmd(["read", "--file", test_dir, "--from", "2026-03-29", "--to", "2026-04-03"])
        assert res_read and res_read.get("status") == "success", f"Read failed: {res_read}"
        assert res_read.get("count") == 2, f"Expected 2 entries, got {res_read.get('count')}"

        # 3. Test Search
        res_search = run_cmd(["search", "--file", test_dir, "--query", "data"])
        assert res_search and res_search.get("status") == "success", f"Search failed: {res_search}"
        assert res_search.get("count") == 3, f"Expected 3 search results, got {res_search.get('count')}"

        # 4. Test Stats
        res_stats = run_cmd(["stats", "--file", test_dir])
        assert res_stats and res_stats.get("status") == "success", f"Stats failed: {res_stats}"
        assert res_stats["data"]["total_entries"] == 2, f"Expected 2 entries in stats, got {res_stats['data']['total_entries']}"

        print("All tests passed!")

    finally:
        shutil.rmtree(test_dir)

if __name__ == "__main__":
    main()
