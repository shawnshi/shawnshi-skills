# Antigravity Agent Tool Mappings

You are running within the Antigravity Agent framework. When following the instructions in `SKILL.md` or `system-prompt.md`, translate generic actions into your specific Antigravity tools.

1. **Ask User Question**: Use `ask_question` tool if multiple choice, or just output text to chat.
2. **Read File**: Use the `view_file` tool to read skeletons and existing templates.
3. **Write File**: 
   - First, create the project directory `C:\Users\shich\.gemini\MEMORY\slide-deck\<project-name>`.
   - Then, copy the assets: `Copy-Item -Path "C:\Users\shich\.gemini\config\skills\tool-web-slide\starter-components\assets" -Destination "C:\Users\shich\.gemini\MEMORY\slide-deck\<project-name>\" -Recurse -Force`
   - Use `write_to_file` to write the full `index.html` based on the skeleton to the target directory. You can use `replace_file_content` or `multi_replace_file_content` for surgical updates based on user feedback.
4. **Preview Server**: Launch a python server in the background using `run_command` with `WaitMsBeforeAsync=500` (e.g., `python -m http.server 4311 --directory C:\Users\shich\.gemini\MEMORY\slide-deck\<project-name>`). Provide the `http://localhost:4311/index.html` URL to the user so they can preview it.
5. **PDF Export**: Run the existing PDF export script using `run_command`: 
   `cd C:\Users\shich\.gemini\config\skills\tool-web-slide; node scripts\export-pdf.mjs "C:\Users\shich\.gemini\MEMORY\slide-deck\<project-name>\index.html" "C:\Users\shich\.gemini\MEMORY\slide-deck\<project-name>\output.pdf"`
6. **AST Validation**: Run the validator via `run_command`:
   `cd C:\Users\shich\.gemini\config\skills\tool-web-slide; node scripts\validate-deck.mjs "C:\Users\shich\.gemini\MEMORY\slide-deck\<project-name>\index.html"`

Use these tools explicitly and automatically to complete the design pipeline.
