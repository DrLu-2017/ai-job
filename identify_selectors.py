import time
import logging
import os
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

def setup_driver_local(use_headless=True):
    options = Options()
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    if use_headless:
        options.add_argument('--headless=new')

    max_retries = 2 # Reduced retries for this specific task
    last_exception = None
    for attempt in range(max_retries):
        try:
            try:
                # Assuming chromedriver might be in current dir or PATH
                service = Service() # Will try to find chromedriver in PATH
                driver = webdriver.Chrome(service=service, options=options)
                logging.info("Successfully initialized Chrome driver with system ChromeDriver.")
                return driver
            except Exception as e_path:
                logging.warning(f"System ChromeDriver failed: {str(e_path)}. Trying local chromedriver.exe as fallback.")
                # In the sandbox, we don't usually have a chromedriver.exe locally like this,
                # but this structure is from the original varbi_scraper.py
                service = Service("./chromedriver.exe")
                driver = webdriver.Chrome(service=service, options=options)
                logging.info("Successfully initialized Chrome driver with local chromedriver.exe.")
                return driver
        except Exception as e:
            last_exception = e
            logging.warning(f"Attempt {attempt + 1} to init driver failed: {str(e)}")
            time.sleep(1)

    error_msg = f"Failed to initialize Chrome driver after {max_retries} attempts. Last error: {str(last_exception)}"
    logging.error(error_msg)
    raise RuntimeError(error_msg)

def save_page_source_and_identify_selectors():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    driver = None
    selectors = {
        "container": "NOT YET IDENTIFIED",
        "job_item": "NOT YET IDENTIFIED",
        "title": "NOT YET IDENTIFIED",
        "link": "NOT YET IDENTIFIED"
    }

    try:
        driver = setup_driver_local()
        url = "https://www.varbi.com/en/jobs/"
        logging.info(f"Navigating to {url}")
        driver.get(url)

        # Wait for page to load (e.g., for body or a known main container)
        try:
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            logging.info("Page body loaded.")
        except TimeoutException:
            logging.error("Timeout waiting for page body to load. Saving source anyway.")

        # Handle cookie consent if any - using a simplified version
        try:
            cookie_buttons = driver.find_elements(By.CSS_SELECTOR, "button[id*='cookie-accept'], button[data-testid='cookie-accept-all']")
            if cookie_buttons:
                cookie_buttons[0].click()
                logging.info("Attempted to click cookie consent button.")
                time.sleep(2) # Wait for potential overlay to disappear
        except Exception as e_cookie:
            logging.warning(f"Could not click cookie button or no cookie button found: {e_cookie}")

        # Save page source
        html_content = driver.page_source
        output_filename = "varbi_jobs_page.html"
        with open(output_filename, "w", encoding="utf-8") as f:
            f.write(html_content)
        logging.info(f"Page source saved to {output_filename}")

        # Conceptual Selector Identification (based on previous knowledge and common patterns)
        # These are educated guesses and would ideally be verified by inspecting the saved HTML.

        # 1. Job Listings Container:
        # Previous attempts used "ul.list-group[role='feed']". Let's assume this is still a primary candidate.
        # Fallbacks could be generic like 'main ul' or a div wrapping job items.
        selectors["container"] = "ul.list-group[role='feed'] (Primary Candidate), div.list-group-container, main > div > ul"

        # 2. Individual Job Items:
        # Previous: "li.list-group-item[data-listing-id]"
        selectors["job_item"] = "li.list-group-item[data-listing-id] (Primary Candidate), article.job, div.job-item"

        # 3. Job Title Element (within a job item):
        # Previous: "h3.heading a"
        selectors["title"] = "h3.heading a (Primary Candidate), h2.job-title a, .title a"

        # 4. Job Link Element (within a job item, for the href):
        # This is often the same element as the title.
        selectors["link"] = "h3.heading a (Primary Candidate, for href), h2.job-title a, .title a"

        logging.info(f"Conceptual Selectors Identified: {selectors}")

    except Exception as e:
        logging.error(f"An error occurred: {e}", exc_info=True)
    finally:
        if driver:
            driver.quit()
            logging.info("WebDriver closed.")

    return selectors

if __name__ == "__main__":
    identified_selectors = save_page_source_and_identify_selectors()
    print("--- Identified Selectors (Conceptual) ---")
    for key, value in identified_selectors.items():
        print(f"{key.replace('_', ' ').capitalize()}: {value}")

    # Verify file creation
    if os.path.exists("varbi_jobs_page.html"):
        print("\nFile 'varbi_jobs_page.html' created successfully.")
        # Optionally print a snippet of the file if allowed and useful
        # with open("varbi_jobs_page.html", "r", encoding="utf-8") as f_check:
        #     print("\nFirst 500 chars of HTML:")
        #     print(f_check.read(500))
    else:
        print("\nFile 'varbi_jobs_page.html' NOT created.")
