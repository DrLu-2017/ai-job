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

def retry_with_backoff(func, retries=3, initial_delay=1, max_delay=10):
    """Execute a function with exponential backoff retry logic"""
    def wrapper(*args, **kwargs):
        delay = initial_delay
        last_exception = None
        
        for attempt in range(retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                print(f"Attempt {attempt + 1}/{retries} failed: {str(e)}")
                
                if attempt < retries - 1:
                    sleep_time = min(delay * (2 ** attempt), max_delay)
                    print(f"Waiting {sleep_time} seconds before retrying...")
                    time.sleep(sleep_time)
                    
                    # Check if we need to refresh the driver
                    if isinstance(e, (InvalidSessionIdException, TimeoutException)):
                        print("Browser session may be invalid, attempting to refresh...")
                        try:
                            if 'driver' in kwargs:
                                kwargs['driver'].refresh()
                            elif len(args) > 0 and isinstance(args[0], webdriver.Chrome):
                                args[0].refresh()
                        except:
                            print("Failed to refresh browser, continuing with retry...")
        
        raise last_exception
    return wrapper

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

@retry_with_backoff
def fetch_job_detail(driver, url, max_retries=3):
    """Fetch detailed job information from a specific URL with retry logic"""
    # Initialize variables
    title = content = institution = location = posted = contract = ''
    content_parts = []
    metadata = {
        'contact_email': '',
        'contact_postal': '',
        'required_documents': [],
        'requirements': [],
        'deadline': '',
        'research_fields': [],
        'department': '',
        'employment_type': '',
        'funding_program': ''
    }

    try:
        print(f"Fetching job details from {url}...")
        driver.get(url)

        # Wait for the page to be fully loaded
        try:
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            time.sleep(2)  # Additional wait for dynamic content
        except TimeoutException as e:
            print(f"Timeout waiting for page load: {str(e)}")
            raise

        # EURAXESS page handling
        if "euraxess.ec.europa.eu" in url:
            try:
                # Wait for main content and get title
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CLASS_NAME, "ecl-content-item-block"))
                )
                title = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".ecl-page-header__title"))
                ).text.strip()

                # Extract research fields
                try:
                    fields = driver.find_elements(By.CSS_SELECTOR, ".id-Research-Field .ecl-text-standard a")
                    if fields:
                        metadata['research_fields'] = [f.text.strip() for f in fields]
                        content_parts.append("Research Fields: " + ", ".join(metadata['research_fields']))
                except Exception as e:
                    print(f"Error getting research fields: {str(e)}")

                # Extract department info
                try:
                    dept = driver.find_element(By.CSS_SELECTOR, ".id-Department .ecl-text-standard").text.strip()
                    if dept:
                        metadata['department'] = dept
                        content_parts.append("Department: " + dept)
                except Exception as e:
                    print(f"Error getting department: {str(e)}")

                # Extract location info
                try:
                    loc = driver.find_element(By.CSS_SELECTOR, ".id-Work-Locations .ecl-text-standard").text.strip()
                    if loc:
                        content_parts.append("Work Locations: " + loc)
                        location = loc
                except Exception as e:
                    print(f"Error getting location: {str(e)}")

                # Extract institution
                try:
                    institution = driver.find_element(By.CLASS_NAME, "organisation-name").text.strip()
                except Exception as e:
                    print(f"Error getting institution: {str(e)}")

                # Extract posting date and deadline
                try:
                    posted_items = driver.find_elements(By.CSS_SELECTOR, ".ecl-content-block__primary-meta-item")
                    for item in posted_items:
                        if "Posted on:" in item.text:
                            posted = item.text.replace("Posted on:", "").strip()
                            break

                    deadline_elem = driver.find_element(By.CSS_SELECTOR, ".id-Application-Deadline time")
                    if deadline_elem:
                        deadline = deadline_elem.get_attribute("datetime")
                        if deadline:
                            metadata['deadline'] = deadline.split('T')[0]
                            content_parts.append(f"Application Deadline: {metadata['deadline']}")
                except Exception as e:
                    print(f"Error getting posting date/deadline: {str(e)}")

                # Extract contact information
                try:
                    contact_sections = driver.find_elements(By.CSS_SELECTOR, ".id-Contact-Information .ecl-text-standard")
                    for section in contact_sections:
                        text = section.text.lower()
                        if '@' in text:  # Look for email
                            email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', text)
                            if email_match:
                                metadata['contact_email'] = email_match.group(0)
                        if any(word in text for word in ['address', 'postal', 'mail to']):  # Look for postal address
                            metadata['contact_postal'] = section.text.strip()
                except Exception as e:
                    print(f"Error extracting contact information: {str(e)}")

                # Extract required documents
                try:
                    doc_sections = driver.find_elements(By.CSS_SELECTOR, 
                        ".id-Required-Documents .ecl-text-standard, .id-How-To-Apply .ecl-text-standard")
                    for section in doc_sections:
                        text = section.text.lower()
                        doc_items = []
                        if any(doc in text for doc in ['cv', 'curriculum vitae', 'resume']):
                            doc_items.append('CV/Resume')
                        if any(doc in text for doc in ['motivation letter', 'cover letter', 'application letter']):
                            doc_items.append('Motivation Letter')
                        if any(doc in text for doc in ['degree', 'diploma', 'certificate']):
                            doc_items.append('Degree Certificates')
                        if any(doc in text for doc in ['reference', 'recommendation']):
                            doc_items.append('Reference Letters')
                        if any(doc in text for doc in ['transcript', 'academic record']):
                            doc_items.append('Academic Transcripts')
                        if doc_items:
                            metadata['required_documents'].extend(doc_items)
                except Exception as e:
                    print(f"Error extracting required documents: {str(e)}")

                # Extract employment details
                try:
                    contract_elem = driver.find_element(By.XPATH, "//*[contains(text(), 'Type of Contract:')]")
                    if contract_elem:
                        contract_text = contract_elem.find_element(By.XPATH, "..").text.strip()
                        if contract_text:
                            metadata['employment_type'] = contract_text
                            contract = contract_text
                            content_parts.append("Contract Type: " + contract_text)
                except Exception as e:
                    print(f"Error getting contract info: {str(e)}")

                # Extract funding information
                try:
                    funding_elem = driver.find_element(By.XPATH, "//*[contains(text(), 'Funding Programme:')]")
                    if funding_elem:
                        funding_text = funding_elem.find_element(By.XPATH, "..").text.strip()
                        if funding_text:
                            metadata['funding_program'] = funding_text.replace('Funding Programme:', '').strip()
                            content_parts.append("Funding Programme: " + metadata['funding_program'])
                except Exception as e:
                    print(f"Error getting funding info: {str(e)}")

            except Exception as e:
                print(f"Error processing EURAXESS page: {str(e)}")
                # Fallback to searching for basic elements
                try:
                    if not title:
                        title = driver.find_element(By.TAG_NAME, "h1").text.strip()
                    if not content:
                        content = driver.find_element(By.TAG_NAME, "article").text.strip()
                except Exception as e:
                    print(f"Error in fallback content extraction: {str(e)}")

        else:
            # Non-EURAXESS page handling
            print("Processing non-EURAXESS page...")
            
            # Extract title
            title_selectors = [
                "h1.job-title", "h1.title", ".position-title", 
                "#page-title", "h1"
            ]
            for selector in title_selectors:
                try:
                    title_elem = driver.find_element(By.CSS_SELECTOR, selector)
                    if title_elem and title_elem.is_displayed():
                        title = title_elem.text.strip()
                        if title:
                            break
                except Exception:
                    continue

            # Extract content
            content_selectors = [
                ".job-description", ".field--name-body", ".description",
                "article", "main", ".content"
            ]
            for selector in content_selectors:
                try:
                    content_elem = driver.find_element(By.CSS_SELECTOR, selector)
                    if content_elem and content_elem.is_displayed():
                        content = content_elem.text.strip()
                        if content:
                            break
                except Exception:
                    continue

            # If still no content, try fallback sections
            if not content:
                try:
                    sections = driver.find_elements(By.CSS_SELECTOR, ".field--type-text-with-summary, .field--type-text-long")
                    if sections:
                        content = "\n\n".join([section.text.strip() for section in sections])
                except Exception:
                    try:
                        content = driver.find_element(By.TAG_NAME, "body").text.strip()
                    except Exception as e:
                        print(f"Error getting fallback content: {str(e)}")

            # Process content for metadata if found
            if content:
                # Extract contact information from content
                email_matches = re.findall(r'[\w\.-]+@[\w\.-]+\.\w+', content)
                if email_matches:
                    metadata['contact_email'] = email_matches[0]  # Take first email found

                # Look for postal address
                address_patterns = [
                    r'(?:postal address|mailing address|send to)[:]\s*([^\.]+\.\s*\d{4,}[^\.]+\.)',
                    r'(?:address|send applications to)[:]\s*([^\.]+\d{4,}[^\.]+\.)'
                ]
                for pattern in address_patterns:
                    match = re.search(pattern, content, re.IGNORECASE)
                    if match:
                        metadata['contact_postal'] = match.group(1).strip()
                        break

                # Extract application deadline from content
                deadline_patterns = [
                    r'(?:closing date|deadline|apply before|submit before)[:]\s*(\d{1,2}(?:st|nd|rd|th)?\s+\w+\s+\d{4})',
                    r'(?:closing date|deadline|apply before|submit before)[:]\s*(\d{4}-\d{2}-\d{2})',
                    r'(?:applications? due)[:]\s*(\d{1,2}(?:st|nd|rd|th)?\s+\w+\s+\d{4})'
                ]
                for pattern in deadline_patterns:
                    match = re.search(pattern, content, re.IGNORECASE)
                    if match:
                        metadata['deadline'] = match.group(1)
                        break

                # Extract required documents
                doc_patterns = [
                    (r'(?:cv|curriculum vitae|resume)', 'CV/Resume'),
                    (r'(?:motivation|cover) letter', 'Motivation Letter'),
                    (r'(?:degree|diploma) certificate', 'Degree Certificates'),
                    (r'reference letter', 'Reference Letters'),
                    (r'transcript', 'Academic Transcripts'),
                    (r'research (proposal|statement)', 'Research Proposal'),
                    (r'language certificate', 'Language Certificate')
                ]
                for pattern, doc_type in doc_patterns:
                    if re.search(pattern, content, re.IGNORECASE):
                        metadata['required_documents'].append(doc_type)

                # Extract requirements
                req_section = None
                req_patterns = [
                    r'(?:requirements|qualifications|we expect)[:]\s*(.+?)(?=\n\n|\Z)',
                    r'(?:candidate|applicant) should[:]\s*(.+?)(?=\n\n|\Z)',
                    r'(?:profile|prerequisites)[:]\s*(.+?)(?=\n\n|\Z)'
                ]
                for pattern in req_patterns:
                    match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
                    if match:
                        req_section = match.group(1)
                        break

                if req_section:
                    # Split requirements into bullet points
                    requirements = re.split(r'[•\-\*]\s*|\d+\.\s+', req_section)
                    requirements = [r.strip() for r in requirements if r.strip()]
                    metadata['requirements'] = requirements

                # Extract employment type/contract info if not already found
                if not contract:
                    contract_patterns = [
                        r'(?:contract type|employment type|position type)[:]\s*([^\.]+)',
                        r'(?:duration|period)[:]\s*((?:\d+|one|two|three|four)\s+(?:year|month)s?)',
                        r'(?:fixed[- ]term|temporary) contract for (\d+\s+(?:year|month)s?)',
                    ]
                    for pattern in contract_patterns:
                        match = re.search(pattern, content, re.IGNORECASE)
                        if match:
                            contract = match.group(1).strip()
                            metadata['employment_type'] = contract
                            break

            # Extract metadata (institution, location, etc.)
            try:
                for selector in [".institution-name", "[class*='institution']"]:
                    try:
                        institution = driver.find_element(By.CSS_SELECTOR, selector).text.strip()
                        if institution:
                            break
                    except Exception:
                        continue

                for selector in [".location-name", "[class*='location']"]:
                    try:
                        location = driver.find_element(By.CSS_SELECTOR, selector).text.strip()
                        if location:
                            break
                    except Exception:
                        continue

            except Exception as e:
                print(f"Error extracting metadata: {str(e)}")

    except Exception as e:
        print(f"Error fetching job details: {str(e)}")
        if not title:
            title = "Position Details"
        if not content:
            content = "Job details not available. Please check the original posting."
        raise

    finally:
        # Add metadata to content parts
        if metadata['contact_email']:
            content_parts.append(f"Contact Email: {metadata['contact_email']}")
        if metadata['contact_postal']:
            content_parts.append(f"Contact Address: {metadata['contact_postal']}")
        if metadata['required_documents']:
            content_parts.append("Required Documents:\n• " + "\n• ".join(metadata['required_documents']))
        if metadata['requirements']:
            content_parts.append("Requirements:\n• " + "\n• ".join(metadata['requirements']))
        if metadata['deadline']:
            content_parts.append(f"Application Deadline: {metadata['deadline']}")

        # Combine content parts if available, otherwise use existing content
        if content_parts:
            content = "\n\n".join(content_parts)
            if not any(metadata['deadline'] in p for p in content_parts):
                posted = f"{posted} (Deadline: {metadata['deadline']})" if metadata['deadline'] else posted
        
        # Clean up any None values
        title = title or "Position Details"
        content = content or "Job details not available. Please check the original posting."
        institution = institution or ""
        location = location or ""
        posted = posted or ""
        contract = contract or ""
        
        print(f"Successfully extracted job details from {url}")
        print(f"Found {len(metadata['required_documents'])} required documents")
        print(f"Found {len(metadata['requirements'])} requirements")
        if metadata['contact_email'] or metadata['contact_postal']:
            print("Successfully extracted contact information")
        
        return title, content, institution, location, posted, contract

def fetch_msca_jobs(use_headless=True, selected_model=None, max_retries=3):
    """Fetch job postings from MSCA and EURAXESS websites with improved error handling"""
    set_windows_proxy_from_pac("http://127.0.0.1:55624/proxy.pac")
    # Update base URLs with correct format, including hosting offers    
    job_urls = {
        'Jobs': 'https://euraxess.ec.europa.eu/jobs/search?f%5B0%5D=offer_type%3Ajob_offer'
    }  # Set up Chrome options
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
    all_jobs = []    # Process each section
    for section_type, section_url in job_urls.items():
        print(f"\nProcessing {section_type} section: {section_url}")
        retry_count = 0
        while retry_count < max_retries:
            try:
                driver.get(section_url)
                time.sleep(5)  # Wait for page to load

                # Try to find job listings
                found_jobs = fetch_euraxess_jobs(driver, section_type)
                if found_jobs:
                    all_jobs.extend(found_jobs)
                    print(f"Found {len(found_jobs)} {section_type} positions")
                    break
                else:
                    retry_count += 1
                    if retry_count < max_retries:
                        print(f"No jobs found, retrying ({retry_count + 1}/{max_retries})...")
                        time.sleep(3)
                        continue
            except Exception as e:
                print(f"Error processing {section_type} section (attempt {retry_count + 1}/{max_retries}): {e}")
                retry_count += 1
                if retry_count < max_retries:
                    time.sleep(3)
                    continue
                break

    # Fetch detailed information for each job
    job_details = []
    print("\nFetching job details...")
    for i, job in enumerate(all_jobs):
        print(f"Processing job {i+1}/{len(all_jobs)} ({int((i+1)/len(all_jobs)*100)}%): {job['title'][:30]}...")
        retry_count = 0
        success = False
        detail_data = None
        
        while retry_count < max_retries and not success:
            try:
                if retry_count > 0:
                    print(f"Retrying job details fetch (attempt {retry_count + 1}/{max_retries})...")
                    # Reinitialize driver if needed
                    try:
                        driver.quit()
                    except:
                        pass
                    try:
                        driver = webdriver.Chrome(options=options)
                        driver.set_page_load_timeout(30)
                    except Exception as e:
                        print(f"Error reinitializing driver: {e}")
                        time.sleep(2)  # Wait before retry
                        continue

                detail_title, detail_content, inst2, loc2, posted, contract = fetch_job_detail(driver, job['link'], max_retries=3)
                detail_data = (detail_title, detail_content, inst2, loc2, posted, contract)
                success = True

            except InvalidSessionIdException:
                print(f"Browser session invalid on attempt {retry_count + 1}")
                retry_count += 1
                if retry_count == max_retries:
                    print("Max retries reached for this job, setting empty values")
                    detail_title = detail_content = inst2 = loc2 = posted = contract = ''
                time.sleep(2)  # Wait before retry
                
            except Exception as e:
                print(f"Error fetching job details on attempt {retry_count + 1}: {e}")
                retry_count += 1
                if retry_count == max_retries:
                    print("Max retries reached for this job, setting empty values")
                    detail_title = detail_content = inst2 = loc2 = posted = contract = ''
                time.sleep(2)  # Wait before retry

        # Use detail page data if available, fall back to list page data if needed
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
        print(f"Successfully processed job {i+1}/{len(all_jobs)}")

    try:
        driver.quit()
    except:
        pass
    
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
        article = f"# Latest MSCA Research Positions ({today})\n\n"
    article += "## About MSCA\n"
    article += "Marie Skłodowska-Curie Actions (MSCA) is the European Union's flagship funding programme for doctoral education and postdoctoral training. This summary contains the 10 most recent job postings.\n\n"
    
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

@retry_with_backoff
def fetch_euraxess_jobs(driver, section_type):
    """Fetch job listings from EURAXESS website."""
    found_jobs = []   
    try:
        print(f"Waiting for page to load and validate...")
        
        # Wait for job cards to be visible
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".ecl-content-item__content-block"))
        )
        
        # Get all job cards
        job_cards = driver.find_elements(By.CSS_SELECTOR, ".ecl-content-item__content-block")
        # Take only the last 10 jobs
        job_cards = job_cards[-10:] if len(job_cards) > 10 else job_cards
        print(f"Processing last {len(job_cards)} job cards...")
        
        for card in job_cards:
            try:
                # Get title and link
                title_elem = card.find_element(By.CSS_SELECTOR, ".ecl-content-block__title a")
                title = title_elem.text.strip()
                link = title_elem.get_attribute("href")
                
                # Get institution
                try:
                    institution_elem = card.find_element(By.CSS_SELECTOR, ".ecl-content-block__primary-meta-item a")
                    institution = institution_elem.text.strip()
                except:
                    institution = ""
                
                # Get posted date
                try:
                    date_elem = card.find_elements(By.CSS_SELECTOR, ".ecl-content-block__primary-meta-item")[1]
                    posted = date_elem.text.replace("Posted on:", "").strip()
                except:
                    posted = ""
                
                # Get description preview
                try:
                    desc = card.find_element(By.CSS_SELECTOR, ".ecl-content-block__description").text.strip()
                except:
                    desc = ""
                
                # Get metadata
                metadata = {}
                meta_items = card.find_elements(By.CSS_SELECTOR, ".ecl-content-block__secondary-meta-item")
                for item in meta_items:
                    try:
                        item_text = item.text.strip()
                        if "Department:" in item_text:
                            metadata['department'] = item_text.split("Department:")[1].strip()
                        elif "Work Locations:" in item_text:
                            metadata['location'] = item_text.split("Work Locations:")[1].strip()
                        elif "Research Field:" in item_text:
                            fields = item.find_elements(By.CSS_SELECTOR, "a")
                            metadata['fields'] = [f.text.strip() for f in fields]
                        elif "Researcher Profile:" in item_text:
                            profiles = item.find_elements(By.CSS_SELECTOR, "a")
                            metadata['profiles'] = [p.text.strip() for p in profiles]
                    except:
                        continue
                
                job_data = {
                    "title": title,
                    "link": link,
                    "institution": institution,
                    "posted": posted,
                    "description": desc,
                    "location": metadata.get('location', ''),
                    "department": metadata.get('department', ''),
                    "research_fields": metadata.get('fields', []),
                    "researcher_profiles": metadata.get('profiles', []),
                    "type": section_type
                }
                
                found_jobs.append(job_data)
                print(f"Added job: {title[:50]}...")
            except:
                pass
        if not validate_page_load(driver):
            raise Exception("Page failed to load properly")
            
        # Try multiple selectors to wait for page load
        primary_selectors = [
            ".view-content",  # EURAXESS main content container
            ".ecl-content-item-block",
            ".ecl-content-block",
            ".ecl-content-item__content-block",
            ".search-result-wrapper",
            ".listing-results-wrapper",
            ".search-results",
            "article"  # Fallback for any article elements
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
            print("Primary selectors not found, trying secondary approach...")            # Wait for any job-related links as fallback
            def find_job_links(driver):
                try:
                    # First try EURAXESS specific links
                    links = driver.find_elements(By.CSS_SELECTOR, ".ecl-content-block__title a, [class*='job-title'] a")
                    if links:
                        return True
                    
                    # Fall back to searching all links
                    links = driver.find_elements(By.TAG_NAME, "a")
                    job_links = []
                    for link in links:
                        try:
                            href = link.get_attribute("href") or ""
                            text = link.text.strip()
                            # More specific keywords for EURAXESS
                            if href and text and any(kw in (href.lower() + " " + text.lower())
                                                   for kw in ["job-details", "phd", "researcher", "position", 
                                                            "research", "fellowship", "vacancy", "hosting"]):
                                job_links.append(link)
                        except:
                            continue
                    return bool(job_links)  # Convert to boolean explicitly
                except Exception as e:
                    print(f"Error in find_job_links: {e}")
                    return False

            try:
                WebDriverWait(driver, 15).until(find_job_links)
                print("Found job-related links")
            except TimeoutException:
                print("No job-related links found within timeout")
                pass
        
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

def validate_page_load(driver, timeout=10):
    """Validate that a page has fully loaded with dynamic content"""
    try:
        # Wait for basic HTML load
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        
        # Wait for page readyState
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        
        # Wait for dynamic content
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("""
                return !document.querySelector('[class*="loading"]') && 
                       !document.querySelector('[class*="spinner"]') &&
                       !document.querySelector('[aria-busy="true"]')
            """)
        )
        
        # Check for common error indicators
        error_indicators = driver.execute_script("""
            return {
                'status': !document.querySelector('.error-page, .error-message, [class*="error"]'),
                'http': !document.title.includes('404') && !document.title.includes('500'),
                'content': document.body.textContent.length > 100
            }
        """)
        
        if not all(error_indicators.values()):
            raise Exception("Page appears to have errors or invalid content")
            
        return True
        
    except Exception as e:
        print(f"Page load validation failed: {str(e)}")
        return False

def retry_with_backoff(func, retries=3, initial_delay=1, max_delay=10):
    """Execute a function with exponential backoff retry logic"""
    def wrapper(*args, **kwargs):
        delay = initial_delay
        last_exception = None
        
        for attempt in range(retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                print(f"Attempt {attempt + 1}/{retries} failed: {str(e)}")
                
                if attempt < retries - 1:
                    sleep_time = min(delay * (2 ** attempt), max_delay)
                    print(f"Waiting {sleep_time} seconds before retrying...")
                    time.sleep(sleep_time)
                    
                    # Check if we need to refresh the driver
                    if isinstance(e, (InvalidSessionIdException, TimeoutException)):
                        print("Browser session may be invalid, attempting to refresh...")
                        try:
                            if 'driver' in kwargs:
                                kwargs['driver'].refresh()
                            elif len(args) > 0 and isinstance(args[0], webdriver.Chrome):
                                args[0].refresh()
                        except:
                            print("Failed to refresh browser, continuing with retry...")
        
        raise last_exception
    return wrapper

if __name__ == "__main__":
    print("=== MSCA Research Positions Scraper ===")
    
    print("\n=== Phase 1: Fetching Job Listings ===")
    
    max_attempts = 3
    attempt = 0
    job_details = []
    
    while attempt < max_attempts and len(job_details) == 0:
        attempt += 1
        try:
            # Try headless mode first
            if attempt == 1:
                print("Attempting to fetch with headless mode...")
                job_details = fetch_msca_jobs(use_headless=True)
            else:
                print(f"\nAttempt {attempt}: Trying with visible browser...")
                job_details = fetch_msca_jobs(use_headless=False)
                
        except Exception as e:
            print(f"Attempt {attempt} failed: {str(e)}")
            if attempt < max_attempts:
                print("Waiting 10 seconds before next attempt...")
                time.sleep(10)
            continue
            
        if len(job_details) > 0:
            print(f"Successfully retrieved {len(job_details)} job listings")
            break
        elif attempt < max_attempts:
            print("No jobs found, will retry with different configuration...")
            time.sleep(5)
    
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
