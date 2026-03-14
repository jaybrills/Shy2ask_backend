import shutil
import unittest

from django.contrib.staticfiles.testing import StaticLiveServerTestCase


try:
    from selenium import webdriver
    from selenium.common.exceptions import WebDriverException
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
except ImportError:  # pragma: no cover
    webdriver = None
    WebDriverException = Exception
    Options = None
    By = None


@unittest.skipUnless(webdriver is not None, "selenium is not installed")
class HomePageSeleniumTest(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        browser_path = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
        if not browser_path:
            raise unittest.SkipTest("Chrome or Chromium browser is not available")

        options = Options()
        options.binary_location = browser_path
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1440,1200")

        try:
            cls.selenium = webdriver.Chrome(options=options)
            cls.selenium.implicitly_wait(5)
        except WebDriverException as exc:  # pragma: no cover
            raise unittest.SkipTest(f"Chrome driver could not start: {exc}")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "selenium"):
            cls.selenium.quit()
        super().tearDownClass()

    def test_home_page_browser_smoke(self):
        self.selenium.get(f"{self.live_server_url}/")

        self.assertIn("Shy2Ask", self.selenium.title)
        self.assertIn("Swiss Exclusive Beta", self.selenium.page_source)

        nav_links = self.selenium.find_elements(By.CSS_SELECTOR, "nav.main-nav a")
        self.assertGreaterEqual(len(nav_links), 4)

        hero_heading = self.selenium.find_element(By.TAG_NAME, "h1")
        self.assertIn("Your Privacy", hero_heading.text)

        footer = self.selenium.find_element(By.CSS_SELECTOR, "footer.site-footer")
        self.assertIn("Only available in Switzerland", footer.text)
