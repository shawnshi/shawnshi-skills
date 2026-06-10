import urllib.request
import urllib.parse
from html.parser import HTMLParser
import subprocess
import json

class SimpleHTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.text = []
    def handle_data(self, d):
        self.text.append(d)
    def get_data(self):
        return ''.join(self.text)

def strip_tags(html):
    s = SimpleHTMLStripper()
    s.feed(html)
    return s.get_data()

def search_web(query: str) -> str:
    """Perform a web search and return results."""
    try:
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
        req = urllib.request.Request(
            url, 
            data=None, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8', errors='ignore')
            text = strip_tags(html)
            # Rough extraction of snippets
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            return "\n".join(lines[:50]) # Return first chunk of text
    except Exception as e:
        return f"[Tool Execution Failed: Search failed with error {e}]"

def fetch_url_content(url: str) -> str:
    """Fetch the text content of a URL."""
    try:
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8', errors='ignore')
            text = strip_tags(html)
            return text[:4000] # Return max 4000 chars to avoid context blowup
    except Exception as e:
        return f"[Tool Execution Failed: Fetch failed with error {e}]"

def query_vector_lake(query: str) -> str:
    """Query the local Vector Lake."""
    try:
        result = subprocess.run(
            ["python", r"C:\Users\shich\.gemini\config\plugins\vector-lake\scripts\query.py", query],
            capture_output=True, text=True, encoding="utf-8", timeout=15
        )
        if result.returncode == 0:
            return result.stdout[:4000]
        return f"[Tool Execution Failed: Vector Lake error: {result.stderr}]"
    except Exception as e:
        return f"[Tool Execution Failed: Vector Lake execution failed {e}]"

TOOL_FUNCTIONS = {
    "Search_Web": search_web,
    "Fetch_URL_Content": fetch_url_content,
    "Query_Vector_Lake": query_vector_lake
}

TOOL_DECLARATIONS = [
    {
        "name": "Search_Web",
        "description": "Perform a web search to find current information, news, or competitor data.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "The search query."}
            },
            "required": ["query"]
        }
    },
    {
        "name": "Fetch_URL_Content",
        "description": "Fetch the raw text content of a specific URL.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "url": {"type": "STRING", "description": "The URL to fetch."}
            },
            "required": ["url"]
        }
    },
    {
        "name": "Query_Vector_Lake",
        "description": "Query the local Vector Lake for historical, internal, or strategic memory.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "The search query."}
            },
            "required": ["query"]
        }
    }
]
