import os
import sys
import argparse
import pyttsx3
import time
import json
import asyncio
import re
import wave
from pathlib import Path
from google import genai
from google.genai import types

class FastTTSEngine:
    def __init__(self, output_dir="output"):
        self.output_dir = Path(output_dir)
        if not self.output_dir.exists():
            self.output_dir.mkdir(parents=True)
        
        # Initialize Gemini API Client
        self.api_key = os.environ.get("GEMINI_API_KEY")
        if self.api_key:
            self.client = genai.Client(api_key=self.api_key)
        else:
            self.client = None
            print("⚠️ WARNING: GEMINI_API_KEY not found in environment.")

    def _save_as_wav(self, filename, pcm_data, channels=1, rate=24000, sample_width=2):
        """将 raw PCM 数据封装为 WAV 格式"""
        try:
            with wave.open(str(filename), 'wb') as wf:
                wf.setnchannels(channels)
                wf.setsampwidth(sample_width)
                wf.setframerate(rate)
                wf.writeframes(pcm_data)
            return True
        except Exception as e:
            print(f"WAV_SAVE_ERROR: {e}")
            return False

    def _format_director_prompt(self, text, profile=None, scene=None, notes=None):
        """构造“导演模式”结构化提示词"""
        prompt = []
        if profile: prompt.append(f"# AUDIO PROFILE: {profile}")
        if scene: prompt.append(f"## THE SCENE: {scene}")
        if notes: prompt.append(f"### DIRECTOR'S NOTES\n{notes}")
        prompt.append(f"\n#### TRANSCRIPT\n{text}")
        return "\n".join(prompt)

    async def _synthesize_sentence(self, text, voice, index, args):
        """合成单句音频 (支持 Director Mode & 动态音色映射)"""
        if not self.client: return None
        
        output_path = self.output_dir / f"part_{index}.wav"
        
        # 1. 提取并剥离 Speaker 标签
        speaker_match = re.match(r'^(\w+):\s*(.*)', text, re.DOTALL)
        v_name = voice
        clean_text = text
        
        if speaker_match:
            speaker_name = speaker_match.group(1)
            clean_text = speaker_match.group(2)
            # 角色音色映射
            mapping = {"Commander": "Charon", "Technical": "Puck", "Expert": "Kore", "Aoede": "Aoede"}
            v_name = mapping.get(speaker_name, voice)
        
        # 2. 构造带环境背景的提示词
        full_prompt = self._format_director_prompt(
            clean_text, profile=args.profile, scene=args.scene, notes=args.notes
        )

        # 3. 使用标准的 voice_config (因为切片后是单说话人请求，更稳定)
        speech_config = types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=v_name)
            )
        )

        try:
            response = self.client.models.generate_content(
                model='gemini-3.1-flash-tts-preview',
                contents=full_prompt,
                config=types.GenerateContentConfig(
                    response_modalities=['AUDIO'],
                    speech_config=speech_config
                )
            )
            
            audio_bytes = None
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if part.inline_data:
                        audio_bytes = part.inline_data.data
                        break
            
            if audio_bytes:
                self._save_as_wav(output_path, audio_bytes)
                return output_path
        except Exception as e:
            print(f"SYNTH_ERROR_{index}: {e}")
        return None

    async def _play_audio(self, file_path):
        """后台静默播放音频"""
        if not file_path or not Path(file_path).exists(): return
        
        cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(file_path)]
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.wait()

    def _split_text(self, text):
        """将文本切分为句子，并保留 Speaker 标识"""
        sentences = re.split(r'(?<=[。！？.!?;；])\s*', text)
        result = []
        current_speaker = None
        
        for s in sentences:
            s = s.strip()
            if not s: continue
            
            speaker_match = re.match(r'^(\w+):', s)
            if speaker_match:
                current_speaker = speaker_match.group(1)
                result.append(s)
            else:
                if current_speaker:
                    result.append(f"{current_speaker}: {s}")
                else:
                    result.append(s)
        return result

    async def process(self, text, args):
        mode = "Director" if (args.scene or args.profile or args.notes) else "Standard"
        print(f"[*] 正在启动【并行极速引擎 ({mode})】...")
        start_time = time.time()
        
        sentences = self._split_text(text)
        if not sentences: sentences = [text]
        
        # 并行任务队列
        pending_synth = [asyncio.create_task(self._synthesize_sentence(s, args.voice, i, args)) 
                         for i, s in enumerate(sentences)]
        
        play_count = 0
        first_audio_ready = False
        
        for i, task in enumerate(pending_synth):
            audio_path = await task
            if audio_path:
                if not first_audio_ready:
                    ttfs = time.time() - start_time
                    print(f"[+] 首句准备就绪 (TTFS: {ttfs:.2f}s)，开始播放...")
                    first_audio_ready = True
                
                await self._play_audio(audio_path)
                play_count += 1
                try: os.remove(audio_path)
                except: pass
        
        if play_count > 0:
            total_duration = time.time() - start_time
            print(f"[+] SUCCESS: 播报完成 (总耗时: {total_duration:.2f}s)")
        else:
            print(f"[!] 云端引擎调用失败。正在激活【优雅降级】方案...")
            self._speak_local(text, 180, 1.0)

    def _speak_local(self, text, rate, volume):
        try:
            import pyttsx3
            engine = pyttsx3.init()
            voices = engine.getProperty('voices')
            for v in voices:
                if "Chinese" in v.name:
                    engine.setProperty('voice', v.id)
                    break
            engine.setProperty('rate', rate)
            engine.setProperty('volume', volume)
            engine.say(text)
            engine.runAndWait()
            return True
        except: return False

async def main():
    parser = argparse.ArgumentParser(description="Gemini TTS Parallel Fast Engine")
    parser.add_argument("text", help="播报内容")
    parser.add_argument("--voice", default="Charon", help="默认音色")
    parser.add_argument("--play", action="store_true", default=True)
    
    # 导演模式参数
    parser.add_argument("--profile", help="Audio Profile")
    parser.add_argument("--scene", help="The Scene")
    parser.add_argument("--notes", help="Director's Notes")
    parser.add_argument("--output", help=argparse.SUPPRESS)

    args = parser.parse_args()
    
    engine = FastTTSEngine()
    await engine.process(args.text, args)

if __name__ == "__main__":
    asyncio.run(main())
