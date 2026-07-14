import subprocess
import sys
import re
import os
from pathlib import Path
from datetime import datetime, timedelta

def main():
    print("🚀 [Phase A] Starting official GarminDB sync...")
    cmd_sync = ["python", "-m", "garmindb_cli", "--download", "--import", "--analyze", "--all", "--latest"]
    
    # Try finding the exact script path for garmindb_cli.py if module execution fails
    scripts_dir = Path(sys.executable).parent / "Scripts"
    cli_path = scripts_dir / "garmindb_cli.py"
    if cli_path.exists():
        cmd_sync = [sys.executable, str(cli_path), "--download", "--import", "--analyze", "--all", "--latest"]

    try:
        result = subprocess.run(cmd_sync, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8')
        output = result.stdout
        print(output)
        
        # Check for 429 or login failure
        if "Failed to login" in output or "429" in output or "Too Many Requests" in output or result.returncode != 0:
            if "Failed to login" in output:
                print("[Phase B] Login failed. Dependencies were not changed; check credentials and installed versions.")
                trigger_fallback()
            else:
                print("⚠️ [Phase B] GarminDB sync hit an error (likely 429 limit). Intercepting...")
                trigger_fallback()
        else:
            print("✅ [Phase A] GarminDB sync successful.")
    except Exception as e:
        print(f"❌ Execution failed: {e}")
        trigger_fallback()

def trigger_fallback():
    print("🛡️ [Phase C] Initiating Fallback Mode (Lightweight API)")
    
    # Find last synced date
    try:
        # Add current directory to path to import the adapter
        sys.path.insert(0, str(Path(__file__).parent))
        import garmin_sqlite_adapter
        conn = garmin_sqlite_adapter.get_connection(Path.home() / ".GarminDb" / "garmin.db")
        cur = conn.cursor()
        # Find which table exists
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        table_name = 'daily_summary' if 'daily_summary' in tables else 'days_summary'
        
        cur.execute(f"SELECT MAX(day) FROM {table_name}")
        max_date = cur.fetchone()[0]
        conn.close()
        
        if max_date:
            max_date = max_date[:10]
            start_date = (datetime.strptime(max_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            
    except Exception as e:
        print(f"⚠️ Could not read SQLite DB for fallback date: {e}")
        start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        
    end_date = datetime.now().strftime("%Y-%m-%d")
    
    # Do we really need to fetch if start_date > end_date?
    if start_date > end_date:
        print("✅ DB is already up to date. Fallback not needed.")
        return
        
    print(f"📥 Fetching missing data from {start_date} to {end_date}...")
    
    out_dir = Path(os.environ.get("GARMIN_OUTPUT_DIR", str(Path.cwd() / "garmin-output"))).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"garmin_missing_{start_date.replace('-','')}_{end_date.replace('-','')}.json"
    
    garmin_data_script = Path(__file__).parent / "garmin_data.py"
    
    cmd_fallback = [
        sys.executable, str(garmin_data_script), "summary",
        "--start", start_date, "--end", end_date
    ]
    
    try:
        with open(out_file, 'w', encoding='utf-8') as f:
            res = subprocess.run(cmd_fallback, stdout=f, stderr=subprocess.PIPE, text=True, encoding='utf-8')
            
        if res.returncode == 0:
            print(f"✅ [Fallback Success] Rescued data saved to {out_file}")
        else:
            print(f"❌ [Fallback Failed] Error: {res.stderr}")
    except Exception as e:
        print(f"❌ [Fallback Failed] Execution error: {e}")

if __name__ == "__main__":
    main()
