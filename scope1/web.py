import re
from bs4 import BeautifulSoup

for name in ["python_programming", "india"]:
    html = open(f"data/input/web/{name}_slice.html", encoding="utf-8").read()
    soup = BeautifulSoup(html, "html.parser")
    headings = soup.find_all(re.compile(r"^h[1-6]$"))
    tables = soup.find_all("table")
    top = [t for t in tables if t.find_parent("table") is None]
    data = [t for t in top if {"wikitable", "infobox"} & set(t.get("class", []))]
    imgs = soup.find_all("img")
    print(f"{name}: headings={len(headings)}  tables(all)={len(tables)}  "
          f"tables(top-level)={len(top)}  tables(data: wikitable/infobox)={len(data)}  images={len(imgs)}")