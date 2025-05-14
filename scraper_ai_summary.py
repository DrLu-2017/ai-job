#from webdriver_manager.chrome import ChromeDriverManager  # Add this import at the top
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time

import hashlib
import json
import requests
import re
from collections import defaultdict

def ollama_highlight(text, model="deepseek-r1:70b", host="http://rf-calcul:11434"):
    prompt = f"请用一句话总结以下学术招聘信息的最大亮点或吸引力，突出岗位优势或独特之处：\n{text}"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False
    }
    try:
        resp = requests.post(f"{host}/api/generate", json=payload, timeout=120)
        resp.raise_for_status()
        result = resp.json()
        return result.get("response", "")
    except Exception as e:
        return f"AI亮点生成失败: {e}"

def classify_position(title, content):
    title_content = (title + ' ' + content).lower()
    if any(x in title_content for x in ['phd', '博士']):
        return '博士'
    if any(x in title_content for x in ['postdoc', 'post-doctoral', '博后', '博士后']):
        return '博后'
    if any(x in title_content for x in ['professor', 'tenure', 'faculty', 'lecturer', 'permanent', '研究员', '讲师', '副教授', '正教授', '永久']):
        return '永久科研职位'
    return '其他'

def extract_direction(text):
    directions = [
        ('人工智能', ['artificial intelligence', 'ai', 'machine learning', '深度学习', '智能']),
        ('计算机', ['computer', 'software', 'algorithm', '计算机']),
        ('材料', ['material', '材料']),
        ('物理', ['physics', '物理']),
        ('化学', ['chemistry', '化学']),
        ('生物', ['biology', '生物']),
        ('医学', ['medicine', 'medical', '医学']),
        ('数学', ['math', 'mathematics', '数学']),
        ('工程', ['engineering', '工程']),
        ('经济', ['economics', 'finance', '经济', '金融']),
        ('管理', ['management', '管理']),
        ('环境', ['environment', '环境']),
        ('地球', ['earth', 'geoscience', '地球']),
        ('社会科学', ['social', '社会']),
        ('心理', ['psychology', '心理']),
        ('法学', ['law', '法律']),
        ('历史', ['history', '历史']),
        ('教育', ['education', '教育']),
        ('语言', ['linguistics', 'language', '语言']),
        ('哲学', ['philosophy', '哲学']),
        ('艺术', ['art', '艺术']),
    ]
    text = text.lower()
    for direction, keywords in directions:
        for kw in keywords:
            if kw in text:
                return direction
    return '其他'

def fetch_job_detail(driver, url):
    driver.get(url)
    time.sleep(2)
    try:
        title = driver.find_element(By.CSS_SELECTOR, 'h1, h2, .job-title').text.strip()
    except:
        title = ''
    try:
        content_elem = driver.find_element(By.CSS_SELECTOR, '.job-description, .description, main, article')
        content = content_elem.text.strip()
    except:
        content = driver.find_element(By.TAG_NAME, 'body').text.strip()
    try:
        institution = driver.find_element(By.CSS_SELECTOR, "a.job-link,span[class*='employer']").text.strip()
    except:
        institution = ''
    try:
        location = driver.find_element(By.CSS_SELECTOR, ".job-locations,span[class*='location']").text.strip()
    except:
        location = ''
    try:
        posted = driver.find_element(By.CSS_SELECTOR, ".job-posting-date,.date").text.strip()
    except:
        posted = ''
    return title, content, institution, location, posted

def fetch_jobs_with_selenium(page=1, max_retries=3):
    jobs = []
    url = f"https://academicpositions.com/find-jobs?page={page}"

    chrome_options = Options()
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--dns-prefetch-disable")
    chrome_options.add_argument("--disable-features=VizDisplayCompositor")
    
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    # Simplified capabilities
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    
    retry_count = 0
    while retry_count < max_retries:
        driver = None
        try:
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            driver.set_page_load_timeout(30)
            driver.set_script_timeout(30)
            
            # 打印当前代理设置（调试用）
            print("Proxy settings:", driver.execute_script('return navigator.proxy'))
            
            print(f"Scraping page {page} (attempt {retry_count + 1})...")
            driver.get(url)
            
            # Add initial wait for page load
            time.sleep(5)
            
            wait = WebDriverWait(driver, 30)  # Increased wait time
            
            # Check if page loaded successfully
            try:
                # First wait for <body> to ensure basic page load
                wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
              
                # Then check for main content or a common element
                try:
                    main_content = wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "main.main-content, .job-posting-card"))
                    )
                    print("Main content loaded successfully")
                except Exception as e:
                    print(f"Could not find main content: {str(e)}")
                    print("Dumping first 1000 chars of page source for debugging:")
                    print(driver.page_source[:1000])
                    raise

                # Try scrolling and waiting for job cards to appear
                job_cards = []
                scroll_attempts = 0
                max_scroll_attempts = 5
                while scroll_attempts < max_scroll_attempts:
                    try:
                        job_cards = driver.find_elements(By.CSS_SELECTOR, ".job-posting-card")
                        if job_cards:
                            print(f"Found {len(job_cards)} job cards after {scroll_attempts} scroll(s)")
                            break
                    except Exception:
                        pass
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(2)
                    scroll_attempts += 1

                if not job_cards:
                    print("No job cards found after scrolling. Dumping first 1000 chars of page source for debugging:")
                    print(driver.page_source[:1000])
                    raise Exception("Job cards not found after scrolling.")

                print("Page loaded successfully")
                
            except Exception as e:
                print(f"Page load error: {str(e)}")
                raise Exception("Failed to load page content")
            
            # Get page source for debugging
            print(f"Page source length: {len(driver.page_source)}")
            
            # Wait specifically for job cards
            job_cards = wait.until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".job-posting-card"))
            )
            print(f"Found {len(job_cards)} job cards")

            for card in job_cards:
                try:
                    # Ensure card is visible
                    driver.execute_script("arguments[0].scrollIntoView(true);", card)
                    time.sleep(0.5)  # Brief pause after scrolling
                    
                    # Updated selectors to match the actual HTML structure
                    title_el = card.find_element(By.CSS_SELECTOR, "a.job-link")
                    title = title_el.text.strip()
                    link = title_el.get_attribute("href")
                    
                    # Updated institution selector
                    institution = card.find_element(By.CSS_SELECTOR, "a.text-reset.job-link").text.strip()
                    
                    # Updated location selector
                    location_el = card.find_element(By.CSS_SELECTOR, ".job-locations a.text-muted")
                    location = location_el.text.strip()
                    
                    # Keep existing posted date selector if it's still valid
                    posted = card.find_element(By.CSS_SELECTOR, ".job-posting-date").text.strip()

                    # 访问详情页获取内容
                    detail_title, content, inst2, loc2, posted2 = fetch_job_detail(driver, link)
                    # 优先用详情页抓到的单位/地点/时间
                    institution = inst2 or institution
                    location = loc2 or location
                    posted = posted2 or posted
                    # AI亮点
                    highlight = ollama_highlight(detail_title + '\n' + content)

                    print(f"Successfully parsed job: {title}")

                    jobs.append({
                        "title": detail_title or title,
                        "institution": institution,
                        "location": location,
                        "posted": posted,
                        "link": link,
                        "content": content,
                        "highlight": highlight
                    })
                except Exception as e:
                    print(f"Error parsing card: {str(e)}")
                    print(f"Card HTML: {card.get_attribute('outerHTML')}")
                    continue

            break  # If successful, exit retry loop

        except Exception as e:
            retry_count += 1
            print(f"Attempt {retry_count} failed: {str(e)}")
            if retry_count < max_retries:
                print(f"Retrying in 5 seconds...")
                time.sleep(5)
            else:
                print(f"Max retries ({max_retries}) reached. Giving up.")
        finally:
            if driver:
                driver.quit()
    
    return jobs

def get_job_digest(jobs):
    # 生成当前10条招聘的唯一摘要
    m = hashlib.md5()
    for job in jobs:
        m.update(job['title'].encode('utf-8'))
        m.update(job['posted'].encode('utf-8'))
        m.update(job['institution'].encode('utf-8'))
        m.update(job['location'].encode('utf-8'))
    return m.hexdigest()

def fetch_top10_jobs():
    jobs = fetch_jobs_with_selenium(page=1)
    # 只取前10条，并格式化输出
    result = []
    for job in jobs[:10]:
        summary = f"{job['institution']} | {job['location']}"
        result.append({
            'title': job['title'],
            'posted': job['posted'],
            'summary': summary
        })
    return result

def generate_summary_article(job_details):
    classified = defaultdict(lambda: defaultdict(list))
    for job in job_details:
        category = classify_position(job['title'], job['content'])
        direction = extract_direction(job['title'] + ' ' + job['content'])
        classified[category][direction].append(job)
    today = '2025-04-16'
    article = f"# 学术招聘信息汇总（{today}）\n\n"
    for category in ['博士', '博后', '永久科研职位', '其他']:
        if category not in classified:
            continue
        article += f"## {category}岗位\n\n"
        for direction, jobs in classified[category].items():
            article += f"### {direction}\n\n"
            for job in jobs:
                article += f"**{job['title']}**\n\n"
                article += f"单位/机构：{job.get('institution', '')}  地点：{job.get('location', '')}  发布时间：{job.get('posted', '')}\n\n"
                article += f"[职位详情]({job['link']})\n\n"
                content = job['content'].replace('\n', ' ').replace('\r', ' ')
                article += f"摘要：{content[:300]}...\n\n"
                article += f"**职位亮点：{job.get('highlight', '')}**\n\n"
    return article

def main():
    jobs = fetch_jobs_with_selenium(page=1)
    article = generate_summary_article(jobs)
    with open('academic_job_summary.md', 'w', encoding='utf-8') as f:
        f.write(article)
    print('已生成 academic_job_summary.md，可直接粘贴到公众号后台。')

if __name__ == "__main__":
    main()
