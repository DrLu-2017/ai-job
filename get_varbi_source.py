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

def setup_driver(use_headless=True):
    """Set up and return a configured Chrome WebDriver."""
    options = Options()
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    if use_headless:
        options.add_argument('--headless=new')

    driver = None
    try:
        # Try system chromedriver first
        service = Service()
        driver = webdriver.Chrome(service=service, options=options)
        logging.info("Successfully initialized Chrome driver with system ChromeDriver.")
        return driver
    except Exception as e_system:
        logging.warning(f"System ChromeDriver failed: {str(e_system)}. Trying bundled chromedriver.exe (less likely to work in sandbox).")
        try:
            # Fallback for local execution, less likely in sandbox
            service = Service("./chromedriver.exe")
            driver = webdriver.Chrome(service=service, options=options)
            logging.info("Successfully initialized Chrome driver with local chromedriver.exe.")
            return driver
        except Exception as e_local:
            logging.error(f"Local chromedriver.exe also failed: {e_local}")
            raise RuntimeError(f"Failed to initialize Chrome driver. System error: {e_system}, Local error: {e_local}")

def get_and_save_source():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    driver = None
    try:
        driver = setup_driver(use_headless=True)
        url = "https://www.varbi.com/en/jobs/"
        logging.info(f"Navigating to {url}")
        driver.get(url)

        # Crucial Wait
        try:
            WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            logging.info("Page body loaded.")
            # Attempt to wait for a plausible main job container, if not found, proceed.
            # Common selectors for lists or main content areas.
            # Based on previous attempts, 'ul.list-group' or 'div.list-group-container' were candidates
            # Let's try a more generic one that might appear on the Varbi jobs page
            possible_containers = ["ul.list-group", "div.list-group-container", "main", "div.job-feed", "#job-ads"]
            container_found = False
            for selector in possible_containers:
                try:
                    WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                    logging.info(f"Found plausible container with selector: {selector}")
                    container_found = True
                    break # Found a container, proceed
                except TimeoutException:
                    logging.info(f"Plausible container with selector '{selector}' not found within 5s.")

            if not container_found:
                logging.warning("No specific job container found after trying several selectors. Proceeding with current page state after body load. This might be okay if jobs are directly in body or loaded very fast.")
            else:
                time.sleep(2) # Small additional sleep if container found, for content within it to render

        except TimeoutException:
            logging.error("Timeout waiting for page body to load. Saving source as is.")
            # Proceed to save source even if timeout

        # Verify Page Title and URL
        actual_title = driver.title
        current_url = driver.current_url
        print(f"Current page title: {actual_title}")
        print(f"Current page URL: {current_url}")

        if "grade.com" in current_url.lower() or "sidan hittades inte" in actual_title.lower().replace("-", " ") or "page not found" in actual_title.lower():
            logging.error(f"ERROR: Page seems incorrect. Title: '{actual_title}', URL: '{current_url}'")
            # Still save the source for debugging
        else:
            logging.info("Page title and URL appear to be for Varbi.")

        page_source = driver.page_source
        output_filename = "varbi_jobs_page_CORRECTED.html"
        with open(output_filename, "w", encoding="utf-8") as f:
            f.write(page_source)
        logging.info(f"Page source saved to {output_filename}")

        if os.path.exists(output_filename):
            print(f"File '{output_filename}' created successfully.")
            with open(output_filename, "r", encoding="utf-8") as f_check:
                print("\nFirst 500 characters of HTML:")
                print(f_check.read(500))
        else:
            print(f"File '{output_filename}' NOT created.")

    except Exception as e:
        logging.error(f"An error occurred in get_and_save_source: {e}", exc_info=True)
    finally:
        if driver:
            driver.quit()
            logging.info("WebDriver closed.")

if __name__ == "__main__":
    get_and_save_source()
EOF

python get_varbi_source.py
