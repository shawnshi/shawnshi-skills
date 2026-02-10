#!/usr/bin/env python3
"""
List Remote Notebooks from NotebookLM
Navigates to the home page and extracts available notebooks
"""

import sys
import time
import json
from pathlib import Path
from patchright.sync_api import sync_playwright

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from auth_manager import AuthManager
from browser_utils import BrowserFactory

def list_remote_notebooks(headless: bool = False):
    auth = AuthManager()

    if not auth.is_authenticated():
        print("⚠️ Not authenticated. Run: python scripts/run.py auth_manager.py setup")
        return None

    print("🌐 Fetching notebook list from NotebookLM...")

    playwright = None
    context = None

    try:
        playwright = sync_playwright().start()
        context = BrowserFactory.launch_persistent_context(playwright, headless=headless)
        page = context.new_page()

        # Navigate to NotebookLM home
        page.goto("https://notebooklm.google.com/", wait_until="domcontentloaded")

        # Wait for notebook cards to load
        print("  ⏳ Waiting for notebooks to load...")
        time.sleep(10) # Heavy sleep to ensure load
        
        # Try to find ANY links or clickable items that look like notebooks
        selectors = [
            "a[href*='/notebook/']",
            "div[role='link'][aria-label*='notebook']",
            ".notebook-card",
            "[data-notebook-id]"
        ]
        
        found = False
        for selector in selectors:
            try:
                page.wait_for_selector(selector, timeout=5000)
                print(f"  ✓ Found notebooks with selector: {selector}")
                found = True
                break
            except:
                continue

        if not found:
            print("  ⚠️ No standard selectors found. Attempting broad search.")
            page.screenshot(path="debug_home_v2.png")

        # Extract notebook info
        notebook_elements = page.query_selector_all("a[href*='/notebook/']")
        
        notebooks = []
        seen_urls = set()

        for el in notebook_elements:
            try:
                name_el = el.query_selector("div") # Usually name is inside a div
                name = name_el.inner_text().strip() if name_el else el.inner_text().strip()
                url = el.get_attribute("href")
                
                if not url.startswith("http"):
                    url = "https://notebooklm.google.com" + url
                
                # Filter out duplicates and common UI elements
                if url not in seen_urls and "/notebook/" in url:
                    # Clean URL (remove fragments/query)
                    clean_url = url.split("?")[0].split("#")[0]
                    if clean_url not in seen_urls:
                        notebooks.append({
                            "name": name if name else "Untitled Notebook",
                            "url": clean_url
                        })
                        seen_urls.add(clean_url)
            except:
                continue

        return notebooks

    except Exception as e:
        print(f"  ❌ Error: {e}")
        return None
    finally:
        if context: context.close()
        if playwright: playwright.stop()

if __name__ == "__main__":
    notebooks = list_remote_notebooks(headless=True)
    if notebooks:
        print(f"\n✅ Found {len(notebooks)} notebooks:\n")
        for i, nb in enumerate(notebooks, 1):
            print(f"  {i}. {nb['name']}")
            print(f"     URL: {nb['url']}")
            print()
    elif notebooks == []:
        print("\n📭 No notebooks found in your account.")
    else:
        print("\n❌ Failed to retrieve notebook list.")
