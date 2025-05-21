from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import requests
import re
import os
import sys
from collections import defaultdict
from selenium.common.exceptions import InvalidSessionIdException, TimeoutException
import json

# Ensure UTF-8 encoding for standard output
sys.stdout.reconfigure(encoding='utf-8')

def set_windows_proxy_from_pac(pac_url):
    """Set Windows system proxy from PAC URL"""
    try:
        import winreg
        reg_path = r"Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "AutoConfigURL", 0, winreg.REG_SZ, pac_url)
        print(f"System proxy PAC set to: {pac_url}")
    except Exception as e:
        print(f"Failed to set system proxy: {e}")

def fetch_job_detail(driver, url):
    """Fetch detailed job information from a specific URL"""
    driver.get(url)
    time.sleep(2)

    # Initialize variables
    title = content = institution = location = posted = contract = ''

    try:
        # Check if it's a EURAXESS page
        if "euraxess.ec.europa.eu" in url:
            # Wait for content to load
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, "group-job-basic-info"))
            )
            
            # Get title
            try:
                title = driver.find_element(By.CLASS_NAME, "job-title").text.strip()
            except:
                try:
                    title = driver.find_element(By.TAG_NAME, "h1").text.strip()
                except:
                    pass
            
            # Get content
            try:
                content_sections = driver.find_elements(By.CLASS_NAME, "field-group")
                contents = []
                for section in content_sections:
                    try:
                        label = section.find_element(By.CLASS_NAME, "field-label").text.strip()
                        value = section.find_element(By.CLASS_NAME, "field-items").text.strip()
                        contents.append(f"{label}:\\n{value}")
                    except:
                        continue
                content = "\\n\\n".join(contents)
            except:
                try:
                    content = driver.find_element(By.CLASS_NAME, "group-job-basic-info").text.strip()
                except:
                    pass
            
            # Get institution
            try:
                institution = driver.find_element(By.CLASS_NAME, "organisation-name").text.strip()
            except:
                pass
            
            # Get location
            try:
                location = driver.find_element(By.CLASS_NAME, "country-name").text.strip()
            except:
                pass
            
            # Get posted date
            try:
                posted = driver.find_element(By.CLASS_NAME, "submitted-date").text.strip()
            except:
                pass
            
            # Get contract information
            try:
                contract_elem = driver.find_element(By.XPATH, "//*[contains(text(), 'Type of Contract:')]")
                contract = contract_elem.find_element(By.XPATH, "..").text.strip()
            except:
                pass
            
        else:
            # Original MSCA selectors
            # Try multiple title selectors
            title_selectors = [
                "h1.job-title",
                "h1.title",
                ".position-title",
                "#page-title",
                "h1"
            ]
            for selector in title_selectors:
                try:
                    title = driver.find_element(By.CSS_SELECTOR, selector).text.strip()
                    if title:
                        break
                except:
                    continue

            # Try multiple content selectors
            content_selectors = [
                ".job-description",
                ".field--name-body",
                ".description",
                "article",
                "main",
                ".content"
            ]
            for selector in content_selectors:
                try:
                    content = driver.find_element(By.CSS_SELECTOR, selector).text.strip()
                    if content:
                        break
                except:
                    continue

            if not content:
                # Fallback: get all text from specific sections
                try:
                    sections = driver.find_elements(By.CSS_SELECTOR, ".field--type-text-with-summary, .field--type-text-long")
                    content = "\n\n".join([section.text.strip() for section in sections])
                except:
                    # Last resort: get body text
                    content = driver.find_element(By.TAG_NAME, "body").text.strip()

            # Institution name
            institution_selectors = [
                ".field--name-field-institution",
                ".institution-name",
                ".organization",
                "[class*='institution']",
                "[class*='organization']"
            ]
            for selector in institution_selectors:
                try:
                    institution = driver.find_element(By.CSS_SELECTOR, selector).text.strip()
                    if institution:
                        break
                except:
                    continue

            # Location information
            location_selectors = [
                ".field--name-field-location",
                ".location-info",
                ".country",
                "[class*='location']",
                "[class*='country']"
            ]
            for selector in location_selectors:
                try:
                    location = driver.find_element(By.CSS_SELECTOR, selector).text.strip()
                    if location:
                        break
                except:
                    continue

            # Posted date
            posting_date_selectors = [
                ".field--name-field-posting-date",
                ".date-posted",
                ".post-date",
                "[class*='date']"
            ]
            for selector in posting_date_selectors:
                try:
                    posted = driver.find_element(By.CSS_SELECTOR, selector).text.strip()
                    if posted:
                        break
                except:
                    continue

            # Contract duration
            contract_selectors = [
                ".field--name-field-duration",
                ".contract-duration",
                ".period",
                "[class*='duration']"
            ]
            for selector in contract_selectors:
                try:
                    contract = driver.find_element(By.CSS_SELECTOR, selector).text.strip()
                    if contract:
                        break
                except:
                    continue

            # If contract duration not found in specific fields, try to find it in the content
            if not contract:
                duration_patterns = [
                    r'duration[:：]\s*([\w\s\-]+)',
                    r'contract period[:：]\s*([\w\s\-]+)',
                    r'period[:：]\s*([\w\s\-]+)',
                    r'contract[:：]\s*([\w\s\-]+\s+(?:month|year|months|years))',
                    r'(\d+\s+(?:month|year|months|years))',
                    r'((?:fixed[- ]term|temporary)[^.]*(?:\d+\s+(?:month|year|months|years)))'
                ]
                
                for pattern in duration_patterns:
                    match = re.search(pattern, content, re.IGNORECASE)
                    if match:
                        contract = match.group(1).strip()
                        break

    except Exception as e:
        print(f"Error fetching job details: {e}")

    # Clean up the data
    title = title.replace('\n', ' ').strip()
    institution = institution.replace('\n', ' ').strip()
    location = location.replace('\n', ' ').strip()
    posted = posted.replace('\n', ' ').strip()
    contract = contract.replace('\n', ' ').strip()

    return title, content, institution, location, posted, contract

def fetch_msca_jobs(use_headless=True, selected_model=None):
    """Fetch job postings from MSCA and EURAXESS websites"""
    set_windows_proxy_from_pac("http://127.0.0.1:55624/proxy.pac")
    
    # Update base URLs with correct format
    job_urls = {
        'PhD': 'https://euraxess.ec.europa.eu/jobs/search/field_research_profile/first-stage-researcher-r1-446',
        'Postdoc': 'https://euraxess.ec.europa.eu/jobs/search/field_research_profile/recognised-researcher-r2-446',
        'Senior': 'https://euraxess.ec.europa.eu/jobs/search/field_research_profile/established-researcher-r3-446'
    }    # Set up Chrome options
    options = webdriver.ChromeOptions()
    # Basic settings
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-gpu')  # Disable GPU hardware acceleration
    options.add_argument('--disable-software-rasterizer')  # Disable software rasterization
    options.add_argument('--ignore-certificate-errors')  # Ignore SSL/TLS errors
    options.add_argument('--window-size=1920,1080')  # Set a standard window size
    
    # Stealth settings to avoid detection
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument(f'user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    
    # Performance settings
    options.add_argument('--disable-notifications')
    options.add_argument('--disable-popup-blocking')
    options.add_argument('--disable-web-security')  # Disable CORS and other security features that might block requests
    options.add_argument('--disable-features=IsolateOrigins,site-per-process')  # Disable site isolation
    
    # Memory optimization
    options.add_argument('--disable-crash-reporter')
    options.add_argument('--disable-infobars')
    options.add_argument('--disable-translate')
    options.add_argument('--disable-logging')
    
    # Enable CDP logging with reduced verbosity
    options.set_capability("goog:loggingPrefs", {
        "browser": "WARNING",
        "driver": "WARNING"
    })
    # Enable Selenium CDP
    options.add_argument("--remote-debugging-port=9222")
    options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

    if use_headless:
        options.add_argument('--headless=new')
        print("Starting browser in headless mode...")
    else:
        print("Starting browser in visible mode...")

    # Initialize ChromeDriver
    driver = None
    try:
        # Try using local chromedriver.exe
        try:
            print("Trying local ChromeDriver...")
            service = Service("./chromedriver.exe")
            driver = webdriver.Chrome(service=service, options=options)
            print("Successfully initialized local ChromeDriver")
        except Exception as e:
            print(f"Local ChromeDriver failed: {e}")
            
            # Try system PATH
            try:
                print("Trying ChromeDriver from system PATH...")
                driver = webdriver.Chrome(options=options)
                print("Successfully initialized ChromeDriver from PATH")
            except Exception as e:
                print(f"System PATH ChromeDriver failed: {e}")
                
                # Try absolute path
                try:
                    current_dir = os.path.dirname(os.path.abspath(__file__))
                    chromedriver_path = os.path.join(current_dir, "chromedriver.exe")
                    print(f"Trying absolute path: {chromedriver_path}")
                    service = Service(chromedriver_path)
                    driver = webdriver.Chrome(service=service, options=options)
                    print("Successfully initialized ChromeDriver from absolute path")
                except Exception as e:
                    print(f"Absolute path initialization failed: {e}")
                    raise Exception("Could not initialize ChromeDriver")
    except Exception as e:
        print(f"All ChromeDriver initialization attempts failed: {e}")
        raise

    # Set page load timeout
    driver.set_page_load_timeout(30)
    all_jobs = []

    # Process each section
    for section_type, section_url in job_urls.items():
        print(f"\nProcessing {section_type} section: {section_url}")
        try:
            driver.get(section_url)
            time.sleep(5)  # Wait for page to load

            # Try to find job listings
            found_jobs = fetch_euraxess_jobs(driver, section_type)
            if found_jobs:
                all_jobs.extend(found_jobs)
                print(f"Found {len(found_jobs)} {section_type} positions")

        except Exception as e:
            print(f"Error processing {section_type} section: {e}")

    # Fetch detailed information for each job
    job_details = []
    print("\nFetching job details...")
    for i, job in enumerate(all_jobs):
        print(f"Processing job {i+1}/{len(all_jobs)} ({int((i+1)/len(all_jobs)*100)}%): {job['title'][:30]}...")
        try:
            detail_title, detail_content, inst2, loc2, posted, contract = fetch_job_detail(driver, job['link'])
        except InvalidSessionIdException:
            print("Browser session invalid, restarting...")
            try:
                driver.quit()
            except Exception as e:
                print(f"Error while quitting the driver: {e}")

            # Reinitialize driver
            try:
                driver = webdriver.Chrome(options=options)
                driver.set_page_load_timeout(30)
                detail_title, detail_content, inst2, loc2, posted, contract = fetch_job_detail(driver, job['link'])
            except Exception as e:
                print(f"Error reinitializing driver or fetching job details: {e}")
        except Exception as e:
            print(f"Error fetching job details for {job['title']}: {e}")

        # Use detail page data if available
        institution = inst2 or job.get('institution', '')
        location = loc2 or job.get('location', '')

        job_details.append({
            "title": detail_title or job['title'],
            "content": detail_content,
            "link": job['link'],
            "institution": institution,
            "location": location,
            "posted": posted,
            "contract": contract,
            "type": job['type']  # Keep track of whether it's PhD or Postdoc
        })
        print(f"Job {i+1}/{len(all_jobs)} processed")

    driver.quit()
    return job_details

def classify_position(title, content):
    """Classify the type of position"""
    title_content = (title + ' ' + content).lower()
    if any(x in title_content for x in ['phd', 'doctoral', 'doctorate', 'thesis']):
        return 'PhD Position'
    if any(x in title_content for x in ['postdoc', 'post-doctoral', 'postdoctoral']):
        return 'Postdoctoral Position'
    if any(x in title_content for x in ['professor', 'lecturer', 'faculty', 'teaching']):
        return 'Academic Position'
    if any(x in title_content for x in ['researcher', 'scientist', 'research fellow']):
        return 'Research Position'
    if any(x in title_content for x in ['engineer', 'technician', 'specialist']):
        return 'Technical Position'
    return 'Other Position'

def extract_research_area(text):
    """Extract research area from job description"""
    areas = [
        ('Computer Science & AI', ['computer science', 'artificial intelligence', 'machine learning', 'data science']),
        ('Life Sciences', ['biology', 'medical', 'health', 'biochemistry', 'neuroscience']),
        ('Physical Sciences', ['physics', 'chemistry', 'materials', 'astronomy']),
        ('Engineering', ['engineering', 'mechanical', 'electrical', 'robotics']),
        ('Environmental Science', ['environmental', 'climate', 'ecology', 'sustainability']),
        ('Social Sciences', ['social', 'economics', 'psychology', 'sociology']),
        ('Humanities', ['history', 'philosophy', 'literature', 'languages']),
        ('Mathematics', ['mathematics', 'statistics', 'computational']),
    ]
    
    text = text.lower()
    for area, keywords in areas:
        if any(kw in text for kw in keywords):
            return area
    return 'Other Fields'

def generate_summary_article(job_details, today=None):
    """Generate a formatted summary article of job listings"""
    if today is None:
        from datetime import datetime
        today = datetime.now().strftime('%Y-%m-%d')
        
    classified = defaultdict(lambda: defaultdict(list))
    for job in job_details:
        category = classify_position(job['title'], job['content'])
        area = extract_research_area(job['title'] + ' ' + job['content'])
        classified[category][area].append(job)
    
    article = f"# MSCA Research Positions Summary ({today})\n\n"
    article += "## About MSCA\n"
    article += "Marie Skłodowska-Curie Actions (MSCA) is the European Union's flagship funding programme for doctoral education and postdoctoral training. It offers various opportunities for researchers at different career stages.\n\n"
    
    categories = ['PhD Position', 'Postdoctoral Position', 'Academic Position', 'Research Position', 'Technical Position', 'Other Position']
    
    for category in categories:
        if category not in classified:
            continue
        article += f"## {category}\n\n"
        for area, jobs in classified[category].items():
            article += f"### {area}\n\n"
            for job in jobs:
                # Job title
                article += f"#### {job['title']}\n\n"
                
                # Job summary
                content = job['content'].replace('\n', ' ').replace('\r', ' ')
                summary = content[:200] + "..." if len(content) > 200 else content
                article += f"{summary}\n\n"
                
                # Institution and location
                if job.get('institution'):
                    article += f"**Institution:** {job['institution']}\n\n"
                if job.get('location'):
                    article += f"**Location:** {job['location']}\n\n"
                
                # Contract duration
                if job.get('contract'):
                    article += f"**Duration:** {job['contract']}\n\n"
                
                # Posted date
                if job.get('posted'):
                    article += f"**Posted:** {job['posted']}\n\n"
                
                # Job link
                if job.get('link'):
                    article += f"**More Information:** [View Details]({job['link']})\n\n"
                
                article += "---\n\n"
    
    return article

# Additional method to fetch job data using JavaScript interaction and network requests
def fetch_jobs_with_js_and_network(driver, section_url):
    """Fetch job listings by interacting with JavaScript and analyzing network requests."""
    try:
        # Enable CDP domains
        driver.execute_cdp_cmd('Network.enable', {})
        driver.execute_cdp_cmd('Page.enable', {})
        
        print(f"Navigating to {section_url}")
        driver.get(section_url)
        time.sleep(5)  # Wait for initial load
        
        # Scroll to load more content
        print("Scrolling page to trigger dynamic loading...")
        last_height = driver.execute_script("return document.body.scrollHeight")
        while True:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
        
        # Try to find job listings
        print("Searching for job listings...")
        found_jobs = []
        
        # Method 1: Check for vacancy listings in tables
        tables = driver.find_elements(By.TAG_NAME, "table")
        for table in tables:
            rows = table.find_elements(By.TAG_NAME, "tr")
            for row in rows[1:]:  # Skip header row
                cells = row.find_elements(By.TAG_NAME, "td")
                if len(cells) >= 1:
                    try:
                        link = cells[0].find_element(By.TAG_NAME, "a")
                        title = link.text.strip()
                        url = link.get_attribute("href")
                        if title and url:
                            found_jobs.append({
                                "element": row,
                                "title": title,
                                "link": url
                            })
                    except:
                        continue
        
        if found_jobs:
            print(f"Found {len(found_jobs)} jobs in table format")
            return found_jobs
        
        # Method 2: Check for card-based layouts
        card_selectors = [
            ".ecl-card",
            ".listing-item",
            "div[class*='vacancy']",
            "div[class*='position']",
            "article"
        ]
        
        for selector in card_selectors:
            cards = driver.find_elements(By.CSS_SELECTOR, selector)
            for card in cards:
                try:
                    # Try to find a link and title within the card
                    link = card.find_element(By.TAG_NAME, "a")
                    title = link.text.strip() or card.text.strip()
                    url = link.get_attribute("href")
                    if title and url and any(keyword in title.lower() or keyword in url.lower() 
                                           for keyword in ["job", "position", "vacancy", "fellowship", "researcher"]):
                        found_jobs.append({
                            "element": card,
                            "title": title,
                            "link": url
                        })
                except:
                    continue
        
        if found_jobs:
            print(f"Found {len(found_jobs)} jobs in card format")
            return found_jobs
        
        # Save debug information if no jobs found
        if not found_jobs:
            print("No job elements found, saving debug information...")
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                driver.save_screenshot(f"debug_screenshot_{timestamp}.png")
                with open(f"debug_source_{timestamp}.html", "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
                print(f"Debug information saved with timestamp {timestamp}")
            except Exception as e:
                print(f"Failed to save debug information: {e}")
        
        return found_jobs
        
    except Exception as e:
        print(f"Error in fetch_jobs_with_js_and_network: {e}")
        return []
    finally:
        try:
            driver.execute_cdp_cmd('Network.disable', {})
            driver.execute_cdp_cmd('Page.disable', {})
        except:
            pass

def fetch_euraxess_jobs(driver, section_type):
    """Fetch job listings from EURAXESS website."""
    found_jobs = []   
    try:
        print(f"Waiting for page to load...")
        # Try multiple selectors to wait for page load
        primary_selectors = [
            ".ecl-content-item-block",
            ".ecl-card",
            ".feed-item",
            ".view-content",
            ".search-results",
            ".jobs-list"
        ]
        
        found_element = False
        for selector in primary_selectors:
            try:
                element = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                if element and element.is_displayed():
                    print(f"Found visible element with selector: {selector}")
                    found_element = True
                    break
            except TimeoutException:
                continue
        
        if not found_element:
            print("Primary selectors not found, trying secondary approach...")
            # Wait for any job-related links as fallback            def find_job_links(driver):
                links = driver.find_elements(By.TAG_NAME, "a")
                job_links = []
                for link in links:
                    try:
                        href = link.get_attribute("href") or ""
                        text = link.text.strip().lower()
                        if href and text and any(kw in (href.lower() + " " + text) 
                                               for kw in ["job", "position", "vacancy", "fellow", "researcher"]):
                            job_links.append(link)
                    except:
                        continue
                return len(job_links) > 0
            
            WebDriverWait(driver, 15).until(find_job_links)
            print("Found job-related links")
        
        # Let the page fully render
        time.sleep(5)
          # Try EURAXESS specific selectors first, then fall back to general ones
        job_selectors = [
            ".ecl-content-block",           # Primary EURAXESS selector
            ".ecl-content-item__content-block",  # EURAXESS content block
            ".ecl-content-item-block",      # Alternative EURAXESS block
            "div[class*='ecl-content']",    # Any EURAXESS content
            # Fallback selectors
            ".view-row",
            ".search-result",
            ".job-item",
            "article",
            ".research-job-item",
            "[class*='job-listing']",
            ".vacancy-item"
        ]
        
        job_cards = []
        for selector in job_selectors:
            try:
                cards = driver.find_elements(By.CSS_SELECTOR, selector)
                if cards:
                    print(f"Found {len(cards)} job cards with selector: {selector}")
                    job_cards.extend(cards)
            except Exception as e:
                print(f"Error with selector {selector}: {e}")
                continue
                
        if not job_cards:
            # If no cards found, try to find any links containing job-related text
            print("No job cards found, trying to find job links...")
            links = driver.find_elements(By.TAG_NAME, "a")
            for link in links:
                try:
                    href = link.get_attribute("href") or ""
                    text = link.text.strip()
                    if text and href and any(kw in (href + text).lower() for kw in ["job", "position", "vacancy", "fellowship"]):
                        job_cards.append(link)
                except:
                    continue
        
        print(f"Processing {len(job_cards)} job cards...")
        for card in job_cards:
            try:
                # Try multiple selectors for title and link
                title = ""
                link = ""
                  # EURAXESS specific title and link
                try:
                    # Look for title in the ecl-content-block__title
                    title_elem = card.find_element(By.CSS_SELECTOR, ".ecl-content-block__title a")
                    title = title_elem.text.strip()
                    link = title_elem.get_attribute("href")
                except Exception:
                    # Fallback to other title selectors if EURAXESS specific one fails
                    title_selectors = [
                        "h3 a", "h2 a", ".title a",
                        "a[class*='job']", "a[class*='position']",
                        ".job-title", "h2", "h3", ".title"
                    ]
                    
                    for selector in title_selectors:
                        try:
                            element = card.find_element(By.CSS_SELECTOR, selector)
                            title = element.text.strip()
                            # If element is a link, get the href
                            if element.tag_name == "a":
                                link = element.get_attribute("href")
                            # If we found a title but no link and element isn't a link,
                            # try to find a parent or child link
                            elif title and not link:
                                try:
                                    link_elem = (element.find_element(By.XPATH, "ancestor::a") or 
                                               element.find_element(By.XPATH, "descendant::a") or 
                                               element.find_element(By.XPATH, "..//a"))
                                    link = link_elem.get_attribute("href")
                                except:
                                    continue
                            if title and link:
                                break
                        except:
                            continue
                
                if not (title and link):
                    continue
                  # Try to get institution from EURAXESS format
                institution = ""
                try:
                    # Look for institution in the primary meta container
                    meta_items = card.find_elements(By.CSS_SELECTOR, ".ecl-content-block__primary-meta-item a")
                    for item in meta_items:
                        if "organisations/profile" in item.get_attribute("href"):
                            institution = item.text.strip()
                            break
                except Exception:
                    # Fallback to traditional selectors
                    inst_selectors = [
                        ".organisation-name", ".institution", ".company",
                        "[class*='organisation']", "[class*='institution']",
                        "[class*='company']", "[class*='employer']"
                    ]
                    for selector in inst_selectors:
                        try:
                            institution = card.find_element(By.CSS_SELECTOR, selector).text.strip()
                            if institution:
                                break
                        except:
                            continue

                # Try to get location from website field
                location = ""
                try:
                    # First try to extract location from the institution name or description
                    description = card.find_element(By.CSS_SELECTOR, ".ecl-content-block__description").text.strip()
                    location_matches = re.findall(r'(?:located in|based in|in) ([^,.]+(?:,[^,.]+)?)', description)
                    if location_matches:
                        location = location_matches[0].strip()
                    elif "," in institution:
                        # If institution contains city/country, extract it
                        location = institution.split(",")[-1].strip()
                except Exception:
                    # Fallback to traditional location selectors
                    loc_selectors = [
                        ".country-name", ".location", ".place",
                        "[class*='country']", "[class*='location']",
                        "[class*='place']", "[class*='city']"
                    ]
                    for selector in loc_selectors:
                        try:
                            location = card.find_element(By.CSS_SELECTOR, selector).text.strip()
                            if location:
                                break
                        except:
                            continue
                
                # Get posting date and deadline from EURAXESS format
                try:
                    # Get posting date
                    posted_items = card.find_elements(By.CSS_SELECTOR, ".ecl-content-block__primary-meta-item")
                    for item in posted_items:
                        if "Posted on:" in item.text:
                            posted = item.text.replace("Posted on:", "").strip()
                            break

                    # Get deadline
                    deadline_item = card.find_element(By.CSS_SELECTOR, ".id-Deadline time")
                    if deadline_item:
                        deadline_date = deadline_item.text.strip()
                        if not posted:  # If we didn't find a posting date, add the deadline
                            posted = f"Deadline: {deadline_date}"
                except Exception:
                    # Fallback to looking for dates in the description
                    try:
                        description = card.find_element(By.CSS_SELECTOR, ".ecl-content-block__description").text
                        deadline_match = re.search(r'deadline[:\s]+([^\.]+)', description, re.IGNORECASE)
                        if deadline_match:
                            posted = f"Deadline: {deadline_match.group(1).strip()}"
                    except:
                        pass

                # Extract additional metadata from secondary meta container
                try:
                    funding = ""
                    website = ""
                    meta_items = card.find_elements(By.CSS_SELECTOR, ".ecl-content-block__secondary-meta-item")
                    for item in meta_items:
                        text = item.text.strip()
                        if "Funding Programme:" in text:
                            funding = text.split("Funding Programme:")[-1].strip()
                        elif "Website:" in text:
                            website = item.find_element(By.CSS_SELECTOR, "a").get_attribute("href")
                except Exception:
                    pass
                
                if title and link:
                    found_jobs.append({
                        "title": title,
                        "institution": institution,
                        "location": location,
                        "link": link,
                        "type": section_type
                    })
                    print(f"Found {section_type} position: {title[:50]}...")
            
            except Exception as e:
                print(f"Error processing job card: {e}")
                continue
        
        # Handle pagination
        page = 1
        while True:
            try:
                # Try different pagination selectors
                next_selectors = [
                    "li.pager-next a", ".pager-next a", ".next a",
                    "a[rel='next']", "[class*='pagination-next']",
                    "a:contains('Next')", ".pagination a[href*='page=']"
                ]
                
                next_button = None
                for selector in next_selectors:
                    try:
                        elements = driver.find_elements(By.CSS_SELECTOR, selector)
                        for element in elements:
                            if element.is_displayed() and element.is_enabled():
                                next_button = element
                                break
                        if next_button:
                            break
                    except:
                        continue
                
                if not next_button or not next_button.is_displayed():
                    print("No more pages to load")
                    break
                
                page += 1
                print(f"Loading page {page}...")
                
                # Try to click using different methods
                try:
                    next_button.click()
                except:
                    try:
                        driver.execute_script("arguments[0].click();", next_button)
                    except:
                        try:
                            href = next_button.get_attribute("href")
                            if href:
                                driver.get(href)
                        except:
                            print("Failed to load next page")
                            break
                
                time.sleep(5)  # Wait for new content to load
                
                # Process the new page's job cards
                # ... (same job card processing code as above)
                
            except Exception as e:
                print(f"Error handling pagination: {e}")
                break
    
    except Exception as e:
        print(f"Error fetching EURAXESS jobs: {e}")
        # Take a screenshot for debugging
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            driver.save_screenshot(f"error_screenshot_{timestamp}.png")
            print(f"Error screenshot saved as error_screenshot_{timestamp}.png")
        except:
            pass
    
    return found_jobs

if __name__ == "__main__":
    print("=== MSCA Research Positions Scraper ===")
    
    print("\n=== Phase 1: Fetching Job Listings ===")
    
    # Try headless mode first
    print("Attempting to fetch with headless mode...")
    job_details = []
    try:
        job_details = fetch_msca_jobs(use_headless=True)
    except Exception as e:
        print(f"Headless mode failed: {e}")
    
    # If headless mode failed, try with visible browser
    if len(job_details) == 0:
        print("\nHeadless mode failed to get jobs, trying with visible browser...")
        job_details = fetch_msca_jobs(use_headless=False)
    
    print(f"Successfully retrieved {len(job_details)} job listings")
    
    # Exit if no jobs found
    if len(job_details) == 0:
        print("No job listings could be retrieved, exiting")
        sys.exit(1)
    
    # Generate and save the report
    print("\n=== Phase 2: Generating Report ===")
    print("Generating summary report...")
    from datetime import datetime
    today = datetime.now().strftime('%Y-%m-%d')
    article = generate_summary_article(job_details, today=today)
    
    print("Saving report...")
    output_file = 'msca_jobs_summary.md'
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(article)
    
    print("\n=== Complete ===")
    print(f'Report generated: {output_file}')
