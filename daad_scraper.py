from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import requests
import re
import os
from collections import defaultdict
from selenium.common.exceptions import InvalidSessionIdException, TimeoutException
import sys
import winreg

# Ensure UTF-8 encoding for standard output
sys.stdout.reconfigure(encoding='utf-8')

def set_windows_proxy_from_pac(pac_url):
    """Set Windows system proxy from PAC URL"""
    try:
        reg_path = r"Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "AutoConfigURL", 0, winreg.REG_SZ, pac_url)
        print(f"System proxy PAC set to: {pac_url}")
    except Exception as e:
        print(f"Failed to set system proxy: {e}")

def fetch_job_detail(driver, url):
    """Fetch detailed job information from DAAD posting"""
    driver.get(url)
    time.sleep(2)
    
    # Initialize variables
    title = content = institution = location = posted = contract = requirements = ''
    
    try:
        # Title
        try:
            title = driver.find_element(By.CSS_SELECTOR, '.research-title, h1').text.strip()
        except:
            try:
                title = driver.find_element(By.TAG_NAME, 'h1').text.strip()
            except:
                pass

        # Content/Description
        try:
            content_elem = driver.find_element(By.CSS_SELECTOR, '.research-description, .position-description')
            content = content_elem.text.strip()
        except:
            try:
                content = driver.find_element(By.TAG_NAME, 'main').text.strip()
            except:
                pass

        # Institution
        try:
            institution = driver.find_element(By.CSS_SELECTOR, '.institution-name, .university-name').text.strip()
        except:
            pass

        # Location
        try:
            location = driver.find_element(By.CSS_SELECTOR, '.location-info, .city-name').text.strip()
        except:
            pass

        # Posted date
        try:
            posted = driver.find_element(By.CSS_SELECTOR, '.posting-date, .date-posted').text.strip()
        except:
            pass

        # Contract/Duration
        try:
            contract = driver.find_element(By.CSS_SELECTOR, '.contract-info, .duration').text.strip()
        except:
            # Try to find duration in content
            duration_patterns = [
                r'duration[:：]\s*([\w\s\-]+)',
                r'contract period[:：]\s*([\w\s\-]+)',
                r'(\d+[\s-](?:year|month)s?)',
                r'((?:fixed[- ]term|temporary)[^.]*(?:\d+\s+(?:month|year|months|years)))'
            ]
            for pattern in duration_patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    contract = match.group(1).strip()
                    break

        # Requirements
        try:
            requirements = driver.find_element(By.CSS_SELECTOR, '.requirements, .qualifications').text.strip()
        except:
            # Try to find requirements section in content
            req_patterns = [
                r'requirements?:[\s\n]*(.*?)(?=\n\n|\Z)',
                r'qualifications?:[\s\n]*(.*?)(?=\n\n|\Z)',
                r'we expect:[\s\n]*(.*?)(?=\n\n|\Z)',
                r'profile:[\s\n]*(.*?)(?=\n\n|\Z)'
            ]
            for pattern in req_patterns:
                match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
                if match:
                    requirements = match.group(1).strip()
                    break

    except Exception as e:
        print(f"Error fetching job details: {e}")

    # Clean up the data
    title = title.replace('\n', ' ').strip()
    institution = institution.replace('\n', ' ').strip()
    location = location.replace('\n', ' ').strip()
    posted = posted.replace('\n', ' ').strip()
    contract = contract.replace('\n', ' ').strip()
    requirements = requirements.replace('\n', ' ').strip()

    return {
        'title': title,
        'content': content,
        'institution': institution,
        'location': location,
        'posted': posted,
        'contract': contract,
        'requirements': requirements
    }

def fetch_daad_jobs(use_headless=True, selected_model=None):
    """Fetch PhD positions from DAAD website"""
    set_windows_proxy_from_pac("http://127.0.0.1:55624/proxy.pac")
    base_url = "https://www.daad.de/en/study-and-research-in-germany/phd-studies-and-research/"

    # Set up Chrome options
    options = webdriver.ChromeOptions()
    
    # Basic settings
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-software-rasterizer')
    options.add_argument('--ignore-certificate-errors')
    options.add_argument('--window-size=1920,1080')
    
    # Stealth settings
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

    if use_headless:
        options.add_argument('--headless=new')
        print("Starting browser in headless mode...")
    else:
        print("Starting browser in visible mode...")

    # Initialize ChromeDriver
    driver = None
    try:
        # Try local chromedriver.exe first
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
                current_dir = os.path.dirname(os.path.abspath(__file__))
                chromedriver_path = os.path.join(current_dir, "chromedriver.exe")
                print(f"Trying absolute path: {chromedriver_path}")
                service = Service(chromedriver_path)
                driver = webdriver.Chrome(service=service, options=options)
                print("Successfully initialized ChromeDriver from absolute path")
    except Exception as e:
        print(f"All ChromeDriver initialization attempts failed: {e}")
        raise

    # Set page load timeout
    driver.set_page_load_timeout(30)
    print(f"Accessing DAAD PhD database: {base_url}")

    try:
        driver.get(base_url)
        time.sleep(5)  # Initial wait for page load

        # Wait for and accept any cookie consent if present
        try:
            cookie_button = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '#cookie-consent button, .cookie-consent-button'))
            )
            cookie_button.click()
        except:
            print("No cookie consent button found or already accepted")

        # Wait for job listings to load
        print("Waiting for job listings to load...")
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '.position-list, .search-results, .phd-positions'))
            )
        except TimeoutException:
            print("Timeout waiting for job listings, will try to proceed anyway")        print("Looking for search button or form...")
        try:
            # Try to find and click the search button if needed
            search_button = driver.find_element(By.CSS_SELECTOR, 'button[type="submit"], input[type="submit"], .search-button')
            search_button.click()
            time.sleep(3)  # Wait for results to load
        except:
            print("No search button found, proceeding with available listings")

        # Try to find job listings with multiple selectors
        job_cards = []
        selectors = [
            '.result-list li',  # Common pattern for search results
            '.search-results li',
            '.list-unstyled li',  # DAAD often uses this class
            '.content-box',  # DAAD content boxes
            '.card',  # General card layout
            'div[class*="result"]',  # Any div containing "result"
            'article',  # Generic article elements
            '.teaser'  # DAAD sometimes uses teasers
        ]

        max_retries = 3
        retry_count = 0
        
        while not job_cards and retry_count < max_retries:
            print(f"Attempt {retry_count + 1} to find job listings...")
            
            # Scroll down to load more content if needed
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            
            for selector in selectors:
                try:
                    cards = driver.find_elements(By.CSS_SELECTOR, selector)
                    if cards:
                        print(f"Found {len(cards)} positions with selector: {selector}")
                        job_cards.extend(cards)
                except Exception as e:
                    print(f"Error with selector {selector}: {e}")
            
            if not job_cards:
                print("No job cards found yet, retrying...")
                retry_count += 1
                time.sleep(3)  # Wait before retry

        if not job_cards:
            print("No job cards found after all retries, attempting to find any links...")
            try:
                # Look for any links that might be job postings
                all_links = driver.find_elements(By.TAG_NAME, 'a')
                job_cards = [link for link in all_links if any(kw in (link.text.lower() + ' ' + (link.get_attribute('href') or '').lower())
                                                              for kw in ['phd', 'doctoral', 'position', 'scholarship', 'stipend'])]
                print(f"Found {len(job_cards)} potential job links")
            except Exception as e:
                print(f"Error finding fallback links: {e}")

        # Process job listings
        jobs = []
        processed_urls = set()  # To avoid duplicates
        
        for card in job_cards[:10]:  # Process up to 10 positions
            try:
                # Try multiple ways to get the title and link
                title = None
                link = None
                
                # First try to get link
                try:
                    if card.tag_name == 'a':
                        link = card.get_attribute('href')
                    else:
                        link_elem = card.find_element(By.TAG_NAME, 'a')
                        link = link_elem.get_attribute('href')
                except:
                    continue  # Skip if no link found
                
                # Skip if we've already processed this URL
                if not link or link in processed_urls:
                    continue
                processed_urls.add(link)
                
                # Try to get title from different elements
                for title_selector in ['h2', 'h3', 'h4', '.title', '.heading', 'a']:
                    try:
                        title_elem = card.find_element(By.CSS_SELECTOR, title_selector)
                        title = title_elem.text.strip()
                        if title:
                            break
                    except:
                        continue
                
                if not title:
                    # Use link text as title if no other title found
                    title = card.text.strip() or "PhD Position"
                
                # Get full details
                details = fetch_job_detail(driver, link)
                jobs.append(details)
                
                print(f"Processed position: {title[:50]}...")
                
            except Exception as e:
                print(f"Error processing position: {e}")
                continue

        return jobs

    except Exception as e:
        print(f"Error fetching DAAD jobs: {e}")
        return []
    finally:
        driver.quit()

def classify_research_field(text):
    """Classify the research field of the position"""
    fields = [
        ('Computer Science', ['computer science', 'informatics', 'software', 'artificial intelligence', 'machine learning']),
        ('Engineering', ['engineering', 'mechanical', 'electrical', 'civil', 'chemical']),
        ('Natural Sciences', ['physics', 'chemistry', 'biology', 'mathematics']),
        ('Life Sciences', ['biology', 'medicine', 'neuroscience', 'biochemistry']),
        ('Social Sciences', ['sociology', 'psychology', 'economics', 'political science']),
        ('Humanities', ['philosophy', 'history', 'literature', 'linguistics']),
    ]
    
    text = text.lower()
    for field, keywords in fields:
        if any(keyword in text for keyword in keywords):
            return field
    return 'Other Fields'

def generate_summary_article(job_details, today=None):
    """Generate a formatted summary article of PhD positions"""
    if today is None:
        from datetime import datetime
        today = datetime.now().strftime('%Y-%m-%d')
    
    # Classify jobs by research field
    classified = defaultdict(list)
    for job in job_details:
        field = classify_research_field(job['title'] + ' ' + job['content'])
        classified[field].append(job)
    
    article = f"# PhD Positions in Germany - DAAD ({today})\n\n"
    article += "## About DAAD\n"
    article += "The German Academic Exchange Service (DAAD) is the world's largest funding organization for the international exchange of students and researchers. "
    article += "These PhD positions offer excellent opportunities for international researchers to pursue their doctoral studies in Germany.\n\n"
    
    # List positions by field
    for field in sorted(classified.keys()):
        article += f"## {field}\n\n"
        for job in classified[field]:
            # Title
            article += f"### {job['title']}\n\n"
            
            # Brief description
            content = job['content'][:300] + "..." if len(job['content']) > 300 else job['content']
            article += f"{content}\n\n"
            
            # Key information
            if job['institution']:
                article += f"**Institution:** {job['institution']}\n\n"
            if job['location']:
                article += f"**Location:** {job['location']}\n\n"
            if job['contract']:
                article += f"**Duration:** {job['contract']}\n\n"
            if job['requirements']:
                article += f"**Requirements:** {job['requirements']}\n\n"
            if job.get('link'):
                article += f"**More Information:** [View Position]({job['link']})\n\n"
            
            article += "---\n\n"
    
    return article

if __name__ == "__main__":
    print("=== DAAD PhD Positions Scraper ===")
    
    print("\n=== Phase 1: Fetching Positions ===")
    
    # Try headless mode first
    print("Attempting to fetch with headless mode...")
    job_details = []
    try:
        job_details = fetch_daad_jobs(use_headless=True)
    except Exception as e:
        print(f"Headless mode failed: {e}")
    
    # If headless mode failed, try with visible browser
    if len(job_details) == 0:
        print("\nHeadless mode failed to get positions, trying with visible browser...")
        job_details = fetch_daad_jobs(use_headless=False)
    
    print(f"Successfully retrieved {len(job_details)} positions")
    
    # Exit if no positions found
    if len(job_details) == 0:
        print("No positions could be retrieved, exiting")
        sys.exit(1)
    
    # Generate and save the report
    print("\n=== Phase 2: Generating Report ===")
    print("Generating summary report...")
    from datetime import datetime
    today = datetime.now().strftime('%Y-%m-%d')
    article = generate_summary_article(job_details, today=today)
    
    print("Saving report...")
    output_file = 'daad_phd_summary.md'
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(article)
    
    print("\n=== Complete ===")
    print(f'Report generated: {output_file}')
