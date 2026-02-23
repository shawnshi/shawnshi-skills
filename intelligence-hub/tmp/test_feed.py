import xml.etree.ElementTree as ET
import urllib.request
import re

urls = [
    "https://www.nature.com/npjdigitalmed.rss", # Nature Digital Medicine
    "https://www.science.org/rss/news_current.xml", # Science News
    "https://www.thelancet.com/rssfeed/landig_current.xml", # The Lancet Digital Health
    "https://www.nejm.org/action/showFeed?type=etoc&feed=rss&jc=nejmai", # NEJM AI
    "http://export.arxiv.org/api/query?search_query=cat:cs.AI+AND+all:medicine&sortBy=lastUpdatedDate&sortOrder=desc&max_results=5", # arXiv cs.AI + medicine
    "https://www.thelancet.com/rssfeed/lancet_current.xml", # The Lancet main
    "https://www.nejm.org/action/showFeed?type=etoc&feed=rss&jc=nejm", # NEJM main
    "https://www.nature.com/nature.rss" # Nature main
]

for url in urls:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            xml_data = response.read().decode('utf-8')
            cleaned_xml = re.sub(r' xmlns="[^"]+"', '', xml_data, count=1)
            root = ET.fromstring(cleaned_xml)
            entries = root.findall('.//item') or root.findall('.//entry')
            print(f"Success for {url}: found {len(entries)} items.")
    except Exception as e:
        print(f"Failed for {url}: {e}")
