from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ...existing code...
try:
    main_content = WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "main.main-content, .job-posting-card"))
    )
except Exception as e:
    print("元素未找到，错误信息：", e)
    print(driver.page_source)  # 打印页面源码帮助调试
# ...existing code...