# Import necessary libraries
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, InvalidSelectorException, StaleElementReferenceException
import time
import re
import os
import sys
from collections import defaultdict
import winreg
from bs4 import BeautifulSoup
import json
from datetime import datetime
import requests

# Ensure UTF-8 encoding for standard output
sys.stdout.reconfigure(encoding='utf-8')

# Initialize global variables
default_server_url = "http://rf-calcul:11434"  # Default to rf-calcul

def set_windows_proxy_from_pac(pac_url):
    """Set Windows system proxy from PAC URL"""
    try:
        reg_path = r"Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "AutoConfigURL", 0, winreg.REG_SZ, pac_url)
        print(f"System proxy PAC set to: {pac_url}")
    except Exception as e:
        print(f"Failed to set system proxy: {e}")

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
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-infobars')
    options.add_argument('--window-size=1920,1080')
    
    # Error handling and logging
    options.add_argument('--log-level=3')  # Only show fatal errors
    options.add_argument('--silent')
    options.add_experimental_option('excludeSwitches', ['enable-logging'])
    
    if use_headless:
        options.add_argument('--headless=new')
        print("Starting browser in headless mode...")
    else:
        print("Starting browser in visible mode...")
    
    # Enhanced error handling for driver initialization
    max_retries = 3
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            try:
                service = Service("./chromedriver.exe")
                driver = webdriver.Chrome(service=service, options=options)
                print("Successfully initialized Chrome driver with local chromedriver.exe")
                return driver
            except Exception as e:
                print(f"Local chromedriver.exe failed, trying system ChromeDriver: {str(e)}")
                driver = webdriver.Chrome(options=options)
                print("Successfully initialized Chrome driver with system ChromeDriver")
                return driver
        except Exception as e:
            last_exception = e
            print(f"Attempt {attempt + 1} failed: {str(e)}")
            time.sleep(2)  # Wait before retrying
    
    # If all attempts failed, try one last time with current directory chromedriver
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        chromedriver_path = os.path.join(current_dir, "chromedriver.exe")
        service = Service(chromedriver_path)
        driver = webdriver.Chrome(service=service, options=options)
        print(f"Successfully initialized Chrome driver with chromedriver at: {chromedriver_path}")
        return driver
    except Exception as final_e:
        error_msg = f"Failed to initialize Chrome driver after {max_retries} attempts.\n"
        error_msg += f"Last error: {str(last_exception)}\n"
        error_msg += f"Final attempt error: {str(final_e)}"
        raise RuntimeError(error_msg)

def handle_cookie_consent(driver):
    """Handle cookie consent popup if present"""
    try:
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 
                '#cookie-consent button, .cookie-banner button, .consent-button'))
        ).click()
        print("Cookie consent handled")
    except TimeoutException:
        print("No cookie consent found or already accepted")

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
                print(f"Attempt {attempt + 1} failed: {e}. Retrying...")
                time.sleep(2)
            else:
                print(f"Failed to load page after {max_retries} attempts: {e}")
                return False

def extract_text_safely(element, selector):
    """Safely extract text from an element using a CSS selector"""
    try:
        # First try direct selector
        try:
            elem = element.find_element(By.CSS_SELECTOR, selector)
            return elem.text.strip()
        except (NoSuchElementException, InvalidSelectorException):
            # If the selector fails, try a more lenient version
            if selector.startswith('.'):
                # For class selectors, try using contains
                class_name = selector.replace('.', '')
                elem = element.find_element(By.CSS_SELECTOR, f"[class*='{class_name}']")
                return elem.text.strip()
            elif selector.startswith('#'):
                # For ID selectors, try partial match
                id_name = selector.replace('#', '')
                elem = element.find_element(By.CSS_SELECTOR, f"[id*='{id_name}']")
                return elem.text.strip()
            
    except (NoSuchElementException, AttributeError, InvalidSelectorException) as e:
        print(f"Failed to extract text with selector {selector}: {str(e)}")
        return ""

def fetch_job_detail(driver, url, model="deepseek-r1:70b"):
    """Fetch detailed job information from DAAD posting"""
    if not get_page_content(driver, url):
        return None

    try:
        # Main content selectors for DAAD
        content_selectors = [
            'main',
            'article',
            '.content-detail',
            '.deg-content',
            '.c-content-area'
        ]

        content = ""
        for selector in content_selectors:
            try:
                if validate_selector(selector):
                    element = find_element_with_retry(driver, By.CSS_SELECTOR, selector)
                    if element:
                        content = element.text
                        if content:
                            break
            except Exception as e:
                print(f"Failed to get content with selector '{selector}': {e}")
                continue        

        # Extract structured data
        info = {
            'title': '',
            'content': content,
            'institution': '',
            'location': '',
            'requirements': '',
            'contract': '',
            'link': url,
            'highlight': ''  # Will be filled with AI-generated highlights
        }

        # Extract title
        title_selectors = [
            'h1', 
            '.deg-title',
            '.content-title',
            'article h2'
        ]
        for selector in title_selectors:
            try:
                if validate_selector(selector):
                    element = find_element_with_retry(driver, By.CSS_SELECTOR, selector)
                    if element:
                        info['title'] = extract_text_with_fallback(element, selector)
                        if info['title']:
                            break
            except Exception as e:
                print(f"Failed to get title with selector '{selector}': {e}")
                continue

        # Extract other information from content
        content_lower = content.lower()
        
        # Institution
        inst_patterns = [
            r'university of [\w\s]+',
            r'[\w\s]+ university',
            r'institut(?:e)? (?:of|für) [\w\s]+',
            r'max planck [\w\s]+',
            r'helmholtz [\w\s]+'
        ]
        for pattern in inst_patterns:
            match = re.search(pattern, content_lower, re.IGNORECASE)
            if match:
                info['institution'] = match.group(0).title()
                break

        # Location
        loc_patterns = [
            r'located in (?:[\w\s,]+)',
            r'based in (?:[\w\s,]+)',
            r'(?:position in|at) (?:[\w\s,]+), germany',
        ]
        for pattern in loc_patterns:
            match = re.search(pattern, content_lower, re.IGNORECASE)
            if match:
                info['location'] = match.group(0).replace('located in ', '').replace('based in ', '').title()
                break

        # Requirements
        req_section = re.search(r'requirements?:[\s\n]*(.*?)(?=\n\n|\Z)', content, re.IGNORECASE | re.DOTALL)
        if req_section:
            info['requirements'] = req_section.group(1).strip()

        # Contract/Duration
        duration_patterns = [
            r'(?:duration|period):?\s*((?:\d+|one|two|three|four)\s+(?:year|month)s?)',
            r'contract (?:period|length):?\s*((?:\d+|one|two|three|four)\s+(?:year|month)s?)',
            r'(?:fixed[- ]term|temporary) contract for (\d+\s+(?:year|month)s?)',
        ]
        for pattern in duration_patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                info['contract'] = match.group(1)
                break

        # Translate relevant fields to Chinese
        fields_to_translate = ['title', 'institution', 'location', 'requirements', 'contract']
        print(f"Translating fields for URL: {url} using model: {model}")
        for field_key in fields_to_translate:
            if info[field_key]: # Check if the field has content
                original_text = info[field_key]
                # 'model' is the selected_model passed to fetch_job_detail
                translated_text = translate_german_to_chinese(original_text, model) 
                info[field_key] = translated_text
                # Limit print length to avoid overly long log lines
                original_snippet = original_text.strip().replace('\n', ' ')[:50]
                translated_snippet = translated_text.strip().replace('\n', ' ')[:50]
                print(f"Translated {field_key}: '{original_snippet}...' to '{translated_snippet}...'")
            else:
                print(f"Skipping translation for empty field: {field_key}")

        # Generate AI highlights for the position using the selected model
        print("Generating AI highlights...")
        # info['title'] is now translated. info['content'] remains original.
        # ollama_highlight's prompt has its own instruction to translate German parts if found.
        text_for_highlight = info['title'] + '\n' + info['content']
        try:
            highlight = ollama_highlight(text_for_highlight, model=model or "deepseek-r1:70b")
            info['highlight'] = highlight
            print("Successfully added AI highlights")
        except Exception as e:
            print(f"Failed to generate AI highlights: {e}")
            info['highlight'] = "Opportunity for research and academic development in a supportive environment."

        return info

    except Exception as e:
        print(f"Error fetching job details: {e}")
        return None

def find_job_listings(driver, num_to_fetch=10):
    """Find job listing elements on the page"""
    print("Looking for job search functionality...")
    job_elements = []
    
    try:
        # First ensure the page is fully loaded
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        time.sleep(2)  # Give extra time for dynamic content to load
        
        # Wait for any loading indicators to disappear
        try:
            WebDriverWait(driver, 10).until_not(
                EC.presence_of_element_located((By.CSS_SELECTOR, '[class*="loading"], [class*="spinner"], [class*="loader"]'))
            )
        except TimeoutException:
            print("No loading indicators found or already gone")
            
        print("Page loaded, searching for job listings...")
        
        # Prioritized list of job listing selectors
        selectors = [
            'article',                      # Main content articles
            '.deg-teaser',                  # DAAD specific teasers
            '.position-listing',            # Position listings
            '[role="article"]',             # Semantic article elements
            '.list-group-item',             # Alternative listing format
            '[class*="result-item"]',       # Dynamic result items
            '.result-item'                  # Basic result items
        ]
        
        # Try each selector
        for selector in selectors:
            if not validate_selector(selector):
                print(f"Invalid selector syntax: {selector}, skipping...")
                continue
            
            try:
                print(f"Trying selector: {selector}")
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                
                if not elements:
                    continue
                    
                print(f"Found {len(elements)} potential elements with {selector}")
                
                # Process each element found with this selector
                for element in elements:
                    try:
                        # Try to get element text
                        text = driver.execute_script("""
                            try {
                                return (arguments[0].innerText || arguments[0].textContent || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                            } catch(e) {
                                return '';
                            }
                        """, element)
                        
                        if text and any(kw in text for kw in ['phd', 'doctoral', 'research', 'position', 'scholarship']):
                            job_elements.append(element)
                            preview = ' '.join(word.capitalize() for word in text.split()[:6])
                            print(f"Found relevant position: {preview}...")
                            
                            if len(job_elements) >= num_to_fetch:
                                print("Found enough positions, stopping search...")
                                return job_elements
                                
                    except Exception as e:
                        print(f"Error processing element: {e}")
                        continue
            
            except Exception as e:
                print(f"Error with selector {selector}: {e}")
                continue
        
        # Fallback to link search if no elements found
        if not job_elements:
            print("Trying direct link search...")
            try:
                for link in driver.find_elements(By.TAG_NAME, 'a'):
                    try:
                        href = link.get_attribute('href') or ''
                        text = link.text.lower()
                        if href and any(kw in (text + ' ' + href.lower()) 
                                      for kw in ['phd', 'doctoral', 'position']):
                            job_elements.append(link)
                            print(f"Found relevant link: {text[:50]}...")
                            if len(job_elements) >= num_to_fetch:
                                break
                    except Exception as e:
                        continue
            except Exception as e:
                print(f"Error in link search: {e}")
        
        return job_elements
        
    except Exception as e:
        print(f"Error in job listing search: {e}")
        # Save debug information
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            driver.save_screenshot(f"debug_screenshot_{timestamp}.png")
            with open(f"debug_source_{timestamp}.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            print(f"Debug information saved with timestamp {timestamp}")
        except Exception as debug_e:
            print(f"Failed to save debug information: {debug_e}")
        return []

def fetch_daad_jobs(use_headless=True, selected_model=None, num_jobs=10):
    """Main function to fetch PhD positions from DAAD
    
    Args:
        use_headless (bool): Whether to use headless browser mode
        selected_model (str): The AI model to use for generating highlights
        num_jobs (int): The number of jobs to fetch
    """
    set_windows_proxy_from_pac("http://127.0.0.1:55624/proxy.pac")
    base_url = "https://www2.daad.de/deutschland/promotion/phd/en/13306-phd-germany-database/"

    driver = None
    jobs = []
    
    try:
        driver = setup_driver(use_headless)
        if not get_page_content(driver, base_url):
            print("Failed to load base URL")
            return []

        handle_cookie_consent(driver)

        # Find job listings with retry logic
        max_retries = 3
        job_elements = []
        
        for attempt in range(max_retries):
            try:
                print(f"\nAttempt {attempt + 1}/{max_retries} to find job listings...")
                job_elements = find_job_listings(driver, num_jobs)
                if job_elements:
                    break
                else:
                    print("No job elements found, retrying...")
                    driver.refresh()
                    time.sleep(3)
            except Exception as e:
                print(f"Error in attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    driver.refresh()
                    time.sleep(3)

        if not job_elements:
            print("Failed to find any job elements after all retries")
            return []

        # Store all job URLs and titles first
        job_info_list = []
        print("\nCollecting job links and titles...")
        
        for element in job_elements:
            try:
                link = None
                title = None
                
                # Try multiple methods to extract link and title
                if element.tag_name == 'a':
                    link = element.get_attribute('href')
                    title = element.text.strip()
                else:
                    # Try to find link within the element
                    link_candidates = element.find_elements(By.TAG_NAME, 'a')
                    for link_elem in link_candidates:
                        try:
                            potential_link = link_elem.get_attribute('href')
                            potential_title = link_elem.text.strip()
                            if potential_link and potential_title and 'phd' in (potential_link + potential_title).lower():
                                link = potential_link
                                title = potential_title
                                break
                        except:
                            continue
                    
                    # If still no title, try to get it from the element itself
                    if not title:
                        title = element.text.strip()
                
                if link and title and not any(x['link'] == link for x in job_info_list):
                    job_info_list.append({
                        'link': link,
                        'title': title
                    })
                    print(f"Found position: {title[:50]}...")
            
            except StaleElementReferenceException:
                print("Encountered stale element, continuing to next...")
                continue
            except Exception as e:
                print(f"Error extracting job info: {e}")
                continue

        if not job_info_list:
            print("No valid job information found")
            return []

        # Process each job with progress tracking
        total_jobs = len(job_info_list)
        print(f"\nFound {total_jobs} positions to process")
        
        for idx, job_info in enumerate(job_info_list, 1):
            try:
                print(f"\nProcessing position {idx}/{total_jobs}")
                print(f"Title: {job_info['title'][:100]}...")
                print(f"URL: {job_info['link']}")
                
                # Get detailed job information with retry logic
                details = None
                retries = 3
                for attempt in range(retries):
                    try:
                        details = fetch_job_detail(driver, job_info['link'], model=selected_model)
                        if details:
                            break
                        print(f"Attempt {attempt + 1} failed, retrying...")
                        time.sleep(2)
                    except Exception as e:
                        print(f"Error in attempt {attempt + 1}: {e}")
                        if attempt < retries - 1:
                            time.sleep(2)
            
                if details:
                    # Ensure we have at least a title
                    if not details.get('title'):
                        details['title'] = job_info['title']
                    jobs.append(details)
                    print(f"Successfully processed position {idx}/{total_jobs}")
                else:
                    print(f"Failed to get details for position {idx}")

            except Exception as e:
                print(f"Error processing job {idx}: {e}")
                continue

        print(f"\nSuccessfully processed {len(jobs)}/{total_jobs} positions")

    except Exception as e:
        print(f"Error in main job fetching process: {e}")
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass

    return jobs

def safe_driver_operation(driver_func):
    """Decorator for safe WebDriver operations with retry logic"""
    def wrapper(*args, **kwargs):
        max_retries = 3
        retry_delay = 2
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                return driver_func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                print(f"Operation failed (attempt {attempt + 1}/{max_retries}): {str(e)}")
                if "chrome not reachable" in str(e).lower():
                    print("Chrome has become unreachable, attempting to recover...")
                    driver = args[0] if args else None
                    if driver:
                        try:
                            driver.quit()
                        except:
                            pass
                        driver = setup_driver(use_headless=True)
                        # Update the driver in the first argument
                        args = list(args)
                        args[0] = driver
                        args = tuple(args)
                elif "gpu process launch failed" in str(e).lower():
                    print("GPU process error detected, retrying with additional GPU disable options...")
                    time.sleep(retry_delay)
                else:
                    time.sleep(retry_delay)
        
        raise RuntimeError(f"Operation failed after {max_retries} attempts. Last error: {str(last_exception)}")
    
    return wrapper

@safe_driver_operation
def scrape_daad_phd_positions(driver, url):
    """Scrape PhD positions from DAAD with enhanced error handling"""
    try:
        driver.get(url)
        print(f"Successfully loaded URL: {url}")
        
        # Wait for page to load and handle cookie consent if present
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        
        # Handle cookie consent if present
        try:
            cookie_button = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.ID, "cookieNoticeDeclined"))
            )
            cookie_button.click()
            print("Cookie consent handled successfully")
        except TimeoutException:
            print("No cookie consent found or already accepted")
        
        # Wait for job listings to load
        job_selectors = [
            '.list-group-item',
            '.search-result-item',
            '.phd-position-item',
            '.position-listing'
        ]
        
        # Try each selector until we find matching elements
        jobs = []
        for selector in job_selectors:
            try:
                elements = WebDriverWait(driver, 5).until(
                    EC.presence_of_all_elements_located((By.CSS_SELECTOR, selector))
                )
                if elements:
                    jobs = elements
                    print(f"Found {len(jobs)} jobs using selector: {selector}")
                    break
            except TimeoutException:
                continue
        
        if not jobs:
            raise Exception("No job listings found with any of the known selectors")
        
        # Process each job listing
        results = []
        for job in jobs:
            try:
                title = job.find_element(By.CSS_SELECTOR, "h3, h4, .title").text.strip()
                link = job.find_element(By.TAG_NAME, "a").get_attribute("href")
                description = job.find_element(By.CSS_SELECTOR, ".description, .content").text.strip()
                
                results.append({
                    "title": title,
                    "link": link,
                    "description": description
                })
                
            except Exception as e:
                print(f"Error processing job listing: {str(e)}")
                continue
        
        return results
        
    except Exception as e:
        print(f"Error during scraping: {str(e)}")
        raise

def list_available_models(host="http://rf-calcul:11434"):
    """List all available models on the server"""
    try:
        resp = requests.get(f"{host}/api/tags", timeout=30)
        resp.raise_for_status()
        models_data = resp.json()
        available_models = []
        
        for model_info in models_data.get('models', []):
            model_name = model_info.get('name', '')
            if model_name:
                available_models.append(model_name)
                
        return available_models
    except Exception as e:
        print(f"获取模型列表失败: {e}")
        return []

def check_model_availability(model, host=None):
    """Check if a specific model is available and loaded. Returns True if available, False if not."""
    global default_server_url
    servers = [host] if host else ["http://rf-calcul:11434"]
    if default_server_url:
        # Put the last successful server first
        if default_server_url in servers:
            servers.remove(default_server_url)
        servers.insert(0, default_server_url)

    for server in servers:
        try:
            # First check if the model exists in the available tags
            try:
                tags_resp = requests.get(f"{server}/api/tags", timeout=30)
                tags_resp.raise_for_status()
                tags_data = tags_resp.json()

                model_exists = False
                for model_info in tags_data.get('models', []):
                    if model_info.get('name') == model:
                        model_exists = True
                        print(f"模型 {model} 在服务器 {server} 上存在")
                        # Update default server URL on success
                        default_server_url = server
                        return True

                if not model_exists:
                    print(f"模型 {model} 在服务器 {server} 上不存在")
                    continue
            except Exception as e:
                print(f"服务器 {server} 检查模型列表失败: {e}")
                continue

            # Test the model with a simple prompt
            print(f"正在测试服务器 {server} 的模型 {model} 响应...")
            resp = requests.post(
                f"{server}/api/generate",
                json={"model": model, "prompt": "test", "stream": False},
                timeout=60
            )
            resp.raise_for_status()
            print(f"模型 {model} 在服务器 {server} 上测试成功")
            # Update default server URL on success
            default_server_url = server
            return True

        except requests.exceptions.Timeout:
            print(f"服务器 {server} 的模型 {model} 检查超时")
            continue
        except Exception as e:
            print(f"服务器 {server} 的模型 {model} 检查失败: {e}")
            continue

    print(f"所有服务器上都未找到可用的模型 {model}")
    return False

def check_ai_server(host="http://rf-calcul:11434"):
    """Check if the AI server is available and models are loaded"""
    # List of servers to try
    servers = ["http://rf-calcul:11434"]
    
    for server in servers:
        try:
            # First check if the server is running by checking the version endpoint
            print(f"正在检查服务器 {server} 连接...")
            resp = requests.get(f"{server}/api/version", timeout=5)  # Short timeout for quick check
            resp.raise_for_status()
            version = resp.json().get('version', 'unknown')
            print(f"服务器连接成功，Ollama 版本: {version}")
            
            # Set the successful server as the default host
            global default_server_url
            default_server_url = server
            
            # Check required models
            models = ["deepseek-r1:70b", "qwen3:30b-a3b"]
            available_models = []

            # First try to get the list of all models
            try:
                print("正在获取可用模型列表...")
                tags_resp = requests.get(f"{server}/api/tags", timeout=30)
                tags_resp.raise_for_status()
                tags_data = tags_resp.json()

                all_models = [model_info.get('name') for model_info in tags_data.get('models', [])]
                print(f"服务器上的所有模型: {', '.join(all_models)}")

                # Check if our required models are in the list
                for model in models:
                    if model in all_models:
                        available_models.append(model)
                        print(f"模型 {model} 在服务器上存在")
                    else:
                        print(f"模型 {model} 在服务器上不存在")
            except Exception as e:
                print(f"获取模型列表失败: {e}")
                print("将尝试直接检查每个模型...")

            # If we couldn't get the list or not all required models were found,
            # check each model individually
            if len(available_models) < len(models):
                for model in models:
                    if model not in available_models and check_model_availability(model, server):
                        available_models.append(model)
                        print(f"模型 {model} 可用")

            if not available_models:
                print(f"在服务器 {server} 上没有可用的模型")
                continue

            print(f"找到 {len(available_models)}/{len(models)} 个可用模型")
            return True
            
        except Exception as e:
            print(f"服务器 {server} 连接失败: {e}")
            continue
    
    print("所有服务器都连接失败")
    return False

def select_model():
    """Let user select which model to use"""
    models = list_available_models()
    if not models:
        print("无法获取模型列表，将使用默认模型 deepseek-r1:70b")
        return "deepseek-r1:70b"
    
    print("\n可用模型列表:")
    for i, model in enumerate(models, 1):
        print(f"{i}. {model}")
    
    while True:
        try:
            choice = input("\n请选择要使用的模型 (输入序号): ")
            idx = int(choice) - 1
            if 0 <= idx < len(models):
                return models[idx]
            else:
                print("无效的选择，请重试")
        except ValueError:
            print("请输入有效的数字")
        except KeyboardInterrupt:
            print("\n已取消选择，使用默认模型 deepseek-r1:70b")
            return "deepseek-r1:70b"

def ollama_highlight(text, model="deepseek-r1:70b", host=None):
    """生成职位亮点，如果主模型失败则使用备用模型"""
    global default_server_url
    servers = [host] if host else ["http://rf-calcul:11434"]
    if default_server_url:
        if default_server_url in servers:
            servers.remove(default_server_url)
        servers.insert(0, default_server_url)    
        example = """
        蒙特利尔大学（Université de Montréal）位于北美著名文化名城蒙特利尔，城市环境宜居，交通便利，四季分明。校园提供卓越的学术环境，拥有世界级的研究资源和多元文化的国际社区。蒙特利尔作为加拿大第二大城市，文化氛围浓厚，生活成本适中，是国际学生的理想选择。
        """    
        prompt = (
        f"请分析以下学术招聘信息，提取并总结该职位的主要亮点、特色和地理位置优势。\n\n"
        f"If the job title or key details in the '招聘信息' (recruitment information) are in German, please first translate them into Chinese. Then, proceed with the analysis and summary in Chinese as requested.\n\n"
        f"要求：\n"
        f"1. 分析研究机构/大学的声誉、研究方向的前沿性、团队影响力和资源设备\n"
        f"2. 特别强调地理位置优势，包括：城市特色、气候环境、交通便利性、国际化程度、生活质量等\n"
        f"3. 用中文输出一段简洁有力的描述（100-150字左右）\n"
        f"4. 直接描述核心亮点，不要有'该职位'、'这个岗位'等词\n"
        f"5. 使用吸引人的表述，突出最具竞争力的方面\n\n"
        f"参考示例：\n{example}\n\n"
        f"招聘信息：\n{text[:2000]}"
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
    for server in servers:
        try:
            url = f"{server}/api/generate"
            print(f"正在使用服务器 {server} 的 {model} 模型生成职位亮点...")
            
            resp = requests.post(url, json=payload, headers=headers, timeout=600)
            resp.raise_for_status()

            result = resp.json()
            if not isinstance(result, dict) or "response" not in result:
                print(f"API响应格式错误: {result}")
                raise Exception("API响应格式错误")

            highlight = result["response"].strip()
            print("亮点生成成功")
            
            # Update the default server URL
            default_server_url = server

            # Clean up common AI prefixes
            common_prefixes = [
                "这个职位的亮点是", "该岗位的优势在于", "职位亮点：",
                "AI分析：", "让我分析：", "分析得出：", "总结：",
                "亮点包括：", "特色在于：", "优势是：", "经分析，",
                "根据描述，", "通过分析，", "主要亮点：",
                "分析如下：", "职位分析：", "优势分析：", "特点如下：",
                "思考过程：", "我的分析：", "我认为", "我觉得",
            ]
            
            for prefix in common_prefixes:
                if highlight.lower().startswith(prefix.lower()):
                    highlight = highlight[len(prefix):].strip()
            
            # Remove thinking patterns and normalize whitespace
            highlight = re.sub(r'<think>.*?</think>', '', highlight, flags=re.DOTALL)
            highlight = re.sub(r'\n\s*\n', '\n', highlight).strip()
            
            return highlight

        except requests.exceptions.Timeout:
            print(f"服务器 {server} 请求超时")
            last_error = "timeout"
            continue
        except Exception as e:
            print(f"服务器 {server} 调用失败: {e}")
            last_error = str(e)
            continue

    # If all servers failed, try backup model
    backup_model = "qwen3:30b-a3b"  # Updated backup model name
    print(f"所有服务器都失败 ({last_error})，尝试备用模型 {backup_model}...")

    try:
        # Use a simpler prompt with backup model
        simple_prompt = f"请用一段话总结以下学术招聘信息的主要亮点和特色：\n\n{text[:1000]}"
        payload["model"] = backup_model
        payload["prompt"] = simple_prompt

        # Try all servers again with backup model
        for server in servers:
            try:
                resp = requests.post(
                    f"{server}/api/generate",
                    json=payload,
                    headers=headers,
                    timeout=600
                )
                resp.raise_for_status()
                result = resp.json()
                highlight = result.get("response", "").strip()
                if highlight:
                    # Update the default server URL
                    default_server_url = server
                    return highlight
            except Exception:
                continue
    except Exception as e:
        print(f"备用模型失败: {e}")    # If all AI attempts fail, use enhanced simple extraction
    print("所有模型都失败，使用增强的简单提取方法...")
    # Extract key information from text
    institution = re.search(r'(?:university|大学|学院|研究所|institute)[\s:]*([\w\s]+)', text, re.IGNORECASE)
    location = re.search(r'(?:location|地点|位于)[\s:]*([\w\s,]+)', text, re.IGNORECASE)
    field = re.search(r'(?:research|field|研究|领域)[\s:]*([\w\s,]+)', text, re.IGNORECASE)
    
    # City/region information extraction
    city_match = re.search(r'(?:in|at|near|位于)?\s*((?:Frankfurt|Berlin|Munich|Hamburg|Cologne|Dresden|Stuttgart|Heidelberg|Aachen|Karlsruhe|Göttingen|Bonn|Leipzig|Freiburg|Münster|Tübingen|Konstanz|Mannheim|Darmstadt|Würzburg|München)(?:\s*am\s*(?:Main|Rhein|Neckar))?)', text, re.IGNORECASE)
    
    # Common German city characteristics
    city_info = {
        'Berlin': '德国首都，国际化大都市，文化艺术中心，创新创业活跃',
        'Munich': '巴伐利亚州首府，高科技产业集群，生活质量极高，临近阿尔卑斯山',
        'Frankfurt': '金融中心，交通枢纽，国际化程度高，生活便利',
        'Hamburg': '德国第二大城市，港口城市，文化多元，环境优美',
        'Heidelberg': '著名大学城，风景如画，学术氛围浓厚，适合求学',
        'Dresden': '文化古城，高科技产业发达，生活成本适中，自然环境优美',
        'Stuttgart': '工业重镇，汽车之都，创新驱动，文化底蕴深厚',
        'Aachen': '德国最西部城市，邻近比利时和荷兰，工程技术实力雄厚',
        'Göttingen': '传统大学城，学术氛围浓厚，生活节奏宜人',
        'Bonn': '前首都，国际组织云集，生活质量高，莱茵河畔风光秀丽'
    }

    highlight_parts = []
    if institution:
        highlight_parts.append(f"{institution.group(1)}是一所知名学术机构")
    if location:
        city = location.group(1).strip()
        if city_match:
            city = city_match.group(1)
            city_description = city_info.get(city.title(), f"位于{city}")
            highlight_parts.append(city_description)
        else:
            highlight_parts.append(f"位于{city}")
    if field:
        highlight_parts.append(f"在{field.group(1)}领域有突出研究")

    if highlight_parts:
        return "，".join(highlight_parts) + "。项目提供完善的科研设施、国际化的学术环境和良好的发展机会。"
    else:
        return "提供国际化的学术环境、完善的科研设施和良好的发展前景，是追求学术卓越的理想选择。"

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
        print(f"Failed to extract text with selector {selector}: {e}")
        
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
                raise
            print(f"Stale element, retrying... ({attempt + 1}/{max_retries})")
            time.sleep(1)
        except TimeoutException:
            if attempt == max_retries - 1:
                raise
            print(f"Timeout, retrying... ({attempt + 1}/{max_retries})")
            time.sleep(1)

def generate_summary_article(jobs, selected_model_name):
    """Generate a markdown summary article from job data with Chinese labels and translated snippets."""
    if not jobs:
        return "未找到职位信息。" # "No positions found."
        
    article = "# DAAD博士职位机会\n\n" # "# DAAD PhD Position Opportunities"
    article += f"*更新于: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n\n" # "*Last updated: ..."
    
    for job in jobs:
        content = job.get('content', '') # Raw content for extracting non-translated fields
        
        # Title (already translated in fetch_job_detail)
        job_title = job.get('title') if job.get('title') else "德国博士职位" # "PhD Position in Germany"
        article += f"## {job_title}\n\n"
        
        # Deadline (extract from raw content and translate)
        deadline_text = "未指定" # "Not specified"
        deadline_match = re.search(r'Application Deadline\s*\n([^\n]+)', content)
        if deadline_match:
            extracted_deadline_text = deadline_match.group(1).strip()
            if extracted_deadline_text:
                # Check if it's already a common non-translatable phrase or a date
                if not re.match(r"^\d{4}-\d{2}-\d{2}$", extracted_deadline_text.lower()) and \
                   extracted_deadline_text.lower() not in ["not specified", "n/a", "none"]:
                    deadline_text = translate_german_to_chinese(extracted_deadline_text, selected_model_name)
                else:
                    deadline_text = extracted_deadline_text # Use as is if it's a date or common placeholder
        article += f"**截止日期:** {deadline_text}\n\n" # "**Application Deadline:**"

        # Highlights (already AI-processed, likely in Chinese or translated by ollama_highlight's prompt)
        if job.get('highlight'):
            article += f"**职位亮点:** {job['highlight']}\n\n" # "**Highlights:**"
            
        # Institution (already translated in fetch_job_detail)
        if job.get('institution'):
            article += f"**机构:** {job['institution']}\n\n" # "**Institution:**"
            
        # Location (already translated in fetch_job_detail)
        if job.get('location'):
            article += f"**地点:** {job['location']}\n\n" # "**Location:**"
            
        # Requirements (already translated in fetch_job_detail)
        if job.get('requirements'):
            article += f"**要求:** {job['requirements']}\n\n" # "**Requirements:**"
        
        # Contract Duration (already translated in fetch_job_detail)
        if job.get('contract'):
            article += f"**合同期限:** {job['contract']}\n\n" # "**Contract Duration:**"

        # Starting Date (extract from raw content and translate)
        starting_date_display = "未指定" # "Not specified"
        start_match = re.search(r'Starting Date\s*\n([^\n]+)', content)
        if start_match:
            extracted_starting_date_text = start_match.group(1).strip()
            if extracted_starting_date_text and extracted_starting_date_text.lower() != "not specified":
                if extracted_starting_date_text.lower() in ["as soon as possible", "sofort", "asap"]:
                    starting_date_display = "尽快" # "As soon as possible"
                # Check if it's already a common non-translatable phrase or a date
                elif not re.match(r"^\d{4}-\d{2}-\d{2}$", extracted_starting_date_text.lower()) and \
                     extracted_starting_date_text.lower() not in ["n/a", "none"]:
                    starting_date_display = translate_german_to_chinese(extracted_starting_date_text, selected_model_name)
                else:
                    starting_date_display = extracted_starting_date_text # Use as is
        article += f"**开始日期:** {starting_date_display}\n\n" # "**Starting Date:**"
        
        # Job Link (no translation needed for URL itself)
        if job.get('link'):
            article += f"**职位链接:** {job.get('link')}\n\n" # "**Job link:**"
        
        article += "---\n\n"
    
    return article

# Initialize default server URL for AI processing
default_server_url = None


def translate_german_to_chinese(text_to_translate, model_name, ollama_host="http://rf-calcul:11434"):
    if not text_to_translate or not isinstance(text_to_translate, str):
        return text_to_translate # Return if empty or not a string

    # Basic check for non-Chinese characters, assuming German text will have them.
    # This is a heuristic; more robust language detection is complex.
    if not re.search(r'[a-zA-ZäöüÄÖÜß]', text_to_translate):
        print(f"Skipping translation for: {text_to_translate[:50]}... (already Chinese or non-translatable)")
        return text_to_translate # Assume already Chinese or non-translatable

    prompt = f"Translate the following German text to Chinese. Output only the translated Chinese text and nothing else:\n\n{text_to_translate}"
    
    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2 # Lower temperature for more deterministic translation
        }
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    try:
        print(f"Translating text to Chinese using model {model_name} on {ollama_host}...")
        api_url = f"{ollama_host}/api/generate"
        resp = requests.post(api_url, json=payload, headers=headers, timeout=300)
        resp.raise_for_status()
        result = resp.json()
        translated_text = result.get("response", "").strip()
        
        # Further clean-up if AI adds prefixes like "Chinese translation:" or "翻译："
        translated_text = re.sub(r"^(Chinese translation:|翻译：|以下是中文翻译：)\s*", "", translated_text, flags=re.IGNORECASE)
        # Remove any potential "German text:" or similar introductions if the AI includes the original
        translated_text = re.sub(r"^(German text:|Original text:|Original:|Ursprünglicher Text:)\s*.*?\n+", "", translated_text, flags=re.IGNORECASE | re.DOTALL)
        translated_text = translated_text.strip()

        if translated_text:
            print(f"Original: {text_to_translate[:50]}... Translated: {translated_text[:50]}...")
            return translated_text
        else:
            print(f"Translation resulted in empty string for: {text_to_translate[:50]}... Returning original.")
            return text_to_translate
    except requests.exceptions.Timeout:
        print(f"Error during translation: Timeout after 300 seconds for {ollama_host}")
        return text_to_translate
    except requests.exceptions.RequestException as e:
        print(f"Error during translation: RequestException {e} for {ollama_host}")
        return text_to_translate
    except Exception as e:
        print(f"An unexpected error occurred during translation: {e}")
        return text_to_translate # Fallback to original text


# Main execution block
if __name__ == "__main__":
    print("=== DAAD PhD Positions Scraper ===")
    
    # Phase 1: Check AI server and select model
    print("\n=== Phase 1: AI Server Setup ===")
    print("正在检查AI服务器连接...")
    if not check_ai_server("http://rf-calcul:11434"):
        print("AI服务器连接失败，将使用简单摘要")
        time.sleep(2)
        selected_model = "deepseek-r1:70b"
    else:
        print("\nAI服务器连接成功")
        # Let user select the model to use
        selected_model = select_model()
    
    print(f"\n使用模型: {selected_model}")

    # Get number of jobs to scrape from user
    num_jobs_to_scrape_str = input("How many job postings would you like to scrape? (Enter a number, default is 10): ")
    try:
        num_jobs_to_scrape = int(num_jobs_to_scrape_str)
        if num_jobs_to_scrape <= 0:
            print("Invalid input. Defaulting to 10 jobs.")
            num_jobs_to_scrape = 10
    except ValueError:
        print("Invalid input. Defaulting to 10 jobs.")
        num_jobs_to_scrape = 10
    print(f"Will attempt to scrape {num_jobs_to_scrape} job postings.")

      # Phase 2: Fetch jobs
    print("\n=== Phase 2: Fetching Positions ===")
    try:
        jobs = fetch_daad_jobs(use_headless=True, selected_model=selected_model, num_jobs=num_jobs_to_scrape)
        if not jobs:
            print("\nNo positions found. Check the logs for errors.")
            sys.exit(1)
            
        print(f"\nSuccessfully found {len(jobs)} positions")
        
        # Phase 3: Generate report
        print("\n=== Phase 3: Generating Report ===")
        
        # Save raw data as JSON with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_file = f"backup/daad_phd_positions_{timestamp}.json"
        os.makedirs("backup", exist_ok=True)
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(jobs, f, ensure_ascii=False, indent=2)
        print(f"Raw data saved to {json_file}")
        
        # Generate and save markdown summary
        article = generate_summary_article(jobs, selected_model)
        summary_file = f"backup/daad_phd_summary.md"
        with open(summary_file, "w", encoding="utf-8") as f:
            f.write(article)
        print(f"\nSummary report saved to {summary_file}")
        print("\n=== Completed Successfully ===")
        
    except Exception as e:
        print(f"\nError running scraper: {e}")
        print("Check the logs for more details.")
        sys.exit(1)
