import subprocess
import sys
import os
import argparse
import pyttsx3

class HybridTTSEngine:
    def __init__(self, output_dir="output"):
        self.output_dir = output_dir
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

    def _speak_cloud(self, text, voice, output_path, rate, pitch):
        """尝试使用神经网络云端引擎 (Edge-TTS)"""
        temp_txt = os.path.join(self.output_dir, "temp_tts_input.txt")
        try:
            with open(temp_txt, "w", encoding="utf-8") as f:
                f.write(text)
            
            # 构造指令
            cmd = [
                "edge-tts",
                "--file", temp_txt,
                "--voice", voice,
                "--write-media", output_path,
                "--rate", rate,
                "--pitch", pitch
            ]
            
            # 执行合成
            result = subprocess.run(cmd, check=True, capture_output=True)
            
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                return True
            return False
        except Exception:
            return False
        finally:
            if os.path.exists(temp_txt):
                os.remove(temp_txt)

    def _speak_local(self, text, rate, volume):
        """本地 SAPI5 引擎兜底播报"""
        try:
            engine = pyttsx3.init()
            # 寻找中文音色
            voices = engine.getProperty('voices')
            for v in voices:
                if "Chinese" in v.name or "Huihui" in v.name:
                    engine.setProperty('voice', v.id)
                    break
            
            engine.setProperty('rate', rate)
            engine.setProperty('volume', volume)
            engine.say(text)
            engine.runAndWait()
            return True
        except Exception as e:
            print(f"LOCAL_ERROR: {str(e)}")
            return False

    def process(self, text, args):
        print(f"[*] 正在请求神经网络云端引擎...")
        
        # 1. 尝试云端生成
        success = self._speak_cloud(text, args.voice, args.output, args.rate, args.pitch)
        
        if success:
            print(f"[+] SUCCESS: 神经网络音频已固化至 {args.output}")
            if args.play:
                print("[*] 正在执行高保真播报...")
                os.startfile(os.path.abspath(args.output))
        else:
            # 2. 云端失败，启动本地兜底
            print(f"[!] 云端引擎握手失败。正在激活【优雅降级】方案...")
            print(f"[*] 启动 Win32 本地物理链路...")
            fallback_success = self._speak_local(text, 180, 1.0)
            if not fallback_success:
                print("[-] CRITICAL: 所有语音链路均已失效。")
                sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Gemini TTS 2.0 Hybrid Engine")
    parser.add_argument("text", help="播报内容")
    parser.add_argument("--voice", default="zh-CN-Yunxi-Neural", help="神经网络音色")
    parser.add_argument("--output", default="output/broadcast.mp3", help="音频保存路径")
    parser.add_argument("--rate", default="+0%", help="云端语速")
    parser.add_argument("--pitch", default="+0Hz", help="云端音调")
    parser.add_argument("--play", action="store_true", default=True, help="是否播放")

    args = parser.parse_args()
    
    engine = HybridTTSEngine()
    engine.process(args.text, args)

if __name__ == "__main__":
    main()
