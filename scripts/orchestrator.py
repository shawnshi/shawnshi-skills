import os
import json
import logging
import time
from typing import List, Dict, Any, Callable, Optional
from google import genai
from google.genai import types

class BasePipelineOrchestrator:
    """
    Base orchestrator for Intelligence Pipelines.
    Offloads flow control, looping, and API calls from the Antigravity Agent Prompts
    into deterministic Python scripts.
    """
    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(name)
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
            
        self._init_client()

    def _init_client(self):
        try:
            self.client = genai.Client()
        except Exception as e:
            self.logger.error(f"Failed to initialize GenAI client: {e}")
            self.client = None

    def call_llm(
        self, 
        prompt: str, 
        system_instruction: str = "", 
        model_name: str = "gemini-2.5-pro", 
        temperature: float = 0.2,
        tools: List[str] = None
    ) -> str:
        if not self.client:
            raise RuntimeError("GenAI client not initialized. Cannot call LLM.")
            
        self.logger.info(f"Calling LLM ({model_name})... Payload length: {len(prompt)}")
        
        config = types.GenerateContentConfig(
            temperature=temperature,
        )
        if system_instruction:
            config.system_instruction = system_instruction
            
        active_tools = []
        if tools:
            try:
                import tool_registry
                active_tools = [td for td in tool_registry.TOOL_DECLARATIONS if td["name"] in tools]
                if active_tools:
                    config.tools = [{"function_declarations": active_tools}]
                    self.logger.info(f"Enabled tools: {tools}")
            except ImportError as e:
                self.logger.warning(f"Could not import tool_registry. Tools disabled. {e}")

        contents = [types.Content(role="user", parts=[types.Part.from_text(text=prompt)])]
        
        # ReAct Loop
        max_turns = 5
        for turn in range(max_turns):
            try:
                response = self.client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=config
                )
                
                # Check for function calls
                if response.function_calls:
                    import tool_registry
                    contents.append(response.candidates[0].content)
                    
                    function_responses = []
                    for fc in response.function_calls:
                        tool_name = fc.name
                        args = {k: v for k, v in fc.args.items()}
                        self.logger.info(f"Executing tool: {tool_name} with args: {args}")
                        
                        if tool_name in tool_registry.TOOL_FUNCTIONS:
                            try:
                                result = str(tool_registry.TOOL_FUNCTIONS[tool_name](**args))
                            except Exception as e:
                                result = f"[Tool Execution Failed: {e}]"
                        else:
                            result = f"Unknown tool: {tool_name}"
                            
                        self.logger.info(f"Tool {tool_name} returned {len(result)} chars.")
                        
                        function_responses.append(
                            types.Part.from_function_response(
                                name=tool_name,
                                response={"result": result}
                            )
                        )
                    
                    contents.append(types.Content(role="user", parts=function_responses))
                    continue # Loop back and call LLM again with tool results
                    
                else:
                    return response.text
                    
            except Exception as e:
                self.logger.error(f"LLM Call failed: {e}")
                raise
                
        self.logger.warning("ReAct loop reached max turns. Returning last text.")
        return response.text if response.text else "Max tool turns exceeded without final text."

    def run_with_retry(self, func: Callable, max_retries: int = 3, retry_delay: int = 2, *args, **kwargs) -> Any:
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                self.logger.warning(f"Attempt {attempt+1}/{max_retries} failed: {e}")
                if attempt == max_retries - 1:
                    self.logger.error("Max retries reached. Aborting.")
                    raise
                time.sleep(retry_delay)
        return None

    def read_file(self, file_path: str) -> str:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()

    def write_file(self, file_path: str, content: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        self.logger.info(f"File written to: {file_path}")
