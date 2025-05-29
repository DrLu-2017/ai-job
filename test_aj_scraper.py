import unittest
from unittest.mock import patch, MagicMock, call
import sys
import os

# Add the parent directory to sys.path to allow importing aj_scraper
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import aj_scraper

class TestAJScraper(unittest.TestCase):

    @patch('aj_scraper.check_ai_server', return_value=True)
    @patch('aj_scraper.select_model', return_value="mock_model")
    @patch('aj_scraper.set_windows_proxy_from_pac')
    @patch('aj_scraper.ollama_highlight')
    @patch('aj_scraper.fetch_job_detail')
    @patch('aj_scraper.webdriver.Chrome')
    def test_fetch_academic_positions_jobs_limiting(
        self,
        mock_chrome,
        mock_fetch_job_detail,
        mock_ollama_highlight,
        mock_set_proxy,
        mock_select_model,
        mock_check_ai_server
    ):
        # Configure the mock driver and its methods
        mock_driver_instance = MagicMock()
        mock_chrome.return_value = mock_driver_instance

        # Mock job card elements
        mock_job_cards = []
        for i in range(20):
            card = MagicMock()
            
            # Mocking find_element for title
            title_elem = MagicMock()
            title_elem.text.strip.return_value = f"Job Title {i+1}"
            
            # Mocking find_element for institution
            institution_elem = MagicMock()
            institution_elem.text.strip.return_value = f"Institution {i+1}"
            
            # Mocking find_element for location
            location_elem = MagicMock()
            location_elem.text.strip.return_value = f"Location {i+1}"
            
            # Mocking find_element for link
            link_elem = MagicMock()
            link_elem.get_attribute.return_value = f"http://example.com/job{i+1}"

            # Configure card.find_element to return different mocks based on selector
            def side_effect_find_element(css_selector, *args, **kwargs):
                if "title" in css_selector: # Simplified check
                    return title_elem
                elif "employer" in css_selector or "job-link" in css_selector : # Simplified check for institution
                     # This part is tricky because institution can be found by two selectors,
                     # and link also uses job-link. We need to ensure the card returns institution first.
                     # For this test, we'll assume the first relevant selector hit is for institution text.
                    if css_selector == "a.job-link,span[class*='employer']":
                        return institution_elem
                    elif css_selector == "a.job-link": # For the link href
                        return link_elem 
                elif "location" in css_selector: # Simplified check
                    return location_elem
                return MagicMock() # Default mock for other calls

            # This is a more robust way for multiple elements on a card
            # Title, Institution, Location, Link
            elements_on_card = {
                "h2[class*='title']": title_elem, # Example selector
                "h3[class*='title']": title_elem,
                "a[class*='title']": title_elem,
                "span[class*='title']": title_elem,
                "a.job-link,span[class*='employer']": institution_elem,
                ".job-locations,span[class*='location']": location_elem,
                "a.job-link": link_elem, # This is for the href
            }
            
            # More precise side effect for find_element on card
            def card_find_element_side_effect(by, value):
                # print(f"Card find_element called with: {by}, {value}")
                if value in elements_on_card:
                    if value == "a.job-link" and elements_on_card[value] == link_elem:
                         # Ensure we distinguish between fetching text for institution and href for link
                         # This logic might need refinement based on actual call order in the code
                        pass
                    return elements_on_card[value]
                # Fallback for general selectors if specific ones not matched
                if "title" in value: return title_elem
                if "employer" in value : return institution_elem # covers span[class*='employer']
                if "location" in value: return location_elem
                if "job-link" == value: return link_elem # for href
                
                # Default, if no match
                # print(f"Warning: Unhandled selector in card.find_element: {value}")
                # return MagicMock(text=MagicMock(strip=MagicMock(return_value="")), get_attribute=MagicMock(return_value=""))
                # More specific for the test to pass if only certain elements are expected:
                mock_to_return = MagicMock()
                mock_to_return.text.strip.return_value = ""
                mock_to_return.get_attribute.return_value = ""

                if "title" in value: mock_to_return.text.strip.return_value = f"Job Title {i+1}"
                elif "employer" in value or (value == "a.job-link"): 
                    # This is tricky logic because a.job-link is used for both text and href
                    # We'll assume the text is grabbed first by the more complex selector
                    mock_to_return.text.strip.return_value = f"Institution {i+1}"
                    mock_to_return.get_attribute.return_value = f"http://example.com/job{i+1}" # if it's for link
                elif "location" in value: mock_to_return.text.strip.return_value = f"Location {i+1}"
                
                return mock_to_return


            # card.find_element.side_effect = card_find_element_side_effect
            # A simpler approach for the test, assuming order or specific calls:
            # The code tries multiple selectors for title. We need one to work.
            # Let's make the first one work.
            
            # For title, institution, location:
            mock_title_el = MagicMock()
            mock_title_el.text.strip.return_value = f'Job Title {i+1}'
            mock_inst_el = MagicMock()
            mock_inst_el.text.strip.return_value = f'Institution {i+1}'
            mock_loc_el = MagicMock()
            mock_loc_el.text.strip.return_value = f'Location {i+1}'
            mock_link_el = MagicMock()
            mock_link_el.get_attribute.return_value = f'http://example.com/job{i+1}'
            mock_link_el.text.strip.return_value = f"Institution {i+1}" # if a.job-link is used for text

            def find_element_dispatcher(by_type, selector_str):
                if "title" in selector_str:
                    if selector_str == "h2[class*='title']": # First one tried for title
                         return mock_title_el
                    raise Exception("Element not found by this title selector") # Simulate not found for others
                elif selector_str == "a.job-link,span[class*='employer']":
                    return mock_inst_el
                elif selector_str == ".job-locations,span[class*='location']":
                    return mock_loc_el
                elif selector_str == "a.job-link": # For the link
                    return mock_link_el
                else:
                    # print(f"Card find_element unhandled: {selector_str}")
                    # Fallback to prevent error, but make it return empty if not expected to be found
                    # This is important because the code tries multiple selectors
                    el = MagicMock()
                    el.text.strip.return_value = ""
                    el.get_attribute.return_value = ""
                    # raise FileNotFoundError(f"Unhandled selector: {selector_str}") # Make test fail if unexpected selector
                    return el # Should return something that doesn't break .text or .get_attribute

            card.find_element.side_effect = find_element_dispatcher
            card.text.strip.return_value = f"Card text {i+1}" # For unique_cards logic
            mock_job_cards.append(card)

        mock_driver_instance.find_elements.return_value = mock_job_cards
        
        # Configure fetch_job_detail to return dummy data
        mock_fetch_job_detail.return_value = (
            "Detail Title", "Detail Content", "Detail Institution",
            "Detail Location", "Detail Posted", "Detail Contract"
        )
        # Configure ollama_highlight
        mock_ollama_highlight.return_value = "Mocked Highlight"

        num_to_fetch = 5
        aj_scraper.fetch_academic_positions_jobs(
            use_headless=True, 
            selected_model="mock_model", 
            num_jobs_to_fetch=num_to_fetch
        )

        self.assertEqual(mock_fetch_job_detail.call_count, num_to_fetch)
        # Also check that ollama_highlight was called num_to_fetch times
        self.assertEqual(mock_ollama_highlight.call_count, num_to_fetch)


    def test_generate_summary_article_output(self):
        sample_job_details = []
        for i in range(3):
            sample_job_details.append({
                "title": f"Awesome Job {i+1}",
                "content": f"This is the detailed content for job {i+1}. It's very interesting.",
                "link": f"http://example.com/awesome-job-{i+1}",
                "institution": f"University of Tests {i+1}",
                "location": f"Testville {i+1}, TS",
                "posted": f"{i+1} days ago",
                "contract": f"{i+1} years",
                "highlight": f"This is the AI highlight for job {i+1}. It is truly awesome."
            })
        
        today_date = "2024-07-30"
        article = aj_scraper.generate_summary_article(sample_job_details, today=today_date)

        self.assertTrue(len(article) > 0, "Article should not be empty")
        self.assertIn(f"# 科研职位信息汇总（{today_date}）", article)

        for job in sample_job_details:
            self.assertIn(f"#### {job['title']}", article)
            # The article uses a snippet of content, not the full content directly
            # self.assertIn(job['content'][:100], article) # Check for snippet
            self.assertIn(f"**职位亮点与特色:**\n\n{job['highlight']}", article)
            self.assertIn(f"**单位/机构:** {job['institution']}", article)
            self.assertIn(f"**地点:** {job['location']}", article)
            self.assertIn(f"查看职位详情({job['link']})", article)
            self.assertIn(f"**合同周期:** {job['contract']}", article) # Check for contract period

        # Check for the short summary from content
        # Example: content = "This is the detailed content..." summary = "This is the detailed content..."
        # If content is short, it's used as is. If long, it's truncated.
        job1_content_summary = sample_job_details[0]['content'].replace('\n', ' ').replace('\r', ' ')
        summary_text = job1_content_summary[:200] + "..." if len(job1_content_summary) > 200 else job1_content_summary
        self.assertIn(summary_text, article)


if __name__ == '__main__':
    unittest.main()
