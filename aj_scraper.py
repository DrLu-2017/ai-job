from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
import time
import requests
import re
import os
import subprocess
from collections import defaultdict
from selenium.common.exceptions import InvalidSessionIdException
import sys
import os # For checking OS type
import zipfile
import shutil

# Ensure UTF-8 encoding for standard output
sys.stdout.reconfigure(encoding='utf-8')

class MockWinreg:
    def __getattr__(self, name):
        def dummy_function(*args, **kwargs):
            pass
        
        # For constants like HKEY_CURRENT_USER, REG_SZ, KEY_SET_VALUE
        if name in ("HKEY_CURRENT_USER", "REG_SZ", "KEY_SET_VALUE"):
            return None
        return dummy_function
    
    def OpenKey(self, *args, **kwargs):
        return self
    
    def SetValueEx(self, *args, **kwargs):
        pass
    
    def CloseKey(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

# Conditionally import winreg only on Windows
if os.name == 'nt':
    import winreg
else:
    winreg = MockWinreg()

def get_chrome_version():
    """Get the version of Chrome installed on Windows"""
    try:
        # Try to get Chrome version from Windows registry
        if os.name == 'nt':  # Windows
            try:
                key_path = r"SOFTWARE\Google\Chrome\BLBeacon"
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path)
                version, _ = winreg.QueryValueEx(key, "version")
                major_version = version.split('.')[0]
                return major_version
            except Exception as e:
                print(f"Registry lookup failed: {e}")
        
        # Fallback: try to get version from Chrome executable
        chrome_path = ""
        if os.name == 'nt':  # Windows
            chrome_path = r'C:\Program Files\Google\Chrome\Application\chrome.exe'
            if not os.path.exists(chrome_path):
                chrome_path = r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe'
        else:  # Linux/Mac
            chrome_path = 'google-chrome'
        
        if os.name == 'nt':
            # Use Windows where command
            result = subprocess.run(['where', chrome_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if result.returncode == 0:
                chrome_path = result.stdout.strip()
        else:
            # Use which command on Linux/Mac
            result = subprocess.run(['which', chrome_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if result.returncode == 0:
                chrome_path = result.stdout.strip()
        
        # Get version string
        if os.name == 'nt':
            process = subprocess.Popen([chrome_path, '--version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        else:
            process = subprocess.Popen(['google-chrome', '--version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        output, _ = process.communicate()
        version = output.decode('utf-8').strip().split()[-1]
        major_version = version.split('.')[0]
        return major_version
    except Exception as e:
        print(f"Error getting Chrome version: {e}")
        return None

def download_chromedriver():
    """Download the appropriate version of ChromeDriver"""
    try:
        chrome_version = get_chrome_version()
        if not chrome_version:
            print("Could not determine Chrome version, using latest stable ChromeDriver")
            chrome_version = "stable"
        
        print(f"Detected Chrome version: {chrome_version}")
        
        # Get the download URL for the matching ChromeDriver version
        version_url = f"https://chromedriver.storage.googleapis.com/LATEST_RELEASE_{chrome_version}"
        print(f"Checking ChromeDriver version at: {version_url}")
        
        response = requests.get(version_url)
        if response.status_code != 200:
            print("Could not find exact version match, trying stable version")
            version_url = "https://chromedriver.storage.googleapis.com/LATEST_RELEASE"
            response = requests.get(version_url)
            
        chromedriver_version = response.text.strip()
        print(f"ChromeDriver version to download: {chromedriver_version}")
        
        # Determine platform
        platform = 'win32' if os.name == 'nt' else 'linux64'
        if platform == 'win32':
            download_url = f"https://chromedriver.storage.googleapis.com/{chromedriver_version}/chromedriver_win32.zip"
        else:
            download_url = f"https://chromedriver.storage.googleapis.com/{chromedriver_version}/chromedriver_linux64.zip"
        
        print(f"Downloading ChromeDriver from: {download_url}")
        response = requests.get(download_url)
        
        # Save the zip file
        with open("chromedriver.zip", "wb") as f:
            f.write(response.content)
        
        # Create a backup of existing chromedriver if it exists
        if os.path.exists("chromedriver.exe"):
            backup_name = "chromedriver.exe.backup"
            try:
                shutil.move("chromedriver.exe", backup_name)
                print(f"Backed up existing ChromeDriver to {backup_name}")
            except Exception as e:
                print(f"Failed to backup existing ChromeDriver: {e}")
        
        # Extract the zip file
        with zipfile.ZipFile("chromedriver.zip", "r") as zip_ref:
            zip_ref.extractall(".")
        
        # Clean up
        os.remove("chromedriver.zip")
        print("Successfully downloaded and extracted new ChromeDriver")
        
        # Make chromedriver executable on Linux
        if platform != 'win32':
            os.chmod("chromedriver", 0o755)
        
        return True
    except Exception as e:
        print(f"Error downloading ChromeDriver: {e}")
        return False

default_server_url = "http://rf-calcul:11434"  # Default to rf-calcul

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

# 设置 Windows 系统代理（适用于大多数公司内网环境）
def set_windows_proxy_from_pac(pac_url):
    if os.name == 'nt':
        try:
            # 设置自动配置脚本（PAC）
            reg_path = r"Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings"
            # Ensure winreg was actually imported and not the mock
            if hasattr(winreg, 'OpenKey') and not isinstance(winreg, MockWinreg): 
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_SET_VALUE) as key:
                    winreg.SetValueEx(key, "AutoConfigURL", 0, winreg.REG_SZ, pac_url)
                print(f"已设置系统代理 PAC: {pac_url}")
            else:
                print("winreg module not available or is mocked, skipping proxy set.")
        except Exception as e:
            print(f"设置系统代理失败: {e}")
    else:
        print("代理设置仅适用于Windows系统。")

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
    contract_keywords = ['contract', 'duration', '周期', '期限', 'term', '合同时间']
    for kw in contract_keywords:
        m = re.search(rf'{kw}[:：]?\s*([\w\- ]+)', content, re.IGNORECASE)
        if m:
            contract = m.group(1).strip()
            break
    # 开始时间
    start_date = ''
    start_date_keywords = ["start date", "commencement date", "开始时间"]
    for kw in start_date_keywords:
        m = re.search(rf'{kw}[:：]?\s*([\w\- ]+)', content, re.IGNORECASE)
        if m:
            start_date = m.group(1).strip()
            break
    return title, content, institution, location, posted, contract, start_date

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

def ollama_summarize(text, model="deepseek-r1:70b", host=None):
    """生成职位摘要，使用大语言模型总结内容"""
    global default_server_url
    servers = [host] if host else ["http://rf-calcul:11434"]
    if default_server_url:
        # Put the last successful server first
        if default_server_url in servers:
            servers.remove(default_server_url)
        servers.insert(0, default_server_url)
    
    # Try each server in sequence
    last_error = None
    for server in servers:
        try:
            # 限制文本长度，避免超出模型上下文窗口
            text_truncated = text[:8000] if len(text) > 8000 else text  # Increased context window

            prompt = f"请对以下学术招聘信息进行汇总和总结，重点提炼岗位要求、研究方向、单位、地点等关键信息：\n{text_truncated}"

            # 标准化请求体格式
            payload = {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.5,  # 降低温度以获得更确定性的输出
                    "top_p": 0.9
                }
            }

            # 添加请求头
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json"
            }

            url = f"{server}/api/generate"
            print(f"正在使用服务器 {server} 的 {model} 模型生成职位摘要...")
            resp = requests.post(url, json=payload, headers=headers, timeout=600)  # Increased timeout to 10 minutes for slow server
            resp.raise_for_status()

            result = resp.json()
            if not isinstance(result, dict) or "response" not in result:
                print(f"API响应格式错误: {result}")
                raise Exception("API响应格式错误")

            summary = result.get("response", "").strip()
            print("摘要生成成功")
            # Update the default server URL
            default_server_url = server
            return summary

        except requests.exceptions.Timeout:
            print(f"服务器 {server} 请求超时")
            last_error = "timeout"
            continue
        except Exception as e:
            print(f"服务器 {server} 调用失败: {e}")
            last_error = str(e)
            continue

    # If all servers failed, try backup model
    print(f"所有服务器都失败 ({last_error})，尝试备用模型...")
    try:
        backup_model = "qwen3:30b-a3b"  # Updated backup model name
        print(f"尝试使用备用模型 {backup_model}...")

        # Use a simpler prompt with the last tried server
        simple_prompt = f"请简要总结以下学术招聘信息的主要内容：\n\n{text_truncated[:2000]}"  # Increased context for backup
        payload["model"] = backup_model
        payload["prompt"] = simple_prompt

        resp = requests.post(f"{server}/api/generate", json=payload, headers=headers, timeout=600)
        resp.raise_for_status()
        result = resp.json()
        return result.get("response", "")
    except Exception as backup_error:
        print(f"备用模型也失败: {backup_error}")
        # Fall back to simple text extraction
        simple_txt = text_truncated[:500]
        return f"职位概要：{simple_txt}..."

def ollama_highlight(text, model="deepseek-r1:70b", host=None):
    """生成职位亮点，如果主模型失败则使用备用模型"""
    global default_server_url
    servers = [host] if host else ["http://rf-calcul:11434"]
    if default_server_url:
        # Put the last successful server first
        if default_server_url in servers:
            servers.remove(default_server_url)
        servers.insert(0, default_server_url)

    example = """
    蒙特利尔大学（Université de Montréal）提供一个卓越的学术环境，结合世界级的研究资源、多元文化的国际社区，以及蒙特利尔这座充满活力的城市所提供的无限机会，是追求学术卓越和个人成长的理想选择。
    """

    # 简化提示，减少模型负担
    prompt = (
        f"请分析以下学术招聘信息，提取并总结该职位的主要亮点和特色。\n\n"
        f"要求：\n"
        f"1. 分析研究机构/大学的声誉、研究方向的前沿性、团队影响力、资源设备、地理位置等方面\n"
        f"2. 用中文输出一段简洁有力的描述（80-120字左右）\n"
        f"3. 直接描述核心亮点，不要有'该职位'、'这个岗位'等词\n"
        f"4. 使用吸引人的表述，突出最具竞争力的方面\n\n"
        f"参考示例：\n{example}\n\n"
        f"招聘信息：\n{text[:8000]}"  # Increased context window
    )

    # 标准化请求体格式
    payload = {
        "model": model,
        "prompt": prompt.strip(),
        "stream": False,
        "options": {
            "temperature": 0.7,
            "top_p": 0.9
        }
    }

    # 添加请求头
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    # Try each server in sequence
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

            # Remove <think> tags and content
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
        # Use a simpler prompt
        simple_prompt = f"请用一段话总结以下学术招聘信息的主要亮点和特色：\n\n{text[:2000]}" # Increased context for backup
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
        print(f"备用模型失败: {e}")

    # If all attempts fail, use simple extraction
    print("所有模型都失败，使用简单提取方法...")
    # Extract key information from text
    institution = re.search(r'(?:university|大学|学院|研究所|institute)[\s:]*([\w\s]+)', text, re.IGNORECASE)
    location = re.search(r'(?:location|地点|位于)[\s:]*([\w\s,]+)', text, re.IGNORECASE)
    field = re.search(r'(?:research|field|研究|领域)[\s:]*([\w\s,]+)', text, re.IGNORECASE)

    highlight_parts = []
    if institution:
        highlight_parts.append(f"{institution.group(1)}是一所知名学术机构")
    if location:
        highlight_parts.append(f"位于{location.group(1)}")
    if field:
        highlight_parts.append(f"在{field.group(1)}领域有突出研究")

    if highlight_parts:
        return "，".join(highlight_parts) + "，提供良好的学术环境和发展机会。"
    else:
        return "提供良好的学术环境和职业发展机会，适合有志于学术研究的人才。"

def classify_position(title, content):
    title_content = (title + ' ' + content).lower()
    if any(x in title_content for x in ['phd', '博士', 'doctoral', 'doctorate']):
        return '博士生项目'
    if any(x in title_content for x in ['postdoc', 'post-doctoral', '博后', '博士后']):
        return '博士后职位'
    if any(x in title_content for x in ['professor', 'tenure', 'faculty', 'lecturer', 'permanent', '研究员', '讲师', '副教授', '正教授', '永久']):
        return '教职与研究员'
    if any(x in title_content for x in ['research', 'scientist', 'researcher', 'engineer', '工程师', '研究']):
        return '科研工作'
    if any(x in title_content for x in ['technician', 'specialist', 'assistant', '技术员', '专员']):
        return '技术支持'
    return '其他科研职位'

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

def fetch_academic_positions_jobs(use_headless=True, selected_model=None, num_jobs_to_fetch=10):
    """
    Fetch academic job postings and generate highlights using the specified model
    """
    set_windows_proxy_from_pac("http://127.0.0.1:55624/proxy.pac")
    base_url = "https://academicpositions.com/find-jobs"
    current_page = 1

    # 设置Chrome选项
    options = webdriver.ChromeOptions()

    # 添加更多选项使headless模式更难被检测
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)

    # 设置一个常见的用户代理
    options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

    # 根据参数决定是否使用headless模式
    if use_headless:
        options.add_argument('--headless=new')  # 使用新版headless模式
        print("正在启动浏览器（后台模式）...")
    else:
        print("正在启动浏览器（可见模式）...")

    # 尝试多种方式初始化ChromeDriver
    driver = None
    try:
        # 方法1：使用当前目录下的chromedriver.exe
        try:
            print("尝试使用当前目录下的ChromeDriver...")
            service = Service("./chromedriver.exe")
            driver = webdriver.Chrome(service=service, options=options)
            print("成功使用当前目录下的ChromeDriver")
        except Exception as e:
            print(f"使用当前目录ChromeDriver失败: {e}")

            # 方法2：尝试使用系统PATH中的chromedriver
            try:
                print("尝试使用系统PATH中的ChromeDriver...")
                driver = webdriver.Chrome(options=options)
                print("成功使用系统PATH中的ChromeDriver")
            except Exception as e:
                print(f"使用系统PATH中的ChromeDriver失败: {e}")

                # 方法3：尝试使用绝对路径
                try:
                    import os
                    current_dir = os.path.dirname(os.path.abspath(__file__))
                    chromedriver_path = os.path.join(current_dir, "chromedriver.exe")
                    print(f"尝试使用绝对路径: {chromedriver_path}")
                    service = Service(chromedriver_path)
                    driver = webdriver.Chrome(service=service, options=options)
                    print(f"成功使用绝对路径: {chromedriver_path}")
                except Exception as e:
                    print(f"使用绝对路径失败: {e}")
                    raise Exception("无法初始化ChromeDriver，请确保chromedriver.exe在当前目录或系统PATH中")
    except Exception as e:
        print(f"初始化ChromeDriver失败: {e}")
        raise

    # 设置页面加载超时
    driver.set_page_load_timeout(30)

    print("正在访问招聘网站...")
    jobs = []
    valid_jobs = 0  # Track number of valid jobs

    # 尝试多种选择器来查找职位卡片
    selectors = [
        "div[class*='job']",
        "div[class*='listing']",
        ".job-posting-card",
        "article",
        "div.card",
        "div.position",
        "a[href*='job']"
    ]
    
    while valid_jobs < num_jobs_to_fetch:
        url = f"{base_url}?page={current_page}"
        print(f"\n正在访问第 {current_page} 页...")
        driver.get(url)

        # 等待页面加载
        print("等待页面加载...")
        time.sleep(5)  # 给页面足够的加载时间

        # 尝试所有选择器
        job_cards = []
        for selector in selectors:
            try:
                print(f"尝试使用选择器: {selector}")
                cards = driver.find_elements(By.CSS_SELECTOR, selector)
                if cards and len(cards) > 0:
                    print(f"  - 找到 {len(cards)} 个元素")
                    job_cards.extend(cards)
            except Exception as e:
                print(f"  - 选择器错误: {e}")

        # 去重
        unique_cards = []
        card_texts = set()
        for card in job_cards:
            try:
                card_text = card.text.strip()
                if card_text and card_text not in card_texts:
                    card_texts.add(card_text)
                    unique_cards.append(card)
            except:
                pass
        
        job_cards = unique_cards
        print(f"第 {current_page} 页检测到职位卡片数量: {len(job_cards)}")

        # 如果这一页没有找到任何卡片，可能已经到达最后一页
        if len(job_cards) == 0:
            print("没有找到更多职位，可能已到达最后一页")
            break

        # 处理本页的职位卡片
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
                
            # Only process if we have both title and institution
            if title and institution and valid_jobs < num_jobs_to_fetch:
                jobs.append({
                    "title": title,
                    "institution": institution,
                    "location": location,
                    "link": link
                })
                valid_jobs += 1
                print(f"已解析职位卡片: {valid_jobs}/{num_jobs_to_fetch} ({int(valid_jobs/num_jobs_to_fetch*100)}%)")
                
                if valid_jobs >= num_jobs_to_fetch:
                    break

        # 如果已经获取足够的职位，退出循环
        if valid_jobs >= num_jobs_to_fetch:
            break

        # 尝试下一页
        current_page += 1
        
    # 继续处理职位详情
    job_details = []
    print("\n开始获取职位详情...")
    for i, job in enumerate(jobs):
        print(f"正在处理职位 {i+1}/{len(jobs)} ({int((i+1)/len(jobs)*100)}%): {job['title'][:30]}...")
        try:
            detail_title, detail_content, inst2, loc2, posted, contract, start_date = fetch_job_detail(driver, job['link'])
        except InvalidSessionIdException:
            # 重新启动driver并重试
            print("浏览器会话失效，正在重新启动...")
            try:
                driver.quit()
            except:
                pass

            # 重新初始化driver
            try:
                # 尝试多种方式初始化ChromeDriver
                if os.path.exists("./chromedriver.exe"):
                    print("尝试使用当前目录下的ChromeDriver...")
                    service = Service("./chromedriver.exe")
                    driver = webdriver.Chrome(service=service, options=options)
                else:
                    current_dir = os.path.dirname(os.path.abspath(__file__))
                    chromedriver_path = os.path.join(current_dir, "chromedriver.exe")
                    print(f"尝试使用绝对路径: {chromedriver_path}")
                    service = Service(chromedriver_path)
                    driver = webdriver.Chrome(service=service, options=options)
            except Exception as e:
                print(f"重新初始化ChromeDriver失败: {e}")
                try:
                    # 最后尝试不指定service
                    driver = webdriver.Chrome(options=options)
                except Exception as e:
                    print(f"所有初始化方法都失败: {e}")
                    raise

            # 设置页面加载超时
            driver.set_page_load_timeout(30)
            detail_title, detail_content, inst2, loc2, posted, contract, start_date = fetch_job_detail(driver, job['link'])
        # 优先用详情页数据补全
        institution = inst2 or job.get('institution', '')
        location = loc2 or job.get('location', '')
        # AI亮点
        print(f"正在生成职位亮点...")
        if selected_model:
            highlight = ollama_highlight(detail_title + '\n' + detail_content, model=selected_model)
        else:
            highlight = ollama_highlight(detail_title + '\n' + detail_content)
        job_details.append({
            "title": detail_title or job['title'],
            "content": detail_content,
            "link": job['link'],
            "institution": institution,
            "location": location,
            "posted": posted,
            "contract": contract,
            "start_date": start_date,
            "highlight": highlight
        })
        print(f"职位 {i+1}/{len(jobs)} 处理完成")
    driver.quit()
    return job_details

def generate_summary_article(job_details, today=None):
    if today is None:
        from datetime import datetime
        today = datetime.now().strftime('%Y-%m-%d')
        
    classified = defaultdict(lambda: defaultdict(list))
    for job in job_details:
        category = classify_position(job['title'], job['content'])
        direction = extract_direction(job['title'] + ' ' + job['content'])
        classified[category][direction].append(job)
    
    article = f"# 科研职位信息汇总（{today}）\n\n"
    categories = ['博士生项目', '博士后职位', '教职与研究员', '科研工作', '技术支持', '其他科研职位']
    for category in categories:
        if category not in classified:
            continue
        article += f"## {category}\n\n"
        for direction, jobs in classified[category].items():
            article += f"### {direction}\n\n"
            for job in jobs:
                # 职位标题
                article += f"#### {job['title']}\n\n"

                # 职位总结
                content = job['content'].replace('\n', ' ').replace('\r', ' ')
                summary = content[:200] + "..." if len(content) > 200 else content
                article += f"{summary}\n\n"

                # 职位特色/亮点
                highlight = job.get('highlight', '').strip()
                if highlight:
                    article += f"**职位亮点与特色:**\n\n{highlight}\n\n"

                # 地点和单位信息
                institution = job.get('institution', '').strip()
                location = job.get('location', '').strip()

                if institution:
                    article += f"**单位/机构:** {institution}\n\n"

                if location:
                    article += f"**地点:** {location}\n\n"

                # 合同周期
                contract = job.get('contract', '').strip()                
                if contract:
                    article += f"**Contract Duration:** {contract}\n\n"
                
                # 开始时间
                start_date = job.get('start_date', '').strip()
                if start_date:
                    article += f"**Start Date:** {start_date}\n\n"

                # 分隔线
                article += "---\n\n"
    return article

def generate_report2(job_details, today=None):
    if today is None:
        from datetime import datetime
        today = datetime.now().strftime('%Y-%m-%d')

    report_content = f"# 科研职位信息简报 ({today})\n\n"

    for job in job_details:
        report_content += f"## {job.get('title', 'N/A')}\n\n" # Use .get for safety

        content = job.get('content', '')
        job_summary = content[:200] + "..." if len(content) > 200 else content
        report_content += f"{job_summary}\n\n"

        link = job.get('link', '')
        if link: # Only add link if it exists
            report_content += f"查看职位详情({link})\n\n"

        report_content += "---\n\n"

    return report_content

# 示例用法：
if __name__ == "__main__":
    print("=== 科研职位信息爬取工具 ===")

    # Check AI server status first
    print("正在检查AI服务器连接...")
    if not check_ai_server("http://rf-calcul:11434"):
        print("AI服务器连接失败，程序退出")
        sys.exit(1)
    print("AI服务器连接成功")
    
    # Let user select the model to use
    selected_model = select_model()
    print(f"\n已选择模型: {selected_model}")

    # Prompt user for the number of jobs to scrape
    while True:
        try:
            num_to_scrape = int(input("请输入要爬取的职位数量 (例如 15): "))
            if num_to_scrape > 0:
                break
            else:
                print("请输入一个大于0的数字。")
        except ValueError:
            print("请输入有效的数字。")
        #except KeyboardInterrupt:
        #    print("\n用户取消输入，将使用默认数量10。")
        #    num_to_scrape = 10 # Default value on interruption
        #    break

    print("\n=== 第1阶段：爬取职位信息 ===")

    # 首先尝试使用无头模式
    print("尝试使用无头模式爬取...")
    job_details = []
    try:
        job_details = fetch_academic_positions_jobs(use_headless=True, selected_model=selected_model, num_jobs_to_fetch=num_to_scrape)
    except Exception as e:
        print(f"无头模式爬取失败: {e}")

    # 如果无头模式没有获取到职位，尝试使用有头模式
    if len(job_details) == 0:
        print("\n无头模式未能获取职位信息，尝试使用有头模式...")
        job_details = fetch_academic_positions_jobs(use_headless=False, selected_model=selected_model, num_jobs_to_scrape=num_to_scrape)

    print(f"成功获取 {len(job_details)} 个职位信息")

    # 如果仍然没有获取到职位，退出程序
    if len(job_details) == 0:
        print("未能获取任何职位信息，程序退出")
        sys.exit(1)

    # Generate and save the report
    print("\n=== 第2阶段：生成报告 ===")
    from datetime import datetime
    today = datetime.now().strftime('%Y-%m-%d')

    print("正在生成报告1...")
    article = generate_summary_article(job_details, today=today)
    print("正在保存报告1...")
    with open('academic_job_summary_report1.md', 'w', encoding='utf-8') as f:
        f.write(article)
    print("已生成 academic_job_summary_report1.md")

    print("\n正在生成报告2...")
    report2_content = generate_report2(job_details, today=today)
    print("正在保存报告2...")
    with open('academic_job_summary_report2.md', 'w', encoding='utf-8') as f:
        f.write(report2_content)
    print("已生成 academic_job_summary_report2.md")

    print("\n=== 完成 ===")
    print('已生成 academic_job_summary_report1.md 和 academic_job_summary_report2.md')
