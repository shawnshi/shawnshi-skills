import os
import sys
import argparse
import time
import json
import asyncio
import re
import wave
from pathlib import Path
try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

class FastTTSEngine:
    def __init__(self, output_dir="output"):
        self.output_dir = Path(output_dir)
        if not self.output_dir.exists():
            self.output_dir.mkdir(parents=True)
        
        # Initialize the optional Google GenAI provider.
        self.api_key = os.environ.get("GEMINI_API_KEY")
        self.model = os.environ.get("GEMINI_TTS_MODEL")
        if self.api_key and self.model and genai is not None:
            self.client = genai.Client(api_key=self.api_key)
        else:
            self.client = None
            print("WARNING: cloud TTS requires google-genai, GEMINI_API_KEY, and GEMINI_TTS_MODEL.")

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
                model=self.model,
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

    def _merge_wav(self, files, output_path):
        """Merge compatible WAV fragments in source order."""
        if not files:
            return False

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        params = None
        frames = []
        try:
            for file_path in files:
                with wave.open(str(file_path), "rb") as source:
                    current = source.getparams()
                    comparable = current[:4]
                    if params is None:
                        params = comparable
                    elif comparable != params:
                        raise ValueError("WAV fragments use incompatible audio parameters")
                    frames.append(source.readframes(source.getnframes()))

            with wave.open(str(output_path), "wb") as target:
                target.setnchannels(params[0])
                target.setsampwidth(params[1])
                target.setframerate(params[2])
                target.setcomptype(params[3], "not compressed")
                for frame_data in frames:
                    target.writeframes(frame_data)
            return True
        except Exception as exc:
            print(f"WAV_MERGE_ERROR: {exc}")
            return False

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
        
        generated_files = []
        play_count = 0
        first_audio_ready = False
        
        for i, task in enumerate(pending_synth):
            audio_path = await task
            if audio_path:
                generated_files.append(audio_path)
                if not first_audio_ready:
                    ttfs = time.time() - start_time
                    print(f"[+] 首句准备就绪 (TTFS: {ttfs:.2f}s)，开始播放...")
                    first_audio_ready = True
                
                if args.play:
                    await self._play_audio(audio_path)
                    play_count += 1

        output_written = False
        if generated_files and args.output:
            output_written = self._merge_wav(generated_files, args.output)

        for audio_path in generated_files:
            try:
                os.remove(audio_path)
            except OSError:
                pass
        
        if generated_files:
            total_duration = time.time() - start_time
            print(f"[+] SUCCESS: generated={len(generated_files)}, played={play_count}, output={output_written}, elapsed={total_duration:.2f}s")
        else:
            print(f"[!] 云端引擎调用失败。正在激活【优雅降级】方案...")
            self._speak_local(text, 180, 1.0, output_path=args.output, play=args.play)

    def _speak_local(self, text, rate, volume, output_path=None, play=False):
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
            if output_path:
                output = Path(output_path)
                output.parent.mkdir(parents=True, exist_ok=True)
                engine.save_to_file(text, str(output))
            if play:
                engine.say(text)
            engine.runAndWait()
            return True
        except: return False

async def main():
    parser = argparse.ArgumentParser(description="TTS engine with optional cloud synthesis and local fallback")
    parser.add_argument("text", help="播报内容")
    parser.add_argument("--voice", default="Charon", help="默认音色")
    parser.add_argument("--play", action="store_true", help="生成后立即播放")
    parser.add_argument("--output-dir", default="output", help="临时音频目录")
    
    # 导演模式参数
    parser.add_argument("--profile", help="Audio Profile")
    parser.add_argument("--scene", help="The Scene")
    parser.add_argument("--notes", help="Director's Notes")
    parser.add_argument("--output", help="最终 WAV 文件路径")

    args = parser.parse_args()
    
    if not args.play and not args.output:
        args.output = str(Path(args.output_dir) / "tts_output.wav")

    engine = FastTTSEngine(output_dir=args.output_dir)
    await engine.process(args.text, args)

if __name__ == "__main__":
    asyncio.run(main())
