import selenium
import requests
import time
import re
import os
import json
from datetime import datetime, timedelta
from collections import defaultdict
import sys
if sys.platform == "win32": # Only import winreg on Windows
    import winreg
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from bs4 import BeautifulSoup
import logging

# Global variable for the default server URL
default_server_url = None

# Functions from daad_scraper_new.py

def set_windows_proxy_from_pac(pac_url):
    """Set Windows system proxy from PAC URL"""
    if sys.platform == "win32":
        try:
            reg_path = r"Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, "AutoConfigURL", 0, winreg.REG_SZ, pac_url)
            logging.info(f"System proxy PAC set to: {pac_url}")
        except Exception as e:
            logging.error(f"Failed to set system proxy: {e}")
    else:
        logging.info("Skipping PAC proxy setup: Not on Windows.")

def setup_driver(use_headless=True):
    """Set up and return a configured Chrome WebDriver with enhanced error handling"""
    options = webdriver.ChromeOptions()

    # System-specific settings for stability
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')

    # Comprehensive GPU and graphics handling
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-gpu-sandbox')
    options.add_argument('--disable-software-rasterizer')
    options.add_argument('--disable-gpu-compositing')
    options.add_argument('--disable-gpu-program-cache')
    options.add_argument('--disable-gpu-watchdog')
    options.add_argument('--disable-accelerated-2d-canvas')
    options.add_argument('--disable-accelerated-video-decode')
    options.add_argument('--disable-webgl')

    # Memory and process handling
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-browser-side-navigation')
    options.add_argument('--disable-site-isolation-trials')
    options.add_argument('--disable-infobars')
    options.add_argument('--window-size=1920,1080')

    # Error handling and logging
    options.add_argument('--log-level=3')  # Only show fatal errors
    options.add_argument('--silent')
    options.add_experimental_option('excludeSwitches', ['enable-logging'])

    if use_headless:
        options.add_argument('--headless=new')
        logging.info("Starting browser in headless mode...")
    else:
        logging.info("Starting browser in visible mode...")

    # Enhanced error handling for driver initialization
    max_retries = 3
    last_exception = None

    for attempt in range(max_retries):
        try:
            try:
                service = Service("./chromedriver.exe")
                driver = webdriver.Chrome(service=service, options=options)
                logging.info("Successfully initialized Chrome driver with local chromedriver.exe")
                return driver
            except Exception as e:
                logging.warning(f"Local chromedriver.exe failed, trying system ChromeDriver: {str(e)}")
                driver = webdriver.Chrome(options=options)
                logging.info("Successfully initialized Chrome driver with system ChromeDriver")
                return driver
        except Exception as e:
            last_exception = e
            logging.warning(f"Attempt {attempt + 1} failed: {str(e)}")
            time.sleep(2)  # Wait before retrying

    # If all attempts failed, try one last time with current directory chromedriver
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        chromedriver_path = os.path.join(current_dir, "chromedriver.exe")
        service = Service(chromedriver_path)
        driver = webdriver.Chrome(service=service, options=options)
        logging.info(f"Successfully initialized Chrome driver with chromedriver at: {chromedriver_path}")
        return driver
    except Exception as final_e:
        error_msg = f"Failed to initialize Chrome driver after {max_retries} attempts.\n"
        error_msg += f"Last error: {str(last_exception)}\n"
        error_msg += f"Final attempt error: {str(final_e)}"
        logging.error(error_msg)
        raise RuntimeError(error_msg)

def handle_cookie_consent(driver):
    """Handle cookie consent popup if present"""
    try:
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR,
                '#cookie-consent button, .cookie-banner button, .consent-button, button[data-testid="cookie-accept-all"], button[id*="cookie-accept"]'))
        ).click()
        logging.info("Cookie consent handled")
    except TimeoutException:
        logging.info("No cookie consent found or already accepted")
    except Exception as e:
        logging.warning(f"Error handling cookie consent: {e}")


def get_page_content(driver, url):
    """Get the content of a page, handling timeouts and retrying if needed"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            driver.get(url)
            time.sleep(3)  # Initial wait
            return True
        except Exception as e:
            if attempt < max_retries - 1:
                logging.warning(f"Attempt {attempt + 1} to load {url} failed: {e}. Retrying...")
                time.sleep(2)
            else:
                logging.error(f"Failed to load page {url} after {max_retries} attempts: {e}")
                return False

def extract_text_safely(element, selector):
    """Safely extract text from an element using a CSS selector"""
    try:
        elem = element.find_element(By.CSS_SELECTOR, selector)
        return elem.text.strip()
    except (NoSuchElementException, AttributeError) : # Removed InvalidSelectorException for now as it's handled by validate_selector
        logging.debug(f"Failed to extract text with selector {selector}")
        return ""

def find_element_with_retry(driver, by, selector, max_retries=3, timeout=10):
    """Find an element with retry logic for stale elements"""
    for attempt in range(max_retries):
        try:
            return WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((by, selector))
            )
        except StaleElementReferenceException:
            if attempt == max_retries - 1:
                logging.error(f"StaleElementReferenceException after {max_retries} retries for selector {selector}")
                raise
            logging.debug(f"Stale element, retrying... ({attempt + 1}/{max_retries}) for selector {selector}")
            time.sleep(1)
        except TimeoutException:
            if attempt == max_retries - 1:
                logging.debug(f"TimeoutException after {max_retries} retries for selector {selector}")
                # Not raising here, as sometimes we want to know if an element is not found
                return None
            logging.debug(f"Timeout, retrying... ({attempt + 1}/{max_retries}) for selector {selector}")
            time.sleep(1)
    return None # Explicitly return None if not found after retries


def validate_selector(selector):
    """Validate if a CSS selector is syntactically correct"""
    try:
        # Simple validation of common selector patterns
        if not selector or not isinstance(selector, str):
            return False
        # Check for unmatched brackets, quotes, or parentheses
        brackets = sum(1 if c in '[(' else -1 if c in '])' else 0 for c in selector)
        quotes = sum(1 if c in '"' else 0 for c in selector)
        return brackets == 0 and quotes % 2 == 0
    except Exception:
        return False

def extract_text_with_fallback(element, selector):
    """Extract text from an element with multiple fallback methods"""
    try:
        # Try direct text extraction first
        text = element.text.strip()
        if text:
            return text

        # Try getting text via JavaScript
        text = element.get_attribute('textContent').strip()
        if text:
            return text

        # Try getting inner text
        text = element.get_attribute('innerText').strip()
        if text:
            return text

    except Exception as e:
        logging.debug(f"Failed to extract text with selector {selector}: {e}")

    return ""

# Placeholder for AI and classification functions (will be added from aj_scraper.py or daad_scraper_new.py)
def ollama_highlight(text, model="deepseek-r1:70b", host=None):
    """Generate position highlights, falling back to backup model if main model fails"""
    global default_server_url
    servers = [host] if host else ["http://rf-calcul:11434"]
    if default_server_url:
        if default_server_url in servers:
            servers.remove(default_server_url)
        servers.insert(0, default_server_url)

    prompt = (
        f"Please analyze this academic position posting and summarize its key highlights, strengths, and location advantages.\n\n"
        f"Requirements:\n"
        f"1. Analyze institution reputation, research focus, team strength, and resources\n"
        f"2. Emphasize location advantages: city characteristics, environment, accessibility, international atmosphere\n"
        f"3. Output a concise description (100-150 words)\n"
        f"4. Focus on core highlights\n"
        f"5. Use engaging language to highlight competitive advantages\n\n"
        f"Position details:\n{text[:2000]}"
    )

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.7,
            "top_p": 0.9
        }
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    last_error = None
    for server_url_to_try in servers: # Renamed to avoid conflict with global
        try:
            url = f"{server_url_to_try}/api/generate"
            logging.info(f"Using {model} model on {server_url_to_try} to generate highlights...")

            resp = requests.post(url, json=payload, headers=headers, timeout=600)
            resp.raise_for_status()

            result = resp.json()
            if not isinstance(result, dict) or "response" not in result:
                logging.error(f"Invalid API response format: {result}")
                raise Exception("Invalid API response format")

            highlight = result["response"].strip()
            logging.info("Successfully generated highlights")

            # Update the default server URL
            default_server_url = server_url_to_try

            # Clean up common AI prefixes
            common_prefixes = [
                "highlights include", "key highlights:", "summary:", "analysis:",
                "main points:", "key features:", "highlights:", "strengths:",
                "advantages:", "position offers:", "overview:", "assessment:",
                "key aspects:", "evaluation:", "review:", "analysis shows:",
                "this position:", "main advantages:", "key benefits:",
            ]

            for prefix in common_prefixes:
                if highlight.lower().startswith(prefix.lower()):
                    highlight = highlight[len(prefix):].strip()

            # Remove thinking patterns and normalize whitespace
            highlight = re.sub(r'<think>.*?</think>', '', highlight, flags=re.DOTALL)
            highlight = re.sub(r'\n\s*\n', '\n', highlight).strip()

            return highlight

        except requests.exceptions.Timeout:
            logging.warning(f"Request timeout for server {server_url_to_try}")
            last_error = "timeout"
            continue
        except Exception as e:
            logging.warning(f"Failed to call server {server_url_to_try}: {e}")
            last_error = str(e)
            continue

    # If all servers failed, try backup model
    backup_model = "qwen3:30b-a3b"
    logging.warning(f"All servers failed ({last_error}), trying backup model {backup_model}...")

    try:
        # Use a simpler prompt with backup model
        simple_prompt = f"Please summarize the key highlights and features of this academic position:\n\n{text[:1000]}"
        payload["model"] = backup_model
        payload["prompt"] = simple_prompt

        # Try all servers again with backup model
        for server_url_to_try in servers: # Renamed to avoid conflict with global
            try:
                resp = requests.post(
                    f"{server_url_to_try}/api/generate",
                    json=payload,
                    headers=headers,
                    timeout=600
                )
                resp.raise_for_status()
                result = resp.json()
                highlight_text = result.get("response", "").strip() # Renamed to avoid conflict
                if highlight_text:
                    # Update the default server URL
                    default_server_url = server_url_to_try
                    return highlight_text
            except Exception:
                continue
    except Exception as e:
        logging.error(f"Backup model failed: {e}")

    # If all AI attempts fail, use simple extraction
    logging.warning("All models failed, using simple extraction method...")
    institution_match = re.search(r'(?:university|institute)[\s:]*([\w\s]+)', text, re.IGNORECASE)
    location_match = re.search(r'(?:location)[\s:]*([\w\s,]+)', text, re.IGNORECASE)
    field_match = re.search(r'(?:research|field)[\s:]*([\w\s,]+)', text, re.IGNORECASE)

    highlight_parts = []
    if institution_match:
        highlight_parts.append(f"{institution_match.group(1)} is a renowned academic institution")
    if location_match:
        city = location_match.group(1).strip()
        highlight_parts.append(f"located in {city}")
    if field_match:
        highlight_parts.append(f"with notable research in {field_match.group(1)}")

    if highlight_parts:
        return " ".join(highlight_parts) + ". The position offers excellent research facilities, an international academic environment, and strong development opportunities."
    else:
        return "The position offers an international academic environment, excellent research facilities, and strong development prospects."

def check_ai_server(host="http://rf-calcul:11434"):
    """Check if the AI server is available and models are loaded"""
    global default_server_url
    servers = [host] if host else ["http://rf-calcul:11434"] # Prioritize specified host
    if default_server_url and default_server_url not in servers:
        servers.append(default_server_url) # Add last known good server if not already included

    for server_url_to_try in servers:
        try:
            logging.info(f"Checking server connection at {server_url_to_try}...")
            resp = requests.get(f"{server_url_to_try}/api/version", timeout=5)
            resp.raise_for_status()
            version = resp.json().get('version', 'unknown')
            logging.info(f"Server connection successful. Ollama version: {version} at {server_url_to_try}")

            default_server_url = server_url_to_try # Set as default if connection is successful

            models_to_check = ["deepseek-r1:70b", "qwen3:30b-a3b"] # Models we ideally want
            available_models_on_server = []

            try:
                logging.info(f"Fetching available models from {server_url_to_try}...")
                tags_resp = requests.get(f"{server_url_to_try}/api/tags", timeout=30)
                tags_resp.raise_for_status()
                tags_data = tags_resp.json()

                all_server_models = [model_info.get('name') for model_info in tags_data.get('models', [])]
                logging.info(f"Models on server {server_url_to_try}: {', '.join(all_server_models)}")

                for model_name in models_to_check:
                    if model_name in all_server_models:
                        available_models_on_server.append(model_name)
                        logging.info(f"Model {model_name} exists on server {server_url_to_try}.")
                    else:
                        logging.warning(f"Model {model_name} does not exist on server {server_url_to_try}.")
            except Exception as e:
                logging.error(f"Failed to get model list from {server_url_to_try}: {e}")
                logging.info("Attempting to check each required model individually...")

            if len(available_models_on_server) < len(models_to_check):
                for model_name in models_to_check:
                    if model_name not in available_models_on_server and check_model_availability(model_name, server_url_to_try):
                        available_models_on_server.append(model_name)
                        logging.info(f"Model {model_name} is available on server {server_url_to_try}.")

            if not available_models_on_server:
                logging.warning(f"No required models are available on server {server_url_to_try}.")
                continue # Try next server

            logging.info(f"Found {len(available_models_on_server)} required models on server {server_url_to_try}.")
            return True # Found a working server with models

        except Exception as e:
            logging.warning(f"Server {server_url_to_try} connection failed: {e}")
            if server_url_to_try == default_server_url: # If the default failed, unset it
                default_server_url = None
            continue

    logging.error("All attempted AI servers failed to connect or lack required models.")
    return False

def list_available_models(host=None):
    """List all available models on the server"""
    global default_server_url
    server_to_use = host or default_server_url or "http://rf-calcul:11434"
    try:
        logging.info(f"Listing available models from {server_to_use}...")
        resp = requests.get(f"{server_to_use}/api/tags", timeout=30)
        resp.raise_for_status()
        models_data = resp.json()
        available_models_list = []

        for model_info in models_data.get('models', []):
            model_name = model_info.get('name', '')
            if model_name:
                available_models_list.append(model_name)
        logging.info(f"Found models: {available_models_list}")
        return available_models_list
    except Exception as e:
        logging.error(f"Failed to list models from {server_to_use}: {e}")
        return []

def select_model():
    """Let user select which model to use"""
    models = list_available_models()
    if not models:
        logging.warning("Cannot get model list. Using default model deepseek-r1:70b")
        return "deepseek-r1:70b"

    print("\nAvailable models:")
    for i, model_name in enumerate(models, 1):
        print(f"{i}. {model_name}")

    while True:
        try:
            choice = input("\nSelect model to use (enter number): ")
            idx = int(choice) - 1
            if 0 <= idx < len(models):
                selected = models[idx]
                logging.info(f"User selected model: {selected}")
                return selected
            else:
                print("Invalid selection. Please try again.")
        except ValueError:
            print("Please enter a valid number.")
        except KeyboardInterrupt:
            logging.info("\nSelection cancelled. Using default model deepseek-r1:70b")
            return "deepseek-r1:70b"

def check_model_availability(model_name_to_check, host=None):
    """Check if a specific model is available and loaded. Returns True if available, False if not."""
    global default_server_url
    server_to_use = host or default_server_url or "http://rf-calcul:11434"

    try:
        logging.info(f"Checking availability of model {model_name_to_check} on {server_to_use}...")
        tags_resp = requests.get(f"{server_to_use}/api/tags", timeout=30)
        tags_resp.raise_for_status()
        tags_data = tags_resp.json()

        for model_info_item in tags_data.get('models', []):
            if model_info_item.get('name') == model_name_to_check:
                logging.info(f"Model {model_name_to_check} exists on server {server_to_use}.")
                # Test with a simple prompt
                logging.info(f"Testing model {model_name_to_check} on {server_to_use}...")
                resp_test = requests.post(
                    f"{server_to_use}/api/generate",
                    json={"model": model_name_to_check, "prompt": "test", "stream": False},
                    timeout=60
                )
                resp_test.raise_for_status()
                logging.info(f"Model {model_name_to_check} on server {server_to_use} tested successfully.")
                default_server_url = server_to_use # Update default on success
                return True

        logging.warning(f"Model {model_name_to_check} does not exist on server {server_to_use}.")
        return False

    except requests.exceptions.Timeout:
        logging.warning(f"Timeout checking model {model_name_to_check} on {server_to_use}.")
        return False
    except Exception as e:
        logging.error(f"Failed to check model {model_name_to_check} on {server_to_use}: {e}")
        return False

def classify_position(title, description, model="qwen3:30b-a3b", host=None):
    """Classify position type (PhD, PostDoc, etc.) using Ollama"""
    global default_server_url
    server_to_use = host or default_server_url or "http://rf-calcul:11434"

    prompt = (
        f"Based on the following title and description, classify this academic position. "
        f"Possible classifications are: PhD, PostDoc, Research Assistant, Professor, Other. "
        f"Provide only the classification label.\n\n"
        f"Title: {title}\n"
        f"Description: {description[:500]}" # Limit description length
    )
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2}
    }
    try:
        logging.info(f"Classifying position using {model} on {server_to_use}...")
        resp = requests.post(f"{server_to_use}/api/generate", json=payload, timeout=120)
        resp.raise_for_status()
        result = resp.json()
        classification = result.get("response", "Other").strip()
        logging.info(f"Position classified as: {classification}")
        if classification not in ["PhD", "PostDoc", "Research Assistant", "Professor"]:
            return "Other"
        return classification
    except Exception as e:
        logging.error(f"Failed to classify position: {e}")
        return "Other" # Default to Other on error

def extract_direction(title, description, model="qwen3:30b-a3b", host=None):
    """Extract research direction using Ollama"""
    global default_server_url
    server_to_use = host or default_server_url or "http://rf-calcul:11434"

    prompt = (
        f"Based on the following title and description, identify the main research direction or field. "
        f"Provide a concise field name (e.g., 'Computer Science', 'Quantum Physics', 'Molecular Biology').\n\n"
        f"Title: {title}\n"
        f"Description: {description[:1000]}" # Limit description length
    )
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.5}
    }
    try:
        logging.info(f"Extracting research direction using {model} on {server_to_use}...")
        resp = requests.post(f"{server_to_use}/api/generate", json=payload, timeout=180)
        resp.raise_for_status()
        result = resp.json()
        direction = result.get("response", "N/A").strip()
        logging.info(f"Research direction extracted as: {direction}")
        return direction
    except Exception as e:
        logging.error(f"Failed to extract research direction: {e}")
        return "N/A" # Default on error

# Functions from aj_scraper.py (or adapted if similar ones existed)

def classify_position_by_keywords(title, content_text): # Renamed to avoid conflict with the AI version
    """Classify position type based on keywords in title and content."""
    # Convert to lowercase for case-insensitive matching
    combined_text = (str(title) + ' ' + str(content_text)).lower()

    # Define keyword sets for each category
    phd_keywords = ['phd', 'doktorand', 'doctoral', 'doctorate', 'promotionsstelle']
    postdoc_keywords = ['postdoc', 'post-doctoral', 'postdoctoral researcher', 'research fellow (postdoc)']
    research_staff_keywords = ['research assistant', 'research associate', 'scientist', 'researcher', 'forskningsassistent']
    # Professor/Lecturer keywords are usually quite specific, e.g. 'professor', 'lecturer', 'universitetslektor'
    # For Varbi, these might be less common for the roles typically scraped, but good to have.
    academic_faculty_keywords = ['professor', 'lecturer', 'associate professor', 'assistant professor', 'universitetslektor', 'adjunkt']

    if any(keyword in combined_text for keyword in phd_keywords):
        return 'PhD'
    if any(keyword in combined_text for keyword in postdoc_keywords):
        return 'PostDoc'
    if any(keyword in combined_text for keyword in academic_faculty_keywords):
        return 'Professor' # Or Faculty
    if any(keyword in combined_text for keyword in research_staff_keywords):
        return 'Research Staff' # Covers a broader range of non-faculty research roles

    return 'Other' # Default if no specific keywords match

def extract_direction_by_keywords(text_content): # Renamed to avoid conflict
    """Extract research direction based on keywords."""
    # Simple keyword-based categorization, can be expanded
    # This is a very basic example and would need significant expansion for accuracy
    text_lower = str(text_content).lower()
    directions_map = {
        'Computer Science': ['computer science', 'software', 'ai', 'machine learning', 'algorithms', 'data science'],
        'Engineering': ['engineering', 'mechanical', 'electrical', 'civil', 'chemical engineering'],
        'Life Sciences': ['biology', 'biomedical', 'neuroscience', 'genetics', 'biotechnology', 'life science'],
        'Physics': ['physics', 'quantum', 'optics', 'astrophysics'],
        'Chemistry': ['chemistry', 'chemical biology', 'analytical chemistry'],
        'Medicine': ['medical', 'clinical research', 'healthcare'],
        'Mathematics': ['mathematics', 'statistics', 'applied math'],
        'Social Sciences': ['sociology', 'psychology', 'economics', 'political science', 'social work'],
        'Humanities': ['history', 'philosophy', 'literature', 'arts'],
        'Environmental Science': ['environmental', 'ecology', 'climate change', 'earth science']
    }

    for direction, keywords in directions_map.items():
        if any(keyword in text_lower for keyword in keywords):
            return direction
    return 'General' # Default if no specific keywords match

def find_varbi_job_listings(driver):
    """
    Finds job listings on the Varbi job page, extracts title and link.
    Handles pagination as a placeholder.
    """
    logging.info("Starting to look for Varbi job listings...")
    job_info_list = []
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S") # For unique debug filenames

    try:
        # 1. Wait for body to ensure page is generally loaded
        logging.info("Waiting for body to load...")
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        logging.info("Body loaded.")

        # Try to identify a main content area
        main_content_area = None
        potential_main_selectors = ['main', 'div#content', 'div.container', 'div#main-content-area', 'div.jobs-list-container', "ul.list-group[role='feed']"]
        for sel in potential_main_selectors:
            try:
                logging.info(f"Trying to find main content area with selector: {sel}")
                main_content_area = driver.find_element(By.CSS_SELECTOR, sel)
                if main_content_area:
                    logging.info(f"Found main content area with selector: {sel}")
                    break
            except NoSuchElementException:
                logging.debug(f"Main content area not found with selector: {sel}")

        if not main_content_area:
            logging.warning("No specific main content area found, will search entire page for job cards.")
            main_content_area = driver # Fallback to whole driver if no specific main area found

        # 2. Selector strategy for job cards
        job_card_selectors = [
            "li.list-group-item[data-listing-id]", # Original specific Varbi selector
            "article.job-item",                   # Generic job item
            "div.job-listing",                    # Generic job listing div
            "li[class*='job']",                   # List item with 'job' in class
            "div[class*='job-card']",             # Div with 'job-card' in class
            "div[role='listitem']",               # ARIA role for list items
            "article",                            # Generic article tag
            "div.job"                             # Simple div with class job
        ]

        job_elements = []
        for selector in job_card_selectors:
            try:
                logging.info(f"Trying to find job cards with selector: '{selector}' within {'main content area' if main_content_area != driver else 'driver scope'}")
                elements = main_content_area.find_elements(By.CSS_SELECTOR, selector)
                if elements:
                    logging.info(f"Found {len(elements)} potential job cards with selector: {selector}")
                    # Filter out elements that are too small or clearly not job cards if possible (basic check)
                    for el_idx, el in enumerate(elements):
                        try:
                            tag_name = el.tag_name
                            class_attr = el.get_attribute('class') or ''
                            id_attr = el.get_attribute('id') or ''
                            text_preview = el.text.strip()[:100].replace('\n', ' ') # First 100 chars of text
                            logging.debug(f"  Potential card [{el_idx+1}/{len(elements)}] with selector '{selector}': <{tag_name} id='{id_attr}' class='{class_attr}'> Text: '{text_preview}...'")
                            # Add more sophisticated filtering here if needed, e.g., checking for a link or certain keywords
                            if len(text_preview) > 20 : # Arbitrary: assume a job card has at least some text
                                if el not in job_elements: # Avoid duplicates if selectors overlap
                                     job_elements.append(el)
                        except StaleElementReferenceException:
                            logging.debug(f"  Encountered stale element while logging card details for selector '{selector}', skipping it.")
                            continue

                    if job_elements: # If any valid elements were added from this selector pass
                        logging.info(f"Collected {len(job_elements)} distinct job cards so far using selector '{selector}'.")
                        # Decide if we should break or continue to gather more from other selectors.
                        # If a specific and usually reliable selector yields results, we might break.
                        if selector in ["li.list-group-item[data-listing-id]", "article.job-item"]:
                             logging.info(f"Breaking job card search as a reliable selector ('{selector}') yielded results.")
                             break
            except NoSuchElementException: # Should not happen with find_elements (returns empty list)
                logging.debug(f"No job cards found with selector: {selector}")
            except Exception as e_sel:
                logging.error(f"Error finding job cards with selector {selector}: {e_sel}")
                continue

        if not job_elements:
            logging.warning("No job card elements found on the page after trying all selectors.")
            try:
                page_source_snippet = driver.page_source[:3000] # Increased snippet size
                logging.info(f"Page source snippet (first 3000 chars):\n{page_source_snippet}")
                driver.save_screenshot(f"debug_screenshot_job_listings_failed_{timestamp}.png")
                logging.info(f"Saved screenshot to debug_screenshot_job_listings_failed_{timestamp}.png")
                with open(f"debug_page_source_job_listings_failed_{timestamp}.html", "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
                logging.info(f"Saved full page source to debug_page_source_job_listings_failed_{timestamp}.html")
            except Exception as e_debug:
                logging.error(f"Could not save debug information: {e_debug}")
            return []

        logging.info(f"Processing {len(job_elements)} unique potential job cards found.")
        for job_card_element in job_elements: # Renamed to avoid confusion
            try:
                title = None
                link = None

                # Log details of the card being processed
                tag_name = job_card_element.tag_name
                class_attr = job_card_element.get_attribute('class') or ''
                id_attr = job_card_element.get_attribute('id') or ''
                logging.debug(f"Processing card: <{tag_name} id='{id_attr}' class='{class_attr}'>")

                # Selector strategy for title and link within each card
                # Title is often within an <h3><a> or <h2><a> structure
                title_link_selectors = [
                    "h3.heading a", # Primary selector based on Varbi structure
                    "h2 a",
                    "h3 a", # Generic h3 link
                    ".job-title a", # Common class for job titles
                    "a[href*='/job/']", # Anchor with '/job/' in href
                    "a[data-id*='job']", # Anchor with 'job' in data-id
                    "a" # Last resort: any link within the card
                ]

                for tl_selector in title_link_selectors:
                    try:
                        title_element = job_card_element.find_element(By.CSS_SELECTOR, tl_selector)
                        temp_title = title_element.text.strip()
                        temp_link = title_element.get_attribute('href')

                        if temp_title and temp_link and temp_link.startswith(('http', '/')):
                            title = temp_title
                            link = temp_link
                            # Ensure link is absolute
                            if link.startswith('/'):
                                from urllib.parse import urljoin
                                base_page_url = driver.current_url # Should be https://www.varbi.com/en/jobs/
                                link = urljoin(base_page_url, link)
                            logging.debug(f"  Extracted title/link using '{tl_selector}': '{title}' / '{link}'")
                            break
                    except NoSuchElementException:
                        logging.debug(f"  Title/link selector '{tl_selector}' not found in card.")
                    except StaleElementReferenceException:
                        logging.warning(f"  Stale element encountered with selector '{tl_selector}' in card. Card might have changed.")
                        break # Stop trying selectors for this card if it's stale

                if title and link:
                    if not any(j['link'] == link for j in job_info_list): # Check for duplicates
                        job_info_list.append({'title': title, 'link': link})
                        logging.info(f"Successfully extracted job: Title='{title}', Link='{link}'")
                    else:
                        logging.debug(f"Duplicate job link found, skipping: {link}")
                else:
                    logging.warning(f"Could not extract title or link from job card: <{tag_name} id='{id_attr}' class='{class_attr}'>. HTML snippet: {job_card_element.get_attribute('outerHTML')[:300]}...")

            except StaleElementReferenceException:
                logging.warning("Encountered a stale element reference while processing a job card. Skipping this card.")
                continue
            except Exception as e:
                logging.error(f"Error processing a job card: {e}. Card HTML: {job_card_element.get_attribute('outerHTML')[:200]}...")
                continue

        logging.info(f"Extracted {len(job_info_list)} unique job listings from the current page.")

        # Handle Pagination (Placeholder)
        # Varbi uses page numbers like: <a href="?page=2">2</a>
        # And a "Next" button: <a rel="next" href="?page=2">Next »</a>
        try:
            next_page_link = driver.find_element(By.CSS_SELECTOR, "a[rel='next']")
            if next_page_link:
                logging.info("Pagination detected. Further pages might exist. Pagination handling is not yet implemented.")
                # Future implementation: click next_page_link and recursively call find_varbi_job_listings or loop.
        except NoSuchElementException:
            logging.info("No 'Next' page link found. Assuming this is the last page or single page of results.")
        except Exception as e:
            logging.warning(f"Error checking for pagination: {e}")

    except TimeoutException:
        logging.error("Timeout waiting for job listings to load. The page structure might have changed or the page is too slow.")
        return []
    except Exception as e:
        logging.error(f"An unexpected error occurred in find_varbi_job_listings: {e}")
        return []

    if not job_info_list:
        logging.warning("No job listings were successfully extracted.")

    return job_info_list

def fetch_varbi_jobs(use_headless=True, selected_model=None):
    """
    Main function to fetch job listings from Varbi.
    Orchestrates driver setup, page loading, cookie handling, and finding job listings.
    Full job detail fetching will be added in a subsequent step.
    """
    # Attempt to set a PAC file proxy. This might be specific to certain network environments.
    # If not needed, it can be commented out or made configurable.
    # Ensure the PAC file is accessible if this line is active.
    # set_windows_proxy_from_pac("http://127.0.0.1:55624/proxy.pac") # Example PAC URL

    logging.info("Starting to fetch Varbi jobs.")
    driver = None
    jobs_processed = [] # This will eventually hold full job details

    try:
        logging.debug(f"Setting up WebDriver. Headless: {use_headless}")
        driver = setup_driver(use_headless)
        if not driver:
            logging.error("WebDriver setup failed. Cannot proceed.")
            return []

        base_url = "https://www.varbi.com/en/jobs/"
        logging.info(f"Navigating to base URL: {base_url}")
        if not get_page_content(driver, base_url):
            logging.error(f"Failed to load the base URL: {base_url}. Aborting.")
            return []

        logging.info("Handling cookie consent...")
        handle_cookie_consent(driver) # Uses generic selectors defined in the function

        logging.info("Finding job listings...")
        job_info_list = find_varbi_job_listings(driver) # This function was defined in the previous step

        if not job_info_list:
            logging.warning("No job listings (titles/links) found on the initial page.")
            # Potentially save screenshot or page source for debugging if nothing is found
            # timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            # driver.save_screenshot(f"debug_no_job_listings_found_{timestamp}.png")
            return []

        logging.info(f"Found {len(job_info_list)} job listings (title and link).")

        # Placeholder for fetching full job details (to be implemented in the next step)
        # For now, we'll just return the list of titles and links.
        # In the next step, we will iterate through job_info_list, visit each link,
        # extract full details, and add to jobs_processed.

        # For now, we assign job_info_list to jobs_processed to simulate returning data
        # jobs_processed = job_info_list
        # logging.info("Placeholder: Full job detail fetching is not yet implemented. Returning list of titles/links.")

        # Iterate through job_info_list, visit each link, and fetch full details
        total_jobs_found = len(job_info_list)
        logging.info(f"Starting to fetch full details for {total_jobs_found} job listings...")

        for i, job_summary in enumerate(job_info_list):
            logging.info(f"Processing job {i+1}/{total_jobs_found}: {job_summary['title']} ({job_summary['link']})")
            try:
                # It's good practice to re-check for driver validity if operations are long
                if not driver or not driver.session_id:
                    logging.error("WebDriver session is invalid. Attempting to re-initialize.")
                    # Attempt re-initialization (optional, or could fail fast)
                    driver = setup_driver(use_headless) # This might be too aggressive here, depends on strategy
                    if not driver:
                        logging.error("Failed to re-initialize WebDriver. Skipping remaining jobs.")
                        break

                job_detail = fetch_varbi_job_detail(driver, job_summary['link'])
                if job_detail:
                    # Merge summary info if detail fetching missed something critical like original title/link
                    job_detail['title'] = job_detail.get('title') or job_summary.get('title')
                    job_detail['link'] = job_detail.get('link') or job_summary.get('link')
                    jobs_processed.append(job_detail)
                    logging.info(f"Successfully processed and added details for job {i+1}/{total_jobs_found}.")
                else:
                    logging.warning(f"Failed to fetch details for job: {job_summary['title']}. Skipping.")
                    # Optionally, add the summary info so it's not completely lost
                    # jobs_processed.append(job_summary)
            except WebDriverException as wde:
                logging.error(f"A WebDriverException occurred while processing job {job_summary['link']}: {wde}")
                logging.info("Attempting to continue with the next job if possible.")
                # Consider if a driver re-initialization is needed here
                try:
                    if driver: driver.quit() # Clean up old driver
                except: pass
                driver = setup_driver(use_headless) # Try to get a fresh driver
                if not driver:
                    logging.error("Failed to re-initialize WebDriver after error. Aborting further processing.")
                    break # Exit loop if driver cannot be restored
                else:
                    logging.info("WebDriver re-initialized. Continuing to next job.")
            except Exception as e_detail:
                logging.error(f"An error occurred fetching details for {job_summary['title']}: {e_detail}", exc_info=True)

        logging.info(f"Successfully fetched details for {len(jobs_processed)} out of {total_jobs_found} job listings.")

    except WebDriverException as e:
        logging.error(f"A WebDriverException occurred: {e}")
        # Consider taking a screenshot on error for debugging
        if driver:
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                driver.save_screenshot(f"error_webdriver_exception_{timestamp}.png")
                logging.info(f"Saved error screenshot to error_webdriver_exception_{timestamp}.png")
            except Exception as se:
                logging.error(f"Could not save error screenshot: {se}")
    except Exception as e:
        logging.error(f"An unexpected error occurred in fetch_varbi_jobs: {e}", exc_info=True)
    finally:
        if driver:
            try:
                logging.info("Closing the WebDriver.")
                driver.quit()
            except Exception as e:
                logging.error(f"Error while quitting WebDriver: {e}")

    logging.info(f"fetch_varbi_jobs finished. Returning {len(jobs_processed)} processed jobs.")
    return jobs_processed

def fetch_varbi_job_detail(driver, job_url, selected_model=None):
    """
    Fetches detailed information for a single job posting from its URL.
    Ensures extraction of key fields and generates an AI highlight.
    """
    logging.info(f"Fetching details for job: {job_url} using model: {selected_model}")
    if not get_page_content(driver, job_url):
        logging.error(f"Failed to load job detail page: {job_url}")
        return None

    # Initialize details dictionary with default empty strings or None for clarity
    details = {
        'title': '',
        'content': '',
        'institution': '',
        'location': '',
        'deadline': '',
        'job_id': '', # Changed from 'id' to 'job_id' for clarity
        'link': job_url,
        'posted_date': '', # Kept for now, can be removed if not strictly needed by spec
        'highlight': ''
    }

    try:
        # 1. Main Content Element (Primary scope for other extractions)
        # Varbi specific: 'div.ad' is common, 'article[role="main"]' or 'main#main-content' are good fallbacks.
        main_content_selectors = [
            "div.ad",                     # Primary Varbi ad container
            "article[role='main']",       # Semantic main content
            "main#main-content",          # Common main content ID
            "div.job-announcement-body",  # Another Varbi specific class
            "div.block-readspeaker",      # Sometimes content is wrapped here
            "div.job-description"         # Generic job description class
        ]
        main_content_element = None
        for selector in main_content_selectors:
            try:
                main_content_element = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                if main_content_element:
                    logging.debug(f"Main content element found using selector: {selector} for {job_url}")
                    break
            except TimeoutException:
                logging.debug(f"Timeout waiting for main content with selector: {selector} for {job_url}")

        if not main_content_element:
            logging.warning(f"Could not find the main content element for job: {job_url}. Attempting body fallback.")
            body_element = find_element_with_retry(driver, By.TAG_NAME, 'body')
            if body_element:
                 details['content'] = body_element.text.strip()
                 main_content_element = body_element # Use body as main_content_element for further extractions
            else:
                logging.error(f"CRITICAL: Failed to extract any main content or body for {job_url}. Returning None.")
                # Debug save
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                driver.save_screenshot(f"error_critical_no_content_{timestamp}.png")
                with open(f"error_critical_no_content_{timestamp}.html", "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
                return None
        else:
            # Extract full HTML content of the main job ad for more robust parsing if needed later,
            # or use .text for just the text. For now, .text is fine for 'content'.
            details['content'] = main_content_element.text.strip()

        # If content is still empty after finding main_content_element, this is critical.
        if not details['content'].strip():
            logging.error(f"CRITICAL: Main content element found for {job_url} but no text could be extracted. Returning None.")
            # Debug save
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            driver.save_screenshot(f"error_critical_empty_content_{details.get('job_id', 'unknown')}_{timestamp}.png")
            with open(f"error_critical_empty_content_{details.get('job_id', 'unknown')}_{timestamp}.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            return None

        # 2. Extract Title
        # Varbi specific: 'h1.heading' or 'div.header h1' or just 'h1'
        title_selectors = [
            "h1.heading",                 # Common on Varbi
            "div.header h1",              # Header structure
            "h1[itemprop='title']",       # Schema.org itemprop
            "h1",                         # Generic H1
            ".job-title",                 # Class based
            "h2.section-header"           # Sometimes used as main title
        ]
        for selector in title_selectors:
            title_text = extract_text_safely(main_content_element, selector)
            if title_text:
                details['title'] = title_text
                logging.debug(f"Extracted Title: '{details['title']}' for {job_url}")
                break
        if not details['title']: # Fallback to searching the whole driver if not found in main_content_element
            for selector in title_selectors:
                title_text = extract_text_safely(driver, selector)
                if title_text:
                    details['title'] = title_text
                    logging.debug(f"Extracted Title (driver scope): '{details['title']}' for {job_url}")
                    break
        if not details['title']:
            logging.warning(f"CRITICAL: Could not extract title for {job_url}. Returning None.")
            # Debug save
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            driver.save_screenshot(f"error_critical_no_title_{details.get('job_id', 'unknown')}_{timestamp}.png")
            with open(f"error_critical_no_title_{details.get('job_id', 'unknown')}_{timestamp}.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            return None

        # 3. Extract Institution
        # Varbi specific: 'span.employer', 'div.company', 'p.organisation'
        institution_selectors = [
            "span.employer",              # Often used directly
            "div.company-name",           # Specific div for company name
            "p.organisation",             # Sometimes in a paragraph
            "a.employer",                 # Link with employer class
            "div.employer a",
            "div[itemprop='hiringOrganization'] span[itemprop='name']", # Schema.org
            "meta[itemprop='name']" # content attribute of meta tag
        ]
        for selector in institution_selectors:
            inst_text = extract_text_safely(main_content_element, selector)
            if not inst_text and selector == "meta[itemprop='name']": # For meta tags, get 'content'
                try:
                    meta_elem = main_content_element.find_element(By.CSS_SELECTOR, selector)
                    inst_text = meta_elem.get_attribute('content').strip()
                except NoSuchElementException:
                    pass # Handled by extract_text_safely effectively for text part
            if inst_text:
                details['institution'] = inst_text
                logging.debug(f"Extracted Institution: '{details['institution']}' for {job_url}")
                break
        if not details['institution']:
             logging.warning(f"Could not extract institution for {job_url}")

        # 4. Extract Location
        # Varbi: `ul.application-details li span.fa-map-marker ~ span` (text next to icon) or specific dd/dt
        location_selectors = [
            "ul.application-details li span.fa-map-marker ~ span", # Primary
            "dt:contains('Location') + dd", # Definition list
            "dt:contains('City') + dd",
            "span[itemprop='jobLocation']", # Schema.org
            "div.location-icon ~ span", # Icon followed by span
            "p.location"
        ]
        location_text = ""
        for selector in location_selectors:
            try:
                loc_element = main_content_element.find_element(By.CSS_SELECTOR, selector)
                location_text = loc_element.text.strip()
                if "fa-map-marker" in selector and not location_text: # If icon selector returned the icon itself
                     parent_text = loc_element.find_element(By.XPATH, "..").text.strip()
                     location_text = parent_text.replace("Location", "").replace("map-marker", "").strip() # Basic clean
                if location_text:
                    details['location'] = location_text.replace("Location:", "").strip()
                    logging.debug(f"Extracted Location: '{details['location']}' for {job_url}")
                    break
            except NoSuchElementException:
                continue
        if not details['location']:
            logging.warning(f"Could not extract location for {job_url}")

        # 5. Extract Application Deadline
        # Varbi: `ul.application-details li span.fa-calendar-alt ~ span` or `dt:contains('Last application date') + dd`
        deadline_selectors = [
            "ul.application-details li span.fa-calendar-alt ~ span", # Primary
            "ul.application-details li span.fa-calendar ~ span",     # Fallback calendar icon
            "dt:contains('Last application date') + dd",
            "dt:contains('Application deadline') + dd",
            "dt:contains('Sista ansökningsdag') + dd", # Swedish
            "span[itemprop='validThrough']", # Schema.org (often a meta tag's content)
            "p.application-deadline"
        ]
        for selector in deadline_selectors:
            deadline_text = extract_text_safely(main_content_element, selector)
            if not deadline_text and "itemprop='validThrough'" in selector:
                 try:
                    meta_elem = main_content_element.find_element(By.CSS_SELECTOR, selector)
                    deadline_text = meta_elem.get_attribute('content').strip()
                 except NoSuchElementException:
                    pass
            if deadline_text:
                details['deadline'] = deadline_text.replace("Deadline:", "").replace("Last application date:", "").strip()
                logging.debug(f"Extracted Deadline: '{details['deadline']}' for {job_url}")
                break
        if not details['deadline']:
            logging.warning(f"Could not extract deadline for {job_url}")

        # 6. Extract Job ID
        # From URL: `/job/JOB_ID/` or `externalid=JOB_ID` or `id=JOB_ID`
        # From page: `span.id`, `span.reference`, `dt:contains('Reference') + dd`
        extracted_job_id = ""
        try:
            url_patterns = [r'/job/([^/]+)/', r'externalid=([^&]+)', r'id=([^&]+)', r'jobid=([^&]+)']
            for pattern in url_patterns:
                match = re.search(pattern, job_url, re.IGNORECASE)
                if match:
                    extracted_job_id = match.group(1)
                    logging.debug(f"Extracted Job ID from URL: '{extracted_job_id}' for {job_url}")
                    break
            if not extracted_job_id:
                id_selectors = [
                    "span.id",
                    "span.reference",
                    "dt:contains('Reference') + dd",
                    "dt:contains('Job ID') + dd",
                    "div[class*='job-id']"
                ]
                for selector in id_selectors:
                    id_text = extract_text_safely(main_content_element, selector)
                    if id_text:
                        extracted_job_id = id_text.replace("Ref:", "").replace("Job ID:", "").replace("ID:", "").strip()
                        logging.debug(f"Extracted Job ID from page: '{extracted_job_id}' for {job_url}")
                        break
            details['job_id'] = extracted_job_id if extracted_job_id else f"varbi_{job_url.split('/')[-2] if job_url.split('/')[-2] else job_url.split('/')[-1]}"
        except Exception as e:
            logging.warning(f"Could not extract job ID for {job_url}: {e}")
            if not details['job_id']: # Ensure fallback if regex/selectors fail badly
                 details['job_id'] = f"varbi_fallback_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"


        # 7. Extract Posted Date (Optional, but good to have)
        posted_date_selectors = [
            "ul.application-details li span.fa-clock-o ~ span",
            "dt:contains('Published') + dd",
            "dt:contains('Posted date') + dd",
            "span[itemprop='datePosted']" # Schema.org (often a meta tag's content)
        ]
        for selector in posted_date_selectors:
            posted_text = extract_text_safely(main_content_element, selector)
            if not posted_text and "itemprop='datePosted'" in selector:
                try:
                    meta_elem = main_content_element.find_element(By.CSS_SELECTOR, selector)
                    posted_text = meta_elem.get_attribute('content').strip()
                except NoSuchElementException:
                    pass
            if posted_text:
                details['posted_date'] = posted_text.replace("Published:", "").replace("Posted:", "").strip()
                logging.debug(f"Extracted Posted Date: '{details['posted_date']}' for {job_url}")
                break
        if not details['posted_date']:
            logging.warning(f"Could not extract posted date for {job_url}")

        # 8. AI Highlight Generation
        if selected_model and details['title'] and details['content']:
            try:
                job_text_for_ai = f"Title: {details['title']}\n\nContent: {details['content'][:3000]}" # Limit content length for AI
                logging.info(f"Generating AI highlight for {job_url} using model {selected_model}...")
                highlight_text = ollama_highlight(job_text_for_ai, model=selected_model)
                details['highlight'] = highlight_text
                logging.debug(f"Generated AI Highlight for {job_url}: {details['highlight'][:100]}...")
            except Exception as e:
                logging.error(f"Failed to generate AI highlight for {job_url}: {e}")
                details['highlight'] = "AI highlight generation failed or was skipped."
        elif not selected_model:
            logging.info(f"No AI model selected. Skipping highlight generation for {job_url}.")
            details['highlight'] = "AI model not selected."
        else:
            logging.warning(f"Skipping AI highlight for {job_url} due to missing title or content.")
            details['highlight'] = "Highlight generation skipped due to missing data."

    except StaleElementReferenceException as sre:
        logging.error(f"StaleElementReferenceException encountered while parsing details for {job_url}: {sre}. This page might have dynamic content issues or navigation conflicts.")
        # No debug save here as driver state is unreliable for screenshot/source
        return None # Critical error, likely indicates page structure changed during scrape
    except Exception as e:
        logging.error(f"Unexpected error fetching job details for {job_url}: {e}", exc_info=True)
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            error_page_filename_base = f"error_detail_page_{details.get('job_id', 'unknown_id')}_{timestamp}"
            driver.save_screenshot(f"{error_page_filename_base}.png")
            with open(f"{error_page_filename_base}.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            logging.info(f"Saved error screenshot and source for {job_url} to {error_page_filename_base}.png/html")
        except Exception as se:
            logging.error(f"Could not save error screenshot/source for {job_url}: {se}")
        return None # Return None on significant unexpected error

    logging.info(f"Successfully fetched details for job ID {details.get('job_id', 'N/A')}: {details.get('title', 'N/A')}")
    return details


def generate_summary_article(jobs, platform_name="Varbi"):
    """Generate a markdown summary article from job data"""
    logging.info(f"Generating summary for {len(jobs)} jobs from {platform_name}.")
    if not jobs:
        logging.warning("No positions found to generate an article.")
        return f"# {platform_name} Job Opportunities - No Jobs Found\n\nNo jobs were found in the latest scrape."

    today = datetime.now().strftime('%Y-%m-%d')
    article = f"# {platform_name} Job Opportunities ({today})\n\n"

    classified_jobs = defaultdict(lambda: defaultdict(list))

    for job in jobs:
        # Ensure job is a dictionary and content/title are present
        if not isinstance(job, dict):
            logging.warning(f"Skipping invalid job item (not a dict): {job}")
            continue
        title = job.get('title', '')
        content = job.get('content', '')

        category = classify_position_by_keywords(title, content)
        # For direction, it might be better to use the full content for more keywords
        direction = extract_direction_by_keywords(title + " " + content) # Pass combined text

        classified_jobs[category][direction].append(job)

    # Define the order of categories for the report
    # Output of classify_position_by_keywords: 'PhD', 'PostDoc', 'Professor', 'Research Staff', 'Other'
    categories_order = ['PhD', 'PostDoc', 'Professor', 'Research Staff', 'Other']

    found_jobs_in_any_category = False
    for category in categories_order:
        if category in classified_jobs and classified_jobs[category]:
            found_jobs_in_any_category = True
            article += f"## {category}\n\n"
            # Sort directions alphabetically for consistent output
            sorted_directions = sorted(classified_jobs[category].keys())
            for direction in sorted_directions:
                article += f"### {direction}\n\n"
                for job_item in classified_jobs[category][direction]:
                    article += f"#### {job_item.get('title', 'N/A')}\n\n"

                    if job_item.get('highlight'):
                        article += f"**AI Highlight:** {job_item.get('highlight')}\n\n"

                    details_list = []
                    if job_item.get('institution'):
                        details_list.append(f"**Institution:** {job_item.get('institution')}")
                    if job_item.get('location'):
                        details_list.append(f"**Location:** {job_item.get('location')}")
                    if job_item.get('deadline'):
                        details_list.append(f"**Application Deadline:** {job_item.get('deadline')}")
                    if job_item.get('posted_date'): # Assuming 'posted_date' might be available
                        details_list.append(f"**Posted Date:** {job_item.get('posted_date')}")

                    if details_list:
                        article += " | ".join(details_list) + "\n\n" # Single line for compact details

                    article += f"**Job Link:** [{job_item.get('link', '#')}]({job_item.get('link', '#')})\n\n"
                    article += "---\n\n"
        else:
            logging.debug(f"No jobs found for category: {category}")

    if not found_jobs_in_any_category:
        article += "No jobs found matching the defined categories in this scrape.\n\n"

    return article


if __name__ == '__main__':
    # Setup basic logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
                        handlers=[logging.StreamHandler(sys.stdout)]) # Ensure logs go to stdout

    logging.info("=== Varbi Scraper Execution Start ===")

    # set_windows_proxy_from_pac("http://127.0.0.1:55624/proxy.pac") # Commented out, configure if needed

    selected_ai_model = None # Default to no model
    jobs_data = []
    platform_name = "Varbi" # Platform name for outputs

    try:
        # 1. Check AI server and select model
        logging.info("--- Phase 1: AI Server Setup ---")
        selected_ai_model = "deepseek-r1:70b" # Default model
        if check_ai_server():
            logging.info("AI Server is available.")
            # selected_ai_model = select_model() # Uncomment for interactive selection
            if not check_model_availability(selected_ai_model):
                logging.warning(f"Model {selected_ai_model} not available. Trying fallback or other models.")
                available_models = list_available_models()
                if "qwen3:30b-a3b" in available_models:
                     selected_ai_model = "qwen3:30b-a3b"
                elif available_models:
                    selected_ai_model = available_models[0]
                else:
                    logging.error("No AI models available on the server. Highlights will be basic or disabled.")
                    selected_ai_model = None
        else:
            logging.warning("AI Server not available. Highlights will be basic or disabled.")
            selected_ai_model = None

        logging.info(f"Using AI model for highlights: {selected_ai_model if selected_ai_model else 'N/A'}")

        # 2. Fetch jobs from Varbi
        logging.info(f"--- Phase 2: Fetching Positions from {platform_name} ---")
        jobs_data = fetch_varbi_jobs(use_headless=True, selected_model=selected_ai_model)

        if not jobs_data:
            logging.warning(f"No job data fetched from {platform_name}. No report will be generated.")
        else:
            logging.info(f"Successfully fetched {len(jobs_data)} job details from {platform_name}.")

            # 3. Save raw data as JSON
            logging.info("--- Phase 3: Saving Data ---")
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = "backup"
            os.makedirs(backup_dir, exist_ok=True) # Ensure backup directory exists

            json_output_filename = os.path.join(backup_dir, f"{platform_name.lower()}_jobs_{timestamp_str}.json")
            try:
                with open(json_output_filename, "w", encoding="utf-8") as f:
                    json.dump(jobs_data, f, ensure_ascii=False, indent=4)
                logging.info(f"Scraped {platform_name} job data saved to {json_output_filename}")
            except IOError as e:
                logging.error(f"Error saving {platform_name} job data to JSON: {e}")
            except TypeError as e:
                logging.error(f"TypeError during JSON serialization for {platform_name} jobs: {e}. Check data structure.")

            # 4. Generate and save markdown summary
            logging.info(f"--- Phase 4: Generating Summary Report for {platform_name} ---")
            summary_article_content = generate_summary_article(jobs_data, platform_name)
            report_filename = os.path.join(backup_dir, f"{platform_name.lower()}_summary_{timestamp_str}.md")
            try:
                with open(report_filename, "w", encoding="utf-8") as f:
                    f.write(summary_article_content)
                logging.info(f"Summary report for {platform_name} saved to {report_filename}")
            except IOError as e:
                logging.error(f"Error saving {platform_name} summary report: {e}")

        logging.info(f"=== {platform_name} Scraper Execution End ===")

    except Exception as e:
        logging.critical(f"A top-level error occurred in the Varbi scraper: {e}", exc_info=True)
        # Try to save any partially fetched data if an error occurs mid-way
        if jobs_data: # jobs_data might be partially populated
            logging.info(f"Attempting to save partially fetched data due to error for {platform_name}...")
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            error_backup_dir = "backup"
            os.makedirs(error_backup_dir, exist_ok=True)
            error_json_filename = os.path.join(error_backup_dir, f"{platform_name.lower()}_jobs_ERROR_{timestamp_str}.json")
            try:
                with open(error_json_filename, "w", encoding="utf-8") as f:
                    json.dump(jobs_data, f, ensure_ascii=False, indent=4)
                logging.info(f"Partially fetched data for {platform_name} saved to {error_json_filename}")
            except Exception as save_e:
                logging.error(f"Could not save partial data for {platform_name} during error handling: {save_e}")
    finally:
        logging.info(f"--- {platform_name} Scraper run finished. ---")
    pass
