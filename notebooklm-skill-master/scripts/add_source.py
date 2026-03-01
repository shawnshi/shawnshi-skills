#!/usr/bin/env python3
"""
Add Source to NotebookLM
Automates the process of adding a file or a link to a specific notebook.
"""

import sys
import time
import argparse
from pathlib import Path
from patchright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# Add parent directory to path to import other modules
sys.path.insert(0, str(Path(__file__).parent))

from browser_utils import BrowserFactory, StealthUtils
from notebook_manager import NotebookLibrary

def wait_for_ready(page):
    """Wait for the NotebookLM page to be fully loaded and ready"""
    try:
        # Wait for either the chat box or the source panel
        page.wait_for_selector("textarea.query-box-input, .source-list-container, button[aria-label*='Add source']", timeout=15000, state="visible")
    except Exception:
        pass
    
    # Random human-like delay
    StealthUtils.random_delay(1000, 2000)

def add_file(page, file_path: str):
    """Add a file source to the notebook"""
    path = Path(file_path).absolute()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    print(f"📄 Attempting to upload file: {path.name}...")
    
    try:
        # Most modern web apps have a global hidden file input handling uploads
        # Let's try to find it and directly set the file
        file_input = page.query_selector("input[type='file']")
        
        if file_input:
            print("  🔧 Found direct file input tag. Uploading...")
            file_input.set_input_files(str(path))
        else:
            # Fallback: Try to open the 'Add source' menu first
            # Look for common aria-labels or text indicating "Add source"
            print("  🔍 Looking for 'Add source' menu...")
            
            # Common selectors for the add source button
            add_selectors = [
                "button[aria-label*='Add source' i]",
                "button[aria-label*='Datenquelle hinzufügen' i]",  # German
                "button[aria-label*='添加数据源' i]",  # Chinese
                "button:has-text('Add source')",
                "div[role='button']:has-text('Add source')"
            ]
            
            clicked = False
            for selector in add_selectors:
                elements = page.query_selector_all(selector)
                for el in elements:
                    if el.is_visible():
                        StealthUtils.random_delay(300, 600)
                        el.click()
                        clicked = True
                        break
                if clicked:
                    break
                    
            if not clicked:
                print("  ⚠️ Could not find explicit 'Add source' button. Trying to inject file anyway via dom evaluation...")
                # Inject a file input into the DOM and trigger the drop/change event (fallback strategy)
                # But typically playwright's set_input_files works better if we can just wait for it
                
            StealthUtils.random_delay(1000, 2000)
            
            # Now wait for the file input which might have been dynamically inserted
            page.set_input_files("input[type='file']", str(path), timeout=5000)
            
        print("  ⏳ Waiting for upload to complete...")
        # Give it some time to process the file
        StealthUtils.random_delay(5000, 10000)
        
        # Check if there's an 'Insert' or 'Upload' confirmation button (sometimes required)
        confirm_selectors = ["button:has-text('Insert')", "button:has-text('Upload')", "button:has-text('Add')"]
        for selector in confirm_selectors:
            elements = page.query_selector_all(selector)
            for el in elements:
                if el.is_visible() and "source" not in el.inner_text().lower():
                    el.click()
                    StealthUtils.random_delay(500, 1000)
                    
        print("✅ File upload sequence completed.")
        
    except Exception as e:
        print(f"❌ Failed to upload file: {e}")
        raise

def add_link(page, url: str):
    """Add a website link source to the notebook"""
    print(f"🔗 Attempting to add website link: {url}...")
    
    try:
        # Step 1: Open the 'Add source' menu
        print("  🔍 Opening 'Add source' menu...")
        add_selectors = [
            "button[aria-label*='Add source' i]",
            "button[aria-label*='Datenquelle hinzufügen' i]",
            "button[aria-label*='添加数据源' i]",
            "div.add-source-button",
            "button:has-text('Add source')"
        ]
        
        clicked_add = False
        for selector in add_selectors:
            elements = page.query_selector_all(selector)
            for el in elements:
                if el.is_visible():
                    StealthUtils.random_delay(300, 600)
                    el.click()
                    clicked_add = True
                    break
            if clicked_add:
                break
                
        if not clicked_add:
            print("  ⚠️ Could not find 'Add source' button. It might be in a different language or already open.")
            
        StealthUtils.random_delay(1000, 2000)
        
        # Step 2: Click the 'Website' or 'Link' option
        print("  🖱️ Selecting 'Website' option...")
        website_selectors = [
            "text='Website'",
            "text='网页链接'",
            "text='Website link'",
            "[aria-label*='Website' i]"
        ]
        
        clicked_website = False
        for selector in website_selectors:
            try:
                el = page.wait_for_selector(selector, timeout=3000, state="visible")
                if el:
                    el.click()
                    clicked_website = True
                    break
            except PlaywrightTimeoutError:
                pass
                
        if not clicked_website:
            print("  ⚠️ Could not explicitly click 'Website'. Attempting to find input box directly.")
            
        StealthUtils.random_delay(1000, 2000)
        
        # Step 3: Type the URL in the input box
        print("  ⌨️ Typing URL...")
        input_selectors = [
            "input[type='url']",
            "input[placeholder*='URL' i]",
            "input[placeholder*='http' i]",
            "input[aria-label*='URL' i]"
        ]
        
        input_found = False
        for selector in input_selectors:
            elements = page.query_selector_all(selector)
            for el in elements:
                if el.is_visible():
                    el.click()
                    StealthUtils.random_delay(200, 500)
                    for char in url:
                        page.keyboard.press(char)
                        time.sleep(0.01)
                    input_found = True
                    break
            if input_found:
                break
                
        if not input_found:
            raise Exception("Could not find the URL input field.")
            
        StealthUtils.random_delay(500, 1000)
            
        # Step 4: Click 'Insert' or press Enter
        print("  🚀 Submitting URL...")
        submit_selectors = [
            "button:has-text('Insert')",
            "button:has-text('Add')",
            "button:has-text('添加')",
            "button:has-text('插入')"
        ]
        
        submitted = False
        for selector in submit_selectors:
            elements = page.query_selector_all(selector)
            for el in elements:
                if el.is_visible():
                    el.click()
                    submitted = True
                    break
            if submitted:
                break
                
        if not submitted:
            # Fallback: Just press Enter
            page.keyboard.press("Enter")
            
        print("  ⏳ Waiting for source to be processed...")
        StealthUtils.random_delay(4000, 7000)
        
        print("✅ Link added successfully.")
        
    except Exception as e:
        print(f"❌ Failed to add link: {e}")
        raise

def main():
    parser = argparse.ArgumentParser(description='Add a source (file or link) to a NotebookLM notebook.')
    parser.add_argument('--notebook', required=True, help='ID or Name of the notebook')
    parser.add_argument('--type', required=True, choices=['file', 'link'], help='Type of source to add')
    parser.add_argument('--path', required=True, help='Path to the file or URL to the link')
    parser.add_argument('--headless', action='store_true', help='Run in headless mode (default: False for debugging UI issues)')
    
    args = parser.parse_args()

    # Load library
    library = NotebookLibrary()
    
    # Try finding exact ID first
    notebook = library.get_notebook(args.notebook)
    if not notebook:
        # Search by name/topics/etc
        results = library.search_notebooks(args.notebook)
        if not results:
            print(f"❌ Notebook not found: '{args.notebook}'")
            print("To list available notebooks: python scripts/run.py notebook_manager.py list")
            sys.exit(1)
        notebook = results[0]
        print(f"🔍 Searched and found notebook: {notebook['name']} ({notebook['id']})")
        
    notebook_url = notebook['url']
    print(f"🌐 Navigating to {notebook['name']}...")
    
    with sync_playwright() as playwright:
        # Launch browser
        # For Add Source, it's highly recommended to start visible if having issues,
        # so we default headless = False if user didn't explicitly request headless.
        # But for agent automation, headless is preferred.
        # Check if running in a pure headless server environment
        context = BrowserFactory.launch_persistent_context(playwright, headless=args.headless)
        
        try:
            page = context.new_page()
            page.goto(notebook_url, wait_until="domcontentloaded", timeout=60000)
            
            # Check login
            if "accounts.google.com" in page.url:
                print("❌ Authentication required. Please run auth_manager.py setup first.")
                sys.exit(1)
            
            wait_for_ready(page)
            
            if args.type == 'file':
                add_file(page, args.path)
            elif args.type == 'link':
                add_link(page, args.path)
                
            # Allow final sync
            StealthUtils.random_delay(2000, 4000)
            
        except Exception as e:
            print(f"❌ Operation failed: {e}")
            sys.exit(1)
        finally:
            context.close()

if __name__ == "__main__":
    main()
