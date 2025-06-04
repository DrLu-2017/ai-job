import selenium # type: ignore
import requests
import time
import re
import os
import json
from datetime import datetime, timedelta
from collections import defaultdict
import sys
if sys.platform == "win32": # Only import winreg on Windows
    import winreg # type: ignore
from selenium import webdriver # type: ignore
from selenium.webdriver.chrome.service import Service # type: ignore
from selenium.webdriver.chrome.options import Options # type: ignore
from selenium.webdriver.common.by import By # type: ignore
from selenium.webdriver.support.ui import WebDriverWait # type: ignore
from selenium.webdriver.support import expected_conditions as EC # type: ignore
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException # type: ignore
from bs4 import BeautifulSoup # type: ignore
import logging
from urllib.parse import urljoin # Added for find_varbi_job_listings adaptation

# Global variable for the default server URL
default_server_url = None
MAX_JOBS_TO_PROCESS = 5 # Limit for AI testing; can be increased or removed for production

# Functions from daad_scraper_new.py / varbi_scraper.py

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

    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-gpu-sandbox')
    options.add_argument('--disable-software-rasterizer')
    options.add_argument('--disable-gpu-compositing')
    options.add_argument('--disable-gpu-program-cache')
    options.add_argument('--disable-gpu-watchdog')
    options.add_argument('--disable-accelerated-2d-canvas')
    options.add_argument('--disable-accelerated-video-decode')
    options.add_argument('--disable-webgl')
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-browser-side-navigation')
    options.add_argument('--disable-site-isolation-trials')
    options.add_argument('--disable-infobars')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--log-level=3')
    options.add_argument('--silent')
    options.add_experimental_option('excludeSwitches', ['enable-logging'])

    if use_headless:
        options.add_argument('--headless=new')
        logging.info("Starting browser in headless mode...")
    else:
        logging.info("Starting browser in visible mode...")

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
            time.sleep(2)

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
                '#cookie-consent button, .cookie-banner button, .consent-button, button[data-testid="cookie-accept-all"], button[id*="cookie-accept"], button[class*="accept-all"], button[class*="consent"]'))
        ).click()
        logging.info("Cookie consent handled or attempted.")
    except TimeoutException:
        logging.info("No cookie consent found or already accepted within timeout.")
    except Exception as e:
        logging.warning(f"Error handling cookie consent: {e}")

def get_page_content(driver, url):
    """Get the content of a page, handling timeouts and retrying if needed"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            driver.get(url)
            time.sleep(3)
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
    except (NoSuchElementException, AttributeError) :
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
                return None
            logging.debug(f"Timeout, retrying... ({attempt + 1}/{max_retries}) for selector {selector}")
            time.sleep(1)
    return None

def validate_selector(selector):
    """Validate if a CSS selector is syntactically correct"""
    try:
        if not selector or not isinstance(selector, str):
            return False
        brackets = sum(1 if c in '[(' else -1 if c in '])' else 0 for c in selector)
        quotes = sum(1 if c in '"' else 0 for c in selector)
        return brackets == 0 and quotes % 2 == 0
    except Exception:
        return False

def extract_text_with_fallback(element, selector):
    """Extract text from an element with multiple fallback methods"""
    try:
        text = element.text.strip()
        if text:
            return text
        text = element.get_attribute('textContent').strip()
        if text:
            return text
        text = element.get_attribute('innerText').strip()
        if text:
            return text
    except Exception as e:
        logging.debug(f"Failed to extract text with selector {selector}: {e}")
    return ""

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
    payload = {"model": model, "prompt": prompt, "stream": False, "options": {"temperature": 0.7, "top_p": 0.9}}
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    last_error = None

    for server_url_to_try in servers:
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
            default_server_url = server_url_to_try
            common_prefixes = [
                "highlights include", "key highlights:", "summary:", "analysis:", "main points:", "key features:",
                "highlights:", "strengths:", "advantages:", "position offers:", "overview:", "assessment:",
                "key aspects:", "evaluation:", "review:", "analysis shows:", "this position:", "main advantages:", "key benefits:",
            ]
            for prefix in common_prefixes:
                if highlight.lower().startswith(prefix.lower()):
                    highlight = highlight[len(prefix):].strip()
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

    backup_model = "qwen3:30b-a3b"
    logging.warning(f"All servers failed ({last_error}), trying backup model {backup_model}...")
    try:
        simple_prompt = f"Please summarize the key highlights and features of this academic position:\n\n{text[:1000]}"
        payload["model"] = backup_model
        payload["prompt"] = simple_prompt
        for server_url_to_try in servers:
            try:
                resp = requests.post(f"{server_url_to_try}/api/generate", json=payload, headers=headers, timeout=600)
                resp.raise_for_status()
                result = resp.json()
                highlight_text = result.get("response", "").strip()
                if highlight_text:
                    default_server_url = server_url_to_try
                    return highlight_text
            except Exception:
                continue
    except Exception as e:
        logging.error(f"Backup model failed: {e}")

    logging.warning("All models failed, using simple extraction method...")
    institution_match = re.search(r'(?:university|institute)[\s:]*([\w\s]+)', text, re.IGNORECASE)
    location_match = re.search(r'(?:location)[\s:]*([\w\s,]+)', text, re.IGNORECASE)
    field_match = re.search(r'(?:research|field)[\s:]*([\w\s,]+)', text, re.IGNORECASE)
    highlight_parts = []
    if institution_match: highlight_parts.append(f"{institution_match.group(1)} is a renowned academic institution")
    if location_match: highlight_parts.append(f"located in {location_match.group(1).strip()}")
    if field_match: highlight_parts.append(f"with notable research in {field_match.group(1)}")
    if highlight_parts:
        return " ".join(highlight_parts) + ". The position offers excellent research facilities, an international academic environment, and strong development opportunities."
    return "The position offers an international academic environment, excellent research facilities, and strong development prospects."

def check_ai_server(host="http://rf-calcul:11434"):
    """Check if the AI server is available and models are loaded"""
    global default_server_url
    servers = [host] if host else ["http://rf-calcul:11434"]
    if default_server_url and default_server_url not in servers:
        servers.append(default_server_url)

    for server_url_to_try in servers:
        try:
            logging.info(f"Checking server connection at {server_url_to_try}...")
            resp = requests.get(f"{server_url_to_try}/api/version", timeout=5)
            resp.raise_for_status()
            version = resp.json().get('version', 'unknown')
            logging.info(f"Server connection successful. Ollama version: {version} at {server_url_to_try}")
            default_server_url = server_url_to_try
            models_to_check = ["deepseek-r1:70b", "qwen3:30b-a3b"]
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
                continue
            logging.info(f"Found {len(available_models_on_server)} required models on server {server_url_to_try}.")
            return True
        except Exception as e:
            logging.warning(f"Server {server_url_to_try} connection failed: {e}")
            if server_url_to_try == default_server_url: default_server_url = None
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
        available_models_list = [model_info.get('name') for model_info in models_data.get('models', []) if model_info.get('name')]
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
    for i, model_name in enumerate(models, 1): print(f"{i}. {model_name}")
    while True:
        try:
            choice = input("\nSelect model to use (enter number): ")
            idx = int(choice) - 1
            if 0 <= idx < len(models):
                selected = models[idx]
                logging.info(f"User selected model: {selected}")
                return selected
            else: print("Invalid selection. Please try again.")
        except ValueError: print("Please enter a valid number.")
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
                logging.info(f"Testing model {model_name_to_check} on {server_to_use}...")
                resp_test = requests.post(f"{server_to_use}/api/generate", json={"model": model_name_to_check, "prompt": "test", "stream": False}, timeout=60)
                resp_test.raise_for_status()
                logging.info(f"Model {model_name_to_check} on server {server_to_use} tested successfully.")
                default_server_url = server_to_use
                return True
        logging.warning(f"Model {model_name_to_check} does not exist on server {server_to_use}.")
        return False
    except requests.exceptions.Timeout:
        logging.warning(f"Timeout checking model {model_name_to_check} on {server_to_use}.")
        return False
    except Exception as e:
        logging.error(f"Failed to check model {model_name_to_check} on {server_to_use}: {e}")
        return False

def classify_position_by_keywords(title, content_text):
    """Classify position type based on keywords in title and content."""
    combined_text = (str(title) + ' ' + str(content_text)).lower()
    phd_keywords = ['phd', 'doktorand', 'doctoral', 'doctorate', 'promotionsstelle']
    postdoc_keywords = ['postdoc', 'post-doctoral', 'postdoctoral researcher', 'research fellow (postdoc)']
    research_staff_keywords = ['research assistant', 'research associate', 'scientist', 'researcher', 'forskningsassistent']
    academic_faculty_keywords = ['professor', 'lecturer', 'associate professor', 'assistant professor', 'universitetslektor', 'adjunkt']
    if any(keyword in combined_text for keyword in phd_keywords): return 'PhD'
    if any(keyword in combined_text for keyword in postdoc_keywords): return 'PostDoc'
    if any(keyword in combined_text for keyword in academic_faculty_keywords): return 'Professor'
    if any(keyword in combined_text for keyword in research_staff_keywords): return 'Research Staff'
    return 'Other'

def extract_direction_by_keywords(text_content):
    """Extract research direction based on keywords."""
    text_lower = str(text_content).lower()
    directions_map = {
        'Computer Science': ['computer science', 'software', 'ai', 'machine learning', 'algorithms', 'data science', 'cybersecurity', 'data engineering'],
        'Engineering': ['engineering', 'mechanical', 'electrical', 'civil', 'chemical engineering', 'robotics', 'aerospace', 'biomedical engineering'],
        'Life Sciences': ['biology', 'biomedical', 'neuroscience', 'genetics', 'biotechnology', 'life science', 'molecular biology', 'bioinformatics'],
        'Physics': ['physics', 'quantum', 'optics', 'astrophysics', 'condensed matter', 'particle physics'],
        'Chemistry': ['chemistry', 'chemical biology', 'analytical chemistry', 'organic chemistry', 'physical chemistry'],
        'Medicine': ['medical', 'clinical research', 'healthcare', 'pharmaceutical', 'public health', 'immunology'],
        'Mathematics': ['mathematics', 'statistics', 'applied math', 'data analysis'],
        'Social Sciences': ['sociology', 'psychology', 'economics', 'political science', 'social work', 'anthropology', 'geography'],
        'Humanities': ['history', 'philosophy', 'literature', 'arts', 'linguistics', 'archaeology'],
        'Environmental Science': ['environmental', 'ecology', 'climate change', 'earth science', 'sustainability', 'oceanography'],
        'Business & Management': ['business administration', 'management', 'finance', 'marketing', 'human resources'],
        'Education': ['education', 'pedagogy', 'curriculum development']
    }
    for direction, keywords in directions_map.items():
        if any(keyword in text_lower for keyword in keywords):
            return direction
    return 'General'

def generate_summary_article(jobs, platform_name="UniversityPositionsEU"):
    """Generate a markdown summary article from job data"""
    logging.info(f"Generating summary for {len(jobs)} jobs from {platform_name}.")
    if not jobs:
        logging.warning("No positions found to generate an article.")
        return f"# {platform_name} Job Opportunities - No Jobs Found\n\nNo jobs were found in the latest scrape."

    today = datetime.now().strftime('%Y-%m-%d')
    article = f"# {platform_name} Job Opportunities ({today})\n\n"

    classified_jobs = defaultdict(lambda: defaultdict(list))

    for job in jobs:
        if not isinstance(job, dict):
            logging.warning(f"Skipping invalid job item (not a dict): {job}")
            continue
        title = job.get('title', '')
        # Content for classification might come from a specific field or a combination
        content_for_classification = job.get('content', '') # Assuming 'content' holds the main job description

        category = classify_position_by_keywords(title, content_for_classification)
        direction = extract_direction_by_keywords(title + " " + content_for_classification)

        classified_jobs[category][direction].append(job)

    categories_order = ['PhD', 'PostDoc', 'Professor', 'Research Staff', 'Other']

    found_jobs_in_any_category = False
    for category in categories_order:
        if category in classified_jobs and classified_jobs[category]:
            found_jobs_in_any_category = True
            article += f"## {category}\n\n"
            sorted_directions = sorted(classified_jobs[category].keys())
            for direction in sorted_directions:
                article += f"### {direction}\n\n"
                for job_item in classified_jobs[category][direction]:
                    article += f"#### {job_item.get('title', 'N/A')}\n\n"
                    if job_item.get('highlight'):
                        article += f"**AI Highlight:** {job_item.get('highlight')}\n\n"
                    details_list = []
                    if job_item.get('institution'): details_list.append(f"**Institution:** {job_item.get('institution')}")
                    if job_item.get('location'): details_list.append(f"**Location:** {job_item.get('location')}")
                    if job_item.get('deadline'): details_list.append(f"**Application Deadline:** {job_item.get('deadline')}")
                    if job_item.get('posted_date'): details_list.append(f"**Posted Date:** {job_item.get('posted_date')}")
                    if details_list: article += " | ".join(details_list) + "\n\n"
                    article += f"**Job Link:** [{job_item.get('link', '#')}]({job_item.get('link', '#')})\n\n"
                    article += "---\n\n"
        else:
            logging.debug(f"No jobs found for category: {category}")

    if not found_jobs_in_any_category:
        article += "No jobs found matching the defined categories in this scrape.\n\n"

    return article

# --- UniversityPositions specific scraping functions ---
def find_up_job_listings(driver, current_url):
    """Finds job listings on UniversityPositions.eu using a robust selector strategy."""
    job_info_list = []
    logging.info(f"Finding job listings on: {current_url}")
    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "section#job-listings"))
        )
        logging.info(f"Job listings container found on {current_url}.")

        job_item_elements = driver.find_elements(By.CSS_SELECTOR, "div.job-listings-item")
        logging.info(f"Found {len(job_item_elements)} job items on {current_url}.")

        for item_element in job_item_elements:
            title = None
            link = None
            try:
                link_element = item_element.find_element(By.CSS_SELECTOR, "a.job-details-link")
                link = link_element.get_attribute('href')

                # Try to find title within the link element, robustly checking common title tags
                title_element = None
                try: # Try h3 first (common on this site)
                    title_element = link_element.find_element(By.CSS_SELECTOR, "h3")
                except NoSuchElementException: # Fallback to other potential title containers if h3 not found
                    logging.debug("h3 title not found in link, trying other common title tags like h2 or span with specific classes.")
                    # Add other attempts if necessary, e.g. h2, or a span with a specific class
                    # For now, keeping it to h3 as per previous findings for this site.
                    pass # No other fallbacks defined yet based on findings

                if title_element:
                    title = title_element.text.strip()
                else: # If no h3, try to get text from the link_element itself, or a prominent child
                    title = link_element.text.strip() # This might be too broad, but a fallback
                    if not title: # If link_element has no direct text, try to find any h-tag or strong tag
                        try: title_element = link_element.find_element(By.CSS_SELECTOR, "h1, h2, h4, h5, h6, strong")
                        except: pass
                        if title_element: title = title_element.text.strip()


                if title and link:
                    job_info_list.append({'title': title, 'link': link})
                else:
                    if not title: logging.warning(f"Job item found with no title text inside a.job-details-link on {current_url}. Link: {link if link else 'N/A'}")
                    if not link: logging.warning(f"Job item found with no link (a.job-details-link missing or no href) on {current_url}.")

            except NoSuchElementException:
                logging.warning(f"Could not find 'a.job-details-link' or title structure within a 'div.job-listings-item' on {current_url}. Item HTML: {item_element.get_attribute('outerHTML')[:200]}")
                continue
            except Exception as e:
                logging.error(f"Error processing a job item on {current_url}: {e}. Item HTML: {item_element.get_attribute('outerHTML')[:200]}")
                continue

    except TimeoutException:
        logging.error(f"Timeout waiting for job listings container on {current_url}.")
    except Exception as e:
        logging.error(f"Error finding job listings on {page_description} page: {e}")

    return job_info_list

def fetch_up_job_detail(driver, job_url, selected_model=None):
    """Fetches detailed information for a single job posting from UniversityPositions.eu."""
    try:
        if not get_page_content(driver, job_url):
            logging.error(f"Failed to load job detail page: {job_url}")
            return None

        details = {'link': job_url}

        details['title'] = extract_text_safely(driver, "h1.jb-color-000000ff")
        details['content'] = extract_text_safely(driver, "div#quill-container-with-job-details > div.jb-color-000000ff")
        details['institution'] = extract_text_safely(driver, "aside.job-inner-left div.job-inner-detail-box a[href*='/companies/']")
        details['location'] = extract_text_safely(driver, "aside.job-inner-left div.job-inner-detail-box a[href*='/jobs/in-']")

        # Initialize fields that might not have direct selectors or require more complex parsing
        details['deadline'] = "Not found"
        details['posted_date'] = "Not found" # Or try to parse from spans if a pattern is reliable
        details['salary'] = "Not found" # Or try to parse from spans
        details['field_category'] = "Not found"

        # Attempt to find posted_date and salary from the general info box
        # This is an example and might need refinement based on actual page variations
        info_spans = driver.find_elements(By.CSS_SELECTOR, "aside.job-inner-left div.job-inner-detail-box div.d-flex span.jb-color-000000ff")
        # Example: last span is often the posted date (e.g., "13h ago")
        if info_spans:
            # This is a heuristic. The actual index or logic might need to be more robust.
            # For instance, iterate and check text patterns.
            if len(info_spans) > 4 : # Assuming employer, loc, salary, date as typical minimum
                 # The date is often the last element among these spans
                possible_date_text = info_spans[-1].text.strip()
                if "ago" in possible_date_text or re.match(r'\d{1,2}\w{2,3} \d{4}', possible_date_text) or re.match(r'\w{3,} \d{1,2}, \d{4}', possible_date_text) or "today" in possible_date_text.lower():
                    details['posted_date'] = possible_date_text

            for span in info_spans:
                text = span.text.strip()
                if "€" in text and ("year" in text or "month" in text):
                    details['salary'] = text
                    break

        # Extract deadline from JSON-LD if available
        try:
            script_elements = driver.find_elements(By.XPATH, "//script[@type='application/ld+json']")
            for script_element in script_elements:
                json_ld_content = script_element.get_attribute('innerHTML')
                if json_ld_content:
                    data = json.loads(json_ld_content)
                    if data.get('@type') == 'JobPosting':
                        if 'validThrough' in data:
                            details['deadline'] = data['validThrough']
                        if 'datePosted' in data and details['posted_date'] == "Not found": # Prefer specific HTML if found
                             details['posted_date'] = data['datePosted']
                        break # Assuming the first JobPosting JSON-LD is the main one
        except Exception as e:
            logging.warning(f"Could not parse JSON-LD for deadline/date: {e}")


        job_text = details.get('title', '') + "\n" + details.get('content', '')
        if selected_model:
            highlight = ollama_highlight(job_text, model=selected_model)
        else:
            highlight = "AI highlight generation skipped."
        details['highlight'] = highlight

        logging.info(f"Extracted Title: {details.get('title', 'N/A')}, Institution: {details.get('institution', 'N/A')}")

        if not details.get('title') and not details.get('content'):
            logging.warning(f"Essential information (title or content) missing for {job_url}")
            # Decide if this means we should return None or the partial details
            # For now, returning partial details.

        return details

    except Exception as e:
        logging.error(f"Error fetching or processing job detail page {job_url}: {e}", exc_info=True)
        return None


def fetch_up_jobs(use_headless=True, selected_model=None):
    """Fetches all job listings and their details from UniversityPositions.eu."""
    driver = None
    processed_jobs = []
    all_job_summaries = []
    processed_job_links = set()
    # MAX_JOBS_TO_PROCESS is now global

    try:
        driver = setup_driver(use_headless=use_headless)

        # 1. Scrape Base URL (Homepage)
        base_url = "https://universitypositions.eu/"
        logging.info(f"Attempting to scrape base URL: {base_url}")
        if get_page_content(driver, base_url):
            handle_cookie_consent(driver)
            current_page_summaries = find_up_job_listings(driver, base_url)
            for summary in current_page_summaries:
                if summary['link'] not in processed_job_links:
                    all_job_summaries.append(summary)
                    processed_job_links.add(summary['link'])
            logging.info(f"Found {len(current_page_summaries)} summaries on {base_url}. Total unique summaries: {len(all_job_summaries)}")
        else:
            logging.error(f"Failed to load the base URL: {base_url}")

        # 2. Scrape "Browse All Jobs" Page with Pagination
        current_jobs_page_url = "https://universitypositions.eu/jobs"
        page_num = 1
        max_pages_to_scrape = 5 # Safety break for pagination loop during testing

        while current_jobs_page_url and page_num <= max_pages_to_scrape:
            if len(all_job_summaries) >= MAX_JOBS_TO_PROCESS:
                logging.info(f"Reached MAX_JOBS_TO_PROCESS ({MAX_JOBS_TO_PROCESS}), stopping further page scraping.")
                break

            logging.info(f"Attempting to scrape jobs page {page_num}: {current_jobs_page_url}")
            if get_page_content(driver, current_jobs_page_url):
                page_summaries = find_up_job_listings(driver, current_jobs_page_url)
                new_summaries_count = 0
                for summary in page_summaries:
                    if summary['link'] not in processed_job_links:
                        all_job_summaries.append(summary)
                        processed_job_links.add(summary['link'])
                        new_summaries_count += 1
                        if len(all_job_summaries) >= MAX_JOBS_TO_PROCESS:
                            break
                logging.info(f"Found {len(page_summaries)} summaries on this page, {new_summaries_count} were new. Total unique summaries: {len(all_job_summaries)}")

                if len(all_job_summaries) >= MAX_JOBS_TO_PROCESS:
                    logging.info(f"Reached MAX_JOBS_TO_PROCESS ({MAX_JOBS_TO_PROCESS}) after processing page {page_num}.")
                    break

                # Pagination Click
                try:
                    next_page_links = driver.find_elements(By.CSS_SELECTOR, "ul.pagination a[rel='next']")
                    if next_page_links:
                        next_page_url = next_page_links[0].get_attribute('href')
                        if next_page_url and next_page_url != current_jobs_page_url : # Ensure it's a new URL
                            logging.info(f"Navigating to next page: {next_page_url}")
                            current_jobs_page_url = next_page_url
                            page_num += 1
                            time.sleep(2) # Be polite
                        else:
                            logging.info("No valid href for next page link, or it's the same as current. Stopping pagination.")
                            current_jobs_page_url = None
                    else:
                        logging.info("No 'next page' link found. Stopping pagination.")
                        current_jobs_page_url = None
                except Exception as e_paginate:
                    logging.error(f"Error during pagination click: {e_paginate}")
                    current_jobs_page_url = None # Stop pagination on error
            else:
                logging.error(f"Failed to load jobs page: {current_jobs_page_url}")
                break # Stop if a page fails to load

        logging.info(f"Total unique job summaries found from all sources: {len(all_job_summaries)}")

        # Process details for the collected (and potentially limited) summaries
        summaries_to_process_actually = all_job_summaries
        if len(all_job_summaries) > MAX_JOBS_TO_PROCESS: # Apply limit if it wasn't hit by page limit
            logging.info(f"Final check: Limiting processing to the first {MAX_JOBS_TO_PROCESS} jobs out of {len(all_job_summaries)} unique summaries.")
            summaries_to_process_actually = all_job_summaries[:MAX_JOBS_TO_PROCESS]

        for summary in summaries_to_process_actually:
            detail_url = summary.get('link')
            if detail_url:
                logging.info(f"Fetching details for: {summary.get('title', 'N/A')} from {detail_url}")
                job_detail = fetch_up_job_detail(driver, detail_url, selected_model)
                if job_detail:
                    processed_jobs.append(job_detail)
                else:
                    logging.warning(f"Failed to fetch details for {detail_url}")
                time.sleep(0.5) # Be polite to the server
            else:
                logging.warning(f"Skipping summary with no link: {summary.get('title', 'N/A')}")

    except Exception as e:
        logging.error(f"An error occurred during the main fetching process for UniversityPositions: {e}", exc_info=True)
    finally:
        if driver:
            driver.quit()
            logging.info("WebDriver closed.")
    return processed_jobs
# --- End of UniversityPositions specific functions ---

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stdout)

    logging.info("=== UniversityPositionsEU Scraper Execution Start ===")

    platform_name = "UniversityPositionsEU"
    jobs_data = []
    # selected_ai_model = None # Comment out to enable AI model selection/usage

    try:
        logging.info(f"--- Phase 1: AI Server Setup for {platform_name} ---")
        selected_ai_model = "deepseek-r1:70b" # Default model, can be changed by select_model if available
        if check_ai_server():
            logging.info(f"AI Server is available for {platform_name}.")
            available_models_on_server = list_available_models()
            if not available_models_on_server:
                logging.warning("No models listed by AI server. Disabling AI highlights.")
                selected_ai_model = None
            elif selected_ai_model not in available_models_on_server:
                logging.warning(f"Default model {selected_ai_model} not in available models: {available_models_on_server}.")
                # Attempt to use a known fallback or the first available model
                if "qwen3:30b-a3b" in available_models_on_server:
                    selected_ai_model = "qwen3:30b-a3b"
                    logging.info(f"Using fallback model: {selected_ai_model}")
                elif available_models_on_server: # Pick the first one if fallback not there
                    selected_ai_model = available_models_on_server[0]
                    logging.info(f"Using first available model: {selected_ai_model}")
                else: # Should not happen if available_models_on_server was not empty
                    logging.error("Logic error: available_models_on_server was populated but no model could be selected.")
                    selected_ai_model = None

            if selected_ai_model and not check_model_availability(selected_ai_model):
                 logging.warning(f"Chosen model {selected_ai_model} is not available/functional. Disabling AI highlights.")
                 selected_ai_model = None
            # Optionally, include user selection if interactive environment is assumed for testing
            # else:
            #    logging.info("AI Server available. You may be prompted to select a model.")
            #    selected_ai_model = select_model() # This would require user input if run directly

        else:
            logging.warning(f"AI Server not available for {platform_name}. AI Highlights will be disabled.")
            selected_ai_model = None
        logging.info(f"Using AI model for {platform_name} highlights: {selected_ai_model if selected_ai_model else 'N/A (AI Disabled)'}")

        logging.info(f"--- Phase 2: Fetching Full Job Details from {platform_name} (Max {MAX_JOBS_TO_PROCESS} jobs) ---")
        jobs_data = fetch_up_jobs(use_headless=True, selected_model=selected_ai_model)

        logging.info(f"Successfully processed {len(jobs_data)} job details.")
        if jobs_data:
            logging.info(f"First job processed: {jobs_data[0]}")


        if not jobs_data:
            logging.warning(f"No job details processed from {platform_name}. No report will be generated.")
        else:
            logging.info(f"--- Phase 3: Saving Data for {platform_name} ---")
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = "backup"
            os.makedirs(backup_dir, exist_ok=True)

            json_output_filename = os.path.join(backup_dir, f"{platform_name.lower()}_jobs_{timestamp_str}.json")
            try:
                with open(json_output_filename, "w", encoding="utf-8") as f:
                    json.dump(jobs_data, f, ensure_ascii=False, indent=4)
                logging.info(f"Scraped {platform_name} job data saved to {json_output_filename}")
            except IOError as e:
                logging.error(f"Error saving {platform_name} job data to JSON: {e}")
            except TypeError as e:
                logging.error(f"TypeError during JSON serialization for {platform_name} jobs: {e}. Check data structure.")

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
        logging.critical(f"A top-level error occurred in the {platform_name} scraper: {e}", exc_info=True)
        if jobs_data:
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
