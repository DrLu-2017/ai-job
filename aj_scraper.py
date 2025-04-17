from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import os
import requests
import re
from collections import defaultdict
from selenium.common.exceptions import InvalidSessionIdException
import sys
import winreg

# Ensure UTF-8 encoding for standard output
sys.stdout.reconfigure(encoding='utf-8')

# 设置 Windows 系统代理（适用于大多数公司内网环境）
def set_windows_proxy_from_pac(pac_url):
    try:
        # 设置自动配置脚本（PAC）
        reg_path = r"Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "AutoConfigURL", 0, winreg.REG_SZ, pac_url)
        print(f"已设置系统代理 PAC: {pac_url}")
    except Exception as e:
        print(f"设置系统代理失败: {e}")

def fetch_job_detail(driver, url):
    driver.get(url)
    time.sleep(2)
    # 标题
    try:
        title = driver.find_element(By.CSS_SELECTOR, 'h1, h2, .job-title').text.strip()
    except:
        title = ''
    # 内容
    try:
        content_elem = driver.find_element(By.CSS_SELECTOR, '.job-description, .description, main, article')
        content = content_elem.text.strip()
    except:
        content = driver.find_element(By.TAG_NAME, 'body').text.strip()
    # 单位
    try:
        institution = driver.find_element(By.CSS_SELECTOR, "a.job-link,span[class*='employer']").text.strip()
    except:
        institution = ''
    # 地点
    try:
        location = driver.find_element(By.CSS_SELECTOR, ".job-locations,span[class*='location']").text.strip()
    except:
        location = ''
    # 发布时间
    try:
        posted = driver.find_element(By.CSS_SELECTOR, ".job-posting-date,.date").text.strip()
    except:
        posted = ''
    # 合同周期
    contract = ''
    for kw in ['contract', 'duration', '周期', '期限', 'term']:
        m = re.search(rf'{kw}[:：]?\s*([\w\- ]+)', content, re.IGNORECASE)
        if m:
            contract = m.group(1).strip()
            break
    return title, content, institution, location, posted, contract

def ollama_summarize(text, model="deepseek-r1:70b", host="http://rf-calcul:11434"):
    url = f"{host}/api/generate"
    prompt = f"请对以下学术招聘信息进行汇总和总结，重点提炼岗位要求、研究方向、单位、地点等关键信息：\n{text}"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False
    }
    try:
        resp = requests.post(url, json=payload, timeout=120)
        resp.raise_for_status()
        result = resp.json()
        return result.get("response", "")
    except Exception as e:
        return f"调用 ollama 失败: {e}"

def ollama_highlight(text, model="deepseek-r1:70b", host="http://rf-calcul:11434"):
    prompt = (
        "请用一句简短的陈述句总结该职位的最大优势或特色，直接描述核心亮点，不要有任何AI思考过程。"
        "格式要求：不超过30字，只输出结论，不要有'该职位''这个岗位'等词。"
        "\n" + text
    )
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False
    }
    try:
        resp = requests.post(f"{host}/api/generate", json=payload, timeout=120)
        resp.raise_for_status()
        result = resp.json()
        highlight = result.get("response", "").strip()
        # Clean up AI thinking phrases
        common_prefixes = [
            "这个职位的亮点是", "该岗位的优势在于", "职位亮点：", 
            "AI分析：", "让我分析：", "分析得出：", "总结：",
            "亮点包括：", "特色在于：", "优势是：", "经分析，",
            "根据描述，", "通过分析，", "主要亮点：",
        ]
        for prefix in common_prefixes:
            if highlight.lower().startswith(prefix.lower()):
                highlight = highlight[len(prefix):].strip()
        return highlight.rstrip('。．.!')  # Remove trailing punctuation
    except Exception as e:
        return ""

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
    # 简单关键词归类，可扩展
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

def fetch_academic_positions_jobs():
    set_windows_proxy_from_pac("http://127.0.0.1:55624/proxy.pac")
    url = "https://academicpositions.com/find-jobs?page=1"
    service = Service("./chromedriver.exe")
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')  # 后台运行，不显示浏览器界面
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    driver = webdriver.Chrome(service=service, options=options)
    driver.get(url)

    jobs = []
    # 尝试查找所有 class 含 'job' 或 'listing' 的 div 作为职位卡片
    job_cards = driver.find_elements(By.CSS_SELECTOR, "div[class*='job'],div[class*='listing']")
    print(f"检测到可能的职位卡片数量: {len(job_cards)}")
    for card in job_cards:
        # 提取职位标题
        title = ""
        title_elem = None
        for tag in ["h2", "h3", "a", "span"]:
            try:
                title_elem = card.find_element(By.CSS_SELECTOR, f"{tag}[class*='title']")
                if title_elem.text.strip():
                    title = title_elem.text.strip()
                    break
            except:
                continue
        # 提取单位
        institution = ""
        try:
            institution = card.find_element(By.CSS_SELECTOR, "a.job-link,span[class*='employer']").text.strip()
        except:
            pass
        # 提取地点
        location = ""
        try:
            location = card.find_element(By.CSS_SELECTOR, ".job-locations,span[class*='location']").text.strip()
        except:
            pass
        # 提取链接
        link = ""
        try:
            link_elem = card.find_element(By.CSS_SELECTOR, "a.job-link")
            link = link_elem.get_attribute("href")
        except:
            pass
        if title and institution:
            jobs.append({
                "title": title,
                "institution": institution,
                "location": location,
                "link": link
            })
        if len(jobs) >= 10:
            break
    # 依次访问每个职位详情页，获取所有字段
    job_details = []
    for job in jobs:
        try:
            detail_title, detail_content, inst2, loc2, posted, contract = fetch_job_detail(driver, job['link'])
        except InvalidSessionIdException:
            # 重新启动driver并重试
            driver.quit()
            driver = webdriver.Chrome(service=service, options=options)
            detail_title, detail_content, inst2, loc2, posted, contract = fetch_job_detail(driver, job['link'])
        # 优先用详情页数据补全
        institution = inst2 or job.get('institution', '')
        location = loc2 or job.get('location', '')
        # AI亮点
        highlight = ollama_highlight(detail_title + '\n' + detail_content)
        job_details.append({
            "title": detail_title or job['title'],
            "content": detail_content,
            "link": job['link'],
            "institution": institution,
            "location": location,
            "posted": posted,
            "contract": contract,
            "highlight": highlight
        })
    driver.quit()
    return job_details

def fetch_euraxess_jobs(job_type='phd'):
    """Fetch jobs from EURAXESS portal
    Args:
        job_type (str): 'phd' or 'postdoc'
    """
    if job_type == 'phd':
        url = "https://euraxess.ec.europa.eu/jobs/search?f%5B0%5D=job_is_eu_founded%3A546&f%5B1%5D=job_is_eu_founded%3A548&f%5B2%5D=job_is_eu_founded%3A4348&f%5B3%5D=job_is_eu_founded%3A4349&f%5B4%5D=job_is_eu_founded%3A6048&f%5B5%5D=job_research_profile%3A447&f%5B6%5D=positions%3Amaster_positions&f%5B7%5D=positions%3Aphp_positions"
    else:  # postdoc
        url = "https://euraxess.ec.europa.eu/jobs/search?f%5B0%5D=job_is_eu_founded%3A546&f%5B1%5D=job_is_eu_founded%3A548&f%5B2%5D=job_is_eu_founded%3A4348&f%5B3%5D=job_is_eu_founded%3A4349&f%5B4%5D=job_is_eu_founded%3A6048&f%5B5%5D=job_research_profile%3A447&f%5B6%5D=job_research_profile%3A448&f%5B7%5D=job_research_profile%3A449&f%5B8%5D=job_research_profile%3A450"

    service = Service("./chromedriver.exe")
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    driver = webdriver.Chrome(service=service, options=options)
    driver.get(url)
    time.sleep(3)  # Wait for dynamic content to load

    jobs = []
    try:
        # Find all job listings
        job_cards = driver.find_elements(By.CSS_SELECTOR, ".views-row")
        print(f"检测到 EURAXESS {job_type} 职位数量: {len(job_cards)}")
        
        for card in job_cards[:10]:  # Limit to first 10 jobs
            try:
                # Extract job title and link
                title_elem = card.find_element(By.CSS_SELECTOR, "h4 a")
                title = title_elem.text.strip()
                link = title_elem.get_attribute("href")
                
                # Extract institution and location
                meta = card.find_element(By.CSS_SELECTOR, ".views-field-field-organisation").text.strip()
                institution = meta
                location = card.find_element(By.CSS_SELECTOR, ".views-field-field-country").text.strip()
                
                if title and link:
                    jobs.append({
                        "title": title,
                        "institution": institution,
                        "location": location,
                        "link": link
                    })
            except Exception as e:
                print(f"Error processing job card: {e}")
                continue

    except Exception as e:
        print(f"Error fetching EURAXESS jobs: {e}")
    finally:
        driver.quit()

    # Fetch job details for each position
    job_details = []
    driver = webdriver.Chrome(service=service, options=options)
    for job in jobs:
        try:
            detail_title, detail_content, inst2, loc2, posted, contract = fetch_job_detail(driver, job['link'])
            # Prefer detail page data, fallback to listing data
            institution = inst2 or job.get('institution', '')
            location = loc2 or job.get('location', '')
            # Get AI highlight
            highlight = ollama_highlight(detail_title + '\n' + detail_content)
            
            job_details.append({
                "title": detail_title or job['title'],
                "content": detail_content,
                "link": job['link'],
                "institution": institution,
                "location": location,
                "posted": posted,
                "contract": contract,
                "highlight": highlight
            })
        except Exception as e:
            print(f"Error fetching job details: {e}")
            continue
    
    driver.quit()
    return job_details

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
                # 只显示有内容的字段
                line = f"单位/机构：{job.get('institution', '')}  地点：{job.get('location', '')}"
                line = line.strip()
                if line.endswith('：') or line.replace(' ', '') == '单位/机构：地点：':
                    line = ''
                article += (line + "\n\n") if line else ""
                article += f"[职位详情]({job['link']})\n\n"
                content = job['content'].replace('\n', ' ').replace('\r', ' ')
                article += f"摘要：{content[:300]}...\n\n"
                # Only add highlight if it's not empty and doesn't contain AI thinking
                highlight = job.get('highlight', '').strip()
                if highlight:
                    article += f"💡 {highlight}\n\n"  # Using emoji instead of "职位亮点："
    return article

def check_ai_server(host="http://rf-calcul:11434"):
    """Check if the AI server is available and responding"""
    try:
        resp = requests.get(f"{host}/api/version", timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"AI服务器连接失败: {e}")
        print(f"请确保服务器 {host} 正在运行")
        return False

# 示例用法：
if __name__ == "__main__":
    # Check AI server status first
    if not check_ai_server():
        sys.exit(1)
        
    # Fetch jobs from all sources
    jobs = []
    # Academic Positions
    ap_jobs = fetch_academic_positions_jobs()
    jobs.extend(ap_jobs)
    
    # EURAXESS PhD positions
    phd_jobs = fetch_euraxess_jobs('phd')
    jobs.extend(phd_jobs)
    
    # EURAXESS Postdoc positions
    postdoc_jobs = fetch_euraxess_jobs('postdoc')
    jobs.extend(postdoc_jobs)
    
    # Generate combined summary
    article = generate_summary_article(jobs)
    with open('academic_job_summary.md', 'w', encoding='utf-8') as f:
        f.write(article)
    print('已生成 academic_job_summary.md，可直接粘贴到公众号后台。')