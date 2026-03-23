import asyncio
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # 建议先设为False，观察效果
        page = await browser.new_page()
        
        # 关键：应用 stealth 插件
        await stealth_async(page)
        
        # 检测 navigator.webdriver 是否被隐藏
        await page.goto("https://bot.sannysoft.com/")
        webdriver_status = await page.evaluate("navigator.webdriver")
        print(f"navigator.webdriver = {webdriver_status}")  # 应该输出 undefined 或 false
        
        await page.wait_for_timeout(5000)  # 观察页面
        await browser.close()

asyncio.run(main())