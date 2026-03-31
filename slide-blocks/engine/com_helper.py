# -*- coding: utf-8 -*-
"""
com_helper.py - PowerPoint COM 进程管理助手
"""

import os
import time
import subprocess
from pathlib import Path
import win32com.client
import pythoncom

class COMManager:
    def __init__(self):
        self.app = None
        self._powerpnt_candidates = [
            r"C:\Program Files\Microsoft Office\root\Office16\POWERPNT.EXE",
            r"C:\Program Files (x86)\Microsoft Office\root\Office16\POWERPNT.EXE",
            r"C:\Program Files\Microsoft Office\Office16\POWERPNT.EXE",
            r"C:\Program Files (x86)\Microsoft Office\Office16\POWERPNT.EXE",
        ]

    def get_app(self, visible=True):
        """安全获取或启动 PowerPoint 实例。使用 CLSID 直连以避开劫持。"""
        pythoncom.CoInitialize()
        
        # PowerPoint 唯一标识符 (CLSID)
        PPT_CLSID = "{91493441-5A91-11CF-8700-00AA0060263B}"
        
        # 1. 尝试 CLSID 获取已运行实例
        try:
            from win32com.client import dynamic
            self.app = dynamic.Dispatch(PPT_CLSID)
            print("  [COM] 通过 CLSID 挂接到现有 PowerPoint 实例。")
            return self.app
        except Exception:
            pass

        # 2. 尝试物理启动
        exe = next((p for p in self._powerpnt_candidates if Path(p).exists()), None)
        if exe:
            print(f"  [COM] 正在物理启动 PowerPoint: {exe}")
            subprocess.Popen([exe])
            # 等待启动并获取
            for _ in range(40):
                time.sleep(0.5)
                try:
                    from win32com.client import dynamic
                    self.app = dynamic.Dispatch(PPT_CLSID)
                    print("  [COM] 实例启动成功。")
                    return self.app
                except Exception:
                    pass

        # 3. 最后的保底
        print("  [COM] 使用通用 Dispatch 尝试最后机会...")
        self.app = win32com.client.Dispatch("PowerPoint.Application")
        return self.app

    def force_quit(self):
        """强制清理 PowerPoint 进程。"""
        try:
            if self.app:
                self.app.Quit()
        except Exception:
            pass
        finally:
            os.system('taskkill /F /IM POWERPNT.EXE /T >nul 2>&1')
            os.system('taskkill /F /IM ppt.exe /T >nul 2>&1')
            self.app = None

    def __enter__(self):
        return self.get_app()

    def __exit__(self, exc_type, exc_val, exc_tb):
        # 建议保留 App 运行，由主逻辑决定何时 force_quit
        pass
