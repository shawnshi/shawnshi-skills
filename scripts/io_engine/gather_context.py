import subprocess
import json
import sqlite3
import datetime
import os

# Dynamically resolve Garmin DB path using the user's home directory
HOME_DIR = os.path.expanduser("~")
GARMIN_DB_PATH = os.path.join(HOME_DIR, ".GarminDb", "HealthData", "DBs", "garmin.db")

def get_garmin_data():
    data_dict = {}
    try:
        if not os.path.exists(GARMIN_DB_PATH):
            return {"error": f"Garmin DB not found at {GARMIN_DB_PATH}"}
            
        conn = sqlite3.connect(GARMIN_DB_PATH)
        cursor = conn.cursor()
        
        # 1. 查询 daily_summary 表 (心率、压力、身体电量)
        cursor.execute("PRAGMA table_info(daily_summary);")
        summary_columns = [row[1] for row in cursor.fetchall()]
        
        summary_query_cols = []
        for c in ['day', 'rhr', 'stress_avg', 'bb_max', 'bb_min']:
            if c in summary_columns:
                summary_query_cols.append(c)
                
        if summary_query_cols:
            query = f"SELECT {', '.join(summary_query_cols)} FROM daily_summary ORDER BY day DESC LIMIT 1"
            cursor.execute(query)
            summary_data = cursor.fetchone()
            if summary_data:
                for k, v in zip(summary_query_cols, summary_data):
                    data_dict[k] = v
        
        # 2. 查询 sleep 表 (睡眠得分和时长)
        cursor.execute("PRAGMA table_info(sleep);")
        sleep_columns = [row[1] for row in cursor.fetchall()]
        
        sleep_query_cols = []
        for c in ['total_sleep', 'score']:
            if c in sleep_columns:
                sleep_query_cols.append(c)
                
        if sleep_query_cols and 'day' in data_dict:
            # 尝试获取对应日期的睡眠数据
            query = f"SELECT {', '.join(sleep_query_cols)} FROM sleep WHERE day = ? LIMIT 1"
            cursor.execute(query, (data_dict['day'][:10],))
            sleep_data = cursor.fetchone()
            if sleep_data:
                for k, v in zip(sleep_query_cols, sleep_data):
                    data_dict[f"sleep_{k}"] = v
                    
    except Exception as e:
        return {"error": str(e)}
        
    return data_dict

def get_calendar_data():
    today = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    # 修改：将 end_of_day 设置为明天的 23:59:59
    end_of_tomorrow = today + datetime.timedelta(days=1, hours=23, minutes=59, seconds=59)
    
    calendar_params = {
        "calendarId": "primary",
        "timeMin": today.isoformat() + "+08:00",
        "timeMax": end_of_tomorrow.isoformat() + "+08:00",
        "singleEvents": True,
        "orderBy": "startTime"
    }
    try:
        res = subprocess.run(["gws", "calendar", "events", "list", "--params", json.dumps(calendar_params)], capture_output=True, text=True, shell=False, encoding='utf-8')
        if res.returncode == 0:
             return json.loads(res.stdout).get("items", [])
        else:
             return {"error": res.stderr}
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    print("=== System Reconnaissance Probe ===")
    print("\n[1] Garmin Health Data (Latest Local)")
    garmin = get_garmin_data()
    print(json.dumps(garmin, indent=2, ensure_ascii=False))
    
    print("\n[2] Google Calendar (Today & Tomorrow)")
    cal = get_calendar_data()
    print(json.dumps(cal, indent=2, ensure_ascii=False))
