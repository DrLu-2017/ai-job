import time
import logging
import sys
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

# Basic logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stdout)

def setup_simple_driver(use_headless=True):
    options = Options()
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36") # Common user agent
    if use_headless:
        options.add_argument('--headless=new')

    driver = None
    try:
        # Try local chromedriver first (assuming it's in the same directory or PATH)
        try:
            # In the sandbox, chromedriver is expected to be in PATH or a known location.
            # The explicit "./chromedriver.exe" is less likely to work here than in a local Windows dev env.
            # Let's rely on Service() finding it in PATH.
            service = Service()
            driver = webdriver.Chrome(service=service, options=options)
            logging.info("Successfully initialized Chrome driver with system ChromeDriver.")
            return driver
        except Exception as e:
            logging.warning(f"System ChromeDriver (via Service()) failed or not found: {e}. Trying webdriver.Chrome(options=options) directly.")
            # This fallback might work if Selenium Manager can download a driver.
            driver = webdriver.Chrome(options=options)
            logging.info("Successfully initialized Chrome driver with system ChromeDriver (direct fallback).")
            return driver
    except Exception as e:
        logging.error(f"Failed to initialize Chrome driver: {e}")
        raise

def handle_simple_cookie_consent(driver, timeout=10):
    # Try a few common patterns for cookie banners / accept buttons
    selectors = [
        "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept')]",
        "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'agree')]",
        "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'got it')]",
        "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'ok')]",
        "//div[contains(@class, 'cookie-banner')]//button",
        "//div[contains(@id, 'cookie-consent')]//button",
        "//button[@id='CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll']" # For Cookiebot
    ]
    for selector in selectors:
        try:
            button = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((By.XPATH, selector))
            )
            # Scroll into view if necessary, and click using JavaScript to bypass potential overlays
            driver.execute_script("arguments[0].scrollIntoView(true);", button)
            driver.execute_script("arguments[0].click();", button)
            logging.info(f"Clicked cookie consent button with XPATH: {selector}")
            time.sleep(2) # Give some time for the banner to disappear
            return True # Assume one click is enough
        except:
            logging.debug(f"Cookie consent button not found or not clickable with XPATH: {selector}")
    logging.info("No common cookie consent button found or handled.")
    return False

if __name__ == "__main__":
    driver = None
    try:
        driver = setup_simple_driver(use_headless=True)

        url = "https://universitypositions.eu/jobs"

        logging.info(f"Navigating to {url}")
        driver.get(url)

        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        logging.info("Page body loaded.")

        handle_simple_cookie_consent(driver)

        actual_title = driver.title
        actual_url = driver.current_url
        logging.info(f"Current page title: {actual_title}")
        logging.info(f"Current page URL: {actual_url}")

        if "universitypositions.eu/jobs" not in actual_url.lower(): # Check if it's the correct page
            logging.error(f"Error: Navigated to an unexpected URL: {actual_url}. Expected 'universitypositions.eu/jobs'.")

        page_source = driver.page_source

        output_filename = "up_browse_all_jobs_page.html"
        with open(output_filename, "w", encoding="utf-8") as f:
            f.write(page_source)
        logging.info(f"Successfully saved page source to {output_filename}")

        # Verify file creation and print snippet
        if os.path.exists(output_filename):
            print(f"File '{output_filename}' created successfully.") # Standard print for direct output
            with open(output_filename, "r", encoding="utf-8") as f_check:
                html_snippet = f_check.read(500)
                print("\nFirst 500 characters of HTML:") # Standard print
                print(html_snippet)
                logging.info(f"First 500 characters of saved HTML for logs: \n{html_snippet}") # Also log it
        else:
            print(f"File '{output_filename}' NOT created.") # Standard print
            logging.error(f"File '{output_filename}' NOT created.")


    except Exception as e:
        logging.error(f"An error occurred: {e}", exc_info=True)
        if driver: # If driver exists, try to get some debug info
            try:
                logging.error(f"Attempting to save debug screenshot. Current URL: {driver.current_url}, Title: {driver.title}")
                driver.save_screenshot("error_screenshot_get_up_source.png")
                logging.info("Saved error screenshot.")
            except Exception as e_screenshot:
                logging.error(f"Could not save error screenshot: {e_screenshot}")
    finally:
        if driver:
            driver.quit()
            logging.info("WebDriver closed.")
